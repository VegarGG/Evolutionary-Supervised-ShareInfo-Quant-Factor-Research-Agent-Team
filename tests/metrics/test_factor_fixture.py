"""Hand-computed factor metrics (PLAN 8.5): 5 instruments A..E over 6 days.

Closes are built so the one-day labels y(t) = close[t+2] / close[t+1] - 1 for decision
days t = 0..3 are exactly the values below (day 4 and 5 have no label inside the
window). Winsorization is switched off (0, 1) so every number is hand-checkable; the
z-score does not change Pearson or Spearman correlations.

    t   f (A..E)          y (A..E)
    0   1 2 3 4 5         -.02 -.01  0   .01  .02
    1   1 2 3 4 5         -.01 -.02  0   .02  .01
    2   1 2 3 5 4          .02  .01  0  -.01 -.02
    3   1 2 3 4 5         -.02 -.01 .01  .02  0

RankIC(t), Spearman with n = 5, rho = 1 - 6 sum(d^2) / 120:
    t0: d = 0 everywhere            ->  1
    t1: y ranks 2 1 3 5 4, sum 4    ->  0.8
    t2: f ranks 1 2 3 5 4 vs y ranks 5 4 3 2 1, d = -4 -2 0 3 3, sum 38 -> -0.9
    t3: y ranks 1 2 4 5 3, sum 6    ->  0.7
IC(t) equals RankIC(t) here: each y has mean 0 and sum of squares .001, f has centred
sum of squares 10, and the cross products are .08, -.09 and .07 (t1, t2, t3).

mean = 0.4; deviations .6 .4 -1.3 .3; sum of squares 2.3; std = sqrt(2.3 / 3).
Newey-West lag = max(1, floor(4 (4/100)^(2/9))) = 1; gamma0 = 2.3/4 = .575;
gamma1 = (.4 * .6 - 1.3 * .4 - .3 * 1.3) / 4 = -.1675; var = .575 - .1675 = .4075;
t = .4 / sqrt(.4075 / 4).

Quintiles: one name per group. Q5 (highest f) is E, except at t2 where it is D.
LS = y(Q5) - y(Q1) = .04, .02, -.03, .02 -> mean .0125.
Top set {E}, {E}, {D}, {E}: top turnover at t1..t3 = 0, 1, 1 -> mean 2/3; bottom {A}
always -> 0. LS_net = LS - 2 * .001 * (top + bottom) at t1..t3 = .02, -.032, .018.
Group means: Q1 -.0075, Q2 -.0075, Q3 .0025, Q4 (D, D, E, D) .0075, Q5 .005.
Monotonicity = Spearman(1..5, means): mean ranks 1.5 1.5 3 5 4 -> 8.5 / sqrt(10 * 9.5).
Rank autocorrelation: Spearman(f(t), f(t-1)) = 1, .9, .9 -> 2.8 / 3.
"""

import math
from datetime import date, timedelta

import numpy as np
import pytest
from qfr_core.metrics.factor import MetricSettings, evaluate_factor
from qfr_core.metrics.matrix import Market

DAYS = [date(2020, 1, 6) + timedelta(days=i) for i in range(6)]
NAMES = ["A", "B", "C", "D", "E"]
F = np.array(
    [
        [1, 2, 3, 4, 5],
        [1, 2, 3, 4, 5],
        [1, 2, 3, 5, 4],
        [1, 2, 3, 4, 5],
        [1, 2, 3, 4, 5],
        [1, 2, 3, 4, 5],
    ],
    dtype=float,
)
Y = np.array(
    [
        [-0.02, -0.01, 0.0, 0.01, 0.02],
        [-0.01, -0.02, 0.0, 0.02, 0.01],
        [0.02, 0.01, 0.0, -0.01, -0.02],
        [-0.02, -0.01, 0.01, 0.02, 0.0],
    ]
)
SETTINGS = MetricSettings(
    winsor_lower=0.0,
    winsor_upper=1.0,
    quantiles=5,
    horizons=(1, 5),
    primary_horizon=1,
    ls_cost_bps_per_side=10,
)


def market() -> Market:
    close = np.full((6, 5), 100.0)
    for t in range(4):
        close[t + 2] = close[t + 1] * (1.0 + Y[t])
    return Market.from_matrices(DAYS, NAMES, close, np.ones((6, 5), dtype=bool), minimum=2)


@pytest.fixture(scope="module")
def result():
    return evaluate_factor(F, market(), DAYS[0], DAYS[-1], 1, SETTINGS)


def test_daily_rank_ic_and_ic(result):
    expected = [1.0, 0.8, -0.9, 0.7, np.nan, np.nan]
    np.testing.assert_allclose(result.series.rank_ic, expected, atol=1e-12)
    np.testing.assert_allclose(result.series.ic, expected, atol=1e-12)


