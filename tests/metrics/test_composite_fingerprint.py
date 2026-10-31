"""Strategy composite and canonical hash (PLAN 7.8), behavioral fingerprints (PLAN 7.5)."""

import math
from datetime import date, timedelta

import numpy as np
import pytest
from qfr_core.composite import (
    CompositePart,
    composite,
    contribution_table,
    strategy_canonical_hash,
)
from qfr_core.contracts import StrategyImplementation
from qfr_core.metrics.factor import MetricSettings
from qfr_core.metrics.fingerprint import behavioral_similarity, fingerprint, fingerprint_dates
from qfr_core.metrics.matrix import Market

PLAIN = MetricSettings(
    winsor_lower=0.0,
    winsor_upper=1.0,
    quantiles=5,
    horizons=(1,),
    primary_horizon=1,
    ls_cost_bps_per_side=10,
)
DAY = [date(2022, 1, 3)]


def one_day_market(names: int = 3) -> Market:
    return Market.from_matrices(
        DAY, [f"N{i}" for i in range(names)], np.ones((1, names)), np.ones((1, names), bool), 2
    )


def test_composite_hand_example():
    """a = 1 2 3 has z = -1 0 1; b = 3 1 2 has z = 1 -1 0 (ddof 1, unit spread).
    Signs +1 and -1, raw weights 1 and 3 normalize to 0.25 and 0.75:
    0.25 * (-1, 0, 1) - 0.75 * (1, -1, 0) = (-1, 0.75, 0.25)."""
    a = CompositePart("a", 1, 1.0, np.array([[1.0, 2.0, 3.0]]))
    b = CompositePart("b", -1, 3.0, np.array([[3.0, 1.0, 2.0]]))
    out = composite([a, b], one_day_market(), PLAIN)
    np.testing.assert_allclose(out, [[-1.0, 0.75, 0.25]], atol=1e-12)


def test_missing_component_values_contribute_zero():
    """b is missing for N2, so its z-scores use N0 and N1 only: (3, 1) -> (+s, -s) with
    s = 1 / sqrt(2). N2 keeps only a's contribution, 0.25 * 1."""
    a = CompositePart("a", 1, 1.0, np.array([[1.0, 2.0, 3.0]]))
    b = CompositePart("b", -1, 3.0, np.array([[3.0, 1.0, np.nan]]))
    out = composite([a, b], one_day_market(), PLAIN)
    s = 1 / math.sqrt(2)
    np.testing.assert_allclose(out, [[-0.25 - 0.75 * s, 0.75 * s, 0.25]], atol=1e-12)
    both_missing = CompositePart("c", 1, 1.0, np.array([[np.nan, np.nan, np.nan]]))
    assert np.isnan(composite([both_missing], one_day_market(), PLAIN)).all()


def test_contribution_table_reports_leave_one_out_rank_ic():
    rng = np.random.default_rng(5)
    days = [date(2022, 1, 3) + timedelta(days=i) for i in range(40)]
    returns = rng.normal(0, 0.02, (40, 30))
    close = 10 * np.cumprod(1 + returns, axis=0)
    label = np.full((40, 30), np.nan)
    label[:-2] = close[2:] / close[1:-1] - 1
    signal = np.nan_to_num(label) + rng.normal(0, 0.02, (40, 30))
    noise = rng.normal(0, 1, (40, 30))
    market = Market.from_matrices(
        days, [f"N{i:02d}" for i in range(30)], close, np.ones((40, 30), bool), 5
    )
    parts = [CompositePart("signal", 1, 1, signal), CompositePart("noise", 1, 1, noise)]
    full, rows = contribution_table(parts, market, days[0], days[-1], PLAIN)
    assert [r.component for r in rows] == ["signal", "noise"]
    assert full is not None and full > 0.2
    assert rows[0].rankic_change is not None and rows[0].rankic_change > 0.2
    assert rows[1].rankic_without is not None and rows[1].rankic_without > full


def implementation(components, top_k=50, dropout=5):
    return StrategyImplementation.model_validate(
        {
            "language": "qfr-strategy/1",
            "components": components,
            "combination": "zscore_weighted_sum",
            "portfolio": {
                "type": "topk_dropout",
                "top_k": top_k,
                "dropout": dropout,
                "rebalance": "daily",
                "long_only": True,
            },
        }
    )


V1 = "01890a5d-ac96-774b-bcce-b302099a8057"
V2 = "01890a5d-ac96-774b-bcce-b302099a8058"


def test_strategy_hash_is_order_and_scale_invariant_but_sees_every_choice():
    base = strategy_canonical_hash(
        implementation(
            [
                {"version_id": V1, "sign": 1, "weight": 1},
                {"version_id": V2, "sign": -1, "weight": 3},
            ]
        )
    )
    reordered = strategy_canonical_hash(
        implementation(
            [
                {"version_id": V2, "sign": -1, "weight": 6},
                {"version_id": V1, "sign": 1, "weight": 2},
            ]
        )
    )
    assert base == reordered
    flipped = strategy_canonical_hash(
        implementation(
            [{"version_id": V1, "sign": 1, "weight": 1}, {"version_id": V2, "sign": 1, "weight": 3}]
        )
    )
    reweighted = strategy_canonical_hash(
        implementation(
            [
                {"version_id": V1, "sign": 1, "weight": 1},
                {"version_id": V2, "sign": -1, "weight": 2},
            ]
        )
    )
    portfolio = strategy_canonical_hash(
        implementation(
            [
                {"version_id": V1, "sign": 1, "weight": 1},
                {"version_id": V2, "sign": -1, "weight": 3},
            ],
            top_k=60,
        )
    )
    assert len({base, flipped, reweighted, portfolio}) == 4


def test_fingerprint_dates_are_seeded_and_similarity_is_absolute_spearman():
    days = [date(2015, 1, 1) + timedelta(days=i) for i in range(300)]
    picked = fingerprint_dates(days, 40, 20261030)
    assert picked == fingerprint_dates(days, 40, 20261030)
    assert picked != fingerprint_dates(days, 40, 1)
    assert len(set(picked)) == 40 and picked == sorted(picked)
    rng = np.random.default_rng(2)
    values = rng.normal(size=(300, 50))
    market = Market.from_matrices(
        days, [f"N{i:02d}" for i in range(50)], np.ones((300, 50)), np.ones((300, 50), bool), 5
    )
    a = fingerprint(values, market, picked)
    assert behavioral_similarity(a, fingerprint(values, market, picked)) == pytest.approx(1.0)
    assert behavioral_similarity(a, fingerprint(-values, market, picked)) == pytest.approx(1.0)
    other = fingerprint(rng.normal(size=(300, 50)), market, picked)
    similarity = behavioral_similarity(a, other)
    assert similarity is not None and similarity < 0.2


def test_fingerprints_compare_on_common_names_across_markets():
    days = [date(2015, 1, 1) + timedelta(days=i) for i in range(60)]
    picked = fingerprint_dates(days, 10, 7)
    values = np.random.default_rng(4).normal(size=(60, 20))
    names = [f"N{i:02d}" for i in range(20)]
    full = Market.from_matrices(days, names, np.ones((60, 20)), np.ones((60, 20), bool), 5)
    subset = Market.from_matrices(days, names[:15], np.ones((60, 15)), np.ones((60, 15), bool), 5)
    a = fingerprint(values, full, picked)
    b = fingerprint(values[:, :15], subset, picked)
    assert behavioral_similarity(a, b) == pytest.approx(1.0)
