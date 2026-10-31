"""Phase 6 through the MCP front door: acceptance cases and decisions, approvals with
case and pool-entry short codes, pool curation and alerts (P6.6 to P6.8, MCP-03,
POOL-01, ACC-03).

The version reaches its case under a test protocol version with gates any correctly
signed signal clears (tests/eval/test_validation.py explains why); the tools, approvals
and audit rows are what these tests check.
"""

from uuid import UUID

import pytest
from qfr_core.ids import uuid7
from qfr_eval.alerts import raise_alert
from sqlalchemy import text

from tests.eval.eval_rig import replay_config
from tests.eval.stack_rig import stack
from tests.eval.test_validation import LOOSE, REPLAY_DAYS_PER_TICK, run_until
from tests.registry_rig import factor_manifest
from tests.synthetic_fixtures import REPLAY_EPOCH

pytestmark = pytest.mark.postgres


@pytest.fixture
def full(tmp_path, monkeypatch, replay_zones):
    with stack(
        tmp_path, monkeypatch, replay_zones, epoch=REPLAY_EPOCH,
        config=replay_config(REPLAY_DAYS_PER_TICK),
    ) as built:  # fmt: skip
        yield built


def incubated(full):
    """One factor through incubation to an open ACCEPT case."""
    full.eval.activate_protocol("test-loose", LOOSE)
    response = full.mcp.registry.publish(factor_manifest("reversal", "-Pct($close,5)"))
    version = UUID(response.json()["version"]["version_id"])
    run_until(full.eval, version, {"AcceptanceReview"}, days=16)
    return version


def record(full, **arguments):
    return full.mcp.call(
        "qfr.approval.record", rationale="The owner reviewed the evidence.", **arguments
    )


def error_text(result):
    assert result.get("isError") is True, result
    return " ".join(c.get("text", "") for c in result["content"])


