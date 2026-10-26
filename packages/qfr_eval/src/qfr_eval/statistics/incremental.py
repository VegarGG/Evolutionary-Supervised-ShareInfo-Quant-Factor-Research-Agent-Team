"""Partial Spearman contribution with an explicitly fixed baseline pool."""

from typing import Literal

import numpy as np
from pydantic import NonNegativeInt
from qfr_core.contracts.base import Contract, Text
from qfr_core.contracts.reports import MetricValue
from qfr_core.metrics.core import correlation, measurement
from scipy.stats import rankdata

from qfr_eval.statistics.diagnostics import CrossSections


class IncrementalResult(Contract):
    convention: Literal["partial_spearman_ols_intercept"]
    status: Literal["estimated", "insufficient_data"]
    period_rank_ic: dict[Text, MetricValue]
    mean_rank_ic: MetricValue
    pool_correlations: dict[Text, MetricValue]
    max_pool_correlation: MetricValue
    pool_argmax: Text | None
    valid_periods: NonNegativeInt


def incremental_contribution(
    data: CrossSections, *, candidate: str, pool: list[str], epsilon: float
) -> IncrementalResult:
    if (
        not pool
        or len(set(pool)) != len(pool)
        or candidate in pool
        or any(name not in data.scores for name in [candidate, *pool])
        or epsilon <= 0
    ):
        raise ValueError("unique, separate candidate and baseline pool with tolerance required")
    values = {
        name: rankdata(data.scores[name], method="average", axis=1) for name in [candidate, *pool]
    }
    labels = rankdata(data.returns, method="average", axis=1)
    periods = {}
    correlations: dict[str, list[float | None]] = {name: [] for name in pool}
    for i, identity in enumerate(data.identities):
        x, y = values[candidate][i], labels[i]
        controls = np.column_stack([values[name][i] for name in pool])
        design = np.column_stack([np.ones(len(x)), controls])
        for name in pool:
            correlations[name].append(correlation(x, values[name][i], epsilon=epsilon))
        value = None
        if (
            np.isfinite(design).all()
            and np.isfinite(x).all()
            and np.isfinite(y).all()
            and len(x) > design.shape[1] + 1
        ):
            coefficient, _, rank, _ = np.linalg.lstsq(
                design, np.column_stack([x, y]), rcond=epsilon
            )
            if rank == design.shape[1]:
                residual = np.column_stack([x, y]) - design @ coefficient
                # Both already-ranked variables are residualized. Ranking residuals
                # again would define a different statistic from partial Spearman.
                value = correlation(residual[:, 0], residual[:, 1], epsilon=epsilon)
        periods[identity] = measurement(value)
    complete = bool(periods) and all(v.value is not None for v in periods.values())
    mean = float(np.mean([v.value for v in periods.values()])) if complete else None
    pooled = {
        name: measurement(
            float(np.mean(np.asarray(v, dtype=float)))
            if v and all(x is not None for x in v)
            else None
        )
        for name, v in correlations.items()
    }
    argmax = None
    maximum = None
    if complete and all(v.value is not None for v in pooled.values()):
        # Local 8.5: absolute value of the time-mean signed Spearman, then max.
        argmax = max(sorted(pooled), key=lambda name: abs(pooled[name].value or 0))
        maximum = abs(pooled[argmax].value or 0)
    return IncrementalResult(
        convention="partial_spearman_ols_intercept",
        status="estimated" if complete else "insufficient_data",
        period_rank_ic=periods,
        mean_rank_ic=measurement(mean),
        pool_correlations=pooled,
        max_pool_correlation=measurement(maximum),
        pool_argmax=argmax,
        valid_periods=sum(v.value is not None for v in periods.values()),
    )
