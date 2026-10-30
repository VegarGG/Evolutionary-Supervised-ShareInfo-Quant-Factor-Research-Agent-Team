"""Dense date-by-instrument matrices and row-wise statistics for the metrics library.

Every metric works on (T, N) float64 matrices with NaN for missing values: one row per
trading date, one column per instrument, columns sorted by instrument id. Row-wise
helpers treat NaN as absent and never look across rows.
"""

from dataclasses import dataclass
from datetime import date
from typing import Self

import numpy as np
import polars as pl
from numpy.typing import NDArray

from qfr_core.data.panel import DATE, INSTRUMENT
from qfr_core.eligibility import Eligibility

Array = NDArray[np.float64]
Mask = NDArray[np.bool_]


@dataclass(frozen=True)
class Market:
    """The panel as matrices. Cells outside an instrument's rows are NaN or False."""

    dates: list[date]
    instruments: list[str]
    rows: NDArray[np.int64]  # Panel row -> date index.
    cols: NDArray[np.int64]  # Panel row -> instrument index.
    close: Array
    adv20: Array
    eligible: Mask
    tradable: Mask  # Traded that day (not suspended); False outside the panel.
    limit_up: Mask
    limit_down: Mask
    benchmark_ret: Array
    minimum: int

    @classmethod
    def from_panel(
        cls, panel: pl.DataFrame, eligibility: Eligibility, calendar: pl.DataFrame | None = None
    ) -> Self:
        """Panel sorted by instrument and date; calendar gives dates and benchmark_ret."""
        if calendar is None:
            calendar = (
                panel.select(DATE).unique().sort(DATE).with_columns(benchmark_ret=pl.lit(None))
            )
        dates = calendar.get_column(DATE).to_list()
        instruments = panel.get_column(INSTRUMENT).unique().sort().to_list()
        rows = (
            calendar.get_column(DATE)
            .search_sorted(panel.get_column(DATE), side="left")
            .to_numpy()
            .astype(np.int64)
        )
        cols = (
            pl.Series(instruments, dtype=pl.String)
            .search_sorted(panel.get_column(INSTRUMENT), side="left")
            .to_numpy()
            .astype(np.int64)
        )
        shape = (len(dates), len(instruments))
        base = cls(
            dates=dates,
            instruments=instruments,
            rows=rows,
            cols=cols,
            close=np.full(shape, np.nan),
            adv20=np.full(shape, np.nan),
            eligible=np.zeros(shape, dtype=bool),
            tradable=np.zeros(shape, dtype=bool),
            limit_up=np.zeros(shape, dtype=bool),
            limit_down=np.zeros(shape, dtype=bool),
            benchmark_ret=calendar.get_column("benchmark_ret")
            .cast(pl.Float64)
            .to_numpy()
            .astype(np.float64),
            minimum=eligibility.cross_section_min,
        )
        base.close[rows, cols] = _floats(panel.get_column("close"))
        base.adv20[rows, cols] = _floats(panel.get_column("adv20"))
        base.eligible[rows, cols] = panel.select(eligibility.mask()).to_series().to_numpy()
        base.tradable[rows, cols] = ~panel.get_column("is_suspended").to_numpy()
        base.limit_up[rows, cols] = panel.get_column("limit_up").to_numpy()
        base.limit_down[rows, cols] = panel.get_column("limit_down").to_numpy()
        return base

    @classmethod
    def from_matrices(
        cls,
        dates: list[date],
        instruments: list[str],
        close: Array,
        eligible: Mask,
        minimum: int,
        *,
        adv20: Array | None = None,
        tradable: Mask | None = None,
        limit_up: Mask | None = None,
        limit_down: Mask | None = None,
        benchmark_ret: Array | None = None,
    ) -> Self:
        """A market built directly from matrices (the generator and hand fixtures)."""
        shape = (len(dates), len(instruments))
        if close.shape != shape or eligible.shape != shape:
            raise ValueError("matrices must be dates x instruments")
        empty = np.zeros(0, dtype=np.int64)
        return cls(
            dates=list(dates),
            instruments=list(instruments),
            rows=empty,
            cols=empty,
            close=close.astype(np.float64),
            adv20=np.full(shape, np.nan) if adv20 is None else adv20,
            eligible=eligible.astype(bool),
            tradable=np.isfinite(close) if tradable is None else tradable,
            limit_up=np.zeros(shape, dtype=bool) if limit_up is None else limit_up,
            limit_down=np.zeros(shape, dtype=bool) if limit_down is None else limit_down,
            benchmark_ret=np.full(shape[0], np.nan) if benchmark_ret is None else benchmark_ret,
            minimum=minimum,
        )

    @property
    def shape(self) -> tuple[int, int]:
        return len(self.dates), len(self.instruments)

    def matrix(self, values: pl.Series | Array) -> Array:
        """Place a series aligned with the panel's rows into a (T, N) matrix."""
        out = np.full(self.shape, np.nan)
        out[self.rows, self.cols] = (
            _floats(values) if isinstance(values, pl.Series) else values.astype(np.float64)
        )
        return out

    def window(self, start: date, end: date) -> tuple[int, int]:
        """Inclusive date-index bounds of [start, end]."""
        days = np.array(self.dates, dtype="datetime64[D]")
        first = int(np.searchsorted(days, np.datetime64(start, "D"), side="left"))
        last = int(np.searchsorted(days, np.datetime64(end, "D"), side="right")) - 1
        if last < first:
            raise ValueError(f"no trading dates in [{start}, {end}]")
        return first, last


