"""Independent Polars/NumPy implementation of the frozen pilot feature transforms."""

from dataclasses import dataclass
from datetime import date

import numpy as np
import polars as pl
from pydantic import PositiveInt

from qfr_core.contracts.base import Contract
from qfr_core.data_layer.snapshots import normalize_table


class PilotFeatureConfig(Contract):
    revision: PositiveInt
    industry_count: PositiveInt
    benchmarks: list[str]
    reverse_windows: list[PositiveInt]
    momentum_windows: list[PositiveInt]
    momentum_skip: PositiveInt
    lowvol_window: PositiveInt
    drawdown_window: PositiveInt
    style_market: str
    style_small: str
    style_momentum: PositiveInt
    style_regression: PositiveInt
    style_min_observations: PositiveInt
    style_round_decimals: PositiveInt
    quarter_review_window: PositiveInt
    quarter_review_benchmarks: list[str]

    def expressions(self) -> dict[str, str]:
        result = {f"reverse{d}": f"-Pct($close,{d})" for d in self.reverse_windows}
        result.update(
            {
                f"momentum{d}_{self.momentum_skip}": (
                    f"Ref($close,{self.momentum_skip})/Ref($close,{d})-1"
                )
                for d in self.momentum_windows
            }
        )
        result[f"lowvol{self.lowvol_window}"] = f"-Std(Pct($close,1),{self.lowvol_window})"
        result[f"drawdown{self.drawdown_window}"] = f"$close/Max($close,{self.drawdown_window})-1"
        return result


def price_features(
    panel: pl.DataFrame, prices: pl.DataFrame, codes: list[str], config: PilotFeatureConfig
) -> pl.DataFrame:
    panel = normalize_table(panel, ["code", "date"])
    if (
        len(codes) != config.industry_count
        or len(set(codes)) != len(codes)
        or set(codes) & set(config.benchmarks)
    ):
        raise ValueError("full distinct industry universe required")
    if panel.is_empty() or not set(panel["code"]) <= set(codes):
        raise ValueError("nonempty industry panel required")
    px = normalize_table(prices, ["code", "date"]).filter(
        pl.col("code").is_in(codes) & (pl.col("date") <= panel["date"].max())
    )
    if (
        px.is_empty()
        or px.filter(
            ~pl.col("close").is_finite() | (pl.col("close") <= 0) | pl.col("close").is_null()
        ).height
    ):
        raise ValueError("finite positive industry prices required; no filling")
    if px.group_by("date").len().filter(pl.col("len") != config.industry_count).height:
        raise ValueError("every price date needs the complete industry universe")
    close = pl.col("close")
    raw = {
        f"reverse{d}": -(close / close.shift(d).over("code") - 1) for d in config.reverse_windows
    }
    raw.update(
        {
            f"momentum{d}_{config.momentum_skip}": close.shift(config.momentum_skip).over("code")
            / close.shift(d).over("code")
            - 1
            for d in config.momentum_windows
        }
    )
    px = px.with_columns((close / close.shift(1).over("code") - 1).alias("ret"))
    raw[f"lowvol{config.lowvol_window}"] = (
        -pl.col("ret")
        .rolling_std(config.lowvol_window, min_samples=config.lowvol_window, ddof=1)
        .over("code")
    )
    raw[f"drawdown{config.drawdown_window}"] = (
        close
        / close.rolling_max(config.drawdown_window, min_samples=config.drawdown_window).over("code")
        - 1
    )
    px = px.with_columns(value.alias("v4_raw_" + name) for name, value in raw.items())
    px = px.with_columns(
        (
            pl.col("v4_raw_" + name).rank(method="average").over("date")
            / pl.col("v4_raw_" + name).count().over("date")
        ).alias("v4_p_" + name)
        for name in raw
    )
    columns = [prefix + name for name in raw for prefix in ("v4_raw_", "v4_p_")]
    px = px.select("code", pl.col("date").alias("v4_price_date"), *columns)
    result = panel.join_asof(
        px,
        left_on="date",
        right_on="v4_price_date",
        by="code",
        strategy="backward",
        check_sortedness=False,
    )
    return result.with_columns(
        pl.all_horizontal(pl.col(["v4_p_" + name for name in raw]).is_finite())
        .fill_null(False)
        .alias("v4_ready")
    )


