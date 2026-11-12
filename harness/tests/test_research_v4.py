import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pytest
from test_research import draft, fixture_data, measured_report
from test_research_specification import specification

from qfh.budget import BudgetRefused
from qfh.research import Operation, PilotExtension, Research


@pytest.fixture
def research(tmp_path, monkeypatch):
    monkeypatch.setattr("qfh.research.admission_open", lambda _: True)
    obj = Research(Path(__file__).resolve().parents[1] / "configs/research-trial.yaml", tmp_path)
    obj.admit("root")
    return obj


def assessment(research, child, evidence, **changes):
    return research.operate(
        Operation(
            op="specification",
            session_id=child,
            args={
                "evidence_id": evidence,
                "specification_json": specification(**changes).model_dump_json(),
            },
        )
    )


def worker(research, role, evidence, **changes):
    child = research.begin_worker("root", role, "Independently inspect the bounded evidence.")[
        "child_id"
    ]
    research.data.grant(child, evidence)
    result = assessment(research, child, evidence, **changes)
    report = {
        **measured_report(research, child, evidence),
        "specification_id": result["specification_id"],
    }
    assert research.submit_report(child, json.dumps(report))["status"] == "accepted"
    research.finish_worker(
        "root",
        child,
        {"stopReason": "completed", "output": [{"type": "text", "text": "Submitted."}]},
    )
    return child, result


def new_draft(evidence, ident):
    body = draft(evidence)
    for key in ("formula", "signal_time", "execution_time"):
        del body[key]
    return {**body, "selected_specification_id": ident}


def extension(**changes):
    return PilotExtension.model_validate(
        {
            "amendment_id": "test-operator-extension",
            "expected_limit": 3,
            "new_limit": 6,
            "authority": "Owner explicitly authorizes extending the bounded pilot "
            "without changing its budget.",
            "reason": "One verification round and two bounded owner trials.",
            **changes,
        }
    )


def test_v4_host_resolves_executable_draft_and_cannot_accept_free_formula(research):
    evidence = fixture_data(research)
    _, first = worker(research, "researcher", evidence)
    _, second = worker(research, "reviewer", evidence)
    assert first["specification_id"] == second["specification_id"]
    body = new_draft(evidence, first["specification_id"])
    with pytest.raises(ValueError):
        research.record_draft("root", {**body, "formula": "unresolved theta or another rule"})
    result = research.record_draft("root", body)["draft"]
    assert result["formula"] == first["canonical_formula"]
    assert result["specification"] == first
    assert result["statistical_outcome"] == "insufficient_data"
    assert result["specification"]["inference"]["interval"] is None


def test_selected_specification_must_be_independently_executed_by_reviewer(research):
    evidence = fixture_data(research)
    _, first = worker(research, "researcher", evidence)
    _, second = worker(research, "reviewer", evidence, threshold="0.01")
    with pytest.raises(ValueError, match="not executed"):
        research.record_draft("root", new_draft(evidence, first["specification_id"]))
    result = research.record_draft("root", new_draft(evidence, second["specification_id"]))
    assert result["draft"]["specification"]["definition"]["threshold"] == "0.01"


def test_report_cannot_copy_another_workers_execution_or_supply_free_formula(research):
    evidence = fixture_data(research)
    _, first = worker(research, "researcher", evidence)
    child = research.begin_worker(
        "root", "reviewer", "Review the bounded specification independently."
    )["child_id"]
    research.data.grant(child, evidence)
    body = {
        **measured_report(research, child, evidence),
        "specification_id": first["specification_id"],
    }
    assert research.submit_report(child, json.dumps(body))["status"] == "rejected"
    assessment(research, child, evidence)
    assert (
        research.submit_report(
            child, json.dumps({**body, "proposed_formula": "alternative alpha unspecified"})
        )["status"]
        == "rejected"
    )
    assert research.submit_report(child, json.dumps(body))["status"] == "accepted"


def test_allowance_extension_keeps_history_policy_and_budget_and_is_idempotent(research):
    research.admit("second")
    research.admit("third")
    with pytest.raises(BudgetRefused, match="allowance"):
        research.admit("fourth")
    budget = research.ledger.snapshot()
    with research.db() as db:
        original_policy = db.execute("SELECT body FROM policy").fetchone()[0]
        count = db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    first = research.extend_allowance(extension())
    assert research.extend_allowance(extension()) == first
    assert research.ledger.snapshot() == budget
    with research.db() as db:
        assert db.execute("SELECT body FROM policy").fetchone()[0] == original_policy
        assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == count + 1
    fresh = Research(research.config_path, research.private)
    assert fresh.allowance() == {
        "original_limit": 3,
        "effective_limit": 6,
        "used": 3,
        "remaining": 3,
    }
    for name in ("fourth", "fifth", "sixth"):
        fresh.admit(name)
    with pytest.raises(BudgetRefused, match="allowance"):
        fresh.admit("seventh")
    with pytest.raises(ValueError, match="immutable"):
        fresh.extend_allowance(extension(new_limit=7))
    with pytest.raises(ValueError, match="match and increase"):
        fresh.extend_allowance(
            extension(amendment_id="another-amendment", expected_limit=3, new_limit=7)
        )
    with pytest.raises(ValueError):
        Operation(op="extend_allowance", session_id="root", args={})


def test_extension_refuses_pending_and_unknown_charges(research, monkeypatch):
    monkeypatch.setattr("qfh.budget.admission_open", lambda _: True)
    research.ledger.reserve(
        "unsettled", "research:root:supervisor", datetime(2026, 11, 12, 12, tzinfo=UTC)
    )
    with pytest.raises(ValueError, match="pending or unknown"):
        research.extend_allowance(extension())
    research.ledger.unknown("unsettled", "synthetic interrupted transport")
    with pytest.raises(ValueError, match="pending or unknown"):
        research.extend_allowance(extension())
    assert research.allowance()["effective_limit"] == 3


def test_concurrent_repeated_extension_adds_only_one_event(research):
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: research.extend_allowance(extension()), range(2)))
    assert results[0] == results[1]
    with research.db() as db:
        assert (
            db.execute(
                "SELECT COUNT(*) FROM events WHERE kind='trial_allowance_extended'"
            ).fetchone()[0]
            == 1
        )
