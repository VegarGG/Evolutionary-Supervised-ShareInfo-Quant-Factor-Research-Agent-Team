"""Planning disclosures reuse released sample counts, never private outcomes."""

import hashlib
import json
import math
from uuid import uuid4

import pytest
from pydantic import ValidationError
from qfr_core.data_layer.snapshots import canonical_json
from qfr_eval.release.cards import pilot_protocol_card, publish_policy_cards
from qfr_eval.release.models import PilotReleasePolicy
from qfr_eval.release.pilot import project_pilot
from qfr_eval.release.policy import public_card
from test_release_preparation import pilot_policy
from test_release_projection import ROOT, evidence, policy


def version_two():
    return PilotReleasePolicy.model_validate_json(
        (ROOT / "configs/evaluation/release_pilot_v2.json").read_bytes()
    )


def project(case, *, bests=None, ordinal=1):
    return project_pilot(
        *case,
        version_two(),
        bests=bests or {},
        ordinals={"root": ordinal},
        frozen_family_scores=[],
        baseline_version_id=None,
        cost_basis_ref="10bps",
        pit_grade_downgrade=False,
    )


def test_planning_matches_closed_form_and_retains_original_count_with_ladder():
    case = evidence(0.5, period_count=100)
    first, best = project(case)
    expected = 2 * math.sqrt((((1 - 7 / 31) ** 2 + (7 / 31) ** 2) / 30 / 2) / 100)
    assert math.isclose(first.minimum_detectable_effect.value, expected, rel_tol=0, abs_tol=1e-16)
    later, updates = project(evidence(0.501, period_count=1000), bests=best, ordinal=2)
    assert not updates and later.scalar.attribution == "lineage_best"
    assert later.minimum_detectable_effect == first.minimum_detectable_effect
    assert later.scalar.period_count == 100
    changed, _ = project(evidence(0.8, period_count=400), bests=best, ordinal=3)
    assert changed.minimum_detectable_effect.value == first.minimum_detectable_effect.value / 2
    assert changed.hurdle_flags.overall == first.hurdle_flags.overall == "fail"


@pytest.mark.parametrize("score,periods", [(0.9, 1000), (None, 0), (0.1, 20)])
def test_planning_never_bypasses_withholding_or_discloses_candidate_diagnostics(score, periods):
    case = evidence(score, period_count=periods, diagnostics={"mde": 123456789})
    content, updates = project(case, ordinal=4)
    assert content.model_dump() == {"type": "withheld", "reason": "budget"}
    assert not updates
    content, _ = project(case)
    assert "123456789" not in content.model_dump_json()
    if score is None:
        assert content.minimum_detectable_effect.missing_reason == "insufficient_data"


def test_v1_policy_and_card_serialization_preserved_and_v2_is_explicit():
    original = json.loads((ROOT / "configs/evaluation/release_pilot_v1.json").read_bytes())
    one, two = policy(), version_two()
    assert one.model_dump(mode="json") == original
    assert one.sha256 == hashlib.sha256(canonical_json(original)).hexdigest()
    assert "planning_detectability" not in public_card(one).model_dump(mode="json")
    assert public_card(two).planning_detectability.admission_effect == "none"
    changes = {k for k, v in two.model_dump(mode="json").items() if original.get(k) != v}
    assert changes == {"version", "planning_detectability"}
    with pytest.raises(ValidationError, match="new policy revision"):
        PilotReleasePolicy.model_validate({**two.model_dump(), "version": 1})
    protocol = evidence()[3]
    old, new = pilot_protocol_card(protocol, one), pilot_protocol_card(protocol, two)
    assert "card_ref" not in old.model_dump(mode="json")
    assert new.protocol_version == old.protocol_version
    assert new.card_ref != old.protocol_version
    assert "independent" in new.metric_definitions["minimum_detectable_effect"]


@pytest.mark.database
def test_versioned_cards_coexist_without_rewriting_an_earlier_public_card(eval_connect):
    with eval_connect() as conn:
        one, two = pilot_policy(conn), pilot_policy(conn, version=2)
        before = publish_policy_cards(conn, one.sha256, principal="test", request_id=uuid4())
        after = publish_policy_cards(conn, two.sha256, principal="test", request_id=uuid4())
        assert before != after
        assert before == publish_policy_cards(
            conn, one.sha256, principal="test", request_id=uuid4()
        )
        refs = [
            pilot_protocol_card(evidence()[3], p).card_ref
            or pilot_protocol_card(evidence()[3], p).protocol_version
            for p in (one, two)
        ]
        assert conn.execute(
            "SELECT count(*) FROM eval.public_protocol_cards WHERE card_ref=ANY(%s)", [refs]
        ).fetchone() == (2,)
