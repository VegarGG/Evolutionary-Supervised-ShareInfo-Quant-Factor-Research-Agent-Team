"""P0 p60 scores, rankings and quarterly review membership; no return evaluation."""

import calendar
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Literal

import numpy as np
import polars as pl
from pydantic import Field, PositiveInt, ValidationInfo, field_validator

from qfr_core.contracts.base import Contract
from qfr_core.metrics.core import Array

Cycle = Literal["weekly", "monthly", "quarterly"]
CORE_COLUMNS = [
    "date",
    "model",
    "industry",
    "code",
    "factor_score",
    "original",
    "rank",
    "selected",
    "relative",
]


class P0Config(Contract):
    revision: PositiveInt
    minimum_names: PositiveInt
    selection_fraction: float = Field(gt=0, lt=0.5)
    replacement_fraction: float = Field(gt=0, le=1)
    selection_score_bonus: float
    missing_percentile: float
    crowding_weight: float
    monthly_preference: float
    monthly_bandwidth: float = Field(gt=0)
    weekly_legacy_breadth_weight: float
    weekly_legacy_trend_weight: float
    weekly_momentum_share: float
    weekly_persistence_share: float
    weekly_breadth_adjustment: float
    weekly_trend_adjustment: float
    weekly_style_weight: float
    monthly_fundamental_weight: float
    monthly_market_weight: float
    monthly_fundamental_internal: dict[str, float]
    monthly_market_internal: dict[str, float]
    quarterly_noncrowding_scale: float

    @field_validator("monthly_fundamental_internal", "monthly_market_internal")
    @classmethod
    def original_arithmetic_order(
        cls, weights: dict[str, float], info: ValidationInfo
    ) -> dict[str, float]:
        # JSON objects have no semantic order; PostgreSQL JSONB and canonical
        # JSON reorder keys differently. Preserve the delivered P0 addition
        # order explicitly so a protocol round-trip cannot alter score bits.
        order = (
            ("cash", "inventory", "revenue_acceleration", "profit_acceleration", "roe_floor")
            if info.field_name == "monthly_fundamental_internal"
            else ("moderate_trend", "breadth_change")
        )
        if set(weights) != set(order):
            raise ValueError("P0 monthly weights must name the original feature set")
        return {name: weights[name] for name in order}


