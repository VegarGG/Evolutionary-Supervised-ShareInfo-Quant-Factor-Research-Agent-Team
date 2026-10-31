"""Synthetic market generator with planted, null and decay worlds (PLAN Section 6.6).

Next-day return of instrument i on day s:

    r(i, s) = beta_i m(s) + ind(g(i), s) + sum_k alpha_k z_k(i, s - 2) + e(i, s)

z_k(i, t) is the cross-sectional z-score of planted signal k at decision day t. The
signal acts on the return from close t+1 to close t+2, which is exactly the one-day
label of decision day t under the timing conventions of Section 6.5. Prices follow a
latent fair value; traded raw closes are rounded to the 0.01 tick and held within the
10% limit of the ex-rights reference, so limit-locked names catch up on later days.

All random numbers are drawn once from the seed (common random numbers). Each alpha_k
is calibrated by bisection on a separate calibration sample so that the evaluator's own
RankIC of signal k hits its target. Signals are computed here with the same validity
rules as the DSL; tests check them against the DSL evaluation of the ground-truth
expressions on the built panel.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import numpy as np
import polars as pl
from numpy.typing import NDArray
from qfr_core.config import EpochConfig
from qfr_core.data.panel import TICK, build_panel, equal_weight_benchmark
from qfr_core.dsl.catalog import min_valid
from qfr_core.metrics.factor import MetricSettings, rank_ic_series
from qfr_core.metrics.matrix import Market

from qfr_eval.ingest.config import SyntheticConfig, World

Array = NDArray[np.float64]
Mask = NDArray[np.bool_]
Ints = NDArray[np.int64]

UNIVERSE = "csi300"
LISTED_DAYS_MIN = 60
GROUND_TRUTH_NOTE = (
    "Test infrastructure for the evaluation side and the benchmark harness only. "
    "Never a default factor set."
)


def weekday_calendar(start: date, days: int) -> list[date]:
    out: list[date] = []
    day = start
    while len(out) < days:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


def round_tick(value: Array) -> Array:
    """Half-up rounding to the tick; the same arithmetic as qfr_core.data.panel."""
    result: Array = np.floor((value / TICK) + 0.5 + 1e-9) * TICK
    return result


@dataclass(frozen=True)
class Draws:
    """Every random number of one world, drawn up front from one seed."""

    market: Array
    industry: Array
    sector: Ints
    beta: Array
    noise: Array
    abs_noise_z: Array
    volume_noise: Array
    log_volume_mean: Array
    price0: Array
    open_noise: Array
    high_noise: Array
    low_noise: Array
    first: Ints
    last: Ints
    suspended: Mask
    ratio: Array
    member: Mask


def _suspensions(rng: np.random.Generator, shape: tuple[int, int], p: float, longest: int) -> Mask:
    starts = rng.random(shape) < p
    lengths = rng.integers(1, longest + 1, size=shape)
    mask = np.zeros(shape, dtype=bool)
    for k in range(longest):
        mask[k:] |= starts[: shape[0] - k] & (lengths[: shape[0] - k] > k)
    return mask


def _membership(
    rng: np.random.Generator, config: SyntheticConfig, days: list[date], first: Ints, last: Ints
) -> Mask:
    total, n = len(days), config.instruments
    member = np.zeros((total, n), dtype=bool)
    current = np.zeros(n, dtype=bool)
    founders = np.flatnonzero(first == 0)
    current[rng.choice(founders, size=config.universe.size, replace=False)] = True
    churn = round(config.universe.annual_churn * n)

    def candidates(t: int) -> Ints:
        ok = (~current) & (first <= t - LISTED_DAYS_MIN) & (last > t)
        return np.flatnonzero(ok)

    for t in range(total):
        if t > 0 and days[t].year != days[t - 1].year and churn:
            leaving = rng.choice(np.flatnonzero(current), size=churn, replace=False)
            pool = candidates(t)
            entering = rng.choice(pool, size=min(churn, pool.size), replace=False)
            current[leaving] = False
            current[entering] = True
        gone = current & (last < t)
        if gone.any():
            current[gone] = False
            pool = candidates(t)
            if pool.size:
                current[rng.choice(pool, size=min(int(gone.sum()), pool.size), replace=False)] = (
                    True
                )
        member[t] = current & (first <= t) & (t <= last)
    return member


def draw(config: SyntheticConfig, seed: int, days: list[date]) -> Draws:
    rng = np.random.default_rng(seed)
    total, n = len(days), config.instruments
    shape = (total, n)
    market = rng.normal(config.market_mean, config.market_sd, total)
    industry = rng.normal(0.0, config.industry_sd, (total, config.industries))
    sector = rng.permutation(np.arange(n) % config.industries).astype(np.int64)
    beta = rng.uniform(*config.beta, n)
    vol = rng.uniform(*config.idio_vol, n)
    df = config.idio_df
    unit = rng.standard_t(df, shape) / math.sqrt(df / (df - 2.0))
    noise = unit * vol[None, :]
    absolute = np.abs(unit)
    abs_noise_z = (absolute - absolute.mean()) / absolute.std()
    volume_noise = rng.standard_normal(shape)
    log_volume_mean = rng.uniform(*config.log_volume_mean, n)
    price0 = rng.uniform(*config.initial_price, n)
    open_noise = rng.normal(0.0, 0.006, shape)
    high_noise = np.abs(rng.normal(0.0, 0.008, shape))
    low_noise = np.abs(rng.normal(0.0, 0.008, shape))
    late = rng.random(n) < config.late_listing_share
    first = np.where(late, rng.integers(LISTED_DAYS_MIN, (3 * total) // 4, n), 0).astype(np.int64)
    last = np.full(n, total - 1, dtype=np.int64)
    founders = np.flatnonzero(first == 0)
    delisted = rng.choice(founders, size=min(config.delistings, founders.size), replace=False)
    last[delisted] = rng.integers(total // 4, total - 1, delisted.size)
    suspended = _suspensions(rng, shape, config.suspension_start_prob, config.suspension_max_days)
    span = np.arange(total)[:, None]
    suspended &= (span > first[None, :]) & (span <= last[None, :])
    dividend = rng.random(shape) < config.dividend_prob_per_year / 252.0
    split = rng.random(shape) < config.split_prob_per_year / 252.0
    ratio = np.ones(shape)
    ratio[dividend] = rng.uniform(*config.dividend_ratio, int(dividend.sum()))
    ratio[split] = rng.choice(np.array(config.split_ratios), int(split.sum()))
    ratio[span <= first[None, :]] = 1.0
    member = _membership(rng, config, days, first, last)
    return Draws(
        market=market,
        industry=industry,
        sector=sector,
        beta=beta,
        noise=noise,
        abs_noise_z=abs_noise_z,
        volume_noise=volume_noise,
        log_volume_mean=log_volume_mean,
        price0=price0,
        open_noise=open_noise,
        high_noise=high_noise,
        low_noise=low_noise,
        first=first,
        last=last,
        suspended=suspended,
        ratio=ratio,
        member=member,
    )


def _window_rows(history: Array, t: int, days: int) -> Array:
    """Rows t-days+1..t, with NaN padding before the first row."""
    start = t - days + 1
    if start >= 0:
        return history[start : t + 1]
    pad = np.full((-start, history.shape[1]), np.nan)
    return np.vstack([pad, history[: t + 1]])


def _rolling(history: Array, t: int, days: int, reducer: str) -> Array:
    window = _window_rows(history, t, days)
    valid = np.isfinite(window)
    count = valid.sum(axis=0)
    filled = np.where(valid, window, 0.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = filled.sum(axis=0) / count
        if reducer == "mean":
            out = mean
        else:
            dev = np.where(valid, window - mean[None, :], 0.0)
            out = np.sqrt((dev * dev).sum(axis=0) / (count - 1))
    out = np.where(count >= max(min_valid(days), 1 if reducer == "mean" else 2), out, np.nan)
    return np.asarray(out, dtype=np.float64)


@dataclass
class _Histories:
    close: Array
    ret: Array
    volume: Array


SignalFn = Callable[[_Histories, int], Array]


def _a1(h: _Histories, t: int) -> Array:
    """-Pct($close,5)."""
    if t < 5:
        return np.full(h.close.shape[1], np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        out = -(h.close[t] / h.close[t - 5] - 1.0)
    return np.asarray(out, dtype=np.float64)


def _a2(h: _Histories, t: int) -> Array:
    """Clip(Sign($ret)*($volume/Mean($volume,20)-1),-3,3)."""
    mean = _rolling(h.volume, t, 20, "mean")
    with np.errstate(invalid="ignore", divide="ignore"):
        shock = h.volume[t] / mean - 1.0
    return np.asarray(np.clip(np.sign(h.ret[t]) * shock, -3.0, 3.0), dtype=np.float64)


def _a3(h: _Histories, t: int) -> Array:
    """-Std($ret,20)."""
    return -_rolling(h.ret, t, 20, "std")


SIGNALS: dict[str, SignalFn] = {"A1": _a1, "A2": _a2, "A3": _a3}


def _zscore(values: Array) -> Array:
    finite = np.isfinite(values)
    out = np.zeros(values.shape)
    if finite.sum() >= 3:
        x = values[finite]
        sd = x.std(ddof=1)
        if sd > 0:
            out[finite] = (x - x.mean()) / sd
    return out


@dataclass(frozen=True)
class Simulation:
    days: list[date]
    instruments: list[str]
    raw_close: Array
    close: Array  # Adjusted, NaN when not traded.
    open: Array
    high: Array
    low: Array
    volume: Array  # Adjusted, NaN when not traded.
    amount: Array
    factor: Array
    listed: Mask
    traded: Mask
    signals: dict[str, Array]
    member: Mask
    listed_days: Ints

    @property
    def eligible(self) -> Mask:
        return self.member & self.traded & (self.listed_days >= LISTED_DAYS_MIN)


def simulate(
    config: SyntheticConfig, days: list[date], draws: Draws, alpha: dict[str, Array]
) -> Simulation:
    """Run the day loop. alpha[k][t] is the loading of signal k decided on day t."""
    total, n = len(days), config.instruments
    shape = (total, n)
    nan = np.full(shape, np.nan)
    close, raw_close, opening, high, low = (
        nan.copy(),
        nan.copy(),
        nan.copy(),
        nan.copy(),
        nan.copy(),
    )
    volume, amount, ret = nan.copy(), nan.copy(), nan.copy()
    factor = nan.copy()
    signals = {name: nan.copy() for name in SIGNALS}
    zscores = {name: np.zeros(shape) for name in alpha}
    histories = _Histories(close, ret, volume)
    fair = np.full(n, np.nan)
    last_close = np.full(n, np.nan)
    adj = np.full(n, np.nan)
    log_volume = draws.log_volume_mean.copy()
    span = np.arange(total)
    listed = (span[:, None] >= draws.first[None, :]) & (span[:, None] <= draws.last[None, :])
    traded = listed & ~draws.suspended
    rho = config.volume_abs_return_corr
    for t in range(total):
        live = listed[t]
        new = draws.first == t
        adj = np.where(new, 1.0, adj * draws.ratio[t])
        r = draws.beta * draws.market[t] + draws.industry[t, draws.sector] + draws.noise[t]
        if t >= 2:
            for name, loading in alpha.items():
                r = r + loading[t - 2] * zscores[name][t - 2]
        fair = np.where(new, draws.price0, fair * (1.0 + np.clip(r, -0.5, 0.5)))
        fair = np.where(live, fair, np.nan)
        reference = last_close / adj
        up = round_tick(reference * (1.0 + config.price_limit))
        down = round_tick(reference * (1.0 - config.price_limit))
        quote = np.maximum(round_tick(fair / adj), TICK)
        quote = np.where(new, quote, np.clip(quote, down, up))
        today = traded[t]
        raw = np.where(today, quote, np.nan)
        base = np.where(new, quote, reference)
        open_raw = np.maximum(round_tick(base * (1.0 + draws.open_noise[t])), TICK)
        open_raw = np.where(new, open_raw, np.clip(open_raw, down, up))
        high_raw = round_tick(np.maximum(open_raw, raw) * (1.0 + draws.high_noise[t]))
        high_raw = np.where(new, high_raw, np.minimum(high_raw, up))
        low_raw = np.maximum(
            round_tick(np.minimum(open_raw, raw) * (1.0 - draws.low_noise[t])), TICK
        )
        low_raw = np.where(new, low_raw, np.maximum(low_raw, down))
        shock = rho * draws.abs_noise_z[t] + math.sqrt(1.0 - rho * rho) * draws.volume_noise[t]
        log_volume = np.where(
            new,
            draws.log_volume_mean,
            draws.log_volume_mean
            + config.volume_ar * (log_volume - draws.log_volume_mean)
            + config.volume_sd * shock,
        )
        raw_volume = np.exp(log_volume)
        raw_close[t] = raw
        close[t] = raw * adj
        opening[t] = np.where(today, open_raw * adj, np.nan)
        high[t] = np.where(today, high_raw * adj, np.nan)
        low[t] = np.where(today, low_raw * adj, np.nan)
        volume[t] = np.where(today, raw_volume / adj, np.nan)
        vwap_raw = (open_raw + high_raw + low_raw + raw) / 4.0
        amount[t] = np.where(today, raw_volume * vwap_raw, np.nan)
        factor[t] = np.where(live, adj, np.nan)
        with np.errstate(invalid="ignore", divide="ignore"):
            ret[t] = np.where(today, close[t] / last_close - 1.0, np.nan)
        last_close = np.where(today, close[t], last_close)
        last_close = np.where(live, last_close, np.nan)
        for name, compute in SIGNALS.items():
            signals[name][t] = compute(histories, t)
        for name in alpha:
            zscores[name][t] = _zscore(signals[name][t])
    listed_days = np.where(listed, span[:, None] - draws.first[None, :], -1).astype(np.int64)
    return Simulation(
        days=days,
        instruments=[f"SY{i + 1:06d}" for i in range(n)],
        raw_close=raw_close,
        close=close,
        open=opening,
        high=high,
        low=low,
        volume=volume,
        amount=amount,
        factor=factor,
        listed=listed,
        traded=traded,
        signals=signals,
        member=draws.member,
        listed_days=listed_days,
    )


def w2_midpoint(epoch: EpochConfig, days: list[date]) -> date:
    """The first trading day of the second half of W2."""
    end = epoch.W2.end
    assert end is not None
    inside = [d for d in days if epoch.W2.start <= d <= end]
    if not inside:
        raise ValueError("W2 has no trading days in the synthetic calendar")
    return inside[len(inside) // 2]


@dataclass(frozen=True)
class ActiveSignal:
    name: str
    expression: str
    target: float
    first: int
    stop: int  # Exclusive decision-day index.


def active_signals(
    config: SyntheticConfig, world: World, epoch: EpochConfig, days: list[date]
) -> list[ActiveSignal]:
    out = []
    for name, spec in sorted(config.signals.items()):
        if world not in spec.worlds:
            continue
        stop = len(days)
        if spec.switch_off == "w2_midpoint" and world == "decay":
            stop = days.index(w2_midpoint(epoch, days))
        out.append(ActiveSignal(name, spec.expression, spec.target_rankic, 0, stop))
    return out


def _loadings(
    signals: list[ActiveSignal], alphas: dict[str, float], total: int
) -> dict[str, Array]:
    out = {}
    for signal in signals:
        loading = np.zeros(total)
        loading[signal.first : signal.stop] = alphas.get(signal.name, 0.0)
        out[signal.name] = loading
    return out


def measured_rankic(
    sim: Simulation, signal: ActiveSignal, settings: MetricSettings, minimum: int
) -> float:
    market = Market.from_matrices(sim.days, sim.instruments, sim.close, sim.eligible, minimum)
    end = sim.days[signal.stop - 1]
    series = rank_ic_series(sim.signals[signal.name], market, sim.days[signal.first], end, settings)
    return float(np.nanmean(series))


@dataclass(frozen=True)
class Calibration:
    alphas: dict[str, float]
    rankic: dict[str, float]
    rounds: int
    evaluations: int


def calibrate(
    config: SyntheticConfig,
    world: World,
    epoch: EpochConfig,
    settings: MetricSettings,
    minimum: int,
) -> Calibration:
    """Coordinate bisection on the calibration sample with common random numbers.

    Each round bisects every alpha in turn with the others fixed, until each measured
    RankIC lies within half the tolerance of its target. The first round brackets
    [0, alpha_max]; later rounds re-bracket around the current value.
    """
    days = weekday_calendar(config.start, config.trading_days)
    signals = active_signals(config, world, epoch, days)
    if not signals:
        return Calibration({}, {}, 0, 0)
    draws = draw(config, config.calibration_seed, days)
    spec = config.calibration
    goal = spec.tolerance / 2.0
    alphas = {s.name: 0.0 for s in signals}
    evaluations = 0

    def measure(trial: dict[str, float], which: list[ActiveSignal]) -> dict[str, float]:
        nonlocal evaluations
        evaluations += 1
        sim = simulate(config, days, draws, _loadings(signals, trial, len(days)))
        return {s.name: measured_rankic(sim, s, settings, minimum) for s in which}

    def bracket(signal: ActiveSignal, first_round: bool) -> tuple[float, float]:
        if first_round:
            low, high = 0.0, spec.alpha_max
            if measure(alphas | {signal.name: high}, [signal])[signal.name] < signal.target:
                raise RuntimeError(f"{signal.name}: alpha_max cannot reach the target RankIC")
            return low, high
        low, high = alphas[signal.name] * 0.8, alphas[signal.name] * 1.25
        while measure(alphas | {signal.name: low}, [signal])[signal.name] > signal.target:
            low /= 2.0
        while measure(alphas | {signal.name: high}, [signal])[signal.name] < signal.target:
            high = min(high * 2.0, spec.alpha_max)
            if high == spec.alpha_max:
                break
        return low, high

    current: dict[str, float] = {}
    rounds = 0
    for rounds in range(1, spec.max_rounds + 1):
        for signal in signals:
            low, high = bracket(signal, rounds == 1)
            for _ in range(spec.max_iterations):
                middle = (low + high) / 2.0
                value = measure(alphas | {signal.name: middle}, [signal])[signal.name]
                alphas[signal.name] = middle
                if abs(value - signal.target) <= goal:
                    break
                if value < signal.target:
                    low = middle
                else:
                    high = middle
        current = measure(alphas, signals)
        if all(abs(current[s.name] - s.target) <= goal for s in signals):
            break
    misses = [s.name for s in signals if abs(current[s.name] - s.target) > spec.tolerance]
    if misses:
        raise RuntimeError(f"calibration did not reach the target RankIC for {misses}")
    return Calibration(alphas, current, rounds, evaluations)


@dataclass(frozen=True)
class SyntheticWorld:
    world: World
    days: list[date]
    observations: pl.DataFrame
    membership: pl.DataFrame
    panel: pl.DataFrame
    calendar: pl.DataFrame
    ground_truth: dict[str, Any]
    simulation: Simulation


def _observations(sim: Simulation) -> pl.DataFrame:
    """Rows for every listed day. Suspended days carry volume 0 and the last close."""
    rows, cols = np.nonzero(sim.listed)
    carried = np.where(sim.traded, sim.close, np.nan)
    for t in range(1, carried.shape[0]):
        gap = sim.listed[t] & ~sim.traded[t]
        carried[t, gap] = carried[t - 1, gap]

    def pick(matrix: Array, fallback: Array | None = None) -> Array:
        values = matrix[rows, cols]
        if fallback is not None:
            values = np.where(np.isfinite(values), values, fallback[rows, cols])
        return values

    vwap = (sim.open + sim.high + sim.low + sim.close) / 4.0
    return pl.DataFrame(
        {
            "date": [sim.days[r] for r in rows],
            "instrument": [sim.instruments[c] for c in cols],
            "open": pick(sim.open, carried),
            "high": pick(sim.high, carried),
            "low": pick(sim.low, carried),
            "close": pick(sim.close, carried),
            "volume": np.where(sim.traded[rows, cols], sim.volume[rows, cols], 0.0),
            "amount": np.where(sim.traded[rows, cols], sim.amount[rows, cols], 0.0),
            "factor": pick(sim.factor),
            "vwap": pick(vwap, carried),
        },
        nan_to_null=True,
    ).sort("instrument", "date")


def _membership_frame(sim: Simulation) -> pl.DataFrame:
    records: list[tuple[str, str, date, date]] = []
    for j, name in enumerate(sim.instruments):
        column = sim.member[:, j]
        t = 0
        while t < len(column):
            if column[t]:
                start = t
                while t + 1 < len(column) and column[t + 1]:
                    t += 1
                records.append((UNIVERSE, name, sim.days[start], sim.days[t]))
            t += 1
    return pl.DataFrame(
        records,
        schema={"universe": pl.String, "instrument": pl.String, "start": pl.Date, "end": pl.Date},
        orient="row",
    )


def generate(
    config: SyntheticConfig,
    world: World,
    epoch: EpochConfig,
    settings: MetricSettings,
    minimum: int,
) -> SyntheticWorld:
    """Calibrate, simulate the world from its seed, and build the canonical frames."""
    days = weekday_calendar(config.start, config.trading_days)
    signals = active_signals(config, world, epoch, days)
    calibration = calibrate(config, world, epoch, settings, minimum)
    draws = draw(config, config.seed, days)
    sim = simulate(config, days, draws, _loadings(signals, calibration.alphas, len(days)))
    observations = _observations(sim)
    membership = _membership_frame(sim)
    panel = build_panel(observations, days, membership)
    benchmark = equal_weight_benchmark(panel)
    calendar = (
        pl.DataFrame({"date": pl.Series(days, dtype=pl.Date)})
        .join(benchmark, on="date", how="left")
        .sort("date")
    )
    ground_truth: dict[str, Any] = {
        "world": world,
        "seed": config.seed,
        "note": GROUND_TRUTH_NOTE,
        "calibration": {
            "seed": config.calibration_seed,
            "rounds": calibration.rounds,
            "evaluations": calibration.evaluations,
            "tolerance": config.calibration.tolerance,
        },
        "signals": [
            {
                "name": s.name,
                "expression": s.expression,
                "target_rankic": s.target,
                "alpha": calibration.alphas[s.name],
                "calibration_rankic": calibration.rankic[s.name],
                "active_from": days[s.first].isoformat(),
                "active_until": days[s.stop - 1].isoformat(),
            }
            for s in signals
        ],
    }
    return SyntheticWorld(world, days, observations, membership, panel, calendar, ground_truth, sim)
