"""qfr-strategy/2 through the evaluator and the sim-engine (PLAN 7.8, P8.2).

A long-short, industry-neutral strategy with position and industry caps over the planted
reversal is screened, measured on W1, W2 and the holdout, and incubated by replay. Its
paper book holds short positions (negative shares), pays borrow, respects the caps, and
NAV is cash plus positions every day. Rules outside the protocol's bounds, or industry
rules without the snapshot's classification, are refused.
"""

import dataclasses
import math
from uuid import UUID

import pytest
from qfr_core.data.industry import NO_INDUSTRY
from qfr_eval.sim import sim_settings
from qfr_eval.worker import MANIFEST

from tests.eval.eval_rig import eval_rig, replay_config
from tests.eval.test_validation import FACTORS, LOOSE, REPLAY_DAYS_PER_TICK, run_until, state_of
from tests.registry_rig import factor_manifest, strategy_manifest
from tests.synthetic_fixtures import REPLAY_EPOCH

pytestmark = pytest.mark.postgres

STRATEGY_LOOSE = LOOSE | {
    "w1_strategy": {"rankic_min": -1.0, "nw_t_min": -100.0, "net_sharpe_min": -100.0,
                    "ir_min": -100.0, "drawdown_max": 1.0, "strategy_correlation_max": 1.0},
    "w2_strategy": {"net_sharpe_min": -100.0, "ir_min": -100.0},
    "holdout_strategy": {"net_sharpe_min": -100.0, "ir_min": -100.0},
}  # fmt: skip
TOP_K = 20
INDUSTRY_CAP = 0.25  # at most 5 names of one industry in each book


def rules_manifest(component: str, name: str = "neutral_ls", **portfolio) -> dict:
    manifest = strategy_manifest([(component, 1, 1.0)], name, top_k=TOP_K)
    manifest["implementation"] = {
        "language": "qfr-strategy/2",
        "components": manifest["implementation"]["components"],
        "combination": "zscore_weighted_sum",
        "neutralize": "industry",
        "portfolio": {
            "type": "topk_dropout",
            "top_k": TOP_K,
            "dropout": 5,
            "rebalance": "daily",
            "long_only": False,
            "max_position_weight": 0.06,
            "max_industry_weight": INDUSTRY_CAP,
        }
        | portfolio,
    }
    return manifest


@pytest.fixture
def rig(tmp_path, replay_zones):
    with eval_rig(
        tmp_path, replay_zones, epoch=REPLAY_EPOCH, config=replay_config(REPLAY_DAYS_PER_TICK)
    ) as built:
        built.activate_protocol("test-loose-strategy", STRATEGY_LOOSE)
        yield built


def component(rig) -> str:
    response = rig.registry.publish(factor_manifest("reversal_5", FACTORS["reversal_5"]))
    assert response.status_code == 201, response.text
    return response.json()["version"]["version_id"]


def publish(rig, manifest) -> UUID:
    response = rig.registry.publish(manifest)
    assert response.status_code == 201, response.text
    return UUID(response.json()["version"]["version_id"])


