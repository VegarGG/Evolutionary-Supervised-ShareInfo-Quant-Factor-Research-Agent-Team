"""Private trial-family statistics. Missing attempts never disappear from counts."""

from collections.abc import Sequence
from typing import Literal, Self

import numpy as np
from pydantic import NonNegativeInt, model_validator
from qfr_core.contracts.base import Contract, Text
from qfr_core.contracts.reports import MetricValue
from qfr_core.metrics.core import Array, measurement
from qfr_core.metrics.statistics import (
    StatisticsConfig,
    deflated_sharpe,
    probability_of_overfit,
    sharpe_moments,
)

from qfr_eval.protocols.models import BootstrapConfig, Cycle, DiagnosticConfig
from qfr_eval.statistics.bootstrap import automatic_block_length, block_indices, index_hash


class TrialObservation(Contract):
    trial_id: Text
    artifact_version_id: Text
    family_id: Text
    economic_lineage_id: Text
    generation_id: Text
    program_id: Text
    protocol_hash: Text
    snapshot_id: Text
    window: Text
    cohort_id: Text
    status: Literal["evaluated", "failed", "withheld", "diagnostic"]
    selectable: bool
    sampling_unit: Literal["trading_date", "mature_matched_decision"]
    returns: list[float | None]
    observation_ids: list[Text]

    @model_validator(mode="after")
    def coherent_attempt(self) -> Self:
        if self.status == "diagnostic" and self.selectable:
            raise ValueError("diagnostic trials cannot be selectable")
        if len(self.observation_ids) != len(self.returns) or len(set(self.observation_ids)) != len(
            self.observation_ids
        ):
            raise ValueError("trial returns require a unique complete observation grid")
        return self


class FamilyStatistics(Contract):
    raw_trials: NonNegativeInt
    effective_trials: NonNegativeInt | None
    failed_trials: NonNegativeInt
    withheld_trials: NonNegativeInt
    diagnostic_trials: NonNegativeInt
    dsr: MetricValue
    pbo: MetricValue
    pbo_cohort: Literal["family", "generation", "insufficient_data"]
    hlz_t: MetricValue
    hlz_status: Literal["pass", "fail", "insufficient_data"]
    rank_in_family: NonNegativeInt | None


def hac_standard_error(values: Array, lag: int) -> Array:
    """Last axis is time; Bartlett NW covariance divisor n, lag fixed before use."""
    x = np.asarray(values, dtype=float)
    n = x.shape[-1]
    if n < 2 or not 0 <= lag < n or not np.isfinite(x).all():
        raise ValueError("HAC requires finite data and a valid fixed lag")
    z = x - x.mean(axis=-1, keepdims=True)
    variance = np.sum(z * z, axis=-1) / n
    for k in range(1, lag + 1):
        variance = (
            variance + 2 * (1 - k / (lag + 1)) * np.sum(z[..., k:] * z[..., :-k], axis=-1) / n
        )
    # Exact constant input must have SE zero despite floating mean residuals.
    variance = np.where(np.ptp(x, axis=-1) == 0, 0, variance)
    result: Array = np.sqrt(np.maximum(variance, 0) / n)
    return result


