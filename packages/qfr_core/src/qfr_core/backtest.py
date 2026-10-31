"""The reference TopK-dropout backtest (PLAN Section 8.6).

A deterministic daily loop on NumPy arrays, written for correctness, not speed. It is
weight based: notional capital 1, no lots. On each decision day t the eligible names
are ranked by score (ties by ascending instrument id). Up to n holdings ranked outside
the top k are sold, lowest score first; holdings without a score at t rank lowest.
Orders execute at the close of t+1. A blocked sell (suspended or limit-down at t+1)
stays pending and is retried on the next execution day; pending sells come on top of
the n new ones. Buys walk down the ranking from the highest name not held, skipping
blocked names (suspended or limit-up at t+1), until there are k holdings again; each
buy is sized at NAV / k from available cash. Retained positions drift with adjusted
closes and are never rebalanced.
"""

import math
from dataclasses import dataclass
from datetime import date
from typing import Self

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, JsonValue

from qfr_core.metrics.factor import PERIODS_PER_YEAR, sharpe
from qfr_core.metrics.matrix import Array, Market


class BacktestSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    top_k: int = Field(ge=1)
    dropout: int = Field(ge=1)
    buy_bps: float = Field(ge=0)
    sell_bps: float = Field(ge=0)

    @classmethod
    def from_protocol(
        cls, protocol: dict[str, JsonValue], top_k: int | None = None, dropout: int | None = None
    ) -> Self:
        strategy, costs = protocol["reference_strategy"], protocol["costs"]
        assert isinstance(strategy, dict) and isinstance(costs, dict)
        return cls.model_validate(
            {
                "top_k": strategy["top_k"] if top_k is None else top_k,
                "dropout": strategy["dropout"] if dropout is None else dropout,
                "buy_bps": costs["buy_bps"],
                "sell_bps": costs["sell_bps"],
            }
        )


class BacktestMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    days: int
    annual_return: float | None
    annual_volatility: float | None
    sharpe: float | None
    information_ratio: float | None
    max_drawdown: float
    calmar: float | None
    turnover: float | None
    average_holding_days: float | None
    final_nav: float


@dataclass(frozen=True)
class BacktestResult:
    """Daily series on execution days (the first decision day carries NAV 1)."""

    dates: list[date]
    nav: Array
    gross_return: Array
    net_return: Array
    turnover: Array
    holdings: Array
    benchmark_return: Array
    metrics: BacktestMetrics


def _ranking(scores: Array, eligible: np.ndarray) -> list[int]:
    """Eligible names with a finite score, best first, ties by ascending column."""
    names = np.flatnonzero(eligible & np.isfinite(scores))
    return sorted(names.tolist(), key=lambda j: (-scores[j], j))


def run_backtest(
    scores: Array, market: Market, start: date, end: date, settings: BacktestSettings
) -> BacktestResult:
    """Backtest decision days in [start, end); the last execution day is end."""
    first, last = market.window(start, end)
    k, n = settings.top_k, settings.dropout
    buy_cost, sell_cost = settings.buy_bps / 10_000.0, settings.sell_bps / 10_000.0
    positions: dict[int, float] = {}
    pending: list[int] = []
    cash, nav = 1.0, 1.0
    last_price = np.full(market.shape[1], np.nan)
    orders: tuple[list[int], list[int]] | None = None
    out_dates: list[date] = []
    navs, gross, net, turnover, holdings, bench = [], [], [], [], [], []
    bought = 0
    for day in range(first, last + 1):
        close = market.close[day]
        for j in list(positions):
            if math.isfinite(close[j]) and math.isfinite(last_price[j]):
                positions[j] *= close[j] / last_price[j]
        last_price = np.where(np.isfinite(close), close, last_price)
        previous_nav = nav
        traded = costs = 0.0
        if orders is not None:
            sells, candidates = orders
            still: list[int] = []
            for j in sells:
                if j not in positions:
                    continue
                if not market.tradable[day, j] or market.limit_down[day, j]:
                    still.append(j)
                    continue
                value = positions.pop(j)
                cash += value * (1.0 - sell_cost)
                traded += value
                costs += value * sell_cost
            pending = still
            nav_now = cash + sum(positions.values())
            size = nav_now / k
            for j in candidates:
                if len(positions) >= k or cash <= 1e-15:
                    break
                if j in positions or not market.tradable[day, j] or market.limit_up[day, j]:
                    continue
                amount = min(size, cash / (1.0 + buy_cost))
                cash -= amount * (1.0 + buy_cost)
                positions[j] = amount
                traded += amount
                costs += amount * buy_cost
                bought += 1
        nav = cash + sum(positions.values())
        out_dates.append(market.dates[day])
        navs.append(nav)
        if day == first:
            gross.append(np.nan)
            net.append(np.nan)
            turnover.append(np.nan)
        else:
            net.append(nav / previous_nav - 1.0)
            gross.append((nav + costs) / previous_nav - 1.0)
            turnover.append(traded / (2.0 * previous_nav))
        holdings.append(float(len(positions)))
        bench.append(float(market.benchmark_ret[day]) if day > first else np.nan)
        if day < last:
            ranking = _ranking(scores[day], market.eligible[day])
            top = set(ranking[:k])
            rank_of = {j: r for r, j in enumerate(ranking)}
            outside = [j for j in positions if j not in top and j not in pending]
            outside.sort(key=lambda j: (-rank_of.get(j, len(ranking)), j))
            sells = pending + outside[:n]
            orders = (sells, [j for j in ranking if j not in positions])
    nav_series = np.array(navs)
    net_series = np.array(net)
    bench_series = np.array(bench)
    metrics = _metrics(nav_series, net_series, bench_series, np.array(turnover), holdings, bought)
    return BacktestResult(
        dates=out_dates,
        nav=nav_series,
        gross_return=np.array(gross),
        net_return=net_series,
        turnover=np.array(turnover),
        holdings=np.array(holdings),
        benchmark_return=bench_series,
        metrics=metrics,
    )


def _metrics(
    nav: Array,
    net: Array,
    benchmark: Array,
    turnover: Array,
    holdings: list[float],
    bought: int,
) -> BacktestMetrics:
    days = int(np.isfinite(net).sum())
    annual = float(nav[-1] ** (PERIODS_PER_YEAR / days) - 1.0) if days and nav[-1] > 0 else None
    finite = net[np.isfinite(net)]
    volatility = (
        float(finite.std(ddof=1) * math.sqrt(PERIODS_PER_YEAR)) if finite.size > 1 else None
    )
    active = net - benchmark
    drawdown = float(np.max(1.0 - nav / np.maximum.accumulate(nav)))
    mean_holdings = float(np.mean(holdings[1:])) if len(holdings) > 1 else 0.0
    buys_per_day = bought / days if days else 0.0
    return BacktestMetrics(
        days=days,
        annual_return=annual,
        annual_volatility=volatility,
        sharpe=sharpe(net),
        information_ratio=sharpe(active),
        max_drawdown=drawdown,
        calmar=annual / drawdown if annual is not None and drawdown > 0 else None,
        turnover=float(np.nanmean(turnover)) if np.isfinite(turnover).any() else None,
        # Little's law: mean holdings divided by mean names bought per day.
        average_holding_days=mean_holdings / buys_per_day if buys_per_day > 0 else None,
        final_nav=float(nav[-1]),
    )
