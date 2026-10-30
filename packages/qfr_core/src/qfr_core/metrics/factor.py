"""Factor metrics for one window (PLAN Section 8.5), shared by the evaluator and the
research workbench so both compute exactly the same numbers.

Notation follows the plan. U(t) is the eligible set on day t with a finite factor and a
finite label; dates with fewer than the protocol minimum are skipped. f(t) is the factor
winsorized at the 1st and 99th percentiles and z-scored over U(t). s is the declared
sign; quintile 5 holds the highest f. "The previous date" is the previous evaluated
date in the window. Quantile ties are ordered by ascending instrument id.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Literal, Self

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict, Field, JsonValue

from qfr_core.metrics.matrix import (
    Array,
    Market,
    Mask,
    forward_label,
    residualize_rows,
    row_pearson,
    row_spearman,
    winsorize_rows,
    zscore_rows,
)
from qfr_core.metrics.stats import newey_west_lag, newey_west_t

PERIODS_PER_YEAR = 252


class MetricSettings(BaseModel):
    """The protocol fields the metrics depend on."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    winsor_lower: float = Field(ge=0, lt=0.5)
    winsor_upper: float = Field(gt=0.5, le=1)
    quantiles: int = Field(ge=2)
    horizons: tuple[int, ...]
    primary_horizon: int
    ls_cost_bps_per_side: float = Field(ge=0)

    @classmethod
    def from_protocol(cls, protocol: dict[str, JsonValue]) -> Self:
        preprocessing = protocol["preprocessing"]
        label = protocol["label"]
        costs = protocol["costs"]
        assert isinstance(preprocessing, dict) and isinstance(label, dict)
        assert isinstance(costs, dict) and isinstance(label["horizons"], list)
        return cls.model_validate(
            {
                "winsor_lower": preprocessing["winsor_lower"],
                "winsor_upper": preprocessing["winsor_upper"],
                "quantiles": protocol["quantiles"],
                "horizons": tuple(label["horizons"]),
                "primary_horizon": label["primary"],
                "ls_cost_bps_per_side": costs["long_short_bps_per_side"],
            }
        )


class LibraryCorrelation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    vacuous: bool
    max_abs: float | None
    argmax: str | None
    note: str | None


