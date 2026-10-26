"""Deterministic synthetic prices with numerically calibrated, executable causal signals."""

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal, Self

import numpy as np
import polars as pl
from numpy.typing import NDArray
from pydantic import Field, PositiveInt, model_validator
from scipy.stats import rankdata

from qfr_core.contracts.base import Contract
from qfr_core.data_layer.snapshots import dense_panel

Array = NDArray[np.float64]
BoolArray = NDArray[np.bool_]


class SyntheticConfig(Contract):
    revision: PositiveInt
    seed: int
    start: date
    instruments: int = Field(ge=4)
    days: int = Field(ge=80)
    industries: PositiveInt
    market_mean: float
    market_std: float = Field(gt=0)
    industry_std: float = Field(ge=0)
    beta_min: float
    beta_max: float
    idio_df: float = Field(gt=2)
    idio_std_min: float = Field(gt=0)
    idio_std_max: float = Field(gt=0)
    log_volume_mean: float
    log_volume_ar: float = Field(ge=0, lt=1)
    log_volume_std: float = Field(gt=0)
    volume_return_coupling: float = Field(ge=0)
    suspension_probability: float = Field(ge=0, lt=1)
    annual_churn_fraction: float = Field(ge=0, lt=1)
    trading_days_per_year: PositiveInt
    price_limit: float = Field(gt=0, lt=1)
    initial_price: float = Field(gt=0)
    initial_membership_fraction: float = Field(gt=0, le=1)
    min_listed_days: PositiveInt
    min_names: int = Field(ge=3)
    volume_clip: float = Field(gt=0)
    target_rankic: tuple[float, float, float]
    calibration_tolerance: float = Field(gt=0, le=0.005)
    alpha_upper_bound: float = Field(gt=0)
    calibration_bisections: PositiveInt
    calibration_sweeps: PositiveInt
    decay_w2_start_fraction: float = Field(gt=0, lt=1)
    decay_w2_end_fraction: float = Field(gt=0, lt=1)

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.min_names > self.instruments or self.min_listed_days >= self.days - 2:
            raise ValueError("synthetic calibration needs eligible names and dates")
        if self.beta_min > self.beta_max or self.idio_std_min > self.idio_std_max:
            raise ValueError("reversed synthetic range")
        if self.decay_w2_start_fraction >= self.decay_w2_end_fraction:
            raise ValueError("reversed synthetic W2")
        return self

    @classmethod
    def load(cls, path: Path) -> "SyntheticConfig":
        return cls.model_validate_json(path.read_bytes())


@dataclass(frozen=True)
class SyntheticWorld:
    panel: pl.DataFrame
    calendar: pl.DataFrame
    membership: pl.DataFrame
    # Evaluation/benchmark-only: zone export must never put this in research snapshots.
    ground_truth: dict[str, object]


@dataclass(frozen=True)
class _Noise:
    returns: Array
    volumes: Array
    suspended: BoolArray
    member: BoolArray


def _noise(config: SyntheticConfig) -> _Noise:
    rng = np.random.default_rng(config.seed)
    n, t = config.instruments, config.days
    beta = rng.uniform(config.beta_min, config.beta_max, n)
    industry = np.arange(n) % config.industries
    market = rng.normal(config.market_mean, config.market_std, (t, 1))
    sector = rng.normal(0, config.industry_std, (t, config.industries))[:, industry]
    vol = rng.uniform(config.idio_std_min, config.idio_std_max, n)
    noise = rng.standard_t(config.idio_df, (t, n)) * np.sqrt((config.idio_df - 2) / config.idio_df)
    returns = np.asarray(market * beta + sector + noise * vol, dtype=np.float64)
    log_volume = np.full((t, n), config.log_volume_mean)
    innovations = rng.normal(0, config.log_volume_std, (t, n))
    for day in range(1, t):
        log_volume[day] = (
            config.log_volume_mean
            + config.log_volume_ar * (log_volume[day - 1] - config.log_volume_mean)
            + innovations[day]
            + config.volume_return_coupling * np.abs(returns[day])
        )
    suspended = rng.random((t, n)) < config.suspension_probability
    volumes = np.exp(log_volume)
    volumes[suspended] = 0
    member = np.ones((t, n), dtype=np.bool_)
    excluded = rng.choice(n, round(n * (1 - config.initial_membership_fraction)), replace=False)
    member[:, excluded] = False
    for day in range(config.trading_days_per_year, t, config.trading_days_per_year):
        previous = member[day - 1].copy()
        inside, outside = np.flatnonzero(previous), np.flatnonzero(~previous)
        swaps = min(round(n * config.annual_churn_fraction), len(inside), len(outside))
        previous[rng.choice(inside, swaps, replace=False)] = False
        previous[rng.choice(outside, swaps, replace=False)] = True
        member[day:] = previous
    return _Noise(returns, volumes, suspended, member)


def _z(values: Array) -> Array:
    deviation = float(np.std(values, ddof=1))
    return (values - np.mean(values)) / deviation if deviation > 0 else np.zeros_like(values)


