"""Deterministic trusted pilot measurement; no DB, provider, network or clock access."""

import hashlib
import math
from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np
import polars as pl
from qfr_core.contracts.enums import ReasonCode
from qfr_core.data_layer.snapshots import canonical_json
from qfr_core.metrics.core import measurement

from qfr_eval.backtest.pairing import pair_periods, window_periods
from qfr_eval.backtest.pilot import PilotRun, evaluate_pilot
from qfr_eval.backtest.prefix import slice_inputs
from qfr_eval.backtest.scorers import built_in_history
from qfr_eval.protocols.models import FrozenProtocol
from qfr_eval.records import EvaluationRequest, Measurement
from qfr_eval.runtime import builtin_definition
from qfr_eval.statistics.bootstrap import (
    automatic_block_length,
    derived_seed,
    official_interval,
    sensitivity_intervals,
)
from qfr_eval.statistics.detectability import minimum_detectable_effect
from qfr_eval.statistics.diagnostics import (
    aligned_cross_sections,
    calendar_shift,
    exclude_year,
    within_date_permutation,
    yearly_deltas,
)
from qfr_eval.statistics.family import TrialObservation, family_statistics, studentized_family
from qfr_eval.statistics.hurdles import fold_majority, pilot_hurdle, turnover_flag
from qfr_eval.statistics.incremental import incremental_contribution

PRIMARY = "extreme_macro_recall"
METRICS = [
    "top_recall",
    "bottom_recall",
    PRIMARY,
    "rank_ic",
    "action_rank_ic",
    "top_excess_equal31_net_0bps",
    "top_excess_equal31_net_10bps",
    "top_excess_equal31_net_30bps",
]


@dataclass(frozen=True)
class MeasuredRun:
    summary: Measurement
    tables: dict[str, tuple[pl.DataFrame, list[str]]]
    primary_deltas: list[float | None]


def strict_mean(values: list[float | None] | np.ndarray) -> float | None:
    x = np.asarray(values, dtype=float)
    return float(x.mean()) if x.size and np.isfinite(x).all() else None


def trial_observation(
    request: EvaluationRequest,
    trial_id: str,
    ids: list[str],
    returns: list[float | None],
    *,
    failed: bool = False,
) -> TrialObservation:
    return TrialObservation(
        trial_id=trial_id,
        artifact_version_id=str(request.artifact_version_id),
        family_id=request.family_id,
        economic_lineage_id=request.economic_lineage_id,
        generation_id=request.generation_id,
        program_id=request.program_id,
        protocol_hash=request.protocol_hash,
        snapshot_id=request.snapshot_id,
        window=request.window,
        cohort_id=request.cohort_id,
        status="failed" if failed else request.intent,
        selectable=not failed and request.intent != "diagnostic",
        sampling_unit="mature_matched_decision",
        returns=returns,
        observation_ids=ids,
    )


def failed_measurement(
    request: EvaluationRequest, trial_id: str, reason: ReasonCode
) -> MeasuredRun:
    return MeasuredRun(
        Measurement(
            status="failed",
            metrics={name: measurement(None) for name in METRICS},
            reason_codes=[reason],
            observation=trial_observation(request, trial_id, [], [], failed=True),
            period_count=0,
            used_seeds={},
            uncertainty=None,
            sensitivity=[],
            family_interval=None,
            family_statistics=None,
            incremental=None,
            turnover={},
            hurdle={"overall": "insufficient_data"},
            diagnostics={"failure": reason.value},
        ),
        {},
        [],
    )


