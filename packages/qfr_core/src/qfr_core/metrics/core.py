"""Shared numerical definitions. No protocol activation, official records or gate decisions."""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal, Self

import numpy as np
import polars as pl
from numpy.typing import NDArray
from pydantic import Field, PositiveInt, model_validator
from scipy.stats import rankdata

from qfr_core.contracts.base import Contract
from qfr_core.contracts.reports import MetricValue
from qfr_core.data_layer.snapshots import normalize_table

Array = NDArray[np.float64]


class MetricConfig(Contract):
    revision: PositiveInt
    profile: Literal["stock_daily_v1"]
    min_names: int = Field(ge=2)
    min_listed_days: PositiveInt
    universe_column: str
    horizons: list[PositiveInt]
    primary_horizon: PositiveInt
    winsor_low: float = Field(ge=0, le=1)
    winsor_high: float = Field(ge=0, le=1)
    quantiles: int = Field(ge=2)
    sign: Literal[-1, 1]
    annual_periods: PositiveInt
    long_short_cost_bps: float = Field(ge=0)
    fingerprint_dates: PositiveInt
    zero_epsilon: float = Field(gt=0)

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if self.winsor_low >= self.winsor_high or self.primary_horizon not in self.horizons:
            raise ValueError("inconsistent metric settings")
        if self.quantiles > self.min_names:
            raise ValueError("min_names must support all quantiles")
        return self


def measurement(value: float | None) -> MetricValue:
    valid = value is not None and math.isfinite(value)
    return MetricValue(
        value=float(value) if valid and value is not None else None,
        missing_reason=None if valid else "insufficient_data",
    )


def correlation(
    x: Sequence[float] | Array,
    y: Sequence[float] | Array,
    *,
    ranked: bool = False,
    epsilon: float = 1e-12,
) -> float | None:
    a, b = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    if a.shape != b.shape or a.ndim != 1:
        raise ValueError("correlation requires equally sized vectors")
    mask = np.isfinite(a) & np.isfinite(b)
    a, b = a[mask], b[mask]
    if len(a) < 2:
        return None
    if np.std(a) < epsilon or np.std(b) < epsilon:
        return None
    if ranked:
        a, b = rankdata(a, method="average"), rankdata(b, method="average")
    a, b = a - a.mean(), b - b.mean()
    scale = float(np.sqrt((a @ a) * (b @ b)))
    return float(np.clip((a @ b) / scale, -1, 1)) if scale >= epsilon else None


def preprocess(values: Array, config: MetricConfig) -> Array:
    result = np.full(len(values), np.nan)
    valid = np.isfinite(values)
    if np.count_nonzero(valid) < 2:
        return result
    clipped = np.clip(
        values[valid], *np.quantile(values[valid], [config.winsor_low, config.winsor_high])
    )
    deviation = clipped.std(ddof=1)
    if deviation >= config.zero_epsilon:
        result[valid] = (clipped - clipped.mean()) / deviation
    return result


def size_neutral(values: Array, adv: Array, epsilon: float) -> Array:
    output = np.full(len(values), np.nan)
    valid = np.isfinite(values) & np.isfinite(adv) & (adv > 0)
    if np.count_nonzero(valid) < 3:
        return output
    x = np.log(adv[valid])
    x -= x.mean()
    if x @ x < epsilon:
        return output
    centered = values[valid] - values[valid].mean()
    output[valid] = centered - (x @ centered) / (x @ x) * x
    return output


def mean(values: Sequence[float | None]) -> float | None:
    sample = np.asarray(values, dtype=float)
    sample = sample[np.isfinite(sample)]
    return float(sample.mean()) if len(sample) else None


def ratio(values: Sequence[float | None], annual_periods: int = 1) -> float | None:
    sample = np.asarray(values, dtype=float)
    sample = sample[np.isfinite(sample)]
    if len(sample) < 2 or sample.std(ddof=1) == 0:
        return None
    return float(sample.mean() / sample.std(ddof=1) * np.sqrt(annual_periods))


def newey_west_t(values: Sequence[float | None], horizon: int) -> float | None:
    sample = np.asarray(values, dtype=float)
    sample = sample[np.isfinite(sample)]
    n = len(sample)
    if horizon < 1:
        raise ValueError("horizon must be positive")
    if n < 2:
        return None
    lag = max(horizon, math.floor(4 * (n / 100) ** (2 / 9)))
    centered = sample - sample.mean()
    variance = float(centered @ centered) / n
    for offset in range(1, min(lag, n - 1) + 1):
        variance += 2 * (1 - offset / (lag + 1)) * float(centered[offset:] @ centered[:-offset]) / n
    return float(sample.mean() / np.sqrt(variance / n)) if variance > 0 else None


