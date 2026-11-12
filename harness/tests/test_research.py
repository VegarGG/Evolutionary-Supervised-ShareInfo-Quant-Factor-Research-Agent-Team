from pathlib import Path

import pytest

from qfh.budget import BudgetRefused
from qfh.data_gateway import dispatch
from qfh.research import Operation, Research


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


def test_arithmetic_and_append_only_events(research):
    import sqlite3

    ident = fixture_data(research)
    assert research.metrics("root", ident)["unadjusted_sample_return"] == "0.1"
    with research.db() as db:
        with pytest.raises(sqlite3.IntegrityError, match="append only"):
            db.execute("DELETE FROM events")
