"""Phase 6 units without a database: the Ladder (REL-06), the W2, advancement, sim and
decision releases with no W3-derived field (REL-05), and the exact clustering behind
N_eff (ACC-01)."""

import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from qfr_core.contracts import AdvancementContent, DecisionContent
from qfr_core.metrics.fingerprint import Fingerprint, behavioral_similarity
from qfr_eval.plugins import ladder_step, quantize, rankic_bucket, release_sim, release_w2
from qfr_eval.trials import similarity_edges, single_linkage

POLICY = json.loads(Path("configs/public_cards.json").read_text())["policy"]
ETA = 0.005


# REL-06: the Ladder ------------------------------------------------------------------------


def test_rel_06_the_first_best_must_clear_zero_by_eta():
    assert not ladder_step(None, ETA / 2, ETA).improved
    first = ladder_step(None, 0.02, ETA)
    assert first.improved and first.best == 0.02 and first.previous_best == 0.0
    assert not ladder_step(None, None, ETA).improved


def test_rel_06_a_new_best_needs_an_improvement_of_at_least_eta():
    best = 0.0300
    assert not ladder_step(best, best + ETA / 2, ETA).improved
    assert ladder_step(best, best + ETA / 2, ETA).best == best  # unchanged
    assert ladder_step(best, best + ETA, ETA).improved
    assert not ladder_step(best, best - 0.01, ETA).improved


@settings(max_examples=200, deadline=None)
@given(
    st.lists(st.floats(-0.1, 0.2, allow_nan=False), min_size=1, max_size=30),
    st.sampled_from([0.001, 0.005, 0.01]),
)
def test_rel_06_released_bests_rise_by_at_least_eta(values, eta):
    best, released = None, []
    for value in values:
        step = ladder_step(best, value, eta)
        if step.improved:
            released.append(step.best)
        best = step.best
    assert all(b - a >= eta - 1e-12 for a, b in zip(released, released[1:], strict=False))
    assert all(b >= eta - 1e-12 for b in released)


def test_rel_06_w2_releases_the_best_only_when_it_improved():
    policy = {"rounding": {"ladder_best": 0.01}}
    improved = release_w2({"passed": True, "improved": True, "released_best": 0.0347}, policy)
    assert (improved.ladder_status, improved.family_best_rankic) == ("IMPROVED", 0.03)
    same = release_w2({"passed": True, "improved": False, "released_best": 0.0347}, policy)
    assert (same.ladder_status, same.family_best_rankic) == ("UNCHANGED", None)
    failed = release_w2({"passed": False, "improved": False}, policy)
    assert failed.status == "FAIL" and failed.family_best_rankic is None


# REL-05: no released report carries a W3-derived field -----------------------------------

# Values a W3 run would produce, planted next to the fields each release reads.
W3_RAW = {
    "w3_rankic_mean": 0.123456,
    "holdout_rankic_mean": 0.123456,
    "holdout_ls_net_sharpe": 2.345678,
    "holdout_reference_ir": 0.876543,
    "holdout_passed": True,
    "gates": [{"name": "rankic_mean", "value": 0.123456}],
}
W3_VALUES = {0.123456, 2.345678, 0.876543}