def _simulate(
    config: SyntheticConfig, noise: _Noise, alphas: Array, switch: int | None
) -> tuple[Array, Array]:
    close = np.full_like(noise.returns, config.initial_price)
    daily = np.zeros_like(close)
    signals = np.full((config.days, config.instruments, 3), np.nan)
    zscores = np.zeros_like(signals)
    for day in range(1, config.days):
        coefficients = alphas.copy()
        if switch is not None and day >= switch:
            coefficients[2] = 0
        # Align with close(t+1) execution and close(t+2) label; no future signal is used.
        planted = zscores[day - 2] @ coefficients if day >= 2 else 0
        daily[day] = np.clip(noise.returns[day] + planted, -config.price_limit, config.price_limit)
        daily[day, noise.suspended[day]] = 0
        close[day] = close[day - 1] * (1 + daily[day])
        if day >= 5:
            signals[day, :, 0] = -(close[day] / close[day - 5] - 1)
        if day >= 19:
            average = noise.volumes[day - 19 : day + 1].mean(axis=0)
            signals[day, :, 1] = np.clip(
                np.sign(daily[day]) * (noise.volumes[day] / average - 1),
                -config.volume_clip,
                config.volume_clip,
            )
        if day >= 60:
            signals[day, :, 2] = -daily[day - 59 : day + 1].std(axis=0, ddof=1)
        for feature in range(3):
            if np.isfinite(signals[day, :, feature]).all():
                zscores[day, :, feature] = _z(signals[day, :, feature])
    return close, signals


def _rankics(
    config: SyntheticConfig, noise: _Noise, close: Array, signals: Array, stop: int | None = None
) -> Array:
    labels = close[2:] / close[1:-1] - 1
    output = []
    for feature in range(3):
        values = []
        for day in range(
            max(config.min_listed_days - 1, 60), min(stop or len(labels), len(labels))
        ):
            eligible = (
                noise.member[day] & ~noise.suspended[day] & np.isfinite(signals[day, :, feature])
            )
            if np.count_nonzero(eligible) < config.min_names:
                continue
            x = np.asarray(rankdata(signals[day, eligible, feature]), dtype=np.float64)
            y = np.asarray(rankdata(labels[day, eligible]), dtype=np.float64)
            if np.std(x) and np.std(y):
                values.append(float(np.corrcoef(x, y)[0, 1]))
        output.append(float(np.mean(values)) if values else np.nan)
    return np.asarray(output, dtype=np.float64)


def generate(config: SyntheticConfig, world: Literal["planted", "null", "decay"]) -> SyntheticWorld:
    if world not in {"planted", "null", "decay"}:
        raise ValueError("unknown synthetic world")
    noise = _noise(config)
    switch = (
        int(config.days * (config.decay_w2_start_fraction + config.decay_w2_end_fraction) / 2)
        if world == "decay"
        else None
    )
    active = 0 if world == "null" else 3 if world == "decay" else 2
    alphas = np.zeros(3)
    targets = np.asarray(config.target_rankic)
    close, signals = _simulate(config, noise, alphas, switch)
    measured = _rankics(config, noise, close, signals, switch)
    for _ in range(config.calibration_sweeps if active else 0):
        for feature in range(active):
            low, high = 0.0, config.alpha_upper_bound
            for _ in range(config.calibration_bisections):
                alphas[feature] = (low + high) / 2
                close, signals = _simulate(config, noise, alphas, switch)
                measured = _rankics(config, noise, close, signals, switch)
                if abs(measured[feature] - targets[feature]) <= config.calibration_tolerance / 2:
                    break
                if measured[feature] < targets[feature]:
                    low = alphas[feature]
                else:
                    high = alphas[feature]
        if np.all(np.abs(measured[:active] - targets[:active]) <= config.calibration_tolerance):
            break
    if active and not np.all(
        np.abs(measured[:active] - targets[:active]) <= config.calibration_tolerance
    ):
        raise ValueError(f"synthetic calibration failed: targets={targets}, measured={measured}")
    dates = np.busday_offset(np.datetime64(config.start), np.arange(config.days)).astype(
        "datetime64[D]"
    )
    codes = [f"SYN{i:06}" for i in range(config.instruments)]
    panel = pl.DataFrame(
        {
            "date": np.repeat(dates, config.instruments),
            "instrument": codes * config.days,
            "open": close.ravel(),
            "high": close.ravel(),
            "low": close.ravel(),
            "close": close.ravel(),
            "volume": noise.volumes.ravel(),
            "amount": (noise.volumes * close).ravel(),
            "factor": np.ones(close.size),
            "in_csi300": noise.member.ravel(),
            "in_csi500": np.zeros(close.size, dtype=bool),
            "limit_up": (
                np.vstack([np.zeros(config.instruments), close[1:] / close[:-1] - 1])
                >= config.price_limit - 1e-12
            ).ravel(),
            "limit_down": (
                np.vstack([np.zeros(config.instruments), close[1:] / close[:-1] - 1])
                <= -config.price_limit + 1e-12
            ).ravel(),
        }
    )
    calendar = pl.DataFrame({"date": dates})
    panel = dense_panel(panel, calendar)
    membership = panel.select("date", "instrument", "in_csi300", "in_csi500")
    truth = {
        "world": world,
        "seed": config.seed,
        "alpha": alphas.tolist(),
        "calibrated_rankic": measured.tolist(),
        "targets": config.target_rankic,
        "switch_off_day": switch,
        "timing": "signal t predicts close(t+2)/close(t+1)-1",
        "signals": [
            "-Pct($close,5)",
            f"Clip(Sign($ret)*($volume/Mean($volume,20)-1),-{config.volume_clip:g},{config.volume_clip:g})",
            "-Std($ret,60)",
        ],
        "config": config.model_dump(mode="json"),
    }
    return SyntheticWorld(panel, calendar, membership, truth)
