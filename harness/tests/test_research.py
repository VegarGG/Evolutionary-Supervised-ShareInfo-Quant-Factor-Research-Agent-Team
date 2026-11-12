import json
from pathlib import Path

import pytest

from qfh.budget import BudgetRefused
from qfh.data_gateway import dispatch
from qfh.research import Operation, Research, parse_worker_report
from qfh.trial_metrics import work_metrics


@pytest.fixture
def research(tmp_path, monkeypatch):
    monkeypatch.setattr("qfh.research.admission_open", lambda _: True)
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
    }


def completed(research, role, evidence_id):
    import json

    worker = research.begin_worker("root", role, "Inspect the bounded test evidence.")
    research.data.grant(worker["child_id"], evidence_id)
    research.finish_worker(
        "root",
        worker["child_id"],
        {
            "stopReason": "completed",
            "output": [{"type": "text", "text": json.dumps(report(evidence_id))}],
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
def test_single_fenced_report_keeps_raw_text_and_validates_citations(research, label):
    worker = research.begin_worker("root", "researcher", "Inspect the bounded test evidence.")
    ident = fixture_data(research, worker["child_id"])
    text = "```" + label + "\n" + json.dumps(report(ident)) + "\n```"
    raw = {"stopReason": "completed", "output": [{"type": "text", "text": text}]}
    result = research.finish_worker("root", worker["child_id"], raw)
    assert result["report"] == report(ident)
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
    assert research.metrics("root", ident)["unadjusted_sample_return"] == "0.1"
    with research.db() as db:
        with pytest.raises(sqlite3.IntegrityError, match="append only"):
            db.execute("DELETE FROM events")