def test_a_case_is_decided_and_its_version_curated_through_mcp(full):
    mcp = full.mcp
    version = incubated(full)

    # P7.2: owner-grade evidence on every window, gates labelled by stage and window,
    # the incubation account and the open case, with the owner_only label.
    evidence = mcp.ok("qfr.evidence.get", version_id=str(version))["data"]
    assert evidence["visibility"] == "owner_only"
    assert evidence["hygiene_warning"].startswith("Never copy owner-only evidence")
    windows = {(w["stage"], w["window"]) for w in evidence["windows"]}
    assert {("w1", "W1"), ("w2", "W2"), ("holdout", "W3")} <= windows
    assert {g["stage"] for g in evidence["gate_values"]} == {"w1", "w2", "holdout", "acceptance"}
    for gate in evidence["gate_values"]:
        expected = {"w1": "W1", "w2": "W2", "holdout": "W3", "acceptance": None}
        assert gate["window"] == expected[gate["stage"]]
    assert {"W1", "W2"} <= {s["window"] for s in evidence["series"]}
    (sim,) = [s for s in evidence["simulation_state"] if s["purpose"] == "incubation"]
    assert sim["days_done"] > 0 and sim["metrics"]["final_nav"] is not None
    assert [c["state"] for c in evidence["acceptance_cases"]] == ["open"]

    listed = mcp.ok("qfr.acceptance.list_cases", state="open")["data"]
    assert listed["visibility"] == "owner_only" and "hygiene_warning" in listed
    (case,) = listed["items"]
    assert case["version_id"] == str(version) and case["recommendation"] == "ACCEPT"
    code = case["short_code"]

    # MCP-03: the case code must be in the owner's words; a paraphrase is refused.
    refused = record(
        full, decision="accept_case", case_id=case["case_id"],
        owner_confirmation="Yes, accept the reversal factor.",
    )  # fmt: skip
    assert "SHORT_CODE_MISSING" in error_text(refused) and code in error_text(refused)
    assert mcp.store.list_approvals(10) == []
    for arguments, expected in (
        ({"decision": "accept_case", "owner_confirmation": f"ACCEPT {code}"}, "SCOPE_INVALID"),
        ({"decision": "rollover_epoch", "owner_confirmation": "ROLL"}, "DECISION_UNSUPPORTED"),
        (
            {"decision": "approve", "version_ids": [str(version)],
             "owner_confirmation": "APPROVE"},
            "VERSION_UNCODED",
        ),
    ):  # fmt: skip
        assert expected in error_text(record(full, **arguments))

    reject = record(
        full, decision="reject_case", case_id=case["case_id"],
        owner_confirmation=f"REJECT {code}",
    )["structuredContent"]["data"]  # fmt: skip
    accept = record(
        full, decision="accept_case", case_id=case["case_id"],
        owner_confirmation=f"accept {code.lower()}",
    )["structuredContent"]["data"]  # fmt: skip
    assert accept["approval"]["short_codes_matched"] == [code]
    assert accept["approval"]["scope"]["version_ids"] == [str(version)]

    # ACC-03 through the front door: the approval must match the decision.
    wrong = mcp.call(
        "qfr.acceptance.decide", case_id=case["case_id"], decision="accept",
        approval_id=reject["approval_id"],
    )  # fmt: skip
    assert "APPROVAL_DECISION_MISMATCH" in error_text(wrong)
    unknown = mcp.call(
        "qfr.acceptance.decide", case_id=case["case_id"], decision="accept",
        approval_id=str(uuid7()),
    )  # fmt: skip
    assert "APPROVAL_NOT_FOUND" in error_text(unknown)
    decided = mcp.ok(
        "qfr.acceptance.decide", case_id=case["case_id"], decision="accept",
        approval_id=accept["approval_id"],
    )["data"]  # fmt: skip
    assert (decided["state"], decided["decision"], decided["approval_id"]) == (
        "decided", "accepted", accept["approval_id"],
    )  # fmt: skip
    again = mcp.call(
        "qfr.acceptance.decide", case_id=case["case_id"], decision="reject",
        approval_id=reject["approval_id"],
    )  # fmt: skip
    assert "CASE_DECIDED" in error_text(again)

    # The accepted version enters the pool at the incubated tier, from its case code.
    tier = record(
        full, decision="approve", case_id=case["case_id"], version_ids=[str(version)],
        tier="incubated", owner_confirmation=f"APPROVE {code} for the pool",
    )  # fmt: skip
    assert "SCOPE_INVALID" not in str(tier), tier
    approval = tier["structuredContent"]["data"]
    assert approval["approval"]["scope"]["tier"] == "incubated"
    entry = mcp.ok(
        "qfr.pool.add", approval_id=approval["approval_id"], version_id=str(version),
        tags=["reversal"],
    )["data"]["entry"]  # fmt: skip
    assert (entry["status"], entry["approved_tier"]) == ("approved", "incubated")
    entry_code = entry["short_code"]

    # POOL-01: annotate needs no approval; a status change needs one naming the entry.
    annotated = mcp.ok(
        "qfr.pool.annotate", pool="factor", entry_id=entry["entry_id"], note="Watch decay."
    )["data"]
    assert annotated["event"]["action"] == "ANNOTATED"
    mismatch = mcp.call(
        "qfr.pool.set_status", pool="factor", entry_id=entry["entry_id"], status="retired",
        approval_id=approval["approval_id"],
    )  # fmt: skip
    assert "APPROVAL_DECISION_MISMATCH" in error_text(mismatch)
    retire = record(
        full, decision="retire", pool="factor", entry_ids=[entry["entry_id"]],
        owner_confirmation=f"RETIRE {entry_code}",
    )["structuredContent"]["data"]  # fmt: skip
    retired = mcp.ok(
        "qfr.pool.set_status", pool="factor", entry_id=entry["entry_id"], status="retired",
        approval_id=retire["approval_id"],
    )["data"]  # fmt: skip
    assert retired["entry"]["status"] == "retired"
    assert (retired["event"]["from_status"], retired["event"]["to_status"]) == (
        "approved", "retired",
    )  # fmt: skip
    events = mcp.ok("qfr.pool.get", pool="factor", entry_id=entry["entry_id"])["data"]["events"]
    assert [e["action"] for e in events] == ["ADDED", "ANNOTATED", "STATUS_CHANGED"]
    assert events[2]["approval_id"] == retire["approval_id"]
    assert events[0]["approval_id"] == approval["approval_id"]

    # The evaluator syncs the retirement and stops the entry's monitoring.
    full.eval.run_days(1)
    status = full.eval.db.scalar("SELECT status FROM eval.library WHERE version_id = :v", v=version)
    assert status == "retired"
    live = full.eval.db.scalar(
        "SELECT count(*) FROM eval.sim_accounts WHERE version_id = :v AND purpose = "
        "'monitoring' AND status IN ('waiting', 'running', 'paused')",
        v=version,
    )
    assert live == 0

    # Every approval and gated write is audited and traced.
    stored = mcp.store.list_approvals(10)
    assert {a.decision for a in stored} == {"accept_case", "reject_case", "approve", "retire"}
    count = "SELECT count(*) FROM trace_steps WHERE step_type = :t"
    assert mcp.control_db.count(count, t="APPROVAL_RECORDED") == 4
    assert mcp.control_db.count(count, t="POOL_EVENT") == 3
    audited = [c.tool for c in mcp.audit.calls if c.outcome == "ok"]
    assert audited.count("qfr.acceptance.decide") == 1 and "qfr.pool.set_status" in audited


