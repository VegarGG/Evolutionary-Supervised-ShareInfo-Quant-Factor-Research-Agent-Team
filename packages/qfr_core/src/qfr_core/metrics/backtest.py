"""Deterministic stock reference strategy. No protocol, simulated account or service."""

import math
from dataclasses import dataclass
from datetime import date
from typing import Literal, Self

import numpy as np
import polars as pl
from pydantic import Field, PositiveInt, model_validator

from qfr_core.contracts.base import Contract
from qfr_core.contracts.reports import MetricValue
from qfr_core.data_layer.snapshots import normalize_table
from qfr_core.metrics.core import mean, measurement, ratio


class BacktestConfig(Contract):
    revision: PositiveInt
    top_k: PositiveInt
    dropout: PositiveInt
    min_listed_days: PositiveInt
    universe_column: str
    sign: Literal[-1, 1]
    buy_cost_bps: float = Field(ge=0, lt=10000)
    sell_cost_bps: float = Field(ge=0, lt=10000)
    annual_periods: PositiveInt
    zero_epsilon: float = Field(gt=0)

    @model_validator(mode="after")
    def valid_dropout(self) -> Self:
        if self.dropout > self.top_k:
            raise ValueError("dropout exceeds top_k")
        return self


@dataclass(frozen=True)
class ReferenceBacktest:
    daily: pl.DataFrame
    trades: pl.DataFrame
    holdings: pl.DataFrame
    summary: dict[str, MetricValue]
    official: Literal[False] = False


