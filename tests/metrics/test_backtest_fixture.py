"""Hand-computed TopK-dropout backtest (PLAN 8.6): 3 stocks, 6 days, k = 1, n = 1.

Costs are the protocol defaults: buy 5 bps, sell 15 bps.

    close      d0   d1   d2   d3   d4   d5
    X          20   20   20   20   22   21     limit-up on d1
    Y          10   10   --    9    9    9     suspended on d2
    Z           5    5    5    5    5    5

    score      d0   d1   d2   d3   d4
    X           3    3    3    3    3
    Y           2    1   --    1    1
    Z           1    2    2    2    2

d0  decide: top 1 = X; buy candidates X, Y, Z.
d1  X is limit-up: the buy is blocked and moves on to Y. Buy Y for
    a = 1 / 1.0005 (NAV / k, capped by cash including the cost); cash 0. NAV = a.
    decide: top 1 = X, Y is outside it, so sell Y (n = 1).
d2  Y is suspended: the sell is blocked and stays pending. Y keeps its d1 value; the
    book is full (1 holding = k), so nothing is bought. NAV = a.
    decide: the pending sell of Y is retried.
d3  Y trades at 9: its value is a * 0.9; the sell yields v = a * 0.9 * (1 - 0.0015).
    Buy X for b = v / 1.0005. NAV = b.
d4  X 20 -> 22: NAV = b * 1.1.
d5  X 22 -> 21: NAV = b * 21 / 20.
"""

import math
from datetime import date, timedelta

import numpy as np
import pytest
from qfr_core.backtest import BacktestSettings, run_backtest
from qfr_core.metrics.matrix import Market

DAYS = [date(2021, 3, 1) + timedelta(days=i) for i in range(6)]
SETTINGS = BacktestSettings(top_k=1, dropout=1, buy_bps=5, sell_bps=15)


def fixture() -> tuple[np.ndarray, Market]:
    nan = np.nan
    close = np.array(
        [
            [20, 10, 5],
            [20, 10, 5],
            [20, nan, 5],
            [20, 9, 5],
            [22, 9, 5],
            [21, 9, 5],
        ],
        dtype=float,
    )
    scores = np.array(
        [[3, 2, 1], [3, 1, 2], [3, nan, 2], [3, 1, 2], [3, 1, 2], [3, 1, 2]], dtype=float
    )
    tradable = np.isfinite(close)
    limit_up = np.zeros(close.shape, dtype=bool)
    limit_up[1, 0] = True
    market = Market.from_matrices(
        DAYS,
        ["X", "Y", "Z"],
        close,
        eligible=tradable.copy(),
        minimum=1,
        tradable=tradable,
        limit_up=limit_up,
        benchmark_ret=np.zeros(6),
    )
    return scores, market


def test_nav_path_with_one_blocked_buy_and_one_blocked_sell():
    scores, market = fixture()
    result = run_backtest(scores, market, DAYS[0], DAYS[-1], SETTINGS)
    a = 1 / 1.0005
    v = a * 0.9 * (1 - 0.0015)
    b = v / 1.0005
    expected = [1.0, a, a, b, b * 1.1, b * 21 / 20]
    np.testing.assert_allclose(result.nav, expected, rtol=1e-12)
    np.testing.assert_allclose(result.holdings, [0, 1, 1, 1, 1, 1])
    # Gross returns add back the day's costs; d1 costs exactly the buy fee.
    assert result.gross_return[1] == pytest.approx(0.0, abs=1e-15)
    assert result.net_return[1] == pytest.approx(a - 1)
    # Turnover = traded value / (2 * previous NAV).
    assert result.turnover[1] == pytest.approx(a / 2)
    assert result.turnover[2] == pytest.approx(0.0)
    assert result.turnover[3] == pytest.approx((a * 0.9 + b) / (2 * a))
    assert result.metrics.final_nav == pytest.approx(b * 21 / 20)
    # The peak stays at the starting NAV of 1 (b * 1.1 < 1), so the deepest point is b.
    assert result.metrics.max_drawdown == pytest.approx(1 - b)


def test_metrics_follow_the_daily_series():
    scores, market = fixture()
    result = run_backtest(scores, market, DAYS[0], DAYS[-1], SETTINGS)
    net = result.net_return[1:]
    m = result.metrics
    assert m.days == 5
    assert m.sharpe == pytest.approx(net.mean() / net.std(ddof=1) * math.sqrt(252))
    assert m.information_ratio == pytest.approx(m.sharpe)  # The benchmark is flat.
    assert m.annual_return == pytest.approx(result.nav[-1] ** (252 / 5) - 1)
    # Two buys over five days with one holding on average: 2.5 days per position.
    assert m.average_holding_days == pytest.approx(1.0 / (2 / 5))


def test_ties_break_by_instrument_order():
    _, market = fixture()
    flat = np.ones((6, 3))
    result = run_backtest(flat, market, DAYS[0], DAYS[-1], SETTINGS)
    # All scores tie, so X ranks first; X is blocked on d1 and Y is bought instead.
    assert result.holdings[1] == 1
    assert result.nav[1] == pytest.approx(1 / 1.0005)
