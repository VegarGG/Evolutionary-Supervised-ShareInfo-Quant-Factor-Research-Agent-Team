"""Thresholdout for W2 (P8.3, PLAN Section 9.5)."""

from pathlib import Path
from uuid import UUID

import numpy as np
import pytest
import yaml
from qfr_core.cards import policy_card
from qfr_core.config import PolicyConfig
from qfr_eval import thresholdout
from qfr_eval.configs import activate_version, create_version
from qfr_eval.thresholdout import Params, State, laplace, start, step

from tests.eval.eval_rig import eval_rig, replay_config
from tests.eval.test_validation import LOOSE, REPLAY_DAYS_PER_TICK, publish, run_until
from tests.synthetic_fixtures import REPLAY_EPOCH

EXAMPLE = Path("docs/examples/release_policy_thresholdout.yaml")
PARAMS = Params(threshold=0.01, sigma=0.002, budget=50, seed=7)


@pytest.fixture
def rig(tmp_path, replay_zones):
    config = replay_config(REPLAY_DAYS_PER_TICK)
    with eval_rig(tmp_path, replay_zones, epoch=REPLAY_EPOCH, config=config) as built:
        yield built


def scripted(values):
    """A draw function that returns the given noise values in order and logs the calls."""
    calls = []

    def draw(purpose, scale):
        calls.append((purpose, scale))
        return values[len(calls) - 1]

    return draw, calls


def test_a_query_consistent_with_w0_answers_w0_and_spends_nothing():
    draw, calls = scripted([0.0005, 0.001])
    state = start(PARAMS, draw)
    assert state == State(0.0105, 50)
    answer, after = step(PARAMS, state, w0=0.030, w2=0.025, draw=draw)
    # |0.025 - 0.030| = 0.005 is not above 0.0105 + 0.001.
    assert (answer.value, answer.source, answer.over) == (0.030, "w0", False)
    assert after == state and answer.budget_after == 50
    assert calls == [("threshold", 0.004), ("query", 0.008)]


def test_a_query_that_differs_answers_noisy_w2_and_spends_the_budget():
    draw, calls = scripted([0.0, -0.002, 0.0007, 0.003])
    state = start(PARAMS, draw)
    answer, after = step(PARAMS, state, w0=0.040, w2=0.010, draw=draw)
    # |0.010 - 0.040| = 0.03 > 0.01 - 0.002: W2 plus Laplace(sigma), and a new threshold.
    assert answer.source == "w2" and answer.over
    assert answer.value == pytest.approx(0.0107)
    assert after.budget == 49 and after.noisy_threshold == pytest.approx(0.013)
    assert [c[0] for c in calls] == ["threshold", "query", "answer", "threshold"]
    assert [c[1] for c in calls] == [0.004, 0.008, 0.002, 0.004]


def test_once_the_budget_is_spent_w2_answers_nothing():
    draw, calls = scripted([])
    state = State(0.01, 0)
    answer, after = step(PARAMS, state, w0=0.04, w2=-0.5, draw=draw)
    assert (answer.value, answer.source) == (None, "exhausted")
    assert after == state and calls == []


def test_draws_are_reproducible_from_the_seed_and_laplace_distributed():
    assert laplace(7, "epoch_001", 3, 0.002) == laplace(7, "epoch_001", 3, 0.002)
    assert laplace(7, "epoch_001", 3, 0.002) != laplace(7, "epoch_002", 3, 0.002)
    assert laplace(7, "epoch_001", 3, 0.002) != laplace(8, "epoch_001", 3, 0.002)
    draws = np.array([laplace(7, "e", i, 0.002) for i in range(1, 4001)])
    # Laplace(b): mean 0, mean absolute deviation b.
    assert abs(draws.mean()) < 0.0002
    assert np.mean(np.abs(draws)) == pytest.approx(0.002, rel=0.1)


def test_the_example_policy_is_valid_and_its_card_hides_the_seed():
    raw = yaml.safe_load(EXAMPLE.read_text())
    policy = PolicyConfig.model_validate(raw)
    assert policy.w2_mode == "thresholdout" and policy.thresholdout is not None
    assert (policy.thresholdout.threshold, policy.thresholdout.sigma) == (0.01, 0.002)
    assert policy.thresholdout.budget == 50
    card = policy_card(raw)
    assert card["thresholdout"] == {"threshold": 0.01, "sigma": 0.002, "budget": 50}
    with pytest.raises(ValueError, match="thresholdout mode needs"):
        PolicyConfig.model_validate(raw | {"thresholdout": None})


