"""The owner override for acceptance (P8.7, PLAN Section 10.3).

A case with a failed gate is accepted only after a request with a written rationale, a
24-hour cooling period and a second, separate confirmation recorded after it; a
rejection withdraws a request still cooling. The tables refuse every shortcut.
"""

import random
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
import sqlalchemy.exc
from pydantic import ValidationError
from qfr_core.contracts import ApprovalScope
from qfr_core.eval_api import CaseOverrideRequest, OverrideApprovalRef
from qfr_core.ids import uuid7
from qfr_eval.acceptance import override_case
from qfr_eval.configs import EvalError, active_state
from sqlalchemy import text

from tests.eval.eval_rig import eval_rig, replay_config
from tests.eval.test_validation import (
    LOOSE,
    REPLAY_DAYS_PER_TICK,
    UNREACHABLE_DSR,
    approval,
    decide,
    publish,
    run_until,
    state_of,
    the_case,
)
from tests.synthetic_fixtures import REPLAY_EPOCH

pytestmark = pytest.mark.postgres


@pytest.fixture
def rig(tmp_path, replay_zones):
    config = replay_config(REPLAY_DAYS_PER_TICK)
    with eval_rig(tmp_path, replay_zones, epoch=REPLAY_EPOCH, config=config) as built:
        yield built


RATIONALE = (
    "The deflated Sharpe gate fails only because this test protocol sets it above one. "
    "The forward incubation, the holdout and the novelty check all pass, and the owner "
    "accepts the factor knowingly for a small, monitored allocation."
)


def uuid7_at(at: datetime) -> UUID:
    """A UUIDv7 made at `at` (the evaluator reads an approval's time from its id)."""
    ms = int(at.timestamp() * 1000)
    rand = random.getrandbits(74)
    value = (ms << 80) | (0x7 << 76) | ((rand >> 62) << 64) | (0b10 << 62) | (rand & (2**62 - 1))
    return UUID(int=value)


def ref(case, decision, approval_id=None):
    scope = ApprovalScope(
        job_id=None, deliverable_id=None, version_ids=[case.version_id], pool=None,
        tier=None, case_id=case.case_id, entry_ids=[],
    )  # fmt: skip
    return OverrideApprovalRef(approval_id=approval_id or uuid7(), decision=decision, scope=scope)


def override(rig, case, step, reference, rationale=None):
    request = CaseOverrideRequest(step=step, rationale=rationale, approval=reference)
    with rig.db.transaction() as conn:
        return override_case(
            conn, active_state(conn), case.case_id, request, "owner", rig.clock.now(), "r",
            "test-sha",
        )  # fmt: skip


def refused(rig, case, step, reference, rationale=None) -> EvalError:
    with pytest.raises(EvalError) as error:
        override(rig, case, step, reference, rationale)
    return error.value