def test_rank_ic_summary(result):
    m = result.metrics
    assert m.dates_evaluated == 4
    assert m.rankic_mean == pytest.approx(0.4)
    assert m.ic_mean == pytest.approx(0.4)
    assert m.rankic_std == pytest.approx(math.sqrt(2.3 / 3))
    assert m.rankic_ir == pytest.approx(0.4 / math.sqrt(2.3 / 3))
    assert m.nw_lag == 1
    assert m.rankic_t_nw == pytest.approx(0.4 / math.sqrt(0.4075 / 4))
    assert m.hit_ratio == pytest.approx(0.75)
    assert m.sign_consistency == 1
    # No h = 5 label fits inside a six-day window.
    assert m.decay == {"1": pytest.approx(0.4), "5": None}
    assert m.yearly_rankic == {"2020": pytest.approx(0.4)}


def test_quantiles_long_short_and_turnover(result):
    m = result.metrics
    np.testing.assert_allclose(result.series.ls[:4], [0.04, 0.02, -0.03, 0.02], atol=1e-12)
    assert m.quantile_returns == pytest.approx([-0.0075, -0.0075, 0.0025, 0.0075, 0.005])
    assert m.ls_gross_mean == pytest.approx(0.0125)
    ls = np.array([0.04, 0.02, -0.03, 0.02])
    assert m.ls_gross_sharpe == pytest.approx(ls.mean() / ls.std(ddof=1) * math.sqrt(252))
    assert m.top_turnover == pytest.approx(2 / 3)
    assert m.bottom_turnover == pytest.approx(0.0)
    net = np.array([0.02, -0.032, 0.018])
    np.testing.assert_allclose(result.series.ls_net[1:4], net, atol=1e-12)
    assert np.isnan(result.series.ls_net[0])
    assert m.ls_net_mean == pytest.approx(0.002)
    assert m.ls_net_sharpe == pytest.approx(net.mean() / net.std(ddof=1) * math.sqrt(252))
    assert m.monotonicity == pytest.approx(8.5 / math.sqrt(95))
    assert m.rank_autocorrelation == pytest.approx(2.8 / 3)
    assert m.coverage == pytest.approx(1.0)


def test_negative_sign_flips_long_short_and_swaps_top_and_bottom():
    m = evaluate_factor(F, market(), DAYS[0], DAYS[-1], -1, SETTINGS).metrics
    assert m.ls_gross_mean == pytest.approx(-0.0125)
    assert m.sign_consistency == -1
    assert m.hit_ratio == pytest.approx(0.25)
    assert m.top_turnover == pytest.approx(0.0)  # The top set is now {A}.
    assert m.bottom_turnover == pytest.approx(2 / 3)
    assert m.monotonicity == pytest.approx(-8.5 / math.sqrt(95))


def test_labels_never_leave_the_window():
    # Ending the window at day 3 leaves labels only for t = 0, 1 (t + 2 <= 3).
    m = evaluate_factor(F, market(), DAYS[0], DAYS[3], 1, SETTINGS).metrics
    assert m.dates_evaluated == 2
    assert m.rankic_mean == pytest.approx(0.9)


def test_coverage_eligibility_and_minimum_cross_section():
    f = F.copy()
    f[0, 0] = np.nan  # A has no value at t0: U(t0) is B..E.
    eligible = np.ones((6, 5), dtype=bool)
    eligible[:, 4] = False  # E is never eligible.
    base = market()
    restricted = Market.from_matrices(DAYS, NAMES, base.close, eligible, minimum=4)
    m = evaluate_factor(f, restricted, DAYS[0], DAYS[-1], 1, SETTINGS).metrics
    # Coverage counts eligible names with a value: 3/4 on t0, 4/4 on days 1..5.
    assert m.coverage == pytest.approx((0.75 + 5 * 1.0) / 6)
    # t0 has only 3 names in U(t0), below the minimum of 4, so it is skipped.
    assert m.dates_evaluated == 3


def test_library_correlation_is_vacuous_when_empty_and_reports_the_argmax(result):
    assert result.metrics.library_correlation.vacuous is True
    assert result.metrics.library_correlation.max_abs is None
    library = {"same": F.copy(), "reverse": -F + 0.0, "flat": np.ones_like(F)}
    m = evaluate_factor(F, market(), DAYS[0], DAYS[-1], 1, SETTINGS, library).metrics
    assert m.library_correlation.vacuous is False
    assert m.library_correlation.max_abs == pytest.approx(1.0)
    assert m.library_correlation.argmax == "reverse"  # Ties keep the first name in order.
