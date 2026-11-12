import json
from pathlib import Path

import pytest

from qfh.budget import BudgetRefused
from qfh.data_gateway import dispatch
from qfh.research import Operation, Research, parse_worker_report
from qfh.trial_metrics import work_metrics


@pytest.fixture
def research(tmp_path, monkeypatch, request):
    monkeypatch.setattr("qfh.research.admission_open", lambda _: True)
    monkeypatch.setattr(
        "qfh.research.REPORT_CONTRACT", getattr(request, "param", "submitted-reports-v3")
    )
    obj = Research(Path(__file__).resolve().parents[1] / "configs/research-trial.yaml", tmp_path)
    obj.admit("root")
    return obj


def fixture_data(research, session_id="root"):
    return dispatch(
        {
            "provider": "baostock",
            "run_id": session_id,
            "kind": "bars",
            "credentials": {},
            "query": research.policy.query.model_dump(mode="json"),
        },
        research.data_policy,
        research.data_root,
        baostock_fetch=lambda *_: (
            [
                {"symbol": "000001.XSHE", "date": "2026-10-19", "close": 10},
                {"symbol": "000001.XSHE", "date": "2026-10-20", "close": 11},
            ],
            {"synthetic": True, "external_requests": 0},
        ),
    )["evidence_id"]


def report(evidence_id):
    return {
        "summary": "Synthetic test report, not a real research finding.",
        "evidence_ids": [evidence_id],
        "findings": ["Two test observations."],
        "proposed_formula": None,
        "recommended_changes": [],
        "limitations": ["Synthetic data only."],
        "measurement_refs": [],
        "specification_id": None,
    }


def measured_report(research, session_id, evidence_id):
    metrics = research.operate(
        Operation(op="metrics", session_id=session_id, args={"evidence_id": evidence_id})
    )
    return {
        **report(evidence_id),
        "measurement_refs": [
            {
                "measurement_id": metrics["measurement_id"],
                "keys": ["sample.observations", "returns.mean"],
            }
        ],
    }


def completed(research, role, evidence_id):
    import json

    worker = research.begin_worker("root", role, "Inspect the bounded test evidence.")
    research.data.grant(worker["child_id"], evidence_id)
    body = measured_report(research, worker["child_id"], evidence_id)
    assert research.submit_report(worker["child_id"], json.dumps(body))["status"] == "accepted"
    research.finish_worker(
        "root",
        worker["child_id"],
        {
            "stopReason": "completed",
            "output": [{"type": "text", "text": json.dumps(body)}],
        },
    )
    return worker


def draft(evidence_id):
    return {
        "title": "Synthetic draft",
        "hypothesis": "Test-only hypothesis without investment meaning.",
        "formula": "test_fixture",
        "signal_time": "close_t",
        "execution_time": "next_trading_day_close",
        "evidence_ids": [evidence_id],
        "decisions": [
            {"worker": r, "adopted": True, "reason": "Accept this synthetic test contribution."}
            for r in ("researcher", "reviewer")
        ],
        "limitations": ["Synthetic test."],
        "next_steps": ["No real evaluation requested."],
    }


def test_trial_bounds_no_recursive_workers_no_replay(research):
    worker = research.begin_worker("root", "researcher", "Inspect the bounded test evidence.")
    assert research.admit(worker["child_id"]).endswith(":researcher")
    with pytest.raises(ValueError, match="recursive"):
        research.begin_worker(worker["child_id"], "reviewer", "Try recursive delegation.")
    with pytest.raises(ValueError, match="already started"):
        research.begin_worker("root", "researcher", "Try a duplicate worker execution.")
    research.admit("second")
    research.admit("third")
    with pytest.raises(BudgetRefused, match="trial allowance"):
        research.admit("fourth")


def test_closed_window_does_not_allocate_trial(research, monkeypatch):
    monkeypatch.setattr("qfh.research.admission_open", lambda _: False)
    with pytest.raises(BudgetRefused, match="window"):
        research.admit("closed")
    with pytest.raises(ValueError, match="not been admitted"):
        research.member("closed")


