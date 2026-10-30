"""Exact two-pass window kernels for one instrument's dense series.

Polars' one-pass rolling variance, skewness, kurtosis and correlation lose precision on
large-magnitude inputs such as $amount (see docs/decisions.md), so these statistics are
computed here over explicit windows. Inputs are float64 arrays with NaN for null; each
window covers d calendar rows ending at the current row, rows before the instrument's
first observation count as invalid, and the output is NaN unless the window holds at
least min_valid(d) valid values (PLAN Section 7.3).
"""

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from numpy.typing import NDArray

from qfr_core.dsl.catalog import DIVISION_EPSILON, min_valid

Array = NDArray[np.float64]


def windows(values: Array, days: int) -> Array:
    padded = np.concatenate([np.full(days - 1, np.nan), values.astype(np.float64)])
    return sliding_window_view(padded, days)


def _prepare(values: Array, days: int, need: int) -> tuple[Array, NDArray[np.bool_], Array]:
    window = windows(values, days)
    valid = ~np.isnan(window)
    count = valid.sum(axis=1).astype(np.float64)
    count[count < max(min_valid(days), need)] = np.nan
    return np.where(valid, window, 0.0), valid, count


def _centered(filled: Array, valid: NDArray[np.bool_], count: Array) -> Array:
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = filled.sum(axis=1) / count
    dev = filled - mean[:, None]
    dev *= valid
    return dev


def _dot(a: Array, b: Array) -> Array:
    """Row-wise sum of products without a temporary matrix."""
    result: Array = np.einsum("ij,ij->i", a, b)
    return result


def _safe_divide(numerator: Array, denominator: Array) -> Array:
    with np.errstate(invalid="ignore", divide="ignore"):
        out = numerator / denominator
    out[~(np.abs(denominator) >= DIVISION_EPSILON)] = np.nan
    return out


def variance(values: Array, days: int) -> Array:
    filled, valid, count = _prepare(values, days, 2)
    dev = _centered(filled, valid, count)
    with np.errstate(invalid="ignore"):
        return _dot(dev, dev) / (count - 1)


def std(values: Array, days: int) -> Array:
    with np.errstate(invalid="ignore"):
        return np.sqrt(variance(values, days))


def ts_zscore(values: Array, days: int) -> Array:
    filled, valid, count = _prepare(values, days, 2)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = filled.sum(axis=1) / count
    dev = filled - mean[:, None]
    dev *= valid
    with np.errstate(invalid="ignore"):
        sd = np.sqrt(_dot(dev, dev) / (count - 1))
    return _safe_divide(values.astype(np.float64) - mean, sd)


def _standardized(values: Array, days: int, need: int) -> tuple[Array, Array]:
    filled, valid, count = _prepare(values, days, need)
    dev = _centered(filled, valid, count)
    with np.errstate(invalid="ignore"):
        population_sd = np.sqrt(_dot(dev, dev) / count)
    scale = np.where(population_sd >= DIVISION_EPSILON, population_sd, np.nan)
    with np.errstate(invalid="ignore"):
        dev /= scale[:, None]
    return dev, count


def skew(values: Array, days: int) -> Array:
    """Adjusted Fisher-Pearson sample skewness G1."""
    z, n = _standardized(values, days, 3)
    with np.errstate(invalid="ignore"):
        g1 = _dot(z * z, z) / n
        return g1 * np.sqrt(n * (n - 1)) / (n - 2)


def kurt(values: Array, days: int) -> Array:
    """Sample excess kurtosis G2."""
    z, n = _standardized(values, days, 4)
    with np.errstate(invalid="ignore"):
        squared = z * z
        g2 = _dot(squared, squared) / n - 3.0
        return ((n + 1) * g2 + 6.0) * (n - 1) / ((n - 2) * (n - 3))


def _pair(a: Array, b: Array, days: int) -> tuple[Array, Array, Array]:
    wa, wb = windows(a, days), windows(b, days)
    valid = ~np.isnan(wa) & ~np.isnan(wb)
    count = valid.sum(axis=1).astype(np.float64)
    count[count < max(min_valid(days), 2)] = np.nan
    fa, fb = np.where(valid, wa, 0.0), np.where(valid, wb, 0.0)
    return _centered(fa, valid, count), _centered(fb, valid, count), count


def cov(a: Array, b: Array, days: int) -> Array:
    da, db, count = _pair(a, b, days)
    with np.errstate(invalid="ignore"):
        return _dot(da, db) / (count - 1)


def corr(a: Array, b: Array, days: int) -> Array:
    da, db, count = _pair(a, b, days)
    with np.errstate(invalid="ignore"):
        covariance = _dot(da, db) / (count - 1)
        sa = np.sqrt(_dot(da, da) / (count - 1))
        sb = np.sqrt(_dot(db, db) / (count - 1))
    return _safe_divide(covariance, sa * sb)


def _regression(values: Array, days: int, need: int) -> tuple[Array, Array, Array, Array, Array]:
    """Least squares of x on the window position 0..d-1 (today is d-1), valid points only."""
    filled, valid, count = _prepare(values, days, need)
    tau = np.where(valid, np.arange(days, dtype=np.float64)[None, :], 0.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        tau_mean = tau.sum(axis=1) / count
        x_mean = filled.sum(axis=1) / count
    dt = np.where(valid, tau - tau_mean[:, None], 0.0)
    dx = np.where(valid, filled - x_mean[:, None], 0.0)
    stt = _dot(dt, dt)
    stx = _dot(dt, dx)
    sxx = _dot(dx, dx)
    with np.errstate(invalid="ignore", divide="ignore"):
        slope = stx / stt
    return slope, x_mean, tau_mean, stx**2 / np.where(stt > 0, stt, np.nan), sxx


def slope(values: Array, days: int) -> Array:
    return _regression(values, days, 2)[0]


def rsq(values: Array, days: int) -> Array:
    _, _, _, explained, sxx = _regression(values, days, 3)
    return _safe_divide(explained, sxx)


def resi(values: Array, days: int) -> Array:
    beta, x_mean, tau_mean, _, _ = _regression(values, days, 3)
    # Centered form avoids cancelling two large fitted values.
    return (values.astype(np.float64) - x_mean) - beta * ((days - 1) - tau_mean)


def wma(values: Array, days: int) -> Array:
    """Linearly decaying weights: today d, yesterday d-1, ..., oldest 1; valid points only."""
    filled, valid, count = _prepare(values, days, 1)
    weights = np.where(valid, np.arange(1, days + 1, dtype=np.float64)[None, :], 0.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        out: Array = (weights * filled).sum(axis=1) / weights.sum(axis=1)
    out[np.isnan(count)] = np.nan
    return out


def _days_since(values: Array, days: int, largest: bool) -> Array:
    window = windows(values, days)
    valid = ~np.isnan(window)
    count = valid.sum(axis=1)
    fill = -np.inf if largest else np.inf
    reversed_window = np.where(valid, window, fill)[:, ::-1]
    # Reversed, the first extreme is the most recent one: 0 means today.
    position = np.argmax(reversed_window, axis=1) if largest else np.argmin(reversed_window, axis=1)
    out = position.astype(np.float64)
    out[count < min_valid(days)] = np.nan
    return out


def argmax(values: Array, days: int) -> Array:
    return _days_since(values, days, largest=True)


def argmin(values: Array, days: int) -> Array:
    return _days_since(values, days, largest=False)
