"""Phase 6 over eval_db: a factor's whole path from W1 to the owner's acceptance decision
on the replay world (P6.1 to P6.6), with REL-05, ACC-01, ACC-02 and ACC-03.

The planted factors are genuine signals, but on the 60-name test universe their daily
RankIC is too noisy for the shipped W2 and holdout gates. These tests check mechanics,
so each activates a test protocol version (never shipped) whose gates any signal with
the right sign clears; the REJECT path adds one acceptance gate nothing clears. The
benchmarks measure the shipped gates (tests/benchmarks).
"""

from uuid import UUID

import pytest
import sqlalchemy.exc
from qfr_core.contracts import ApprovalScope
from qfr_core.eval_api import CaseApprovalRef, CaseDecisionRequest
from qfr_core.ids import uuid7
from qfr_eval.acceptance import decide_case, open_case
from qfr_eval.configs import EvalError, active_state

from tests.eval.eval_rig import eval_rig, replay_config
from tests.registry_rig import factor_manifest
from tests.synthetic_fixtures import REPLAY_EPOCH

pytestmark = pytest.mark.postgres

# Gates any correctly signed signal clears; the forward RankIC must still be positive.
LOOSE = {
    "w1_factor": {"rankic_min": 0.0, "ir_min": 0.0, "nw_t_min": 0.0, "turnover_max": 2.0,
                  "library_correlation_max": 1.0},
    "w2_factor": {"rankic_min": 0.0, "ir_min": 0.0, "ls_net_sharpe_min": -100.0},
    "holdout_factor": {"rankic_min": -1.0, "ls_net_sharpe_min": -100.0,
                       "reference_ir_min": -100.0},
    "acceptance": {"dsr_min": 0.0, "pbo_max": 1.0, "hlz_t_min": -100.0,
                   "consistency_z_min": -100.0, "forward_drawdown_max": 1.0,
                   "library_correlation_max": 1.0, "complete_data_min": 0.0},
}  # fmt: skip
UNREACHABLE_DSR = LOOSE | {"acceptance": LOOSE["acceptance"] | {"dsr_min": 1.01}}

# Planted A1 (short-term reversal) variants, each in its own family.
FACTORS = {
    "reversal_5": "-Pct($close,5)",
    "reversal_ema": "EMA(-Pct($close,2),5)",
    "reversal_vol": "-Pct($close,3)/Std($ret,20)",
}
REPLAY_DAYS_PER_TICK = 30  # the 60-day incubation takes two simulation ticks


@pytest.fixture
def rig(tmp_path, replay_zones):
    with eval_rig(
        tmp_path, replay_zones, epoch=REPLAY_EPOCH, config=replay_config(REPLAY_DAYS_PER_TICK)
    ) as built:
        yield built


def publish(rig, names):
    ids = {}
    for name in names:
        response = rig.registry.publish(factor_manifest(name, FACTORS[name]))
        assert response.status_code == 201, response.text
        ids[name] = UUID(response.json()["version"]["version_id"])
    return ids


def state_of(rig, version_id):
    return rig.db.scalar("SELECT state FROM eval.intake WHERE version_id = :v", v=version_id)


def run_until(rig, version_id, states, days=12):
    for _ in range(days):
        if state_of(rig, version_id) in states:
            return
        rig.run_days(1)
    assert state_of(rig, version_id) in states, (state_of(rig, version_id), rig.state_counts())


def approval(case, decision, version_id=None):
    scope = ApprovalScope(
        job_id=None, deliverable_id=None, version_ids=[version_id or case.version_id],
        pool=None, tier=None, case_id=case.case_id, entry_ids=[],
    )  # fmt: skip
    return CaseApprovalRef(approval_id=uuid7(), decision=decision, scope=scope)


def decide(rig, case, decision, ref):
    request = CaseDecisionRequest(decision=decision, rationale="Reviewed the gates.", approval=ref)
    with rig.db.transaction() as conn:
        state = active_state(conn)
        return decide_case(
            conn, state, case.case_id, request, "owner", rig.clock.now(), "r", "test-sha"
        )


def the_case(rig, version_id):
    return rig.db.rows("SELECT * FROM eval.acceptance_cases WHERE version_id = :v", v=version_id)[0]


