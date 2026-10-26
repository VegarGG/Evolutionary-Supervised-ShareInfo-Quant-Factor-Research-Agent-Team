"""Independent deterministic pilot return evaluation from canonical input tables."""

import hashlib
from dataclasses import dataclass
from datetime import date

import numpy as np
import polars as pl
from qfr_core.data_layer.snapshots import canonical_json
from qfr_core.metrics.pilot import drift_weights, pilot_metrics
from qfr_core.pilot.baseline import Cycle, P0History

from qfr_eval.backtest.schedule import build_schedule, snapshot
from qfr_eval.protocols.models import EvaluationWindow, FrozenProtocol


def eligible_pool_hash(codes: list[str]) -> str:
    if not codes or len(set(codes)) != len(codes):
        raise ValueError("eligibility identifiers must be nonempty and unique")
    return hashlib.sha256(canonical_json(sorted(codes))).hexdigest()


def assign_split(
    entry: date | None, exit_date: date | None, windows: dict[str, EvaluationWindow]
) -> str:
    if entry is None or exit_date is None:
        return "unmatured"
    if exit_date <= entry:
        raise ValueError("exit must follow entry")
    matches = [name for name, w in windows.items() if w.start <= entry < exit_date <= w.end]
    if len(matches) > 1:
        raise ValueError("overlapping windows")
    return matches[0] if matches else "purged_boundary"


@dataclass(frozen=True)
class PilotRun:
    ledger: pl.DataFrame
    periods: pl.DataFrame
    predictions: pl.DataFrame
    outcomes: pl.DataFrame


class PriceBook:
    def __init__(self, prices: pl.DataFrame):
        if prices.select("date", "code").is_duplicated().any():
            raise ValueError("duplicate price key")
        self.values = {(d, c): v for d, c, v in prices.select("date", "code", "close").iter_rows()}

    def returns(self, codes: list[str], entry: date, exit_date: date) -> dict[str, float]:
        result = {}
        for code in codes:
            a, b = self.values.get((entry, code)), self.values.get((exit_date, code))
            if a is None or b is None or not np.isfinite([a, b]).all() or min(a, b) <= 0:
                raise ValueError(f"missing or invalid execution prices: {entry}/{exit_date}/{code}")
            result[code] = b / a - 1
        return result


