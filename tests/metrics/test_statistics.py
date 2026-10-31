"""PSR, DSR, PBO and Newey-West against worked examples (PLAN 8.7)."""

import math

import numpy as np
import pytest
from qfr_core.metrics.stats import (
    dsr,
    expected_max_sharpe,
    moments,
    newey_west_lag,
    newey_west_t,
    pbo,
    psr,
)
from scipy import stats


def test_dsr_matches_the_bailey_lopez_de_prado_worked_example():
    """Bailey and Lopez de Prado (2014), "The Deflated Sharpe Ratio", Section 5:
    annualized SR 2.5 over T = 1,250 daily returns, skewness -3, kurtosis 10, N = 100
    trials whose annualized Sharpe ratios have variance 0.5. In per-period units
    SR = 2.5 / sqrt(250) and V = 0.5 / 250; the paper reports SR0 = 0.1132 and DSR 0.9004.
    """
    sharpe = 2.5 / math.sqrt(250)
    variance = 0.5 / 250
    assert expected_max_sharpe(variance, 100) == pytest.approx(0.1132, abs=5e-5)
    assert dsr(sharpe, 1250, -3.0, 10.0, variance, 100) == pytest.approx(0.9004, abs=5e-4)


def test_psr_closed_form_under_normal_returns():
    # SR 0.1 over T = 101 with g3 = 0 and g4 = 3: z = 0.1 * 10 / sqrt(1 + 0.5 * 0.01).
    expected = stats.norm.cdf(1.0 / math.sqrt(1.005))
    assert psr(0.1, 0.0, 101, 0.0, 3.0) == pytest.approx(expected, rel=1e-12)
    assert psr(0.1, 0.1, 101, 0.0, 3.0) == pytest.approx(0.5)


def test_psr_penalizes_negative_skew_and_fat_tails():
    base = psr(0.1, 0.0, 500, 0.0, 3.0)
    assert psr(0.1, 0.0, 500, -2.0, 3.0) < base
    assert psr(0.1, 0.0, 500, 0.0, 9.0) < base


def test_moments_use_raw_kurtosis():
    returns = np.random.default_rng(3).normal(0.001, 0.01, 200_000)
    sharpe, skew, kurt, count = moments(returns)
    assert count == 200_000
    assert sharpe == pytest.approx(0.1, abs=0.01)
    assert skew == pytest.approx(0.0, abs=0.03)
    assert kurt == pytest.approx(3.0, abs=0.05)
    assert skew == pytest.approx(stats.skew(returns))
    assert kurt == pytest.approx(stats.kurtosis(returns, fisher=False))


def test_newey_west_matches_a_direct_computation():
    x = np.array([1.0, 0.8, -0.9, 0.7, 0.3, -0.2, 0.5, 0.1])
    lag = 2
    dev = x - x.mean()
    gamma = [float(dev[k:] @ dev[: len(x) - k]) / len(x) for k in range(lag + 1)]
    variance = gamma[0] + 2 * sum((1 - k / (lag + 1)) * gamma[k] for k in (1, 2))
    assert newey_west_t(x, lag) == pytest.approx(x.mean() / math.sqrt(variance / len(x)))
    assert newey_west_lag(4, 1) == 1
    assert newey_west_lag(1000, 1) == math.floor(4 * 10 ** (2 / 9))
    assert newey_west_lag(1000, 20) == 20


def test_pbo_hand_fixture_with_four_blocks():
    """T = 8 returns in S = 4 blocks of 2 rows, N = 2 versions.

    Blocks 0 and 1 are identical, and so are blocks 2 and 3:
        a: [.03, .01]  [.03, .01]  [-.01, .01]  [-.01, .01]
        b: [0, .02]    [0, .02]    [.01, .03]   [.01, .03]
    In-sample {0,1}: a wins (SR 1.73 vs .87) but is worse out of sample (0 vs 1.73):
    w = 1/3, lambda = ln(1/2). In-sample {2,3}: b wins (1.73 vs 0) and loses out of sample
    (.87 vs 1.73): lambda = ln(1/2). Every mixed choice ({0,2}, {0,3}, {1,2}, {1,3}) sees
    a = [.03, .01, -.01, .01] (SR .61) and b = [0, .02, .01, .03] (SR 1.16) on both
    halves, so b wins in and out of sample: w = 2/3, lambda = ln 2. PBO = 2 / 6.
    """
    a = [0.03, 0.01, 0.03, 0.01, -0.01, 0.01, -0.01, 0.01]
    b = [0.0, 0.02, 0.0, 0.02, 0.01, 0.03, 0.01, 0.03]
    value, logits = pbo(np.array([a, b]).T, blocks=4)
    assert value == pytest.approx(1 / 3)
    half, two = math.log(0.5), math.log(2.0)
    # Combination order: (0,1) (0,2) (0,3) (1,2) (1,3) (2,3).
    assert logits == pytest.approx([half, two, two, two, two, half])


def test_pbo_is_low_for_a_persistently_better_version_and_uses_12870_splits():
    rng = np.random.default_rng(11)
    noise = rng.normal(0, 0.01, (320, 5))
    noise[:, 0] += 0.004
    value, logits = pbo(noise, blocks=16)
    assert len(logits) == 12_870
    assert value < 0.05


def test_pbo_rejects_bad_shapes():
    with pytest.raises(ValueError):
        pbo(np.zeros((10, 1)), blocks=2)
    with pytest.raises(ValueError):
        pbo(np.zeros((10, 3)), blocks=3)
    with pytest.raises(ValueError):
        pbo(np.zeros((6, 3)), blocks=4)