def reference_backtest(
    panel: pl.DataFrame,
    scores: pl.DataFrame,
    benchmark: pl.DataFrame,
    config: BacktestConfig,
    *,
    start: date,
    end: date,
) -> ReferenceBacktest:
    """At t+1 close mark holdings, retry sells, then buy from the t ranking.

    Costs come from cash, so the final buy may be smaller than NAV/k. Suspended
    holdings with null quotes retain the last mark, explicitly counted each day.
    Turnover is half the traded notional divided by pre-trade NAV. Holding period
    is in trading sessions for completed positions. No forced terminal sale.
    """
    if end < start:
        raise ValueError("invalid window")
    frame = normalize_table(panel, ["instrument", "date"]).filter(
        pl.col("date").is_between(start, end)
    )
    frame = frame.drop("value", strict=False).join(
        scores.select("instrument", "date", "value"),
        on=["instrument", "date"],
        how="left",
        validate="1:1",
    )
    benchmark = normalize_table(benchmark, ["date"])
    benchmark_returns = dict(benchmark.select("date", "return").iter_rows())
    holdings: dict[str, tuple[float, int]] = {}  # adjusted units and entry session
    marks: dict[str, float] = {}
    pending: set[str] = set()
    previous_ranking: list[str] = []
    cash, previous_nav = 1.0, 1.0
    daily_rows, trade_rows, holding_rows, durations = [], [], [], []
    buy_cost, sell_cost = config.buy_cost_bps / 10000, config.sell_cost_bps / 10000
    for session, ((day,), cross) in enumerate(
        frame.sort("date", "instrument").group_by("date", maintain_order=True)
    ):
        quotes = {row["instrument"]: row for row in cross.iter_rows(named=True)}
        stale = 0
        for instrument in holdings:
            if instrument not in quotes:
                raise ValueError(f"held instrument missing from dense panel: {instrument} on {day}")
            row = quotes[instrument]
            price = row["close"]
            if price is None or not math.isfinite(price) or price <= 0:
                if row["is_suspended"] and instrument in marks:
                    stale += 1
                else:
                    raise ValueError(
                        f"held instrument has invalid tradable quote: {instrument} on {day}"
                    )
            else:
                marks[instrument] = float(price)
        before = cash + sum(units * marks[name] for name, (units, _) in holdings.items())
        traded, costs, blocked_sells, blocked_buys = 0.0, 0.0, 0, 0
        if session:
            ranks = {name: i for i, name in enumerate(previous_ranking)}
            top = set(previous_ranking[: config.top_k])
            outside = sorted(
                set(holdings) - top - pending,
                key=lambda name: (-ranks.get(name, len(ranks)), name),
            )
            selected = sorted(pending)[: config.dropout]
            selected += outside[: config.dropout - len(selected)]
            pending.update(selected)
            for instrument in selected:
                row = quotes[instrument]
                if row["is_suspended"] or row["limit_down"]:
                    blocked_sells += 1
                    continue
                units, entered = holdings.pop(instrument)
                value = units * marks[instrument]
                cost = value * sell_cost
                cash += value - cost
                traded += value
                costs += cost
                durations.append(session - entered)
                pending.remove(instrument)
                trade_rows.append(
                    {
                        "date": day,
                        "instrument": instrument,
                        "side": "sell",
                        "notional": value,
                        "cost": cost,
                    }
                )
            for instrument in previous_ranking:
                if len(holdings) >= config.top_k or cash <= config.zero_epsilon:
                    break
                if instrument in holdings:
                    continue
                buy_quote = quotes.get(instrument)
                if (
                    buy_quote is None
                    or buy_quote["is_suspended"]
                    or buy_quote["limit_up"]
                    or buy_quote["close"] is None
                    or not math.isfinite(buy_quote["close"])
                    or buy_quote["close"] <= 0
                ):
                    blocked_buys += 1
                    continue
                value = min(before / config.top_k, cash / (1 + buy_cost))
                cost = value * buy_cost
                marks[instrument] = float(buy_quote["close"])
                holdings[instrument] = (value / marks[instrument], session)
                cash -= value + cost
                traded += value
                costs += cost
                trade_rows.append(
                    {
                        "date": day,
                        "instrument": instrument,
                        "side": "buy",
                        "notional": value,
                        "cost": cost,
                    }
                )
        after = cash + sum(units * marks[name] for name, (units, _) in holdings.items())
        if cash < -config.zero_epsilon or abs(after - (before - costs)) > config.zero_epsilon * max(
            1, before
        ):
            raise ArithmeticError("portfolio accounting invariant failed")
        bench = benchmark_returns.get(day)
        if session and (bench is None or not math.isfinite(bench)):
            raise ValueError(f"benchmark return missing on {day}")
        daily_rows.append(
            {
                "date": day,
                "nav": after,
                "gross_return": before / previous_nav - 1,
                "net_return": after / previous_nav - 1,
                "benchmark_return": bench,
                "turnover": traded / (2 * before),
                "cost": costs,
                "cash": cash,
                "holdings_count": len(holdings),
                "blocked_sells": blocked_sells,
                "blocked_buys": blocked_buys,
                "carried_marks": stale,
            }
        )
        for name, (units, entered) in sorted(holdings.items()):
            holding_rows.append(
                {
                    "date": day,
                    "instrument": name,
                    "units": units,
                    "weight": units * marks[name] / after,
                    "age": session - entered,
                }
            )
        previous_nav = after
        eligible = cross.filter(
            pl.col(config.universe_column)
            & (pl.col("listed_days") >= config.min_listed_days)
            & ~pl.col("is_suspended")
            & pl.col("value").is_finite()
        ).with_columns((pl.col("value") * config.sign).alias("score"))
        previous_ranking = eligible.sort(["score", "instrument"], descending=[True, False])[
            "instrument"
        ].to_list()
    if not daily_rows:
        raise ValueError("empty backtest window")
    daily = pl.DataFrame(daily_rows)
    returns = daily["net_return"].to_numpy()[1:]
    benchmark_array = daily["benchmark_return"].to_numpy()[1:]
    nav = np.r_[1.0, daily["nav"].to_numpy()]
    drawdown = float(np.max(1 - nav / np.maximum.accumulate(nav)))
    annual_return = (
        float(nav[-1] ** (config.annual_periods / len(returns)) - 1) if len(returns) else None
    )
    summary = {
        "annualized_net_return": measurement(annual_return),
        "annualized_volatility": measurement(
            float(returns.std(ddof=1) * math.sqrt(config.annual_periods))
            if len(returns) > 1
            else None
        ),
        "sharpe": measurement(ratio(returns.tolist(), config.annual_periods)),
        "information_ratio": measurement(
            ratio((returns - benchmark_array).tolist(), config.annual_periods)
        ),
        "max_drawdown": measurement(drawdown),
        "calmar": measurement(
            annual_return / drawdown if annual_return is not None and drawdown > 0 else None
        ),
        "turnover": measurement(mean(daily["turnover"].to_list()[1:])),
        "average_holding_period": measurement(mean(durations)),
    }
    return ReferenceBacktest(daily, pl.DataFrame(trade_rows), pl.DataFrame(holding_rows), summary)
