"""Evaluator-owned flags. Missing, unstable and inapplicable evidence never pass."""

from typing import Literal

import numpy as np
from pydantic import NonNegativeInt
from qfr_core.contracts.base import Contract
from qfr_core.contracts.reports import MetricValue

from qfr_eval.protocols.models import FrozenProtocol
from qfr_eval.statistics.bootstrap import Interval, automatic_block_length
from qfr_eval.statistics.family import FamilyInterval

GateStatus = Literal["pass", "fail", "insufficient_data", "not_applicable"]


class TurnoverResult(Contract):
    status: GateStatus
    eligible_decisions: NonNegativeInt
    missing_decisions: NonNegativeInt
    excluded_initial: NonNegativeInt
    exceedances: NonNegativeInt | None
    threshold: float | None
    mean: float | None
    p95: float | None
    maximum: float | None


def turnover_flag(
    values: list[float | None],
    initial: list[bool],
    protocol: FrozenProtocol,
    *,
    cycle: str,
    basket: Literal["top", "bottom"],
    required_evidence_complete: bool = True,
) -> TurnoverResult:
    if len(values) != len(initial) or sum(initial) > 1:
        raise ValueError("one genuine initial construction may be excluded")
    selected = np.asarray([v for v, i in zip(values, initial, strict=True) if not i], dtype=float)
    n = len(selected)
    base: dict[str, int | float | None] = dict(
        eligible_decisions=n,
        missing_decisions=int((~np.isfinite(selected)).sum()),
        excluded_initial=sum(initial),
        exceedances=None,
        threshold=None,
        mean=None,
        p95=None,
        maximum=None,
    )
    policy = protocol.turnover
    if policy is None or cycle != policy.cycle:
        return TurnoverResult.model_validate({**base, "status": "not_applicable"})
    threshold = policy.top_threshold if basket == "top" else policy.bottom_threshold
    base["threshold"] = threshold
    length = automatic_block_length(n, protocol.bootstrap.block_floors["weekly"])
    if (
        not required_evidence_complete
        or base["missing_decisions"]
        or n < protocol.bootstrap.minimum_periods
        or n // length < protocol.bootstrap.minimum_blocks
        or (selected < 0).any()
    ):
        return TurnoverResult.model_validate({**base, "status": "insufficient_data"})
    count = int((selected > threshold).sum())
    passes = (
        count * policy.maximum_exceedance_denominator <= n * policy.maximum_exceedance_numerator
    )
    return TurnoverResult.model_validate(
        {
            **base,
            "status": "pass" if passes else "fail",
            "exceedances": count,
            "mean": float(selected.mean()),
            "p95": float(np.quantile(selected, 0.95, method="linear")),
            "maximum": float(selected.max()),
        }
    )


def fold_majority(yearly: list[float | None], leave_one_out: list[float | None]) -> GateStatus:
    if len(yearly) < 2 or len(leave_one_out) != len(yearly):
        return "insufficient_data"
    if not np.isfinite(np.asarray([*yearly, *leave_one_out], dtype=float)).all():
        return "insufficient_data"
    return (
        "pass"
        if sum(v > 0 for v in yearly if v is not None) > len(yearly) / 2
        and all(v is not None and v > 0 for v in leave_one_out)
        else "fail"
    )


def pilot_hurdle(
    family: FamilyInterval,
    candidate: int,
    protocol: FrozenProtocol,
    *,
    incremental_rank_ic: MetricValue,
    placebo_percentile: MetricValue,
    max_pool_correlation: MetricValue,
    folds: GateStatus,
    top_turnover: TurnoverResult,
    bottom_turnover: TurnoverResult,
    block_sensitivity: list[Interval],
) -> dict[str, GateStatus]:
    if not 0 <= candidate < family.raw_trials:
        raise ValueError("candidate absent from full trial family")

    def threshold(metric: MetricValue, limit: float, above: bool) -> GateStatus:
        if metric.value is None:
            return "insufficient_data"
        return "pass" if (metric.value > limit if above else metric.value < limit) else "fail"

    low, p = family.ci_lower[candidate], family.adjusted_p[candidate]
    paired: GateStatus = "insufficient_data"
    if family.status == "estimated" and low is not None and p is not None:
        paired = "pass" if low > 0 and p <= 1 - protocol.bootstrap.confidence else "fail"
    turnover: GateStatus = "insufficient_data"
    if top_turnover.status in ("pass", "fail") and bottom_turnover.status in ("pass", "fail"):
        turnover = "pass" if top_turnover.status == bottom_turnover.status == "pass" else "fail"
    stability: GateStatus = "insufficient_data"
    if block_sensitivity and all(
        i.status == "estimated" and i.ci_lower is not None for i in block_sensitivity
    ):
        decisions = {i.ci_lower > 0 for i in block_sensitivity if i.ci_lower is not None}
        stability = "pass" if len(decisions) == 1 else "fail"
    flags: dict[str, GateStatus] = {
        "paired_primary": paired,
        "incremental_contribution": threshold(incremental_rank_ic, 0, True),
        "fold_majority": folds,
        "placebo": threshold(
            placebo_percentile, protocol.diagnostics.placebo_percentile_hurdle, True
        ),
        "novelty": threshold(
            max_pool_correlation, protocol.diagnostics.max_pool_correlation, False
        ),
        "turnover": turnover,
        "uncertainty_stability": stability,
    }
    flags["overall"] = (
        "pass"
        if all(v == "pass" for v in flags.values())
        else ("insufficient_data" if "insufficient_data" in flags.values() else "fail")
    )
    return flags