def test_a_long_short_neutral_strategy_is_measured_and_paper_traded(rig):
    version = publish(rig, rules_manifest(component(rig)))
    run_until(rig, version, {"Incubating"}, days=20)
    w1 = rig.db.rows(
        "SELECT summary FROM eval.official_records WHERE version_id = :v AND stage = 'w1'",
        v=version,
    )[0]
    assert w1.summary["portfolio"] == {
        "top_k": TOP_K, "dropout": 5, "long_only": False, "max_position_weight": 0.06,
        "max_industry_weight": INDUSTRY_CAP, "neutralize": "industry",
    }  # fmt: skip
    query = "SELECT * FROM eval.sim_accounts WHERE version_id = :v AND purpose = 'incubation'"
    sim = rig.db.rows(query, v=version)[0]
    assert sim.settings["long_only"] is False and sim.settings["borrow_bps"] == 800.0
    assert sim.settings["neutralize"] == "industry"
    while rig.db.rows(query, v=version)[0].days_done < 10:
        rig.sim.tick()
    sim = rig.db.rows(query, v=version)[0]

    positions = rig.db.rows(
        "SELECT day, instrument, shares, value FROM eval.sim_positions WHERE sim_id = :s "
        "ORDER BY day, instrument",
        s=sim.sim_id,
    )
    last = [p for p in positions if p.day == sim.last_day]
    longs = [p for p in last if p.shares > 0]
    shorts = [p for p in last if p.shares < 0]
    assert 0 < len(longs) <= TOP_K and 0 < len(shorts) <= TOP_K
    assert all(p.value < 0 for p in shorts)
    assert not {p.instrument for p in longs} & {p.instrument for p in shorts}

    # Industry cap: at most 5 names of one industry in either book.
    with rig.db.read() as conn:
        from qfr_eval.configs import active_state

        state = active_state(conn)
    assert state is not None
    manifest = MANIFEST.validate_python(
        rig.db.scalar("SELECT manifest FROM eval.intake WHERE version_id = :v", v=version)[
            "manifest"
        ]
    )
    from qfr_eval.plugins import plugin_for

    data = rig.sim.markets.get(state.epoch.snapshot_id, plugin_for(state.protocol.config,
                                                                   manifest))  # fmt: skip
    assert data.market.industry is not None
    day = data.index[sim.last_day]
    for book in (longs, shorts):
        codes = [
            int(data.market.industry.codes[day, data.market.instruments.index(p.instrument)])
            for p in book
        ]
        assert NO_INDUSTRY not in codes
        assert max(codes.count(c) for c in set(codes)) <= 5

    reasons = {
        r.reason
        for r in rig.db.rows("SELECT reason FROM eval.sim_orders WHERE sim_id = :s", s=sim.sim_id)
    }
    assert {"short_entry", "entry"} <= reasons

    # NAV is cash plus signed positions, and the short book pays borrow every day.
    navs = rig.db.rows(
        "SELECT day, nav, cash, costs FROM eval.sim_nav WHERE sim_id = :s ORDER BY day",
        s=sim.sim_id,
    )
    for row in navs:
        held = sum(p.value for p in positions if p.day == row.day)
        assert math.isclose(row.nav, row.cash + held, rel_tol=1e-9)
    assert all(row.costs > 0 for row in navs[1:])
    # Gross exposure is about 2 x NAV and net exposure near 0.
    gross = sum(abs(p.value) for p in last)
    net = sum(p.value for p in last)
    assert 1.5 < gross / navs[-1].nav < 2.2 and abs(net) / navs[-1].nav < 0.4


def test_rules_outside_the_protocol_bounds_are_refused(rig):
    version = publish(rig, rules_manifest(component(rig), "too_big", max_position_weight=0.15))
    rig.cycle(rounds=5)
    row = rig.db.rows("SELECT state, reason_code FROM eval.intake WHERE version_id = :v",
                      v=version)[0]  # fmt: skip
    assert (row.state, row.reason_code) == ("IntakeRejected", "COMPONENT_INVALID")


def test_industry_rules_without_the_classification_fail_screening(rig):
    markets = rig.worker.evaluator.markets
    original = markets.get

    def without_industry(snapshot_id, plugin):
        return dataclasses.replace(original(snapshot_id, plugin), industry=None)

    markets.get = without_industry
    version = publish(rig, rules_manifest(component(rig), "blind"))
    rig.cycle(rounds=5)
    assert state_of(rig, version) == "ScreenFailed"
    record = rig.db.rows(
        "SELECT summary FROM eval.official_records WHERE version_id = :v AND stage = 'screening'",
        v=version,
    )[0]
    assert record.summary["reasons"] == ["COMPONENT_INVALID"]
    assert record.summary["detail"] == "industry_classification_missing"


def test_a_v1_strategy_pins_no_rules(rig):
    manifest = MANIFEST.validate_python(strategy_manifest([(component(rig), 1, 1.0)]))
    with rig.db.read() as conn:
        from qfr_eval.configs import active_state

        state = active_state(conn)
    assert state is not None
    settings = sim_settings(state.protocol.config, manifest)
    assert not {"long_only", "borrow_bps", "neutralize"} & set(settings)