def test_scope_and_data_do_not_allow_paid_sources_or_scope_expansion(research, monkeypatch):
    research.admit("paid")
    with pytest.raises(ValueError, match="BaoStock only"):
        research.scope("paid", "ifind")

    def forbidden(*args, **kwargs):
        pytest.fail("out of scope requests must stop before provider dispatch")

    monkeypatch.setattr("qfh.research.dispatch", forbidden)
    for args in [
        {"kind": "news", "query": research.policy.query.model_dump(mode="json")},
        {
            "kind": "bars",
            "query": {"symbols": ["600000.XSHG"], "start": "2026-10-19", "end": "2026-10-30"},
        },
        {
            "kind": "bars",
            "query": {"symbols": ["000001.XSHE"], "start": "2026-10-19", "end": "2026-11-12"},
        },
    ]:
        with pytest.raises(ValueError):
            research.operate(Operation(op="data", session_id="root", args=args))


def test_draft_requires_valid_workers_citations_and_cannot_be_overwritten(research):
    ident = fixture_data(research)
    with pytest.raises(ValueError, match="both workers"):
        research.record_draft("root", draft(ident))
    worker = completed(research, "researcher", ident)
    completed(research, "reviewer", ident)
    with pytest.raises(ValueError, match="supervisor"):
        research.record_draft(worker["child_id"], draft(ident))
    with pytest.raises(ValueError, match="not granted"):
        research.record_draft("root", draft("f" * 64))
    result = research.record_draft("root", draft(ident))
    assert result["evaluation"] == "not run" and result["publication"] == "not published"
    with pytest.raises(ValueError, match="immutable"):
        research.record_draft("root", draft(ident))
    with pytest.raises(BudgetRefused, match="already finished"):
        research.admit(worker["child_id"])


def test_failed_worker_retains_raw_output_and_stops_draft(research):
    worker = research.begin_worker("root", "reviewer", "Check the test evidence independently.")
    with pytest.raises(ValueError, match="raw result retained"):
        research.finish_worker(
            "root",
            worker["child_id"],
            {"stopReason": "completed", "output": [{"type": "text", "text": "invalid report"}]},
        )
    row = research.member(worker["child_id"])
    assert row["state"] == "failed" and "invalid report" in row["result"]


@pytest.mark.parametrize("label", ["json", ""])
@pytest.mark.parametrize("research", ["measured-observations-v2"], indirect=True)
def test_single_fenced_report_keeps_raw_text_and_validates_citations(research, label):
    worker = research.begin_worker("root", "researcher", "Inspect the bounded test evidence.")
    ident = fixture_data(research, worker["child_id"])
    body = measured_report(research, worker["child_id"], ident)
    text = "```" + label + "\n" + json.dumps(body) + "\n```"
    raw = {"stopReason": "completed", "output": [{"type": "text", "text": text}]}
    result = research.finish_worker("root", worker["child_id"], raw)
    assert result["report"] == body
    assert result["measured_facts"][0]["value"] == "2"
    member = research.member(worker["child_id"])
    assert json.loads(member["result"]) == raw
    assert (
        work_metrics(member, [], None)["model_authored_report"]["summary"]
        == report(ident)["summary"]
    )
    with research.db() as db:
        event = json.loads(
            db.execute("SELECT body FROM events WHERE kind='worker_finished'").fetchone()[0]
        )
    assert event["report_format"] == "json_fence" and event["validation_error"] is None
    with pytest.raises(ValueError, match="already recorded"):
        research.finish_worker("root", worker["child_id"], raw)