def forward_labels(panel: pl.DataFrame, horizon: int, start: date, end: date) -> pl.DataFrame:
    if horizon < 1 or end < start:
        raise ValueError("invalid label horizon or window")
    frame = normalize_table(panel, ["instrument", "date"])
    entry = pl.col("close").shift(-1).over("instrument")
    exit_price = pl.col("close").shift(-1 - horizon).over("instrument")
    exit_date = pl.col("date").shift(-1 - horizon).over("instrument")
    valid = pl.col("date").is_between(start, end) & exit_date.is_between(start, end) & (entry > 0)
    return frame.select(
        "instrument", "date", pl.when(valid).then(exit_price / entry - 1).alias("label")
    )


def turnover(current: set[str], previous: set[str] | None) -> float | None:
    if not current:
        return None
    return 1.0 if previous is None else 1 - len(current & previous) / len(current)


@dataclass(frozen=True)
class StockMetrics:
    series: pl.DataFrame
    summary: dict[str, MetricValue]
    decay: dict[int, MetricValue]
    yearly_rank_ic: dict[str, MetricValue]
    library_argmax: str | None
    official: Literal[False] = False


def _series(
    panel: pl.DataFrame,
    scores: pl.DataFrame,
    config: MetricConfig,
    horizon: int,
    start: date,
    end: date,
) -> pl.DataFrame:
    labels = forward_labels(panel, horizon, start, end)
    frame = panel.join(
        scores.select("instrument", "date", "value"),
        on=["instrument", "date"],
        how="left",
        validate="1:1",
    ).join(labels, on=["instrument", "date"])
    frame = frame.filter(pl.col("date").is_between(start, end)).sort("date", "instrument")
    rows = []
    previous_top: set[str] | None = None
    previous_bottom: set[str] | None = None
    previous_factors: dict[str, float] = {}
    for (day,), cross in frame.group_by("date", maintain_order=True):
        eligible = cross.filter(
            pl.col(config.universe_column)
            & (pl.col("listed_days") >= config.min_listed_days)
            & ~pl.col("is_suspended")
        )
        raw = eligible["value"].to_numpy()
        coverage = float(np.isfinite(raw).mean()) if len(raw) else None
        sample = eligible.filter(pl.col("value").is_finite() & pl.col("label").is_finite())
        row: dict[str, object] = {
            "date": day,
            "coverage": coverage,
            "ic": None,
            "rank_ic": None,
            "size_neutral_rank_ic": None,
            "ls_gross": None,
            "ls_net": None,
            "top_turnover": None,
            "bottom_turnover": None,
            "autocorrelation": None,
        }
        row.update({f"q{i + 1}": None for i in range(config.quantiles)})
        if sample.height >= config.min_names:
            f = preprocess(sample["value"].to_numpy(), config)
            labels_array = sample["label"].to_numpy()
            ids = sample["instrument"].to_list()
            row["ic"] = correlation(f, labels_array, epsilon=config.zero_epsilon)
            row["rank_ic"] = correlation(f, labels_array, ranked=True, epsilon=config.zero_epsilon)
            row["size_neutral_rank_ic"] = correlation(
                size_neutral(f, sample["adv20"].to_numpy(), config.zero_epsilon),
                labels_array,
                ranked=True,
                epsilon=config.zero_epsilon,
            )
            if np.isfinite(f).all():
                order = np.lexsort((np.asarray(ids), f))
                groups = np.array_split(order, config.quantiles)
                returns = [float(labels_array[group].mean()) for group in groups]
                row.update({f"q{i + 1}": r for i, r in enumerate(returns)})
                top_group, bottom_group = (
                    (groups[-1], groups[0]) if config.sign == 1 else (groups[0], groups[-1])
                )
                top, bottom = {ids[i] for i in top_group}, {ids[i] for i in bottom_group}
                top_turnover, bottom_turnover = (
                    turnover(top, previous_top),
                    turnover(bottom, previous_bottom),
                )
                assert top_turnover is not None and bottom_turnover is not None
                gross = config.sign * (returns[-1] - returns[0])
                row.update(
                    ls_gross=gross,
                    top_turnover=top_turnover,
                    bottom_turnover=bottom_turnover,
                    ls_net=gross
                    - 2 * config.long_short_cost_bps / 10000 * (top_turnover + bottom_turnover),
                )
                factors = dict(zip(ids, f, strict=True))
                common = sorted(factors.keys() & previous_factors.keys())
                row["autocorrelation"] = correlation(
                    [factors[k] for k in common], [previous_factors[k] for k in common], ranked=True
                )
                previous_top, previous_bottom, previous_factors = top, bottom, factors
        else:
            previous_factors = {}
        rows.append(row)
    schema = {
        "date": pl.Date,
        **{
            name: pl.Float64
            for name in [
                "coverage",
                "ic",
                "rank_ic",
                "size_neutral_rank_ic",
                "ls_gross",
                "ls_net",
                "top_turnover",
                "bottom_turnover",
                "autocorrelation",
                *[f"q{i + 1}" for i in range(config.quantiles)],
            ]
        },
    }
    return pl.DataFrame(rows, schema=schema)


