"""Phase 8 strategy rules in the backtester (PLAN 7.8, P8.2): long-short books, position
caps with trims, industry caps and industry neutralization, on hand-computed markets.

Costs are zero unless a test says otherwise, so NAV paths are exact."""

from datetime import date, timedelta

import numpy as np
import pytest
from qfr_core.backtest import BacktestSettings, run_backtest
from qfr_core.data.industry import NO_INDUSTRY, IndustryCodes
from qfr_core.metrics.matrix import Market
from qfr_core.portfolio import PortfolioRules, capped, decide, neutralize

DAYS = [date(2022, 1, 3) + timedelta(days=i) for i in range(6)]


def market(close, *, industry=None, limit_up=None, limit_down=None):
    close = np.array(close, dtype=float)
    tradable = np.isfinite(close)
    codes = None
    if industry is not None:
        grid = np.tile(np.array(industry, dtype=np.int64), (close.shape[0], 1))
        codes = IndustryCodes("test", ["A", "B"], grid)
    return Market.from_matrices(
        DAYS[: close.shape[0]],
        [f"N{j}" for j in range(close.shape[1])],
        close,
        eligible=tradable.copy(),
        minimum=1,
        tradable=tradable,
        limit_up=limit_up,
        limit_down=limit_down,
        benchmark_ret=np.zeros(close.shape[0]),
        industry=codes,
    )


def settings(**rules):
    return BacktestSettings(top_k=rules.pop("k", 1), dropout=1, buy_bps=0, sell_bps=0, **rules)


def test_neutralize_demeans_within_each_industry_and_drops_unclassified_names():
    scores = np.array([[1.0, 3.0, 10.0, 20.0, 5.0]])
    codes = np.array([[0, 0, 1, 1, NO_INDUSTRY]])
    out = neutralize(scores, codes)
    np.testing.assert_allclose(out[0, :4], [-1.0, 1.0, -5.0, 5.0])
    assert np.isnan(out[0, 4])


def test_the_capped_top_takes_at_most_the_slots_per_industry():
    industry = np.array([0, 0, 0, 1, NO_INDUSTRY])
    assert capped([0, 1, 2, 3, 4], 3, industry, 1) == [0, 3]
    assert capped([0, 1, 2, 3, 4], 3, industry, 2) == [0, 1, 3]
    assert capped([0, 1, 2, 3, 4], 3, None, None) == [0, 1, 2]


def test_v1_decisions_are_the_reference_rules():
    scores = np.array([4.0, 3.0, 2.0, 1.0])
    eligible = np.ones(4, dtype=bool)
    rules = PortfolioRules(top_k=2, dropout=1)
    decision = decide(scores, eligible, None, {3: 0.5, 2: 0.5}, {}, [], [], 1.0, rules)
    assert decision.sells == [3]  # the worst holding outside the top 2; n = 1
    assert decision.buys == [0, 1]
    assert decision.covers == decision.shorts == decision.trims == []


def test_a_long_short_book_holds_the_best_long_and_the_worst_short():
    # N0 is the best name, N3 the worst; both rise 10% on day 2.
    close = [[10, 10, 10, 10]] * 2 + [[11, 10, 10, 11]] * 4
    scores = np.tile([3.0, 2.0, 1.0, 0.0], (6, 1))
    result = run_backtest(scores, market(close), DAYS[0], DAYS[-1], settings(long_only=False))
    # Day 1: long N0 for 1, short N3 for 1 (gross 2, net 0); day 2 both rise 10%.
    np.testing.assert_allclose(result.nav, [1.0] * 6)
    np.testing.assert_allclose(result.holdings, [0, 2, 2, 2, 2, 2])
    # Market neutral: the information ratio is measured against cash.
    assert result.metrics.information_ratio is None or np.isfinite(result.metrics.information_ratio)


