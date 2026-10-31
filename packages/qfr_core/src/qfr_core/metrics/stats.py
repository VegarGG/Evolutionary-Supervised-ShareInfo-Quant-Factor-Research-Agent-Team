"""Newey-West t, PSR, DSR and PBO by CSCV (PLAN Sections 8.5 and 8.7)."""

import math
from itertools import combinations
from statistics import NormalDist

import numpy as np

from qfr_core.metrics.matrix import Array

EULER_GAMMA = 0.5772156649015329
_NORMAL = NormalDist()


def newey_west_lag(observations: int, horizon: int) -> int:
    """The larger of h and floor(4 (T / 100)^(2/9))."""
    return max(horizon, int(math.floor(4.0 * (observations / 100.0) ** (2.0 / 9.0))))


def newey_west_t(series: Array, lag: int) -> float | None:
    """Mean divided by its Newey-West standard error with Bartlett weights."""
    x = series[np.isfinite(series)]
    count = x.size
    if count < 2:
        return None
    dev = x - x.mean()
    variance = float(dev @ dev) / count
    for k in range(1, min(lag, count - 1) + 1):
        weight = 1.0 - k / (lag + 1.0)
        variance += 2.0 * weight * float(dev[k:] @ dev[:-k]) / count
    if not variance > 0:
        return None
    return float(x.mean() / math.sqrt(variance / count))


def moments(returns: Array) -> tuple[float, float, float, int]:
    """Per-period Sharpe (ddof 1), skewness and raw (Pearson) kurtosis, and T.

    Skewness and kurtosis are the population moment ratios used by Bailey and
    Lopez de Prado; kurtosis is 3 for a normal distribution.
    """
    x = returns[np.isfinite(returns)]
    count = x.size
    if count < 3:
        raise ValueError("at least three returns are needed")
    sd = float(x.std(ddof=1))
    if not sd > 0:
        raise ValueError("returns have no variance")
    dev = x - x.mean()
    m2 = float(np.mean(dev**2))
    skew = float(np.mean(dev**3)) / m2**1.5
    kurt = float(np.mean(dev**4)) / m2**2
    return float(x.mean()) / sd, skew, kurt, count


def psr(sharpe: float, benchmark: float, observations: int, skew: float, kurt: float) -> float:
    """PSR(SR*) = Phi((SR - SR*) sqrt(T - 1) / sqrt(1 - g3 SR + (g4 - 1) / 4 SR^2))."""
    spread = 1.0 - skew * sharpe + (kurt - 1.0) / 4.0 * sharpe**2
    if not spread > 0:
        raise ValueError("the PSR denominator is not positive for these moments")
    z = (sharpe - benchmark) * math.sqrt(observations - 1) / math.sqrt(spread)
    return _NORMAL.cdf(z)


def expected_max_sharpe(variance: float, trials: int) -> float:
    """SR0 = sqrt(V) ((1 - gamma) Phi^-1(1 - 1/N) + gamma Phi^-1(1 - 1/(N e)))."""
    if trials < 2:
        raise ValueError("the deflated Sharpe ratio needs at least two trials")
    if variance < 0:
        raise ValueError("the Sharpe variance must be non-negative")
    first = _NORMAL.inv_cdf(1.0 - 1.0 / trials)
    second = _NORMAL.inv_cdf(1.0 - 1.0 / (trials * math.e))
    return math.sqrt(variance) * ((1.0 - EULER_GAMMA) * first + EULER_GAMMA * second)


def dsr(
    sharpe: float, observations: int, skew: float, kurt: float, variance: float, trials: int
) -> float:
    """DSR = PSR(SR0) with SR0 from the trial count and the Sharpe variance."""
    return psr(sharpe, expected_max_sharpe(variance, trials), observations, skew, kurt)


def _sharpe_columns(block: Array) -> Array:
    with np.errstate(invalid="ignore", divide="ignore"):
        sd = block.std(axis=0, ddof=1)
        out = block.mean(axis=0) / sd
    out[~(sd > 0)] = np.nan
    return np.asarray(out, dtype=np.float64)


def _average_rank(values: Array, index: int) -> float:
    """1-based rank of values[index] among values, ties averaged."""
    target = values[index]
    below = float(np.sum(values < target))
    equal = float(np.sum(values == target))
    return below + (equal + 1.0) / 2.0


def pbo(returns: Array, blocks: int) -> tuple[float, list[float]]:
    """Probability of backtest overfitting by CSCV (Bailey, Borwein, Lopez de Prado, Zhu).

    returns is the T x N matrix of daily returns, one column per version. Rows split into
    S = blocks contiguous blocks (the protocol's pbo_blocks); for each choice of S/2
    in-sample blocks, the best in-sample column's out-of-sample relative rank
    w = rank / (N + 1) gives lambda = ln(w / (1 - w)).
    PBO is the share of lambda <= 0. Ties in in-sample Sharpe pick the first column.
    Returns PBO and the lambda values in combination order.
    """
    if returns.ndim != 2 or returns.shape[1] < 2:
        raise ValueError("PBO needs a T x N matrix with N >= 2")
    if blocks < 2 or blocks % 2:
        raise ValueError("the block count must be even and at least 2")
    if not np.isfinite(returns).all():
        raise ValueError("PBO needs complete returns; drop or fill missing days first")
    parts = np.array_split(np.arange(returns.shape[0]), blocks)
    if min(len(p) for p in parts) < 2:
        raise ValueError("each block needs at least two rows")
    columns = returns.shape[1]
    logits: list[float] = []
    for chosen in combinations(range(blocks), blocks // 2):
        inside = np.concatenate([parts[b] for b in chosen])
        outside = np.concatenate([parts[b] for b in range(blocks) if b not in chosen])
        in_sharpe = _sharpe_columns(returns[inside])
        out_sharpe = _sharpe_columns(returns[outside])
        if np.isnan(in_sharpe).all():
            continue
        best = int(np.nanargmax(in_sharpe))
        filled = np.where(np.isnan(out_sharpe), -np.inf, out_sharpe)
        omega = _average_rank(filled, best) / (columns + 1.0)
        logits.append(math.log(omega / (1.0 - omega)))
    if not logits:
        raise ValueError("no combination had a defined in-sample Sharpe ratio")
    return float(np.mean(np.array(logits) <= 0.0)), logits