@dataclass(frozen=True)
class WeeklyPrices:
    dates: list[date]
    codes: list[str]
    values: np.ndarray[tuple[int, ...], np.dtype[np.float64]]


def weekly_prices(panel: pl.DataFrame, prices: pl.DataFrame) -> WeeklyPrices:
    dates, codes = (
        sorted(panel["date"].unique().to_list()),
        sorted(prices["code"].unique().to_list()),
    )
    keys = (
        pl.DataFrame({"date": dates})
        .join(pl.DataFrame({"code": codes}), how="cross")
        .sort("code", "date")
    )
    aligned = keys.join_asof(
        prices.select("code", "date", "close").sort("code", "date"),
        on="date",
        by="code",
        strategy="backward",
        check_sortedness=False,
    )
    wide = aligned.pivot(on="code", index="date", values="close").sort("date")
    return WeeklyPrices(dates, codes, wide.select(codes).to_numpy())


def enrich_p0(
    panel: pl.DataFrame, prices: pl.DataFrame, config: PilotFeatureConfig
) -> pl.DataFrame:
    """Frozen features input plus lagged style regression and quarter review inputs.

    Uses the accepted cached features as the original replay does; it never
    imports the old runtime or reads a reference score/ranking.
    """
    panel = normalize_table(panel, ["code", "date"])
    weekly = weekly_prices(panel, prices)
    px, codes, dates = weekly.values, weekly.codes, weekly.dates
    returns = np.full_like(px, np.nan)
    returns[1:] = px[1:] / px[:-1] - 1
    market = returns[:, codes.index(config.style_market)]
    size = returns[:, codes.index(config.style_small)] - market
    momentum = np.full_like(px, np.nan)
    lag = config.style_momentum
    momentum[lag:] = px[lag:] / px[:-lag] - 1
    state = (
        momentum[:, codes.index(config.style_small)] - momentum[:, codes.index(config.style_market)]
    )
    rows = []
    for i, day in enumerate(dates):
        lo = max(0, i - config.style_regression)
        design = np.column_stack([np.ones(i - lo), market[lo:i], size[lo:i]])
        for j, code in enumerate(codes):
            y = returns[lo:i, j]
            valid = np.isfinite(design).all(axis=1) & np.isfinite(y)
            n = int(valid.sum())
            bm, bs = np.nan, np.nan
            if n >= config.style_min_observations and np.linalg.matrix_rank(design[valid]) == 3:
                coefficients = np.linalg.lstsq(design[valid], y[valid], rcond=None)[0]
                bm, bs = coefficients[1:]
            rows.append(
                {
                    "date": day,
                    "code": code,
                    "beta_market": bm,
                    "beta_size": bs,
                    "beta_n": n,
                    "style_state": state[i],
                    "style_raw": float(np.round(bs * state[i], config.style_round_decimals)),
                }
            )
    exposure = pl.DataFrame(rows).fill_nan(None)
    result = panel.join(exposure, on=["date", "code"], validate="1:1").with_columns(
        (
            pl.col("style_raw").rank(method="average").over("date")
            / pl.col("style_raw").count().over("date")
        ).alias("p_style")
    )
    long = pl.DataFrame(
        {
            "date": [day for day in dates for _ in codes],
            "code": codes * len(dates),
            "close": px.reshape(-1),
        },
        schema_overrides={"date": pl.Date},
        nan_to_null=True,
    ).sort("code", "date")
    d = config.quarter_review_window
    long = long.with_columns(
        (pl.col("close") / pl.col("close").shift(d).over("code") - 1).alias("ret4"),
        (pl.col("close") / pl.col("close").rolling_mean(d, min_samples=d).over("code") - 1).alias(
            "ma_gap"
        ),
    )
    benchmark = (
        long.filter(pl.col("code").is_in(config.quarter_review_benchmarks))
        .group_by("date")
        .agg(pl.col("ret4").mean().alias("benchmark"))
    )
    review = long.join(benchmark, on="date").with_columns(
        (pl.col("ret4") - pl.col("benchmark")).alias("relative4")
    )
    return result.join(
        review.select("date", "code", "ma_gap", "relative4"), on=["date", "code"], validate="1:1"
    ).sort("date", "industry")