def test_the_short_book_pays_borrow_and_profits_when_its_names_fall():
    close = [[10, 10, 10, 10]] * 2 + [[10, 10, 10, 9]] * 4
    scores = np.tile([3.0, 2.0, 1.0, 0.0], (6, 1))
    borrow = 2520.0  # 25.2% a year: 0.1% of the short value a day
    result = run_backtest(
        scores, market(close), DAYS[0], DAYS[-1], settings(long_only=False, borrow_bps=borrow)
    )
    day = 0.001
    nav1 = 1.0 - day * 1.0  # the short N3 is worth -1 at the day-1 close
    nav2 = nav1 + 0.1 - day * 0.9  # N3 falls 10%: the short gains 0.1 and costs less
    assert result.nav[1] == pytest.approx(nav1, rel=1e-12)
    assert result.nav[2] == pytest.approx(nav2, rel=1e-12)


def test_short_entries_wait_for_a_tradable_non_limit_down_day_and_covers_for_non_limit_up():
    close = [[10, 10, 10, 10]] * 6
    limit_down = np.zeros((6, 4), dtype=bool)
    limit_down[1, 3] = True  # the first short entry day: N3 cannot be sold short
    scores = np.tile([3.0, 2.0, 1.0, 0.0], (6, 1))
    result = run_backtest(
        scores,
        market(close, limit_down=limit_down),
        DAYS[0],
        DAYS[-1],
        settings(long_only=False),
    )
    # Day 1 walks on to the next worst name (N2) instead.
    assert result.holdings[1] == 2
    # Day 2: N3 is now the worst and N2 is outside the short top 1, so it is covered and
    # N3 shorted: two trades of 1 each on a NAV of 1.
    assert result.turnover[2] == pytest.approx(2.0 / 2.0)


def test_a_position_above_its_cap_is_trimmed_back_to_the_cap():
    # Two names at 0.5 each; N0 doubles on day 2 (weight 2/3 > 0.5 x 1.1).
    close = [[20, 10]] * 2 + [[40, 10]] * 4
    scores = np.tile([2.0, 1.0], (6, 1))
    result = run_backtest(
        scores, market(close), DAYS[0], DAYS[-1], settings(k=2, max_position_weight=0.5)
    )
    np.testing.assert_allclose(result.nav, [1.0, 1.0, 1.5, 1.5, 1.5, 1.5])
    # Day 3 trims N0 from 1.0 to 0.75 (cap x NAV): traded 0.25 on a NAV of 1.5.
    assert result.turnover[3] == pytest.approx(0.25 / 3.0)
    assert result.turnover[4] == 0.0


def test_entries_are_sized_at_the_cap_when_it_is_below_one_over_k():
    close = [[10, 10]] * 6
    scores = np.tile([2.0, 1.0], (6, 1))
    result = run_backtest(
        scores, market(close), DAYS[0], DAYS[-1], settings(k=1, max_position_weight=0.4)
    )
    assert result.turnover[1] == pytest.approx(0.4 / 2.0)


def test_an_industry_cap_takes_the_best_name_of_each_industry():
    # N0 and N1 are industry A, N2 and N3 industry B; the plain top 2 is N0 and N1.
    close = [[10, 10, 10, 10]] * 2 + [[10, 11, 9, 10]] * 4
    scores = np.tile([4.0, 3.0, 2.0, 1.0], (6, 1))
    plain = run_backtest(scores, market(close), DAYS[0], DAYS[-1], settings(k=2))
    capped_market = market(close, industry=[0, 0, 1, 1])
    one_each = run_backtest(
        scores, capped_market, DAYS[0], DAYS[-1], settings(k=2, max_industry_weight=0.5)
    )
    assert plain.nav[2] == pytest.approx(1.05)  # N0 flat, N1 up 10%
    assert one_each.nav[2] == pytest.approx(0.95)  # N0 flat, N2 down 10%


def test_an_industry_cap_needs_the_industry_table():
    close = [[10, 10]] * 6
    with pytest.raises(ValueError, match="industry"):
        run_backtest(
            np.ones((6, 2)), market(close), DAYS[0], DAYS[-1], settings(max_industry_weight=0.5)
        )