def _floats(series: pl.Series) -> Array:
    return series.cast(pl.Float64).fill_null(np.nan).to_numpy().astype(np.float64)


def forward_label(close: Array, horizon: int, last: int | None = None) -> Array:
    """y(t, h) = close[t+1+h] / close[t+1] - 1 (PLAN 6.5).

    With last, labels whose end day t+1+h falls after date index last are NaN, so a
    window never uses prices from outside itself.
    """
    out = np.full(close.shape, np.nan)
    days = close.shape[0]
    if days > 1 + horizon:
        with np.errstate(invalid="ignore", divide="ignore"):
            out[: days - 1 - horizon] = close[1 + horizon :] / close[1 : days - horizon] - 1.0
    if last is not None:
        out[max(last - horizon, 0) :] = np.nan
    out[~np.isfinite(out)] = np.nan
    return out


def rank_rows(values: Array) -> Array:
    """Average ranks 1..n per row over finite values (ties averaged); NaN elsewhere."""
    finite = np.isfinite(values)
    filled = np.where(finite, values, np.inf)
    order = np.argsort(filled, axis=1, kind="stable")
    ordered = np.take_along_axis(filled, order, axis=1)
    width = values.shape[1]
    position = np.broadcast_to(np.arange(width), values.shape)
    starts = np.ones(values.shape, dtype=bool)
    starts[:, 1:] = ordered[:, 1:] != ordered[:, :-1]
    ends = np.ones(values.shape, dtype=bool)
    ends[:, :-1] = starts[:, 1:]
    first = np.maximum.accumulate(np.where(starts, position, 0), axis=1)
    last = np.minimum.accumulate(np.where(ends, position, width - 1)[:, ::-1], axis=1)[:, ::-1]
    average = (first + last) / 2.0 + 1.0
    ranks = np.empty(values.shape)
    np.put_along_axis(ranks, order, average, axis=1)
    ranks[~finite] = np.nan
    return ranks


def row_pearson(a: Array, b: Array, minimum: int = 2) -> Array:
    """Pearson correlation per row on cells where both are finite; NaN below minimum."""
    joint = np.isfinite(a) & np.isfinite(b)
    count = joint.sum(axis=1)
    x = np.where(joint, a, 0.0)
    y = np.where(joint, b, 0.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        dx = np.where(joint, x - x.sum(axis=1, keepdims=True) / count[:, None], 0.0)
        dy = np.where(joint, y - y.sum(axis=1, keepdims=True) / count[:, None], 0.0)
        denominator = np.sqrt((dx * dx).sum(axis=1) * (dy * dy).sum(axis=1))
        out = (dx * dy).sum(axis=1) / denominator
    out[(count < minimum) | ~(denominator > 1e-300)] = np.nan
    return np.asarray(out, dtype=np.float64)


def row_spearman(a: Array, b: Array, minimum: int = 2) -> Array:
    """Spearman per row: Pearson on ranks over the joint finite set, ties averaged."""
    joint = np.isfinite(a) & np.isfinite(b)
    ra = rank_rows(np.where(joint, a, np.nan))
    rb = rank_rows(np.where(joint, b, np.nan))
    return row_pearson(ra, rb, minimum)


def winsorize_rows(values: Array, lower: float, upper: float) -> Array:
    """Clip each row at its lower and upper quantiles (linear interpolation)."""
    out = values.copy()
    has = np.isfinite(values).any(axis=1)
    if has.any():
        bounds = np.nanquantile(values[has], [lower, upper], axis=1)
        out[has] = np.clip(values[has], bounds[0][:, None], bounds[1][:, None])
    return out


def zscore_rows(values: Array) -> Array:
    """(x - mean) / std per row, ddof 1; NaN when the spread is below 1e-12."""
    finite = np.isfinite(values)
    count = finite.sum(axis=1)
    filled = np.where(finite, values, 0.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = filled.sum(axis=1) / count
        dev = np.where(finite, values - mean[:, None], np.nan)
        spread = np.sqrt(np.nansum(dev * dev, axis=1) / (count - 1))
        out = dev / spread[:, None]
    out[~(spread >= 1e-12)] = np.nan
    return np.asarray(out, dtype=np.float64)


def residualize_rows(values: Array, regressor: Array) -> Array:
    """Per-row OLS residual of values on a constant and regressor (joint finite cells)."""
    joint = np.isfinite(values) & np.isfinite(regressor)
    count = joint.sum(axis=1)
    x = np.where(joint, regressor, 0.0)
    y = np.where(joint, values, 0.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        dx = np.where(joint, x - x.sum(axis=1, keepdims=True) / count[:, None], 0.0)
        dy = np.where(joint, y - y.sum(axis=1, keepdims=True) / count[:, None], 0.0)
        sxx = (dx * dx).sum(axis=1)
        beta = np.where(sxx >= 1e-12, (dx * dy).sum(axis=1) / sxx, np.nan)
    out = dy - beta[:, None] * dx
    out[~joint] = np.nan
    return np.asarray(out, dtype=np.float64)
