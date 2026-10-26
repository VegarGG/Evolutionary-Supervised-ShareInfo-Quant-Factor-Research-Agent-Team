"""Closed-form null detectability, explicitly conditional on independent periods."""

import math
from typing import Literal

from qfr_core.contracts.reports import MetricValue
from qfr_core.metrics.core import measurement


def null_variance(
    metric: Literal["rank_ic", "top_recall", "extreme_macro_recall"], universe: int, selected: int
) -> float:
    if not 0 < selected < universe / 2:
        raise ValueError("disjoint top/bottom groups and a nonempty middle are required")
    if metric == "rank_ic":
        return 1 / (universe - 1)
    # X ~ Hypergeometric(N, K, K); recall is X/K. Macro recall includes
    # positive covariance of the two disjoint extreme groups in one permutation.
    recall_variance = (1 - selected / universe) ** 2 / (universe - 1)
    if metric == "top_recall":
        return recall_variance
    if metric == "extreme_macro_recall":
        covariance = selected**2 / (universe**2 * (universe - 1))
        return (recall_variance + covariance) / 2
    raise ValueError("unknown metric identity")


def minimum_detectable_effect(
    metric: Literal["rank_ic", "top_recall", "extreme_macro_recall"],
    *,
    universe: int,
    selected: int,
    periods: int,
    critical_t: float,
) -> MetricValue:
    if periods < 0 or not math.isfinite(critical_t) or critical_t <= 0:
        raise ValueError("invalid detectability parameters")
    if periods == 0:
        return measurement(None)
    return measurement(critical_t * math.sqrt(null_variance(metric, universe, selected) / periods))
