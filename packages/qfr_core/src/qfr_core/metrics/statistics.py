"""PSR, DSR and CSCV primitives; no ledger, cohort selection or acceptance policy."""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import combinations
from typing import Self

import numpy as np
from pydantic import Field, PositiveInt, model_validator
from scipy.stats import norm, rankdata

from qfr_core.contracts.base import Contract
from qfr_core.contracts.reports import MetricValue
from qfr_core.metrics.core import Array, measurement


class StatisticsConfig(Contract):
    revision: PositiveInt
    min_observations: int = Field(ge=3)
    min_pbo_candidates: int = Field(ge=4)
    pbo_blocks: int = Field(ge=2)
    zero_epsilon: float = Field(gt=0)

    @model_validator(mode="after")
    def even_blocks(self) -> Self:
        if self.pbo_blocks % 2:
            raise ValueError("CSCV needs an even number of blocks")
        return self


@dataclass(frozen=True)
class SharpeMoments:
    observations: int
    sharpe: float
    skewness: float
    pearson_kurtosis: float


def sharpe_moments(
    returns: Sequence[float] | Array, config: StatisticsConfig
) -> SharpeMoments | None:
    """Sample-standard-deviation Sharpe; empirical central-moment skew/raw kurtosis.

    Missing observations must be resolved by the caller's window policy, never dropped here.
    """
    sample = np.asarray(returns, dtype=float)
    if sample.ndim != 1:
        raise ValueError("returns must be a vector")
    if len(sample) < config.min_observations or not np.isfinite(sample).all():
        return None
    std = float(sample.std(ddof=1))
    if std < config.zero_epsilon:
        return None
    centered = sample - sample.mean()
    second = float(np.mean(centered**2))
    return SharpeMoments(
        len(sample),
        float(sample.mean()) / std,
        float(np.mean(centered**3)) / second**1.5,
        float(np.mean(centered**4)) / second**2,
    )


def probabilistic_sharpe(moments: SharpeMoments | None, benchmark: float) -> MetricValue:
    if not math.isfinite(benchmark):
        raise ValueError("benchmark Sharpe must be finite")
    if moments is None:
        return measurement(None)
    t, sr, skew, kurtosis = (
        moments.observations,
        moments.sharpe,
        moments.skewness,
        moments.pearson_kurtosis,
    )
    if t < 3 or not all(math.isfinite(x) for x in (sr, skew, kurtosis)) or kurtosis < 1:
        return measurement(None)
    variance = 1 - skew * sr + (kurtosis - 1) / 4 * sr**2
    if variance <= 0:
        return measurement(None)
    return measurement(float(norm.cdf((sr - benchmark) * math.sqrt(t - 1) / math.sqrt(variance))))


@dataclass(frozen=True)
class DeflatedSharpe:
    probability: MetricValue
    raw_trials: int
    effective_trials: int
    sharpe_variance: MetricValue
    expected_maximum_sharpe: MetricValue


def expected_maximum_sharpe(variance: float, effective_trials: int) -> float:
    if not math.isfinite(variance) or variance < 0 or effective_trials < 1:
        raise ValueError("invalid trial variance or effective count")
    # A single unskilled trial has expected SR zero. The asymptotic maximum
    # approximation is only defined for N > 1.
    if effective_trials == 1 or variance == 0:
        return 0.0
    gamma = float(np.euler_gamma)
    return float(
        math.sqrt(variance)
        * (
            (1 - gamma) * norm.ppf(1 - 1 / effective_trials)
            + gamma * norm.ppf(1 - 1 / (effective_trials * math.e))
        )
    )


def deflated_sharpe(
    moments: SharpeMoments | None, trial_sharpes: Sequence[float], *, effective_trials: int
) -> DeflatedSharpe:
    sample = np.asarray(trial_sharpes, dtype=float)
    n = len(sample)
    if sample.ndim != 1 or not 1 <= effective_trials <= n:
        raise ValueError("effective count must be between one and the raw trial count")
    if n < 2 or not np.isfinite(sample).all():
        return DeflatedSharpe(
            measurement(None), n, effective_trials, measurement(None), measurement(None)
        )
    variance = float(sample.var(ddof=1))
    benchmark = expected_maximum_sharpe(variance, effective_trials)
    return DeflatedSharpe(
        probabilistic_sharpe(moments, benchmark),
        n,
        effective_trials,
        measurement(variance),
        measurement(benchmark),
    )


@dataclass(frozen=True)
class ProbabilityOfOverfit:
    probability: MetricValue
    candidates: int
    combinations: int
    invalid_combinations: int
    logits: tuple[float, ...]


def probability_of_overfit(returns: Array, config: StatisticsConfig) -> ProbabilityOfOverfit:
    """CSCV: ascending average OOS rank/(N+1), stable lowest-index IS tie break.

    Invalid inputs/splits give a missing statistic, never a successful gate or a
    reduced cohort. Block sufficient statistics avoid copying every split.
    """
    matrix = np.asarray(returns, dtype=float)
    if matrix.ndim != 2:
        raise ValueError("CSCV needs a T by N matrix")
    t, n = matrix.shape
    blocks = config.pbo_blocks
    if n < config.min_pbo_candidates or t < blocks or not np.isfinite(matrix).all():
        return ProbabilityOfOverfit(measurement(None), n, 0, 0, ())
    parts = np.array_split(matrix, blocks)
    counts = np.array([len(part) for part in parts])
    sums = np.array([part.sum(axis=0) for part in parts])
    squares = np.array([(part**2).sum(axis=0) for part in parts])
    logits: list[float] = []
    invalid = 0
    total = math.comb(blocks, blocks // 2)

    def sharpes(indices: list[int]) -> Array | None:
        count = int(counts[indices].sum())
        summed = sums[indices].sum(axis=0)
        variance = (
            (squares[indices].sum(axis=0) - summed**2 / count) / (count - 1)
            if count > 1
            else np.zeros(n)
        )
        if count < config.min_observations or (variance < config.zero_epsilon**2).any():
            return None
        result: Array = summed / count / np.sqrt(variance)
        return result

    for chosen in combinations(range(blocks), blocks // 2):
        inside = sharpes(list(chosen))
        outside = sharpes([i for i in range(blocks) if i not in chosen])
        if inside is None or outside is None:
            invalid += 1
            continue
        winner = int(np.argmax(inside))
        omega = float(rankdata(outside, method="average")[winner]) / (n + 1)
        logits.append(math.log(omega / (1 - omega)))
    probability = sum(value <= 0 for value in logits) / total if invalid == 0 else None
    return ProbabilityOfOverfit(measurement(probability), n, total, invalid, tuple(logits))