def test_a_factor_goes_from_w1_to_an_accepted_case(rig):
    rig.activate_protocol("test-loose", LOOSE)
    ids = publish(rig, FACTORS)
    version = ids["reversal_5"]

    run_until(rig, version, {"Incubating"})
    path = [
        r.action
        for r in rig.db.rows(
            "SELECT action FROM eval.events WHERE entity_id = :v "
            "OR payload ->> 'version_id' = :v ORDER BY at, event_id",
            v=str(version),
        )
    ]
    assert path.index("w2_queued") < path.index("w2_admitted") < path.index("holdout_admitted")
    assert path.index("holdout_admitted") < path.index("sim_created")

    # ACC-02: no case while the incubation runs, and the table refuses an early one.
    sim = rig.db.rows("SELECT * FROM eval.sim_accounts WHERE version_id = :v", v=version)[0]
    assert (sim.mode, sim.purpose, sim.required_days) == ("replay", "incubation", 60)
    assert rig.db.scalar("SELECT count(*) FROM eval.acceptance_cases") == 0
    intake = rig.db.rows("SELECT * FROM eval.intake WHERE version_id = :v", v=version)[0]
    with pytest.raises(sqlalchemy.exc.DBAPIError, match="only after incubation ends"):
        with rig.db.transaction() as conn:
            open_case(conn, active_state(conn), intake, sim, [], rig.clock.now(), "t", "r")

    run_until(rig, version, {"AcceptanceReview"}, days=4)
    sim = rig.db.rows("SELECT * FROM eval.sim_accounts WHERE version_id = :v", v=version)[0]
    assert sim.status == "completed" and sim.days_done == 60
    case = the_case(rig, version)
    gates = {g["name"]: g for g in case.gate_results}
    assert set(gates) == {
        "G-W1", "G-W2", "G-HOLDOUT", "G-DSR", "G-PBO", "G-HLZ", "G-FWD", "G-NOVELTY", "G-OPS",
    }  # fmt: skip
    assert case.short_code.startswith("C-") and case.state == "open"
    assert case.recommendation == "ACCEPT", case.failing_gates
    assert gates["G-FWD"]["detail"]["mode"] == "replay"

    # ACC-01: the case's N_eff is the number of factor clusters in the latest run.
    detail = gates["G-DSR"]["detail"]
    clusters = rig.db.scalar(
        "SELECT count(DISTINCT c.cluster_id) FROM eval.trial_clusters c "
        "JOIN eval.intake i ON i.version_id = c.version_id "
        "WHERE c.run_id = CAST(:r AS uuid) AND i.kind = 'factor'",
        r=detail["cluster_run_id"],
    )
    assert detail["n_eff"] == clusters and 1 <= clusters <= detail["n_raw"]
    latest = rig.db.scalar(
        "SELECT run_id FROM eval.trial_cluster_runs ORDER BY computed_at DESC, run_id DESC LIMIT 1"
    )
    assert str(latest) == detail["cluster_run_id"]

    # ACC-03: the decision needs an approval that names this case and decision.
    for wrong in (approval(case, "reject_case"), approval(case, "accept_case", uuid7())):
        with pytest.raises(EvalError) as refused:
            decide(rig, case, "accept", wrong)
        assert (refused.value.status, refused.value.code) == (403, "APPROVAL_SCOPE_MISMATCH")
    other = approval(case, "accept_case")
    other = other.model_copy(update={"scope": other.scope.model_copy(update={"case_id": uuid7()})})
    with pytest.raises(EvalError, match="must name the case"):
        decide(rig, case, "accept", other)
    ref = approval(case, "accept_case")
    view = decide(rig, case, "accept", ref)
    assert (view["decision"], view["reason"], view["approval_id"]) == (
        "accepted", "gates_passed", ref.approval_id,
    )  # fmt: skip
    with pytest.raises(EvalError) as again:
        decide(rig, case, "reject", approval(case, "reject_case"))
    assert again.value.code == "CASE_DECIDED"
    assert state_of(rig, version) == "Accepted"

    # The decision is released at once; monitoring starts for the accepted version.
    rig.run_days(1)
    decision = rig.db.rows(
        "SELECT report FROM eval.released_reports WHERE version_id = :v AND report_type = "
        "'decision'",
        v=version,
    )
    assert decision and decision[0].report["content"]["status"] == "ACCEPTED"
    assert state_of(rig, version) == "Monitoring"
    monitoring = rig.db.scalar(
        "SELECT count(*) FROM eval.sim_accounts WHERE version_id = :v AND purpose = 'monitoring'",
        v=version,
    )
    assert monitoring == 1

    # REL-05: no released report names or carries a holdout value.
    holdout = rig.db.rows("SELECT metrics FROM eval.official_records WHERE stage = 'holdout'")
    planted = {
        round(float(v), 6)
        for r in holdout
        for v in (r.metrics or {}).values()
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v not in (0, 1)
    }
    assert planted
    for row in rig.db.rows("SELECT report FROM eval.released_reports"):
        content = row.report["content"]
        assert not any("w3" in k.lower() or "holdout" in k.lower() for k in content)
        if content["type"] in ("w2", "advancement", "sim", "decision"):
            numbers = {
                round(float(v), 6)
                for v in content.values()
                if isinstance(v, (int, float)) and not isinstance(v, bool)
            }
            assert not numbers & planted, content
    types = {r.report_type for r in rig.db.rows("SELECT report_type FROM eval.released_reports")}
    assert {"w1", "w2", "advancement", "sim", "decision"} <= types


def test_acc_03_a_case_with_a_failed_gate_cannot_be_accepted(rig):
    rig.activate_protocol("test-unreachable-dsr", UNREACHABLE_DSR)
    version = publish(rig, ["reversal_ema"])["reversal_ema"]
    run_until(rig, version, {"AcceptanceReview"}, days=16)
    case = the_case(rig, version)
    assert case.recommendation == "REJECT" and "G-DSR" in case.failing_gates
    with pytest.raises(EvalError) as refused:
        decide(rig, case, "accept", approval(case, "accept_case"))
    assert (refused.value.status, refused.value.code) == (409, "GATE_FAILED")
    view = decide(rig, case, "reject", approval(case, "reject_case"))
    assert (view["decision"], view["reason"], view["reason_gate"]) == (
        "rejected", "gate_failed", "G-DSR",
    )  # fmt: skip
    assert state_of(rig, version) == "Rejected"
    rig.run_days(1)
    (decision,) = rig.db.rows(
        "SELECT report FROM eval.released_reports WHERE version_id = :v AND report_type = "
        "'decision'",
        v=version,
    )
    content = decision.report["content"]
    assert (content["status"], content["reason"], content["gate"]) == (
        "REJECTED", "gate_failed", "G-DSR",
    )  # fmt: skip
    # A rejected version is not monitored.
    monitored = rig.db.scalar(
        "SELECT count(*) FROM eval.sim_accounts WHERE version_id = :v AND purpose = 'monitoring'",
        v=version,
    )
    assert monitored == 0
