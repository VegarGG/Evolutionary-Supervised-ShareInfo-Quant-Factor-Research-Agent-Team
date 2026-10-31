"""Synthetic worlds (PLAN 6.6) and the Phase 1 acceptance check on planted RankIC."""

from pathlib import Path

import numpy as np
import polars as pl
import pytest
from qfr_core.dsl import compile_expression
from qfr_core.metrics.factor import evaluate_factor
from qfr_core.metrics.matrix import Market
from qfr_core.operators import evaluate
from qfr_eval.ingest.config import load_epoch, load_synthetic
from qfr_eval.ingest.synthetic import active_signals, generate, w2_midpoint, weekday_calendar

from tests.dsl_strategies import LIMITS
from tests.synthetic_fixtures import (
    ELIGIBILITY,
    MINIMUM,
    SETTINGS,
    small_config,
    small_epoch,
    small_world,
)


@pytest.fixture(scope="module")
def planted():
    return small_world("planted")


def test_signals_are_the_dsl_expressions_of_the_ground_truth(planted):
    """The generator's internal signals equal the DSL evaluation on the built panel."""
    market = Market.from_panel(planted.panel, ELIGIBILITY, planted.calendar)
    for signal in planted.ground_truth["signals"]:
        tree = compile_expression(signal["expression"], LIMITS).tree
        dsl = market.matrix(evaluate(planted.panel, tree, ELIGIBILITY))
        own = planted.simulation.signals[signal["name"]]
        np.testing.assert_array_equal(np.isnan(dsl), np.isnan(own))
        np.testing.assert_allclose(dsl, own, rtol=1e-12, atol=1e-12, equal_nan=True)


def test_eligibility_matches_the_panel(planted):
    market = Market.from_panel(planted.panel, ELIGIBILITY, planted.calendar)
    np.testing.assert_array_equal(market.eligible, planted.simulation.eligible)
    np.testing.assert_allclose(market.close, planted.simulation.close, equal_nan=True)


def test_realism_features(planted):
    sim = planted.simulation
    suspended = (sim.listed & ~sim.traded).sum() / sim.listed.sum()
    assert 0.002 < suspended < 0.01
    late = (
        planted.panel.group_by("instrument").agg(pl.col("date").min()).get_column("date")
        > planted.days[0]
    ).sum()
    assert late > 0
    # Every year after the first, members rotate in and out.
    entries = planted.membership.filter(pl.col("start") > planted.days[0]).height
    assert entries >= 2
    # Limit flags fire exactly where the generator clipped prices.
    assert planted.panel["limit_up"].sum() > 0 and planted.panel["limit_down"].sum() > 0
    # Within the 10% limit, plus at most one tick of rounding on low-priced names.
    assert planted.panel["ret_1d"].abs().max() <= 0.12
    # Corporate actions move the factor, not the adjusted price path.
    assert (
        planted.panel.group_by("instrument")
        .agg(pl.col("factor").n_unique())
        .get_column("factor")
        .max()
        > 1
    )


def test_ground_truth_is_test_infrastructure_with_calibrated_alphas(planted):
    truth = planted.ground_truth
    assert "never a default factor set" in truth["note"].lower()
    names = [s["name"] for s in truth["signals"]]
    assert names == ["A1", "A2"]
    for signal in truth["signals"]:
        assert signal["alpha"] > 0
        assert abs(signal["calibration_rankic"] - signal["target_rankic"]) <= 0.001


def test_null_world_has_no_planted_signal():
    world = small_world("null")
    assert world.ground_truth["signals"] == []
    assert world.ground_truth["calibration"]["evaluations"] == 0


def test_decay_world_switches_a3_off_at_the_w2_midpoint():
    config, epoch = small_config(), small_epoch()
    days = weekday_calendar(config.start, config.trading_days)
    signals = {s.name: s for s in active_signals(config, "decay", epoch, days)}
    assert sorted(signals) == ["A1", "A2", "A3"]
    off = w2_midpoint(epoch, days)
    assert days[signals["A3"].stop] == off
    assert signals["A1"].stop == len(days)
    w2 = [d for d in days if epoch.W2.start <= d <= epoch.W2.end]
    assert off == w2[len(w2) // 2]


def test_generation_is_deterministic(planted):
    again = small_world("planted")
    assert again.panel.equals(planted.panel)
    assert again.ground_truth == planted.ground_truth


@pytest.mark.slow
def test_acceptance_planted_rank_ic_is_within_0005_of_target():
    """Phase 1 acceptance: on the default planted world (300 names, 2,600 days), the
    evaluator's RankIC of A1 and A2 is within 0.005 of the calibrated target."""
    config = load_synthetic(Path("configs"))
    epoch = load_epoch(Path("configs"), config.epoch)
    world = generate(config, "planted", epoch, SETTINGS, MINIMUM)
    market = Market.from_panel(world.panel, ELIGIBILITY, world.calendar)
    for signal in world.ground_truth["signals"]:
        tree = compile_expression(signal["expression"], LIMITS).tree
        values = market.matrix(evaluate(world.panel, tree, ELIGIBILITY))
        rank_ic = evaluate_factor(
            values, market, world.days[0], world.days[-1], 1, SETTINGS
        ).metrics.rankic_mean
        assert rank_ic is not None
        assert abs(rank_ic - signal["target_rankic"]) <= 0.005, (signal["name"], rank_ic)