def test_an_approval_cannot_name_a_tier_above_the_one_reached(full):
    version = incubated(full)
    (case,) = full.mcp.ok("qfr.acceptance.list_cases")["data"]["items"]
    # Before the decision the version has reached the advanced tier, not incubated.
    refused = record(
        full, decision="approve", case_id=case["case_id"], version_ids=[str(version)],
        tier="incubated", owner_confirmation=f"APPROVE {case['short_code']}",
    )  # fmt: skip
    assert "TIER_NOT_REACHED" in error_text(refused)
    lower = record(
        full, decision="approve", case_id=case["case_id"], version_ids=[str(version)],
        tier="w1_pass", owner_confirmation=f"APPROVE {case['short_code']}",
    )["structuredContent"]["data"]  # fmt: skip
    assert lower["approval"]["scope"]["tier"] == "w1_pass"


def test_ops_alerts_lists_and_acknowledges_the_evaluator_alerts(full):
    full.eval.scheduler.tick()
    empty = full.mcp.ok("qfr.ops.alerts")["data"]
    assert empty["items"] == [] and empty["open"]["evaluation"] == 0
    assert empty["open"]["operations"] == 0
    # This rig has no research-api: the source is named, not guessed.
    assert empty["sources"]["research"] == "not_configured"
    with full.eval.db.transaction() as conn:
        raise_alert(
            conn, "decay", "decay:test", {"rolling_rankic_mean": -0.01, "days_below": 20},
            full.eval.clock.now(), "sim-engine", "r",
        )  # fmt: skip
    page = full.mcp.ok("qfr.ops.alerts", kind="decay")["data"]
    assert page["open"]["evaluation"] == 1
    [item] = page["items"]
    assert item["kind"] == "decay" and item["source"] == "evaluation"
    # A kind belongs to one source; the others are skipped rather than asked.
    assert page["sources"] == {"evaluation": "ok", "research": "skipped", "operations": "skipped"}
    assert full.mcp.ok("qfr.ops.alerts", kind="burn")["data"]["items"] == []
    status = full.mcp.ok("qfr.status")["data"]
    assert status["alerts"]["evaluation"] == 1 and status["alerts"]["tool"] == "qfr.ops.alerts"
    acked = full.mcp.ok(
        "qfr.ops.acknowledge_alert", source="evaluation", alert_id=item["alert_id"],
        note="Seen; the factor stays monitored.",
    )["data"]  # fmt: skip
    assert (
        acked["alert"]["state"] == "acknowledged" and acked["alert"]["acknowledged_by"] == "owner"
    )
    assert acked["acknowledgement"]["note"] == "Seen; the factor stays monitored."
    again = full.mcp.ok(
        "qfr.ops.acknowledge_alert", source="evaluation", alert_id=item["alert_id"]
    )["data"]
    assert again["acknowledgement"]["ack_id"] == acked["acknowledgement"]["ack_id"]
    assert full.mcp.ok("qfr.ops.alerts", state="open")["data"]["open"]["evaluation"] == 0
    missing = full.mcp.error(
        "qfr.ops.acknowledge_alert", source="evaluation", alert_id=str(uuid7())
    )
    assert "ALERT_NOT_FOUND" in missing
    with full.eval.db.read() as conn:
        events = (
            conn.execute(
                text("SELECT payload FROM eval.events WHERE action = 'alert_acknowledged'")
            )
            .scalars()
            .all()
        )
    assert events == [{"by": "owner", "note": "Seen; the factor stays monitored."}]