def stock_metrics(
    panel: pl.DataFrame,
    scores: pl.DataFrame,
    config: MetricConfig,
    *,
    start: date,
    end: date,
    library: Mapping[str, pl.DataFrame] | None = None,
) -> StockMetrics:
    panel = normalize_table(panel, ["instrument", "date"])
    scores = normalize_table(scores, ["instrument", "date"])
    series = _series(panel, scores, config, config.primary_horizon, start, end)
    rankics = series["rank_ic"].drop_nulls().to_list()
    average = mean(rankics)
    summary = {
        "RankIC_mean": measurement(average),
        "RankIC_std": measurement(float(np.std(rankics, ddof=1)) if len(rankics) > 1 else None),
        "RankIC_IR": measurement(ratio(rankics)),
        "RankIC_t_NW": measurement(newey_west_t(rankics, config.primary_horizon)),
        "hit_ratio": measurement(mean([float(config.sign * value > 0) for value in rankics])),
        "sign_consistency": measurement(
            config.sign * float(np.sign(average)) if average is not None else None
        ),
        "ls_gross_sharpe": measurement(ratio(series["ls_gross"].to_list(), config.annual_periods)),
        "ls_net_sharpe": measurement(ratio(series["ls_net"].to_list(), config.annual_periods)),
    }
    for name in [
        "coverage",
        "top_turnover",
        "bottom_turnover",
        "size_neutral_rank_ic",
        "autocorrelation",
        "ic",
    ]:
        summary[name] = measurement(mean(series[name].to_list()))
    group_means = [mean(series[f"q{i + 1}"].to_list()) for i in range(config.quantiles)]
    monotonicity = correlation(
        np.arange(config.quantiles, dtype=float), np.asarray(group_means, dtype=float), ranked=True
    )
    summary["monotonicity"] = measurement(
        config.sign * monotonicity if monotonicity is not None else None
    )
    decay = {
        h: measurement(mean(_series(panel, scores, config, h, start, end)["rank_ic"].to_list()))
        for h in config.horizons
    }
    yearly = {
        str(year): measurement(
            mean(series.filter(pl.col("date").dt.year() == year)["rank_ic"].to_list())
        )
        for year in series["date"].dt.year().unique().sort().to_list()
    }
    correlations = {}
    eligible_keys = panel.filter(
        pl.col(config.universe_column)
        & (pl.col("listed_days") >= config.min_listed_days)
        & ~pl.col("is_suspended")
    ).select("instrument", "date")
    eligible_keys = eligible_keys.join(
        forward_labels(panel, config.primary_horizon, start, end)
        .filter(pl.col("label").is_finite())
        .select("instrument", "date"),
        on=["instrument", "date"],
        validate="1:1",
    )
    for name, factor in (library or {}).items():
        joined = scores.join(factor, on=["instrument", "date"], suffix="_other", validate="1:1")
        joined = joined.join(eligible_keys, on=["instrument", "date"], validate="1:1").filter(
            pl.col("value").is_finite() & pl.col("value_other").is_finite()
        )
        values = [
            correlation(g["value"].to_numpy(), g["value_other"].to_numpy(), ranked=True)
            for _, g in joined.filter(pl.col("date").is_between(start, end)).group_by("date")
            if g.height >= config.min_names
        ]
        value = mean(values)
        if value is not None:
            correlations[name] = abs(value)
    argmax = max(sorted(correlations), key=correlations.__getitem__) if correlations else None
    summary["library_correlation"] = measurement(correlations[argmax] if argmax else None)
    return StockMetrics(series, summary, decay, yearly, argmax)


def fingerprint(
    scores: pl.DataFrame, *, cutoff: date, seed: int | None, dates: int
) -> pl.DataFrame:
    if seed is None:
        raise ValueError("fingerprint seed must be explicitly frozen")
    if dates <= 0:
        raise ValueError("fingerprint date count must be positive")
    scores = normalize_table(scores, ["instrument", "date"]).filter(pl.col("date") <= cutoff)
    available = sorted(scores["date"].unique().to_list())
    if len(available) < dates:
        raise ValueError("insufficient W0 dates for fingerprint")
    selected = np.random.default_rng(seed).choice(len(available), dates, replace=False)
    return scores.filter(pl.col("date").is_in([available[i] for i in sorted(selected)])).select(
        "date", "instrument", pl.col("value").rank(method="average").over("date").alias("rank")
    )


def behavioral_similarity(a: pl.DataFrame, b: pl.DataFrame) -> MetricValue:
    joined = a.join(b, on=["instrument", "date"], suffix="_other", validate="1:1").sort(
        "date", "instrument"
    )
    values = [
        correlation(g["rank"].to_numpy(), g["rank_other"].to_numpy(), ranked=True)
        for _, g in joined.group_by("date", maintain_order=True)
    ]
    return measurement(mean([abs(value) for value in values if value is not None]))