@pytest.mark.parametrize(
    "template",
    [
        "Here is the report: ```json\n%s\n```",
        "```json\n%s\n```\nAdditional claims.",
        "```python\n%s\n```",
        "```json\n%s\n```\n```json\n{}\n```",
        "%s {}",
    ],
)
def test_report_decoder_rejects_prose_multiple_objects_and_wrong_fences(template):
    raw = {
        "stopReason": "completed",
        "output": [{"type": "text", "text": template % json.dumps(report("f" * 64))}],
    }
    with pytest.raises(ValueError):
        parse_worker_report(raw, 50000)


def test_fence_does_not_bypass_schema_size_stop_or_citation_checks(research):
    worker = research.begin_worker("root", "researcher", "Inspect the bounded test evidence.")
    body = report("f" * 64)
    raw = {
        "stopReason": "completed",
        "output": [{"type": "text", "text": "```json\n" + json.dumps(body) + "\n```"}],
    }
    with pytest.raises(ValueError, match="result limit"):
        parse_worker_report(raw, 10)
    with pytest.raises(ValueError, match="complete normally"):
        parse_worker_report({**raw, "stopReason": "error"}, 50000)
    invalid = {**body, "unexpected_field": True}
    with pytest.raises(ValueError):
        parse_worker_report(
            {**raw, "output": [{"type": "text", "text": json.dumps(invalid)}]}, 50000
        )
    with pytest.raises(ValueError, match="raw result retained"):
        research.finish_worker("root", worker["child_id"], raw)
    assert research.member(worker["child_id"])["state"] == "failed"


def test_rejected_report_exposes_observed_operations_without_vendor_rows(research):
    worker = research.begin_worker("root", "researcher", "Inspect the bounded test evidence.")
    ident = fixture_data(research, worker["child_id"])
    research.operate(
        Operation(op="metrics", session_id=worker["child_id"], args={"evidence_id": ident})
    )
    with pytest.raises(ValueError, match='Completed worker operations: {"metrics": 1}') as err:
        research.finish_worker(
            "root",
            worker["child_id"],
            {"stopReason": "completed", "output": [{"type": "text", "text": "invalid"}]},
        )
    assert ident not in str(err.value)


def test_arithmetic_and_append_only_events(research):
    import sqlite3

    ident = fixture_data(research)
    assert research.metrics("root", ident)["facts"]["sample.net_return"]["value"] == "0.1"
    with research.db() as db:
        with pytest.raises(sqlite3.IntegrityError, match="append only"):
            db.execute("DELETE FROM events")


@pytest.mark.parametrize(
    "fault",
    [
        "unknown_measurement",
        "unobserved",
        "unknown_key",
        "duplicate_key",
        "invented_value",
        "numeric_prose",
    ],
)
def test_report_measurements_cannot_be_fabricated_or_copied_from_another_worker(research, fault):
    child = research.begin_worker("root", "researcher", "Inspect bounded evidence independently.")[
        "child_id"
    ]
    ident = fixture_data(research, child)
    source = "root" if fault == "unobserved" else child
    research.data.grant(source, ident)
    body = measured_report(research, source, ident)
    ref = body["measurement_refs"][0]
    if fault == "unknown_measurement":
        ref["measurement_id"] = "0" * 64
    if fault == "unknown_key":
        ref["keys"] = ["invented.alpha"]
    if fault == "duplicate_key":
        ref["keys"] = ["returns.mean", "returns.mean"]
    if fault == "invented_value":
        ref["value"] = "999"
    if fault == "numeric_prose":
        body["summary"] = "The measured return is 999 percent."
    rejection = research.submit_report(child, json.dumps(body))
    assert rejection["status"] == "rejected"
    assert research.submitted_report(child) is None
    with pytest.raises(ValueError, match="raw result retained"):
        research.finish_worker(
            "root",
            child,
            {"stopReason": "completed", "output": [{"type": "text", "text": json.dumps(body)}]},
        )
    assert research.member(child)["state"] == "failed"