def family_statistics(
    trials: Sequence[TrialObservation],
    current: str,
    effective_trials: int | None,
    diagnostics: DiagnosticConfig,
    *,
    block_length: int,
    minimum_periods: int,
    minimum_blocks: int,
    zero_epsilon: float,
) -> FamilyStatistics:
    if not trials or len({t.trial_id for t in trials}) != len(trials):
        raise ValueError("a unique frozen trial family is required")
    keys = {
        (t.program_id, t.protocol_hash, t.snapshot_id, t.window, t.cohort_id, t.sampling_unit)
        for t in trials
    }
    if len(keys) != 1:
        raise ValueError("trial cohort semantics differ")
    target = next((t for t in trials if t.trial_id == current), None)
    if target is None:
        raise ValueError("current attempt absent from trial ledger")
    config = StatisticsConfig(
        revision=1,
        min_observations=minimum_periods,
        min_pbo_candidates=diagnostics.minimum_pbo_candidates,
        pbo_blocks=diagnostics.pbo_blocks,
        zero_epsilon=zero_epsilon,
    )
    moments = [sharpe_moments(np.asarray(t.returns, dtype=float), config) for t in trials]
    own = sharpe_moments(np.asarray(target.returns, dtype=float), config)
    raw = len(trials)
    if effective_trials is not None and not 1 <= effective_trials <= raw:
        raise ValueError("effective count outside all-attempt ledger size")
    dsr = measurement(None)
    if effective_trials is not None:
        dsr = deflated_sharpe(
            own,
            [m.sharpe if m else float("nan") for m in moments],
            effective_trials=effective_trials,
        ).probability
    family = [t for t in trials if t.economic_lineage_id == target.economic_lineage_id]
    cohort: Literal["family", "generation", "insufficient_data"] = "family"
    if len(family) < config.min_pbo_candidates:
        family = [t for t in trials if t.generation_id == target.generation_id]
        cohort = "generation"
    pbo = measurement(None)
    if len(family) < config.min_pbo_candidates:
        cohort = "insufficient_data"
    elif all(
        t.observation_ids == family[0].observation_ids and len(t.returns) == len(t.observation_ids)
        for t in family
    ):
        matrix = np.asarray([t.returns for t in family], dtype=float).T
        pbo = probability_of_overfit(matrix, config).probability
    returns = np.asarray(target.returns, dtype=float)
    t_value = None
    if own is not None and len(returns) // block_length >= minimum_blocks:
        se = float(hac_standard_error(returns, block_length - 1))
        if se > 0:
            t_value = float(returns.mean() / se)
    ranks = None
    own_family = [
        i for i, t in enumerate(trials) if t.economic_lineage_id == target.economic_lineage_id
    ]
    if own is not None and all(moments[i] is not None for i in own_family):
        ranks = 1 + sum(m.sharpe > own.sharpe for i in own_family if (m := moments[i]) is not None)
    return FamilyStatistics(
        raw_trials=raw,
        effective_trials=effective_trials,
        failed_trials=sum(t.status == "failed" for t in trials),
        withheld_trials=sum(t.status == "withheld" for t in trials),
        diagnostic_trials=sum(t.status == "diagnostic" for t in trials),
        dsr=dsr,
        pbo=pbo,
        pbo_cohort=cohort,
        hlz_t=measurement(t_value),
        hlz_status="insufficient_data"
        if t_value is None
        else "pass"
        if t_value >= diagnostics.hlz_t_hurdle
        else "fail",
        rank_in_family=ranks,
    )


class FamilyInterval(Contract):
    status: Literal["estimated", "insufficient_data"]
    raw_trials: NonNegativeInt
    means: list[float | None]
    standard_errors: list[float | None]
    adjusted_p: list[float | None]
    ci_lower: list[float | None]
    ci_upper: list[float | None]
    block_length: NonNegativeInt
    draws: NonNegativeInt
    index_sha256: Text | None
    method: Literal["romano_wolf_stepdown_studentized_maxT"]
    interval_method: Literal["simultaneous_full_family_maxT_envelope"]


def stepdown_max_t(observed: Array, bootstrap_t: Array, confidence: float) -> tuple[Array, Array]:
    """Romano-Wolf two-sided step-down maxT; monotone adjusted p-values.

    Returned critical values belong to the ordered hypothesis tests. They must
    not be used as rectangular simultaneous confidence-interval endpoints:
    that would incorrectly reuse the ordering for nonzero parameter values.
    All family members and every bootstrap draw must be present.
    """
    observed = np.asarray(observed, dtype=float)
    null = np.abs(np.asarray(bootstrap_t, dtype=float))
    if null.ndim != 2 or null.shape[1] != len(observed) or not len(null) or not 0 < confidence < 1:
        raise ValueError("invalid step-down family")
    if not np.isfinite(observed).all() or not np.isfinite(null).all():
        raise ValueError("step-down family contains missing statistics")
    order = np.argsort(-np.abs(observed), kind="stable")
    adjusted = np.zeros(len(observed))
    critical = np.zeros(len(observed))
    previous = 0.0
    for rank, index in enumerate(order):
        maxima = null[:, order[rank:]].max(axis=1)
        p = (1 + int((maxima >= abs(observed[index])).sum())) / (len(maxima) + 1)
        previous = max(previous, p)
        adjusted[index] = previous
        critical[index] = float(np.quantile(maxima, confidence, method="higher"))
    return adjusted, critical