class FactorMetrics(BaseModel):
    """Full-precision metrics for one factor on one window."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    start: date
    end: date
    sign: Literal[1, -1]
    dates_evaluated: int
    ic_mean: float | None
    rankic_mean: float | None
    rankic_std: float | None
    rankic_ir: float | None
    rankic_t_nw: float | None
    nw_lag: int
    hit_ratio: float | None
    sign_consistency: int
    decay: dict[str, float | None]
    quantile_returns: list[float | None]
    ls_gross_mean: float | None
    ls_gross_sharpe: float | None
    ls_net_mean: float | None
    ls_net_sharpe: float | None
    top_turnover: float | None
    bottom_turnover: float | None
    monotonicity: float | None
    rank_autocorrelation: float | None
    coverage: float | None
    library_correlation: LibraryCorrelation
    size_neutral_rankic: float | None
    yearly_rankic: dict[str, float | None]


@dataclass(frozen=True)
class FactorSeries:
    """Daily series behind the metrics, aligned with dates (NaN on skipped dates)."""

    dates: list[date]
    ic: Array
    rank_ic: Array
    ls: Array
    ls_net: Array
    top_turnover: Array
    bottom_turnover: Array
    quantile_returns: Array  # (T, quantiles)


@dataclass(frozen=True)
class FactorEvaluation:
    metrics: FactorMetrics
    series: FactorSeries


def _finite(value: float | np.floating | None) -> float | None:
    if value is None:
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _mean(values: Array) -> float | None:
    x = values[np.isfinite(values)]
    return float(x.mean()) if x.size else None


def _std(values: Array) -> float | None:
    x = values[np.isfinite(values)]
    return float(x.std(ddof=1)) if x.size >= 2 else None


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or not denominator > 0:
        return None
    return numerator / denominator


def sharpe(values: Array, periods: int = PERIODS_PER_YEAR) -> float | None:
    """Annualized mean / std (ddof 1) times sqrt(periods)."""
    ratio = _ratio(_mean(values), _std(values))
    return None if ratio is None else ratio * math.sqrt(periods)


def preprocess(factor: Array, sample: Mask, settings: MetricSettings) -> Array:
    """Winsorize then z-score each date over the sample cells."""
    x = np.where(sample, factor, np.nan)
    return zscore_rows(winsorize_rows(x, settings.winsor_lower, settings.winsor_upper))


def _sample(factor: Array, label: Array, eligible: Mask, minimum: int) -> tuple[Mask, Mask]:
    sample = eligible & np.isfinite(factor) & np.isfinite(label)
    evaluated = sample.sum(axis=1) >= minimum
    sample[~evaluated] = False
    return sample, evaluated


@dataclass(frozen=True)
class _Window:
    first: int
    last: int
    factor: Array
    eligible: Mask

    def label(self, market: Market, horizon: int) -> Array:
        return forward_label(market.close, horizon, self.last)[self.first : self.last + 1]


def _quantile_groups(values: Array, sample: Mask, quantiles: int) -> NDArray[np.int64]:
    """Equal-count groups 0..Q-1 by value, ties by ascending instrument id; -1 outside."""
    count = sample.sum(axis=1)
    order = np.argsort(np.where(sample, values, np.inf), axis=1, kind="stable")
    position = np.empty(values.shape, dtype=np.int64)
    np.put_along_axis(position, order, np.arange(values.shape[1])[None, :], axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        groups = np.floor(position * quantiles / np.maximum(count, 1)[:, None]).astype(np.int64)
    groups[~sample] = -1
    return groups


def _turnover(held: Mask, evaluated: Mask) -> Array:
    out = np.full(held.shape[0], np.nan)
    previous: int | None = None
    for t in np.flatnonzero(evaluated):
        if previous is not None:
            size = int(held[t].sum())
            if size:
                out[t] = 1.0 - float((held[t] & held[previous]).sum()) / size
        previous = int(t)
    return out


def _consecutive_spearman(values: Array, evaluated: Mask, minimum: int) -> Array:
    rows = np.flatnonzero(evaluated)
    out = np.full(values.shape[0], np.nan)
    if rows.size >= 2:
        current, previous = values[rows[1:]], values[rows[:-1]]
        out[rows[1:]] = row_spearman(current, previous, minimum)
    return out


def library_correlation(
    preprocessed: Array,
    sample: Mask,
    library: Mapping[str, Array],
    window: tuple[int, int],
    window_aligned: bool = False,
) -> LibraryCorrelation:
    """Max over library factors of |mean over t of Spearman(f(t), g(t))|.

    Library values span the whole market, or only the window's rows when window_aligned
    (the evaluator stores each version's W1 rows once and reads them back lazily).
    """
    if not library:
        return LibraryCorrelation(
            vacuous=True, max_abs=None, argmax=None, note="the library is empty"
        )
    first, last = window
    best_name: str | None = None
    best: float | None = None
    for name in sorted(library):
        values = library[name] if window_aligned else library[name][first : last + 1]
        if values.shape != preprocessed.shape:
            raise ValueError(f"library factor {name} is not aligned with the window")
        other = np.where(sample, values, np.nan)
        value = _mean(row_spearman(preprocessed, other))
        if value is not None and (best is None or abs(value) > best):
            best, best_name = abs(value), name
    return LibraryCorrelation(vacuous=False, max_abs=best, argmax=best_name, note=None)


def evaluate_factor(
    factor: Array,
    market: Market,
    start: date,
    end: date,
    sign: Literal[1, -1],
    settings: MetricSettings,
    library: Mapping[str, Array] | None = None,
    library_window_aligned: bool = False,
) -> FactorEvaluation:
    """All Section 8.5 factor metrics on [start, end], labels confined to the window."""
    first, last = market.window(start, end)
    rows = slice(first, last + 1)
    dates = market.dates[rows]
    window = _Window(first, last, factor[rows], market.eligible[rows])
    minimum = market.minimum

    def rank_ic_for(horizon: int) -> tuple[Array, Array, Mask, Mask, Array]:
        label = window.label(market, horizon)
        sample, evaluated = _sample(window.factor, label, window.eligible, minimum)
        values = preprocess(window.factor, sample, settings)
        y = np.where(sample, label, np.nan)
        return row_spearman(values, y, minimum), values, sample, evaluated, y

    primary = settings.primary_horizon
    rank_ic, values, sample, evaluated, y = rank_ic_for(primary)
    ic = row_pearson(values, y, minimum)
    decay: dict[str, float | None] = {}
    for horizon in settings.horizons:
        daily = rank_ic if horizon == primary else rank_ic_for(horizon)[0]
        decay[str(horizon)] = _mean(daily)

    # Quantile portfolios always use the one-day label.
    label_1 = window.label(market, 1)
    q_sample, q_evaluated = _sample(window.factor, label_1, window.eligible, minimum)
    q_values = preprocess(window.factor, q_sample, settings)
    groups = _quantile_groups(q_values, q_sample, settings.quantiles)
    group_returns = np.full((len(dates), settings.quantiles), np.nan)
    for g in range(settings.quantiles):
        members = groups == g
        counts = members.sum(axis=1)
        with np.errstate(invalid="ignore", divide="ignore"):
            group_returns[:, g] = np.where(members, label_1, 0.0).sum(axis=1) / counts
        group_returns[counts == 0, g] = np.nan
    high, low = group_returns[:, -1], group_returns[:, 0]
    ls = sign * (high - low)
    top_group, bottom_group = (
        (settings.quantiles - 1, 0) if sign == 1 else (0, settings.quantiles - 1)
    )
    top_turnover = _turnover(groups == top_group, q_evaluated)
    bottom_turnover = _turnover(groups == bottom_group, q_evaluated)
    cost = settings.ls_cost_bps_per_side / 10_000.0
    ls_net = ls - 2.0 * cost * (top_turnover + bottom_turnover)

    group_means = [_mean(group_returns[:, g]) for g in range(settings.quantiles)]
    monotonicity: float | None = None
    if all(v is not None for v in group_means):
        means = np.array([group_means], dtype=np.float64)
        index = np.arange(1, settings.quantiles + 1, dtype=np.float64)[None, :]
        monotonicity = _finite(sign * row_spearman(index, means)[0])

    rankic_mean, rankic_std = _mean(rank_ic), _std(rank_ic)
    count = int(np.isfinite(rank_ic).sum())
    lag = newey_west_lag(count, primary)
    hits = rank_ic[np.isfinite(rank_ic)]
    eligible_counts = window.eligible.sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        coverage_rows = (window.eligible & np.isfinite(window.factor)).sum(axis=1) / eligible_counts
    coverage = _mean(np.where(eligible_counts > 0, coverage_rows, np.nan))

    size = np.where(market.adv20[rows] > 0, np.log(market.adv20[rows]), np.nan)
    neutral = residualize_rows(values, np.where(sample, size, np.nan))
    size_neutral = _mean(row_spearman(neutral, y, minimum))

    years: dict[str, list[float]] = {}
    for day, value in zip(dates, rank_ic, strict=True):
        if math.isfinite(value):
            years.setdefault(str(day.year), []).append(float(value))
    yearly: dict[str, float | None] = {k: float(np.mean(v)) for k, v in sorted(years.items())}

    metrics = FactorMetrics(
        start=start,
        end=end,
        sign=sign,
        dates_evaluated=count,
        ic_mean=_mean(ic),
        rankic_mean=rankic_mean,
        rankic_std=rankic_std,
        rankic_ir=_ratio(rankic_mean, rankic_std),
        rankic_t_nw=newey_west_t(rank_ic, lag),
        nw_lag=lag,
        hit_ratio=float(np.mean(sign * hits > 0)) if hits.size else None,
        sign_consistency=int(sign * np.sign(rankic_mean)) if rankic_mean is not None else 0,
        decay=decay,
        quantile_returns=group_means,
        ls_gross_mean=_mean(ls),
        ls_gross_sharpe=sharpe(ls),
        ls_net_mean=_mean(ls_net),
        ls_net_sharpe=sharpe(ls_net),
        top_turnover=_mean(top_turnover),
        bottom_turnover=_mean(bottom_turnover),
        monotonicity=monotonicity,
        rank_autocorrelation=_mean(_consecutive_spearman(values, evaluated, minimum)),
        coverage=coverage,
        library_correlation=library_correlation(
            values, sample, library or {}, (first, last), library_window_aligned
        ),
        size_neutral_rankic=size_neutral,
        yearly_rankic=yearly,
    )
    series = FactorSeries(
        dates=dates,
        ic=ic,
        rank_ic=rank_ic,
        ls=ls,
        ls_net=ls_net,
        top_turnover=top_turnover,
        bottom_turnover=bottom_turnover,
        quantile_returns=group_returns,
    )
    return FactorEvaluation(metrics, series)


def rank_ic_series(
    factor: Array, market: Market, start: date, end: date, settings: MetricSettings
) -> Array:
    """Daily RankIC(t) at the primary horizon on [start, end]; the calibration hook."""
    first, last = market.window(start, end)
    rows = slice(first, last + 1)
    label = forward_label(market.close, settings.primary_horizon, last)[rows]
    sample, _ = _sample(factor[rows], label, market.eligible[rows], market.minimum)
    values = preprocess(factor[rows], sample, settings)
    return row_spearman(values, np.where(sample, label, np.nan), market.minimum)