def test_host_activity_and_draft_show_measured_facts_without_trusting_agent_counts(research):
    ident = fixture_data(research)
    first = completed(research, "researcher", ident)
    completed(research, "reviewer", ident)
    result = research.record_draft("root", draft(ident))
    assert result["draft"]["proposal_phase"] == "post_observation_exploration"
    assert {f["worker"] for f in result["draft"]["measured_facts"]} == {"researcher", "reviewer"}
    assert all(
        f["value"] == "2"
        for f in result["draft"]["measured_facts"]
        if f["key"] == "sample.observations"
    )
    activity = research.activity("root")
    assert activity["draft_recorded"] is True
    assert activity["roles"]["supervisor"]["report_state"] == "draft_recorded"
    assert activity["roles"]["researcher"]["completed_operations"]["metrics"] == 1
    assert research.member(first["child_id"])["state"] == "completed"


def test_oversized_findings_can_be_corrected_in_same_active_worker(research):
    worker = research.begin_worker("root", "reviewer", "Check the evidence independently.")
    child = worker["child_id"]
    ident = fixture_data(research, child)
    body = measured_report(research, child, ident)
    rejected = research.operate(
        Operation(
            op="submit_report",
            session_id=child,
            args={"report_json": json.dumps({**body, "findings": ["Qualitative finding."] * 9})},
        )
    )
    assert rejected["status"] == "rejected"
    assert rejected["issues"][0]["loc"] == ("findings",)
    assert rejected["issues"][0]["type"] == "too_long"
    assert "input" not in rejected["issues"][0]
    assert research.member(child)["state"] == "active"
    assert research.submitted_report(child) is None
    accepted = research.operate(
        Operation(op="submit_report", session_id=child, args={"report_json": json.dumps(body)})
    )
    assert accepted["status"] == "accepted"
    raw = {"stopReason": "completed", "output": [{"type": "text", "text": "Report submitted."}]}
    result = research.finish_worker("root", child, raw)
    assert result["report"] == body
    assert json.loads(research.member(child)["result"]) == raw
    with research.db() as db:
        events = [
            {**dict(r), "body": json.loads(r["body"])} for r in db.execute("SELECT * FROM events")
        ]
    exported = work_metrics(research.member(child), events, None)
    assert exported["report_submission_rejections"] == 1
    assert exported["model_authored_report"]["summary"] == body["summary"]
    with pytest.raises(BudgetRefused, match="already finished"):
        research.admit(child)


def test_submission_is_own_report_immutable_and_requires_normal_native_completion(research):
    child = research.begin_worker("root", "researcher", "Inspect the bounded evidence.")["child_id"]
    ident = fixture_data(research, child)
    body = measured_report(research, child, ident)
    with pytest.raises(ValueError, match="active worker"):
        research.submit_report("root", json.dumps(body))
    assert research.submit_report(child, json.dumps(body))["status"] == "accepted"
    with pytest.raises(ValueError, match="immutable"):
        research.submit_report(child, json.dumps(body))
    with pytest.raises(ValueError, match="raw result retained"):
        research.finish_worker("root", child, {"stopReason": "error", "output": []})
    assert research.member(child)["state"] == "failed"


def test_final_text_cannot_bypass_submission_and_failed_worker_stops_tools(research):
    child = research.begin_worker("root", "reviewer", "Inspect the bounded evidence.")["child_id"]
    ident = fixture_data(research, child)
    body = measured_report(research, child, ident)
    with pytest.raises(ValueError, match="raw result retained"):
        research.finish_worker(
            "root",
            child,
            {"stopReason": "completed", "output": [{"type": "text", "text": json.dumps(body)}]},
        )
    assert research.scope("root")["activity"]["roles"]["reviewer"]["report_state"] == "failed"
    for op, args in [
        ("data", {"kind": "read", "evidence_id": ident}),
        ("draft", {}),
        ("begin_worker", {"role": "researcher", "task": "Try again."}),
    ]:
        with pytest.raises(ValueError, match="trial stopped"):
            research.operate(Operation(op=op, session_id="root", args=args))