def activate_policy(rig, version: str, **thresholdout_values) -> None:
    rig.scheduler.tick()
    raw = yaml.safe_load(EXAMPLE.read_text())
    raw["version"] = version
    raw["thresholdout"] = raw["thresholdout"] | thresholdout_values
    now = rig.clock.now()
    with rig.db.transaction() as conn:
        created, _ = create_version(conn, "policy", yaml.safe_dump(raw), "test", "r", now)
        activate_version(conn, "policy", created.id, created.version, "test", None, "r", now)


def w2_reports(rig):
    return {
        r.version_id: r.report["content"]
        for r in rig.db.rows(
            "SELECT version_id, report FROM eval.released_reports WHERE report_type = 'w2'"
        )
    }


def test_w2_releases_thresholdout_answers_and_logs_every_draw(rig):
    rig.activate_protocol("test-loose", LOOSE)
    # A threshold no difference reaches: every answer is the W0 value, the budget stays.
    activate_policy(rig, "t-wide", threshold=10.0, sigma=0.002, budget=3, seed=11)
    version = publish(rig, ["reversal_5"])["reversal_5"]
    run_until(rig, version, {"HoldoutCheck", "W2Failed", "AwaitingSlot", "Incubating"})
    (query,) = rig.db.rows("SELECT * FROM eval.thresholdout_queries")
    assert query.version_id == version and query.source == "w0" and not query.over_threshold
    assert query.answer == query.w0_value and query.budget_after == 3
    record = rig.db.rows(
        "SELECT metrics FROM eval.official_records WHERE record_id = :r", r=query.record_id
    )[0]
    assert query.w2_value == pytest.approx(record.metrics["rankic_mean"])  # sign +1
    draws = rig.db.rows("SELECT purpose, scale, seq FROM eval.thresholdout_draws ORDER BY seq")
    assert [(d.purpose, d.scale) for d in draws] == [("threshold", 0.004), ("query", 0.008)]
    state = rig.db.rows("SELECT * FROM eval.thresholdout_state")[0]
    assert (state.budget_remaining, state.draws, state.queries, state.seed) == (3, 2, 1, 11)
    assert state.noisy_threshold == pytest.approx(10.0 + laplace(11, state.epoch_id, 1, 0.004))
    rig.release.tick()
    content = w2_reports(rig)[version]
    assert content["mode"] == "thresholdout" and content["ladder_status"] is None
    assert content["family_best_rankic"] is None and content["answer_budget"] == "open"
    assert content["answer_rankic"] == pytest.approx(round(query.w0_value / 0.005) * 0.005)


def test_a_spent_budget_answers_nothing_and_raises_a_burn_alert(rig):
    rig.activate_protocol("test-loose", LOOSE)
    # A threshold every difference passes and a budget of one query.
    activate_policy(rig, "t-tight", threshold=1e-9, sigma=1e-9, budget=1, seed=5)
    ids = publish(rig, ["reversal_5", "reversal_ema"])
    for version in ids.values():
        run_until(rig, version, {"HoldoutCheck", "W2Failed", "AwaitingSlot", "Incubating"})
    queries = rig.db.rows("SELECT * FROM eval.thresholdout_queries ORDER BY at, budget_after DESC")
    assert [q.source for q in queries] == ["w2", "exhausted"]
    first, second = queries
    assert first.answer == pytest.approx(first.w2_value, abs=1e-6) and first.budget_after == 0
    assert second.answer is None
    (alert,) = rig.db.rows("SELECT dedup_key, details FROM eval.alerts WHERE kind = 'burn'")
    assert alert.dedup_key.endswith(":thresholdout")
    assert alert.details["rule"] == "thresholdout_budget_exhausted"
    rig.release.tick()
    reports = w2_reports(rig)
    exhausted = reports[UUID(str(second.version_id))]
    assert exhausted["answer_budget"] == "exhausted"
    assert exhausted["answer_rankic"] is None
    assert exhausted["status"] in ("PASS", "FAIL")  # the true gate is still released
    assert thresholdout.Params.from_policy({"w2_mode": "ladder"}) is None