def sample_dates(panel: pl.DataFrame, cycle: Cycle) -> list[date]:
    dates = sorted(panel["date"].unique().to_list())
    if not dates or cycle == "weekly":
        return dates
    latest = dates[-1]
    groups: dict[tuple[int, int], date] = {}
    for day in dates:
        end_month = day.month if cycle == "monthly" else 3 * ((day.month - 1) // 3 + 1)
        period_end = date(day.year, end_month, calendar.monthrange(day.year, end_month)[1])
        if period_end <= latest:
            groups[(day.year, end_month)] = day
    return list(groups.values())


def p0_scores(panel: pl.DataFrame, cycle: Cycle, config: P0Config) -> Array:
    def feature(name: str) -> Array:
        values = panel["p_" + name].to_numpy()
        if cycle == "monthly" and name == "moderate_trend":
            values = np.clip(
                1
                - np.abs(panel["p_ret4"].to_numpy() - config.monthly_preference)
                / config.monthly_bandwidth,
                0,
                1,
            )
        result: Array = np.where(np.isfinite(values), values, config.missing_percentile)
        return result

    def weighted(weights: dict[str, float]) -> Array:
        result = np.zeros(panel.height)
        for name, weight in weights.items():
            result = result + weight * feature(name)
        return result

    if cycle == "weekly":
        # Preserve the delivered arithmetic order, including its substitutions.
        # Algebraically collapsing these terms changes low bits of P0 scores.
        trend = (
            config.weekly_momentum_share * panel["p_momentum12"].to_numpy()
            + config.weekly_persistence_share * panel["p_persistence"].to_numpy()
        )
        trend = np.where(np.isfinite(trend), trend, config.missing_percentile)
        base = config.weekly_legacy_breadth_weight * feature(
            "breadth_change"
        ) + config.weekly_legacy_trend_weight * feature("moderate_trend")
        base = base + config.weekly_legacy_trend_weight * (trend - feature("moderate_trend"))
        base = base + config.weekly_legacy_breadth_weight * (
            feature("relative_breadth_change") - feature("breadth_change")
        )
        base = base + config.crowding_weight * (1 - panel["crowding_weekly"].to_numpy())
        result: Array = (
            base
            - config.weekly_breadth_adjustment * feature("relative_breadth_change")
            - config.weekly_trend_adjustment * trend
            + config.weekly_style_weight * feature("style")
        )
        return result
    elif cycle == "monthly":
        base = np.zeros(panel.height)
        for weight, internal in [
            (config.monthly_fundamental_weight, config.monthly_fundamental_internal),
            (config.monthly_market_weight, config.monthly_market_internal),
        ]:
            base = base + weight * weighted(internal) / sum(internal.values())
    else:
        base = panel["base_quarterly"].to_numpy() * config.quarterly_noncrowding_scale
    result = base + config.crowding_weight * (1 - panel["crowding_" + cycle].to_numpy())
    return result


def p0_signals(
    panel: pl.DataFrame,
    cycle: Cycle,
    config: P0Config,
    scores: Array | None = None,
    *,
    allow_empty: bool = False,
) -> pl.DataFrame:
    frame = panel.with_columns(
        pl.Series(
            "factor_score",
            p0_scores(panel, cycle, config) if scores is None else scores,
            nan_to_null=True,
        )
    )
    dates = sample_dates(panel, cycle)
    rows = []
    for day in dates:
        cross = frame.filter((pl.col("date") == day) & pl.col("eligible_" + cycle))
        if cross.height < config.minimum_names:
            continue
        if cross["factor_score"].null_count() or not cross["factor_score"].is_finite().all():
            raise ValueError(f"eligible P0 score missing at {day}")
        cross = cross.sort(["factor_score", "industry"], descending=[True, False]).with_columns(
            pl.int_range(1, pl.len() + 1).alias("rank")
        )
        cross = cross.with_columns(
            (pl.col("rank") <= math.ceil(cross.height * config.selection_fraction)).alias(
                "selected"
            ),
            pl.col("factor_score").alias("original"),
            pl.lit(cycle).alias("model"),
            pl.lit(0.0).alias("relative"),
        )
        rows.append(cross.select(CORE_COLUMNS))
    if not rows:
        if allow_empty:
            return (
                frame.head(0)
                .with_columns(
                    pl.lit(cycle).alias("model"),
                    pl.col("factor_score").alias("original"),
                    pl.lit(0, dtype=pl.Int64).alias("rank"),
                    pl.lit(False).alias("selected"),
                    pl.lit(0.0).alias("relative"),
                )
                .select(CORE_COLUMNS)
            )
        raise ValueError(f"no eligible P0 {cycle} dates")
    return pl.concat(rows)


@dataclass(frozen=True)
class P0History:
    signals: dict[Cycle, pl.DataFrame]
    rankings: dict[Cycle, pl.DataFrame]
    review_actions: pl.DataFrame


def p0_history(
    panel: pl.DataFrame,
    config: P0Config,
    scores: Mapping[Cycle, Array] | None = None,
    *,
    allow_empty: bool = False,
) -> P0History:
    cycles: tuple[Cycle, ...] = ("weekly", "monthly", "quarterly")
    signals = {
        cycle: p0_signals(
            panel, cycle, config, None if scores is None else scores[cycle], allow_empty=allow_empty
        )
        for cycle in cycles
    }
    quarters = signals["quarterly"]
    qdates = set(quarters["date"])
    months = [d for d in sample_dates(panel, "monthly") if qdates and d >= min(qdates)]
    frozen: pl.DataFrame | None = None
    held: set[str] = set()
    events, actions = [], []
    for day in sorted(qdates | set(months)):
        if day in qdates:
            frozen = quarters.filter(pl.col("date") == day).sort("rank")
            held = set(frozen.filter(pl.col("selected"))["code"])
            kind, changed = "quarter_reset", True
        elif frozen is None:
            continue
        else:
            current = {
                row["code"]: row
                for row in panel.filter(pl.col("date") == day).iter_rows(named=True)
            }
            allowed = frozen.filter(
                pl.col("rank") <= math.ceil(frozen.height * config.replacement_fraction)
            )["code"].to_list()

            weak = [
                code
                for code in frozen["code"]
                if code in held
                and current[code]["ma_gap"] is not None
                and current[code]["relative4"] is not None
                and current[code]["ma_gap"] < 0
                and current[code]["relative4"] < 0
            ]
            replacements = [
                code
                for code in allowed
                if code not in held
                and current[code]["eligible_quarterly"]
                and current[code]["ma_gap"] is not None
                and current[code]["relative4"] is not None
                and current[code]["ma_gap"] >= 0
                and current[code]["relative4"] >= 0
            ]
            changed = False
            for code in weak:
                replacement = replacements.pop(0) if replacements else code
                if replacement != code:
                    held.remove(code)
                    held.add(replacement)
                    changed = True
                actions.append(
                    {
                        "date": day,
                        "quarter_signal": frozen["date"][0],
                        "removed": code,
                        "added": replacement,
                        "action": "replace" if replacement != code else "retain_no_candidate",
                    }
                )
            kind = "monthly_review"
        if changed:
            assert frozen is not None
            event = frozen.with_columns(
                pl.lit(day).alias("date"),
                pl.col("code").is_in(sorted(held)).alias("selected"),
                pl.lit(kind).alias("event_type"),
            )
            event = event.with_columns(
                (
                    pl.col("factor_score")
                    + config.selection_score_bonus * pl.col("selected").cast(pl.Float64)
                ).alias("original")
            )
            if event["selected"].sum() != math.ceil(event.height * config.selection_fraction):
                raise ValueError("quarter review selection count changed")
            events.append(event)
    signals["quarterly"] = (
        pl.concat(events)
        if events
        else quarters.with_columns(pl.lit(None, dtype=pl.String).alias("event_type"))
    )
    rankings = {}
    for cycle, signal in signals.items():
        last = signal["date"].max()
        latest = (
            (signal.filter(pl.col("date") == last) if last is not None else signal.head(0))
            .sort("rank")
            .with_columns(
                pl.col("selected").alias("candidate"),
                pl.col("factor_score").alias("score_" + cycle),
                pl.lit(
                    max(months) if cycle == "quarterly" and months else last, dtype=pl.Date
                ).alias("last_review_date"),
                pl.lit("p60").alias("preference_group"),
                pl.lit(cycle == "monthly").alias("preference_applies"),
            )
        )
        if cycle == "quarterly":
            latest = latest.with_columns(
                pl.lit(max(qdates) if qdates else None, dtype=pl.Date).alias("quarter_signal_date")
            )
        rankings[cycle] = latest
    return P0History(signals, rankings, pl.DataFrame(actions))