def simultaneous_critical_value(bootstrap_t: Array, confidence: float) -> float:
    """Conservative joint envelope from the SAME centered studentized draws."""
    values = np.asarray(bootstrap_t, dtype=float)
    if (
        values.ndim != 2
        or not values.shape[0]
        or not values.shape[1]
        or not np.isfinite(values).all()
        or not 0 < confidence < 1
    ):
        raise ValueError("complete finite family draws required for simultaneous interval")
    return float(np.quantile(np.max(np.abs(values), axis=1), confidence, method="higher"))


def studentized_family(
    deltas: Array, config: BootstrapConfig, cycle: Cycle, *, seed: int, raw_trials: int
) -> FamilyInterval:
    matrix = np.asarray(deltas, dtype=float)
    if matrix.ndim != 2 or matrix.shape[1] != raw_trials or raw_trials < 1:
        raise ValueError("all declared family trials must be represented as columns")
    n, k = matrix.shape
    length = automatic_block_length(n, config.block_floors[cycle])
    base = dict(
        raw_trials=k,
        means=[None] * k,
        standard_errors=[None] * k,
        adjusted_p=[None] * k,
        ci_lower=[None] * k,
        ci_upper=[None] * k,
        block_length=length,
        draws=config.draws,
        index_sha256=None,
        method="romano_wolf_stepdown_studentized_maxT",
        interval_method="simultaneous_full_family_maxT_envelope",
    )

    def insufficient() -> FamilyInterval:
        return FamilyInterval.model_validate({**base, "status": "insufficient_data"})

    if config.draws < 10000:
        raise ValueError("official studentized inference requires >=10000 draws")
    if (
        n < config.minimum_periods
        or n // length < config.minimum_blocks
        or not np.isfinite(matrix).all()
    ):
        return insufficient()
    means = matrix.mean(axis=0)
    se = hac_standard_error(matrix.T, length - 1)
    base.update(means=means.tolist(), standard_errors=se.tolist())
    if not np.isfinite(se).all() or (se <= 0).any():
        return insufficient()
    indices = block_indices(n, length, config.draws, seed)
    base["index_sha256"] = index_hash(indices)
    null = np.empty((config.draws, k))
    # Bound intermediate RAM independently of the requested draw count.
    for begin in range(0, config.draws, 128):
        sample = matrix[indices[begin : begin + 128]]
        errors = hac_standard_error(sample.transpose(0, 2, 1), length - 1)
        if not np.isfinite(errors).all() or (errors <= 0).any():
            return insufficient()
        null[begin : begin + len(sample)] = (sample.mean(axis=1) - means) / errors
    adjusted, _ = stepdown_max_t(means / se, null, config.confidence)
    critical = simultaneous_critical_value(null, config.confidence)
    return FamilyInterval.model_validate(
        {
            **base,
            "status": "estimated",
            "adjusted_p": adjusted.tolist(),
            "ci_lower": (means - critical * se).tolist(),
            "ci_upper": (means + critical * se).tolist(),
        }
    )


def child_parent_interval(
    child: Array, parent: Array, config: BootstrapConfig, cycle: Cycle, *, seed: int
) -> FamilyInterval:
    if np.shape(child) != np.shape(parent) or np.ndim(child) != 1:
        raise ValueError("paired child/parent observations must share a grid")
    return studentized_family(
        (np.asarray(child) - np.asarray(parent))[:, None], config, cycle, seed=seed, raw_trials=1
    )