def evaluate_pilot(
    panel: pl.DataFrame,
    history: P0History,
    prices: pl.DataFrame,
    calendar: pl.DataFrame,
    universe: pl.DataFrame,
    protocol: FrozenProtocol,
    *,
    variant: str,
    start: date | None = None,
    end: date | None = None,
    fixed_quarter: bool = False,
) -> PilotRun:
    dates = sorted(panel["date"].unique().to_list())
    end = end or max(prices["date"])
    schedule = build_schedule(dates, calendar, start=start or dates[0], end=end)
    book = PriceBook(prices)
    price_days = set(prices["date"])
    ledgers, periods, predictions, outcomes = [], [], [], []
    cycles: tuple[Cycle, ...] = (
        ("quarterly",) if fixed_quarter else ("weekly", "monthly", "quarterly")
    )
    for cycle in cycles:
        events = [r for r in schedule if r["model_cycle"] == cycle]
        snaps = {
            r["period_key"]: snapshot(history, panel, r["publication_date"], cycle)
            for r in events
            if r["snapshot_available"]
        }
        if fixed_quarter:
            kept, fixed_snaps, seen = [], {}, set()
            for event in events:
                ranks = snaps.get(event["period_key"])
                if ranks is None or ranks.is_empty():
                    continue
                source = ranks["feature_source_date"][0]
                if source in seen:
                    continue
                seen.add(source)
                key = event["publication_date"].isoformat()
                kept.append({**event, "period_key": key})
                base = (
                    history.signals["quarterly"]
                    .filter((pl.col("date") == source) & (pl.col("event_type") == "quarter_reset"))
                    .with_columns(
                        pl.col("factor_score").alias("original"),
                        pl.lit(source).alias("feature_source_date"),
                    )
                )
                fixed_snaps[key] = base
            events, snaps = kept, fixed_snaps
        label = "fixed_quarter" if fixed_quarter else cycle
        actual = [
            r for r in events if r["period_key"] in snaps and not snaps[r["period_key"]].is_empty()
        ]
        following = {a["period_key"]: b for a, b in zip(actual, actual[1:], strict=False)}
        state: dict[str, dict[str, float]] = {}
        state_asof: date | None = None
        initial = True
        for event in events:
            key = event["period_key"]
            ranks = snaps.get(key, history.signals[cycle].head(0))
            nxt = following.get(key)
            entry = event["execution_date"]
            exit_date = nxt["execution_date"] if nxt else None
            row = dict(
                variant=variant,
                group_name="p60",
                model_cycle=label,
                period_key=key,
                decision_id=f"{variant}:p60:{label}:{key}",
                publication_date=event["publication_date"],
                execution_date=entry,
                exit_date=exit_date,
                next_publication_date=nxt["publication_date"] if nxt else None,
                feature_source_date=ranks["feature_source_date"][0] if ranks.height else None,
                snapshot_available=event["snapshot_available"],
                prediction_count=ranks.height,
                eligible_pool_hash=eligible_pool_hash(ranks["code"].to_list())
                if ranks.height
                else None,
                in_execution_cohort=event["in_execution_cohort"],
                execution_cohort_class=event["execution_cohort_class"],
                split=assign_split(entry, exit_date, protocol.windows),
                is_live_forecast=False,
                clean_out_of_sample=False,
                probability_confidence_available=False,
                initial_construction=initial,
            )
            keys = [
                "variant",
                "group_name",
                "model_cycle",
                "period_key",
                "decision_id",
                "publication_date",
                "execution_date",
                "exit_date",
                "split",
            ]
            if ranks.height:
                predictions.append(ranks.with_columns(pl.lit(row[k]).alias(k) for k in keys))
            if not event["snapshot_available"]:
                status = "missing_snapshot"
            elif ranks.is_empty():
                status = "missing_prediction"
            elif entry is None or entry not in price_days:
                status = "pending_entry"
            elif exit_date is None or exit_date not in price_days:
                status = "pending_exit"
            else:
                status = "evaluated"
                if state_asof is not None and state_asof > entry:
                    raise ValueError("portfolio state from future interval")
                for side, weights in state.items():
                    if state_asof != entry:
                        assert state_asof is not None
                        state[side] = drift_weights(
                            weights, book.returns(list(weights), state_asof, entry)
                        )
                returns = book.returns(universe["code"].to_list(), entry, exit_date)
                actual_frame = universe.select("code", "industry").with_columns(
                    pl.Series("return", [returns[c] for c in universe["code"]])
                )
                benchmark = book.returns(protocol.features.benchmarks, entry, exit_date)
                measurement = pilot_metrics(
                    ranks,
                    actual_frame,
                    benchmark_return=benchmark["000905.SH"],
                    config=protocol.metrics,
                    previous_weights=state,
                )
                values = {k: v.value for k, v in measurement.metrics.items()}
                values.update(
                    reference_industries=31,
                    eligible_industries=ranks.height,
                    top_count=int(ranks["selected"].sum()),
                    bottom_count=int(ranks["selected"].sum()),
                    actual_top_count=7,
                    actual_bottom_count=7,
                    random_precision_reference=7 / 31,
                    random_recall_reference=int(ranks["selected"].sum()) / 31,
                    terminal_liquidation=False,
                )
                periods.append({**row, "status": status, **values})
                detail = (
                    actual_frame.rename({"return": "actual_return"})
                    .sort(["actual_return", "industry"], descending=[True, False])
                    .with_row_index("actual_rank", 1)
                )
                detail = (
                    detail.join(ranks.drop("industry"), on="code", how="left")
                    .with_columns(
                        pl.when(pl.col("actual_rank") <= 7)
                        .then(pl.lit("top"))
                        .when(pl.col("actual_rank") > 24)
                        .then(pl.lit("bottom"))
                        .otherwise(pl.lit("middle"))
                        .alias("actual_bucket"),
                        pl.when(pl.col("selected"))
                        .then(pl.lit("top"))
                        .when(pl.col("rank") > ranks.height - int(ranks["selected"].sum()))
                        .then(pl.lit("bottom"))
                        .when(pl.col("factor_score").is_not_null())
                        .then(pl.lit("middle"))
                        .otherwise(pl.lit("unavailable"))
                        .alias("selection_bucket"),
                    )
                    .with_columns(pl.lit(row[k]).alias(k) for k in keys)
                )
                outcomes.append(detail)
                state, state_asof = measurement.next_weights, exit_date
                initial = False
            row["status"] = status
            ledgers.append(row)
    return PilotRun(
        pl.DataFrame(ledgers, infer_schema_length=None),
        pl.DataFrame(periods, infer_schema_length=None),
        pl.concat(predictions, how="diagonal_relaxed"),
        pl.concat(outcomes, how="diagonal_relaxed"),
    )