def measure_pilot(
    request: EvaluationRequest,
    protocol: FrozenProtocol,
    tables: dict[str, pl.DataFrame],
    *,
    trial_id: str,
    prior: list[TrialObservation],
    prior_deltas: dict[str, list[float | None]],
    effective_trials: int | None,
) -> MeasuredRun:
    if protocol.sha256 != request.protocol_hash or protocol.scope != "P0_P1_verification_only":
        raise ValueError("measurement requires the exact approved protocol")
    window = protocol.windows[request.window]
    if window.access == "locked":
        raise ValueError("locked confirmation is not authorized")
    artifact_id, digest, _ = builtin_definition(request.variant)
    if artifact_id != request.artifact_version_id or digest != request.content_hash:
        raise ValueError("built-in artifact identity differs")
    # Preserve warmup and carry-in state, but never measure later/confirmation outcomes.
    tables = slice_inputs(tables, window.end)
    runs: dict[str, PilotRun] = {}

    def run(variant: str) -> PilotRun:
        if variant not in runs:
            _, _, spec = builtin_definition(variant)
            panel, history = built_in_history(
                tables["features"],
                tables["prices_daily"],
                tables["universe"]["code"].to_list(),
                protocol,
                spec=spec,
            )
            runs[variant] = evaluate_pilot(
                panel,
                history,
                tables["prices_daily"],
                tables["calendar"],
                tables["universe"],
                protocol,
                variant=variant,
                fixed_quarter=request.cycle == "fixed_quarter",
            )
        return runs[variant]

    baseline, candidate = run(protocol.baseline), run(request.variant)
    periods = window_periods(candidate.periods, window.start, window.end).filter(
        pl.col("model_cycle") == request.cycle
    )
    pairs = window_periods(
        pair_periods(baseline.periods, candidate.periods, METRICS), window.start, window.end
    ).filter(pl.col("model_cycle") == request.cycle)
    ids = pairs["period_key"].to_list()
    delta = pairs["delta_" + PRIMARY].to_numpy()
    period_map = {row["period_key"]: row for row in periods.iter_rows(named=True)}
    returns = [
        period_map[key]["top_net_return_10bps"] - period_map[key]["bottom_net_return_10bps"]
        if key in period_map
        else None
        for key in ids
    ]
    observation = trial_observation(request, trial_id, ids, returns)
    if any(t.trial_id == trial_id for t in prior):
        raise ValueError("current trial already present in frozen prior cohort")
    all_trials = [*prior, observation]
    grid_hash = hashlib.sha256(
        canonical_json(pairs.select("period_key", "execution_date", "exit_date").write_json())
    ).hexdigest()
    seeds = {
        name: derived_seed(seed, request.window, request.cycle, grid_hash)
        for name, seed in protocol.diagnostics.purpose_seeds.items()
    }
    uncertainty = official_interval(
        delta, protocol.bootstrap, request.cycle, seed=seeds["official_uncertainty"]
    )
    sensitivity = sensitivity_intervals(
        delta, protocol.bootstrap, request.cycle, seed=seeds["official_uncertainty"]
    )
    columns = []
    for previous in prior:
        values = prior_deltas.get(previous.trial_id)
        columns.append(
            values
            if previous.observation_ids == ids and values is not None and len(values) == len(ids)
            else [None] * len(ids)
        )
    matrix = np.asarray([*columns, delta.tolist()], dtype=float).T
    family_interval = studentized_family(
        matrix,
        protocol.bootstrap,
        request.cycle,
        seed=seeds["official_uncertainty"],
        raw_trials=len(all_trials),
    )
    stats = family_statistics(
        all_trials,
        trial_id,
        effective_trials,
        protocol.diagnostics,
        block_length=automatic_block_length(
            len(ids), protocol.bootstrap.block_floors[request.cycle]
        ),
        minimum_periods=protocol.bootstrap.minimum_periods,
        minimum_blocks=protocol.bootstrap.minimum_blocks,
        zero_epsilon=protocol.metrics.zero_epsilon,
    )
    metrics = {name: measurement(strict_mean(periods[name].to_numpy())) for name in METRICS}
    metrics["paired_primary_delta"] = measurement(strict_mean(delta))
    metrics["long_short_net_per_period"] = measurement(strict_mean(returns))
    for metric in ("rank_ic", "top_recall", "extreme_macro_recall"):
        for critical in (2, 3):
            metrics[f"mde_{metric}_t{critical}"] = minimum_detectable_effect(
                metric,
                universe=protocol.metrics.industry_count,
                selected=math.ceil(
                    protocol.metrics.industry_count * protocol.metrics.selection_fraction
                ),
                periods=len(ids),
                critical_t=critical,
            )
    yearly = yearly_deltas(pairs, "delta_" + PRIMARY)
    loyo = {
        year: strict_mean(exclude_year(pairs, "delta_" + PRIMARY, int(year))) for year in yearly
    }
    turnover = {}
    coverage = {}
    complete = all(value == "matched" for value in pairs["pair_status"])
    for name, result in [("baseline", baseline), ("candidate", candidate)]:
        active = result.periods.filter(pl.col("model_cycle") == request.cycle)[
            "execution_date"
        ].min()
        if not isinstance(active, date):
            raise ValueError("no mature cycle observations")
        ledger = result.ledger.filter(
            (pl.col("model_cycle") == request.cycle)
            & (pl.col("execution_date") >= max(window.start, active))
        )
        coverage[name] = dict(ledger.group_by("status").len().iter_rows())
        if ledger.filter(pl.col("status").is_in(["missing_snapshot", "missing_prediction"])).height:
            complete = False
    for basket in ("top", "bottom"):
        turnover[basket] = turnover_flag(
            periods[basket + "_one_way_turnover"].to_list(),
            periods["initial_construction"].to_list(),
            protocol,
            cycle=request.cycle,
            basket=basket,
            required_evidence_complete=complete,
        )
    incremental = None
    shift_summary: list[dict[str, Any]] = []
    permutation: dict[str, Any] = {"status": "insufficient_data"}
    placebo = measurement(None)
    if ids and complete:
        arms = {
            name: window_periods(result.outcomes, window.start, window.end).filter(
                pl.col("model_cycle") == request.cycle
            )
            for name, result in [("baseline", baseline), ("candidate", candidate)]
        }
        cross = aligned_cross_sections(arms)
        incremental = incremental_contribution(
            cross, candidate="candidate", pool=["baseline"], epsilon=protocol.metrics.zero_epsilon
        )
        distance = protocol.diagnostics.placebo_min_shift[request.cycle]
        if len(ids) >= 2 * distance:
            shift_summary, _ = calendar_shift(
                cross,
                baseline="baseline",
                candidate="candidate",
                minimum_distance=distance,
                equality_atol=protocol.atol,
            )
            placebo = measurement(
                next(
                    r["observed_empirical_midrank_percentile"]
                    for r in shift_summary
                    if r["variant"] == "candidate_minus_baseline" and r["metric"] == PRIMARY
                )
            )
        permutation = within_date_permutation(
            cross,
            baseline="baseline",
            candidate="candidate",
            draws=protocol.diagnostics.permutation_draws,
            seed=seeds["permutation"],
        )
    flags = pilot_hurdle(
        family_interval,
        len(prior),
        protocol,
        incremental_rank_ic=incremental.mean_rank_ic if incremental else measurement(None),
        placebo_percentile=placebo,
        max_pool_correlation=incremental.max_pool_correlation if incremental else measurement(None),
        folds=fold_majority(list(yearly.values()), list(loyo.values())),
        top_turnover=turnover["top"],
        bottom_turnover=turnover["bottom"],
        block_sensitivity=sensitivity,
    )
    if not complete:
        flags["coverage"] = flags["overall"] = "insufficient_data"
    # Weekly is the primary acceptance cycle; no monthly/quarterly cap is fabricated.
    if request.cycle != protocol.primary_cycle:
        flags["overall"] = "not_applicable"
    summary = Measurement.model_validate(
        dict(
            status="complete",
            metrics=metrics,
            reason_codes=[] if complete else [ReasonCode.LOW_COVERAGE],
            observation=observation,
            period_count=len(ids),
            used_seeds=seeds,
            uncertainty=uncertainty,
            sensitivity=sensitivity,
            family_interval=family_interval,
            family_statistics=stats,
            incremental=incremental,
            turnover=turnover,
            hurdle=flags,
            diagnostics={
                "coverage": coverage,
                "calendar_shift": shift_summary,
                "within_date_permutation": permutation,
                "yearly_deltas": yearly,
                "leave_one_year_out": loyo,
                "previously_seen": True,
                "primary_cycle": protocol.primary_cycle,
                "confirmation_computed": False,
            },
        )
    )
    output = {"pairs": (pairs, ["model_cycle", "period_key"])}
    for name, frame, keys in [
        ("periods", periods, ["model_cycle", "period_key"]),
        ("ledger", candidate.ledger, ["model_cycle", "period_key"]),
        ("predictions", candidate.predictions, ["model_cycle", "period_key", "code"]),
        ("outcomes", candidate.outcomes, ["model_cycle", "period_key", "code"]),
    ]:
        output[name] = (frame, keys)
    return MeasuredRun(summary, output, [float(v) if np.isfinite(v) else None for v in delta])
