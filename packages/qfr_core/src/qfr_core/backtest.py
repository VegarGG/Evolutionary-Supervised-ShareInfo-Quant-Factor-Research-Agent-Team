"""The reference TopK-dropout backtest (PLAN Section 8.6) and Phase 8 strategy rules.

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

Phase 8 strategies (qfr-strategy/2) add the rules in qfr_core.portfolio: a short book
(positions carry negative values; covers execute after sells, then trims, short entries
and buys), position caps with trims, industry caps and a daily borrow cost. A long-short
book is market neutral, so its information ratio is measured against cash.
"""

import math
from dataclasses import dataclass
from datetime import date
from typing import Self

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, JsonValue

from qfr_core.metrics.factor import PERIODS_PER_YEAR, sharpe
from qfr_core.metrics.matrix import Array, Market
from qfr_core.portfolio import PortfolioRules, decide, industry_full


class BacktestSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    top_k: int = Field(ge=1)
    dropout: int = Field(ge=1)
    buy_bps: float = Field(ge=0)
    sell_bps: float = Field(ge=0)
    # Phase 8 rules; the defaults are the v1 reference strategy.
    long_only: bool = True
    max_position_weight: float | None = Field(default=None, gt=0, le=1)
    max_industry_weight: float | None = Field(default=None, gt=0, le=1)
    borrow_bps: float = Field(default=0.0, ge=0)

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

    @property
    def rules(self) -> PortfolioRules:
        return PortfolioRules(
            top_k=self.top_k,
            dropout=self.dropout,
            long_only=self.long_only,
            max_position_weight=self.max_position_weight,
            max_industry_weight=self.max_industry_weight,
            borrow_bps=self.borrow_bps,
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


def run_backtest(
    scores: Array, market: Market, start: date, end: date, settings: BacktestSettings
) -> BacktestResult:
    """Backtest decision days in [start, end); the last execution day is end."""
    first, last = market.window(start, end)
    rules = settings.rules
    k = rules.top_k
    if rules.needs_industry and market.industry is None:
        raise ValueError("an industry cap needs the snapshot's industry classification")
    codes = market.industry.codes if market.industry is not None else None
    slots = rules.industry_slots
    buy_cost, sell_cost = settings.buy_bps / 10_000.0, settings.sell_bps / 10_000.0
    longs: dict[int, float] = {}
    shorts: dict[int, float] = {}
    pending: list[int] = []
    pending_covers: list[int] = []
    cash, nav = 1.0, 1.0
    last_price = np.full(market.shape[1], np.nan)
    orders = None
    out_dates: list[date] = []
    navs, gross, net, turnover, holdings, bench = [], [], [], [], [], []
    bought = 0
    for day in range(first, last + 1):
        close = market.close[day]
        for book in (longs, shorts):
            for j in list(book):
                if math.isfinite(close[j]) and math.isfinite(last_price[j]):
                    book[j] *= close[j] / last_price[j]
        last_price = np.where(np.isfinite(close), close, last_price)
        previous_nav = nav
        traded = costs = 0.0
        industry = codes[day] if codes is not None else None
        if orders is not None:
            still: list[int] = []
            for j in orders.sells:
                if j not in longs:
                    continue
                if not market.tradable[day, j] or market.limit_down[day, j]:
                    still.append(j)
                    continue
                value = longs.pop(j)
                cash += value * (1.0 - sell_cost)
                traded += value
                costs += value * sell_cost
            pending = still
            still_covers: list[int] = []
            for j in orders.covers:
                if j not in shorts:
                    continue
                if not market.tradable[day, j] or market.limit_up[day, j]:
                    still_covers.append(j)
                    continue
                value = -shorts.pop(j)
                cash -= value * (1.0 + buy_cost)
                traded += value
                costs += value * buy_cost
            pending_covers = still_covers
            nav_now = cash + sum(longs.values()) + sum(shorts.values())
            cap = rules.max_position_weight
            for j in orders.trims:
                if cap is None or not market.tradable[day, j]:
                    continue
                target = cap * nav_now
                if j in longs and longs[j] > target and not market.limit_down[day, j]:
                    cut = longs[j] - target
                    longs[j] = target
                    cash += cut * (1.0 - sell_cost)
                elif j in shorts and -shorts[j] > target and not market.limit_up[day, j]:
                    cut = -shorts[j] - target
                    shorts[j] = -target
                    cash -= cut * (1.0 + buy_cost)
                else:
                    continue
                traded += cut
                costs += cut * (sell_cost if j in longs else buy_cost)
            nav_now = cash + sum(longs.values()) + sum(shorts.values())
            size = rules.entry_size(nav_now)
            for j in orders.shorts:
                if len(shorts) >= k:
                    break
                if j in shorts or j in longs or not market.tradable[day, j]:
                    continue
                if market.limit_down[day, j] or industry_full(j, shorts, industry, slots):
                    continue
                shorts[j] = -size
                cash += size * (1.0 - sell_cost)
                traded += size
                costs += size * sell_cost
                bought += 1
            for j in orders.buys:
                if len(longs) >= k or cash <= 1e-15:
                    break
                if j in longs or j in shorts or not market.tradable[day, j]:
                    continue
                if market.limit_up[day, j] or industry_full(j, longs, industry, slots):
                    continue
                amount = min(size, cash / (1.0 + buy_cost))
                cash -= amount * (1.0 + buy_cost)
                longs[j] = amount
                traded += amount
                costs += amount * buy_cost
                bought += 1
        if shorts:
            borrow = rules.daily_borrow(sum(shorts.values()))
            cash -= borrow
            costs += borrow
        nav = cash + sum(longs.values()) + sum(shorts.values())
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
        holdings.append(float(len(longs) + len(shorts)))
        bench.append(float(market.benchmark_ret[day]) if day > first else np.nan)
        if day < last:
            orders = decide(
                scores[day], market.eligible[day], industry, longs, shorts, pending,
                pending_covers, nav, rules,
            )  # fmt: skip
    nav_series = np.array(navs)
    net_series = np.array(net)
    bench_series = np.array(bench)
    active_benchmark = bench_series if rules.long_only else np.zeros_like(bench_series)
    metrics = _metrics(
        nav_series, net_series, active_benchmark, np.array(turnover), holdings, bought
    )
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
