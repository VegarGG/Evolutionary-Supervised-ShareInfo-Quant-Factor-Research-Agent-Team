"""The Phase 8 CUSUM decay detector (P8.7, PLAN Section 10.4)."""

import math

import numpy as np
import pytest
from qfr_eval.monitoring import CusumReference, lower_cusum, reference_from_metrics

REFERENCE = CusumReference("r", "holdout", mu0=0.03, sigma=0.1)  # daily IR 0.3
K_FRACTION, H = 0.5, 12.0  # the shipped protocol's values


def test_the_reference_is_the_signed_mean_and_the_daily_spread():
    ref = reference_from_metrics("r", "w1", {"rankic_mean": -0.04, "rankic_ir": -0.2}, -1)
    assert ref is not None
    assert (ref.mu0, ref.sigma) == pytest.approx((0.04, 0.2))
    # No one-sided anchor: a mean against the declared sign, no IR, a zero IR.
    assert reference_from_metrics("r", "w1", {"rankic_mean": 0.04, "rankic_ir": 0.2}, -1) is None
    assert reference_from_metrics("r", "w1", {"rankic_mean": 0.04}, 1) is None
    assert reference_from_metrics("r", "w1", {"rankic_mean": 0.04, "rankic_ir": 0.0}, 1) is None


def test_the_statistic_follows_its_recursion_and_skips_missing_days():
    values = [0.03, -0.17, math.nan, -0.07, 0.23]
    result = lower_cusum(values, REFERENCE, K_FRACTION, H)
    # (mu0 - x - k) / sigma with k = 0.015: 0 -> max(0, -0.15) = 0, then 1.85, then
    # unchanged, then 1.85 + 0.85 = 2.7, then 2.7 - 2.15 = 0.55.
    assert result.alarm_index is None and result.days == 4
    assert result.statistic == pytest.approx(0.55) and result.peak == pytest.approx(2.7)
    assert lower_cusum([-0.2] * 20, REFERENCE, K_FRACTION, 5.0).alarm_index == 2


def paths(n: int, days: int, mean: float, seed: int) -> np.ndarray:
    return np.random.default_rng(seed).normal(mean, REFERENCE.sigma, size=(n, days))


def test_false_alarms_are_rare_while_the_signal_holds():
    # 400 years of daily RankIC at the measured level (IR 0.3): Siegmund's
    # approximation gives an average run of about 1,040 trading days before a false
    # alarm, so about a fifth of the years see one.
    alarms = sum(
        lower_cusum(row, REFERENCE, K_FRACTION, H).alarm_index is not None
        for row in paths(400, 250, REFERENCE.mu0, 7)
    )
    assert alarms / 400 < 0.35


def test_a_full_decay_is_found_in_about_three_months():
    # The signal switches off on day 60 (mean 0 afterwards); about 66 days on average.
    before = paths(300, 60, REFERENCE.mu0, 11)
    after = paths(300, 250, 0.0, 12)
    delays = []
    for head, tail in zip(before, after, strict=True):
        index = lower_cusum(np.concatenate([head, tail]), REFERENCE, K_FRACTION, H).alarm_index
        if index is not None and index >= 60:
            delays.append(index - 60)
    assert len(delays) >= 270  # nearly every path, after the switch-off
    assert 40 <= float(np.median(delays)) <= 100