def _numbers(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from _numbers(item)
    elif isinstance(value, list):
        for item in value:
            yield from _numbers(item)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        yield float(value)


policies = st.fixed_dictionaries(
    {
        "rounding": st.fixed_dictionaries(
            {
                "ladder_best": st.sampled_from([0.001, 0.005, 0.01, 0.02]),
                "sharpe": st.sampled_from([0.05, 0.1, 0.25, 0.5]),
            }
        ),
        "sim_rankic_buckets": st.lists(
            st.floats(-0.02, 0.05, allow_nan=False), min_size=3, max_size=3
        ).map(sorted),
    }
)


@settings(max_examples=300, deadline=None)
@given(
    policies,
    st.booleans(),
    st.booleans(),
    st.floats(-0.1, 0.2, allow_nan=False),
    st.floats(-3, 3, allow_nan=False),
    st.sampled_from(["COMPLETED", "FAILED"]),
)
def test_rel_05_releases_carry_no_w3_field_under_any_policy(
    policy, passed, improved, best, sharpe, status
):
    w2 = release_w2(
        {"passed": passed, "improved": improved, "released_best": best} | W3_RAW, policy
    )
    sim = release_sim({"status": status, "rankic_mean": best, "sharpe": sharpe} | W3_RAW, policy)
    advancement = AdvancementContent(type="advancement", status="ADVANCED")
    decision = DecisionContent(
        type="decision", status="REJECTED", reason="gate_failed", gate="G-HOLDOUT"
    )
    for content in (w2, sim, advancement, decision):
        dumped = content.model_dump(mode="json")
        assert not any("w3" in k.lower() or "holdout" in k.lower() for k in dumped)
        assert not set(_numbers(dumped)) & W3_VALUES, dumped
    # The released numbers are coarse: a multiple of the policy step, or a bucket label.
    if w2.family_best_rankic is not None:
        assert w2.family_best_rankic == quantize(best, policy["rounding"]["ladder_best"])
    assert sim.forward_sharpe_bucket == quantize(sharpe, policy["rounding"]["sharpe"])
    assert sim.forward_rankic_bucket == rankic_bucket(best, policy["sim_rankic_buckets"])


def test_rel_05_the_public_report_schema_names_no_w3_field():
    schema = json.loads(Path("schemas/public/released_report.json").read_text())

    def names(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "properties" and isinstance(value, dict):
                    yield from value
                yield from names(value)
        elif isinstance(node, list):
            for item in node:
                yield from names(item)

    found = set(names(schema))
    assert found, "the schema has properties"
    assert not {n for n in found if "w3" in n.lower() or "holdout" in n.lower()}, found
    # The advancement report is a status only (Section 9.2).
    advancement = AdvancementContent.model_json_schema()
    assert set(advancement["properties"]) == {"type", "status"}
    assert POLICY["release_w3_metrics"] is False


# ACC-01: the exact clustering behind N_eff ------------------------------------------------


def _fingerprint(ranks, names=None):
    days = [date(2011, 1, 3) + timedelta(days=i) for i in range(ranks.shape[0])]
    return Fingerprint(days, names or [f"N{j:03d}" for j in range(ranks.shape[1])], ranks)


def _ranks(values):
    return np.argsort(np.argsort(values, axis=1), axis=1).astype(float) + 1.0


def test_acc_01_block_similarity_equals_the_pairwise_measure():
    rng = np.random.default_rng(7)
    base = rng.normal(size=(30, 40))
    prints = [
        _fingerprint(_ranks(base)),
        _fingerprint(_ranks(base + 0.3 * rng.normal(size=base.shape))),  # close to the first
        _fingerprint(_ranks(base + 2.0 * rng.normal(size=base.shape))),  # loosely related
        _fingerprint(_ranks(rng.normal(size=base.shape))),  # unrelated
    ]
    for threshold in (0.3, 0.5, 0.7, 0.9):
        expected = {
            (i, j)
            for i in range(len(prints))
            for j in range(i + 1, len(prints))
            if (behavioral_similarity(prints[i], prints[j]) or 0.0) >= threshold
        }
        assert set(similarity_edges(prints, threshold)) == expected, threshold


def test_acc_01_fingerprints_with_different_supports_are_compared_pairwise():
    rng = np.random.default_rng(11)
    base = rng.normal(size=(20, 30))
    gappy = _ranks(base)
    gappy[3, :5] = np.nan  # a different eligible set on one date
    prints = [_fingerprint(_ranks(base)), _fingerprint(gappy)]
    value = behavioral_similarity(prints[0], prints[1])
    assert value is not None and value > 0.9
    assert similarity_edges(prints, 0.7) == [(0, 1)]


def test_acc_01_single_linkage_joins_chains_into_one_cluster():
    assert single_linkage(5, [(0, 1), (1, 2), (3, 4)]) == [0, 0, 0, 1, 1]
    assert single_linkage(3, []) == [0, 1, 2]
    assert single_linkage(0, []) == []


@pytest.mark.parametrize(
    ("value", "label"),
    [(None, "negative"), (-0.01, "negative"), (0.0, "0_to_0.01"), (0.02, "0.01_to_0.03"),
     (0.05, "above_0.03")],
)  # fmt: skip
def test_the_sim_report_buckets_forward_rankic(value, label):
    assert rankic_bucket(value, POLICY["sim_rankic_buckets"]) == label