def test_a_failed_gate_is_overridden_only_after_cooling_and_a_second_confirmation(rig):
    rig.activate_protocol("test-unreachable-dsr", UNREACHABLE_DSR)
    ids = publish(rig, ["reversal_ema", "reversal_5"])
    for version in ids.values():
        run_until(rig, version, {"AcceptanceReview"}, days=16)
    case = the_case(rig, ids["reversal_ema"])
    assert case.recommendation == "REJECT" and "G-DSR" in case.failing_gates

    # The table refuses an owner_override decision without a confirmed override.
    with pytest.raises(sqlalchemy.exc.DBAPIError, match="confirmation after the cooling"):
        with rig.db.transaction() as conn:
            conn.execute(
                text(
                    "UPDATE eval.acceptance_cases SET state = 'decided', decision = 'accepted', "
                    "reason = 'owner_override', rationale = 'x', approval_id = :a, "
                    "decided_by = 'owner', decided_at = now() WHERE case_id = :c"
                ),
                {"a": uuid7(), "c": case.case_id},
            )

    # The request needs its own approval, the written rationale and a failed gate.
    with pytest.raises(ValidationError):
        CaseOverrideRequest(
            step="request", rationale="Too short.", approval=ref(case, "override_case")
        )
    assert refused(rig, case, "confirm", ref(case, "confirm_override")).code == (
        "OVERRIDE_NOT_REQUESTED"
    )
    wrong = refused(rig, case, "request", ref(case, "confirm_override"), RATIONALE)
    assert wrong.code == "APPROVAL_SCOPE_MISMATCH"
    assert refused(rig, case, "request", ref(case, "override_case")).code == "RATIONALE_REQUIRED"
    request_ref = ref(case, "override_case")
    requested_at = rig.clock.now()
    view = override(rig, case, "request", request_ref, RATIONALE)
    assert view["state"] == "open" and view["decision"] is None
    pending = view["override"]
    assert pending["state"] == "pending" and pending["failing_gates"] == ["G-DSR"]
    assert pending["eligible_at"] == requested_at + timedelta(hours=24)
    assert state_of(rig, case.version_id) == "AcceptanceReview"
    assert refused(rig, case, "request", ref(case, "override_case"), RATIONALE).code == (
        "OVERRIDE_EXISTS"
    )

    # Cooling: 23 hours later the confirmation is still refused.
    rig.clock.advance(hours=23)
    cooling = refused(rig, case, "confirm", ref(case, "confirm_override"))
    assert cooling.code == "OVERRIDE_COOLING"
    rig.clock.advance(hours=1)
    # The confirmation is a second approval, recorded after the cooling period.
    same = ref(case, "confirm_override", request_ref.approval_id)
    assert refused(rig, case, "confirm", same).code == "OVERRIDE_SAME_APPROVAL"
    early = ref(case, "confirm_override", uuid7_at(rig.clock.now() - timedelta(hours=2)))
    assert refused(rig, case, "confirm", early).code == "OVERRIDE_CONFIRMED_EARLY"
    confirm = ref(case, "confirm_override", uuid7_at(rig.clock.now() + timedelta(minutes=1)))
    decided = override(rig, case, "confirm", confirm)
    assert (decided["decision"], decided["reason"], decided["reason_gate"]) == (
        "accepted", "owner_override", "G-DSR",
    )  # fmt: skip
    assert decided["approval_id"] == confirm.approval_id and decided["rationale"] == RATIONALE
    assert decided["override"]["state"] == "confirmed"
    assert state_of(rig, case.version_id) == "Accepted"
    with pytest.raises(sqlalchemy.exc.DBAPIError, match="confirmed or withdrawn once"):
        with rig.db.transaction() as conn:
            conn.execute(
                text("UPDATE eval.acceptance_overrides SET state = 'withdrawn', "
                     "withdrawn_at = now() WHERE case_id = :c"),
                {"c": case.case_id},
            )  # fmt: skip

    # Research reads the decision and the overridden gate, never the rationale.
    rig.run_days(1)
    (report,) = rig.db.rows(
        "SELECT report FROM eval.released_reports WHERE version_id = :v AND report_type = "
        "'decision'",
        v=case.version_id,
    )
    assert report.report["content"] == {
        "type": "decision", "status": "ACCEPTED", "reason": "owner_override", "gate": "G-DSR",
    }  # fmt: skip
    assert state_of(rig, case.version_id) == "Monitoring"

    # The other case: a rejection withdraws an override still cooling.
    other = the_case(rig, ids["reversal_5"])
    override(rig, other, "request", ref(other, "override_case"), RATIONALE)
    view = decide(rig, other, "reject", approval(other, "reject_case"))
    assert (view["decision"], view["reason"]) == ("rejected", "gate_failed")
    assert view["override"]["state"] == "withdrawn"
    assert refused(rig, other, "confirm", ref(other, "confirm_override")).code == "CASE_DECIDED"


def test_an_override_is_not_for_a_passing_case(rig):
    rig.activate_protocol("test-loose", LOOSE)
    version = publish(rig, ["reversal_5"])["reversal_5"]
    run_until(rig, version, {"AcceptanceReview"}, days=16)
    case = the_case(rig, version)
    assert case.recommendation == "ACCEPT"
    assert refused(rig, case, "request", ref(case, "override_case"), RATIONALE).code == (
        "OVERRIDE_UNNEEDED"
    )
    assert datetime.now(UTC) > case.opened_at  # the case is real and open
