import math
import statistics
from datetime import date, timedelta
from pathlib import Path

import polars as pl
import pytest
from qfr_core.metrics.backtest import BacktestConfig, reference_backtest


def fixture():
    days = [date(2020, 1, 1) + timedelta(days=i) for i in range(6)]
    prices = [[10, 10, 10], [10, 10, 20], [10, 12, 20], [10, 11, 20], [10, 11, 22], [10, 11, 20]]
    ranks = [[3, 2, 1], [3, 1, 2], [2, 1, 3], [2, 1, 3], [3, 1, 2], [3, 1, 2]]
    rows = [
        dict(
            date=day,
            instrument=name,
            close=prices[i][j],
            in_csi300=True,
            listed_days=100,
            is_suspended=False,
            limit_up=i == 1 and name == "A",
            limit_down=i == 2 and name == "B",
            value=float(ranks[i][j]),
        )
        for i, day in enumerate(days)
        for j, name in enumerate("ABC")
    ]
    config = BacktestConfig.model_validate_json(
        Path("configs/backtest/stock_daily_v1.json").read_text()
    ).model_copy(
        update={
            "top_k": 1,
            "dropout": 1,
            "buy_cost_bps": 100,
            "sell_cost_bps": 200,
            "annual_periods": 5,
        }
    )
    panel = pl.DataFrame(rows)
    benchmark = pl.DataFrame({"date": days, "return": [0.0] * 6})
    return panel, benchmark, config, days


def test_topk_hand_computed_nav_blocked_trades_and_metrics():
    panel, benchmark, config, days = fixture()
    result = reference_backtest(
        panel,
        panel.select("date", "instrument", "value"),
        benchmark,
        config,
        start=days[0],
        end=days[-1],
    )
    expected = [1, 100 / 101, 120 / 101, 10780 / 10201, 11858 / 10201, 1056440 / 1030301]
    assert result.daily["nav"].to_list() == pytest.approx(expected)
    assert result.daily["gross_return"].to_list() == pytest.approx(
        [0, 0, 0.2, -1 / 12, 0.1, -1 / 11]
    )
    assert result.daily["blocked_buys"].to_list() == [0, 1, 0, 0, 0, 0]
    assert result.daily["blocked_sells"].to_list() == [0, 0, 1, 0, 0, 0]
    assert result.trades.select("date", "instrument", "side").rows() == [
        (days[1], "B", "buy"),
        (days[3], "B", "sell"),
        (days[3], "C", "buy"),
        (days[5], "C", "sell"),
        (days[5], "A", "buy"),
    ]
    net = [expected[i] / expected[i - 1] - 1 for i in range(1, 6)]
    for name, value in {
        "annualized_net_return": expected[-1] - 1,
        "annualized_volatility": statistics.stdev(net) * math.sqrt(5),
        "sharpe": statistics.mean(net) / statistics.stdev(net) * math.sqrt(5),
        "information_ratio": statistics.mean(net) / statistics.stdev(net) * math.sqrt(5),
        "max_drawdown": 1 - expected[-1] / expected[2],
        "calmar": (expected[-1] - 1) / (1 - expected[-1] / expected[2]),
        "average_holding_period": 2,
        "turnover": ((1 / 1.01) / 2 + 2 * (1 + 0.98 / 1.01) / 2) / 5,
    }.items():
        assert result.summary[name].value == pytest.approx(value), name
    assert result.official is False


def test_retained_units_drift_and_window_does_not_trade_on_future_scores():
    panel, benchmark, config, days = fixture()
    config = config.model_copy(update={"top_k": 2, "buy_cost_bps": 0, "sell_cost_bps": 0})
    # Unchanging rank retains B and C after A's initial blocked buy.
    panel = panel.with_columns(
        pl.when(pl.col("instrument") == "A")
        .then(3.0)
        .when(pl.col("instrument") == "B")
        .then(2.0)
        .otherwise(1.0)
        .alias("value")
    )
    full = reference_backtest(panel, panel, benchmark, config, start=days[0], end=days[-1])
    prefix = reference_backtest(panel, panel, benchmark, config, start=days[0], end=days[2])
    assert full.daily.head(3).equals(prefix.daily)
    # At day 2 B cannot sell; its units have not changed despite its price rise.
    assert full.holdings.filter((pl.col("instrument") == "B") & pl.col("date").is_in(days[1:3]))[
        "units"
    ].to_list() == [0.05, 0.05]


def test_missing_benchmark_or_tradable_quote_is_not_silent_success():
    panel, benchmark, config, days = fixture()
    with pytest.raises(ValueError, match="benchmark"):
        reference_backtest(panel, panel, benchmark.head(2), config, start=days[0], end=days[-1])
    broken = panel.with_columns(
        pl.when((pl.col("date") == days[2]) & (pl.col("instrument") == "B"))
        .then(None)
        .otherwise(pl.col("close"))
        .alias("close")
    )
    with pytest.raises(ValueError, match="invalid tradable quote"):
        reference_backtest(broken, broken, benchmark, config, start=days[0], end=days[-1])
    suspended = broken.with_columns(
        ((pl.col("date") == days[2]) & (pl.col("instrument") == "B")).alias("is_suspended")
    )
    result = reference_backtest(
        suspended, suspended, benchmark, config, start=days[0], end=days[-1]
    )
    assert result.daily["carried_marks"].to_list() == [0, 0, 1, 0, 0, 0]
