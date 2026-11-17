import json

import pytest
from test_case_factor import spec
from test_case_research import host

from qfh.case_report import CHECKS, render
from qfh.shared_state import digest


def setup(tmp_path):
    obj = host(tmp_path, protocol="structured-v3", reference_mode="task_bound")
    task = obj.begin("root", "analyze", "Analyze assigned case", [])
    finding = {
        "candidate_id": "assigned",
        "topic": "normalization",
        "statement": "Prices vary.",
        "status": "supported",
        "citations": [{"evidence_id": "prices", "quote": "Observed prices vary."}],
        "contradicts": [],
    }
    return obj, task, finding


def analyzed(tmp_path):
    obj, task, finding = setup(tmp_path)
    payload = json.dumps({"findings": [finding]})
    assert obj.submit(task["child_id"], "findings", payload)["status"] == "accepted"
    obj.finish("root", task["child_id"], {"stopReason": "completed"})
    recorded = obj.scope("root")["findings"][0]
    assert recorded["body"]["candidate_id"] == obj.scope("root")["head"]["id"]
    with obj.board.locked() as events:
        bound = next(e for e in events if e["kind"] == "submission_bound")
    assert bound["body"]["raw_payload_sha256"] == digest(json.loads(payload))
    assert json.loads(obj.read("root", "finding:1", 0)["text"]) == recorded
    assert json.loads(obj.read("root", f"event:{recorded['sequence']}", 0)["text"]) == recorded
    with pytest.raises(ValueError, match="unknown"):
        obj.read("root", f"event:{bound['sequence']}", 0)
    return obj, recorded["id"], finding


@pytest.mark.parametrize(
    "reference",
    [
        "f" * 64,
        "assigned\n",
        "latest",
        "49dfb7306466d52bca81a2435c71c1f10703c7aeeba057a893c25357d6b48",
    ],
)
def test_bad_ids_are_not_guessed_repaired_or_retargeted(tmp_path, reference):
    obj, task, finding = setup(tmp_path)
    finding["candidate_id"] = reference
    result = obj.submit(task["child_id"], "findings", json.dumps({"findings": [finding]}))
    assert result["status"] == "rejected"
    assert not obj.scope("root")["findings"]


def test_task_binding_refuses_a_changed_head(tmp_path):
    obj, task, finding = setup(tmp_path)
    with obj.board.locked() as events:
        head = obj.board._head(events)
        obj.board._append(
            events, "operator", "initial_candidate", {**head["body"], "test": "changed head"}
        )
    result = obj.submit(task["child_id"], "findings", json.dumps({"findings": [finding]}))
    assert result["status"] == "rejected" and "stale" in result["error"]


def test_complete_task_bound_report_keeps_exact_hashes_and_selects_own_inspection(tmp_path):
    obj, finding_id, finding = analyzed(tmp_path)
    task = obj.begin("root", "design", "Inspect a proposal", ["finding:1"])
    schema = json.loads(task["prompt"])["scope"]["submission_schema"]
    assert schema["properties"]["parent_id"]["const"] == "assigned"
    assert (
        "changed_rows_from_initial"
        in schema["$defs"]["Argument"]["properties"]["fact_refs"]["items"]["enum"]
    )
    first = obj.inspect(task["child_id"], spec(lookback=3).model_dump_json())
    second = obj.inspect(task["child_id"], spec(lookback=4).model_dump_json())
    assert first["inspection_ref"] == "inspection:1" and second["inspection_ref"] == "inspection:2"
    value = {
        "parent_id": "assigned",
        "inspection_id": "inspection:1",
        "facts_sha256": "inspection",
        "hypothesis": {"text": "Explore persistence.", "fact_refs": ["spec"]},
        "rationale": {
            "text": "No improvement is established.",
            "fact_refs": ["scope", "changed_rows_from_initial"],
        },
        "decisions": [
            {"finding_id": "finding:1", "disposition": "adopt", "reason": "Explore the finding."}
        ],
        "citations": finding["citations"],
        "basis_review_id": None,
        "issue_resolutions": [],
    }
    missing = {**value, "inspection_id": "inspection:6"}
    assert obj.submit(task["child_id"], "revise", json.dumps(missing))["status"] == "rejected"
    result = obj.submit(task["child_id"], "revise", json.dumps(value))
    assert result["status"] == "accepted", result
    body = result["artifact"]["body"]["structured_submission"]
    assert body["inspection_id"] == first["inspection_id"]
    assert body["facts_sha256"] == first["facts_sha256"]
    obj.finish("root", task["child_id"], {"stopReason": "completed"})
    scope = obj.scope("root")
    task = obj.begin("root", "review", "Review assigned complete report", ["finding:1"])
    value = {
        "candidate_id": "assigned",
        "report_sha256": "assigned",
        "verdict": "reviewed_with_limits",
        "checks": dict.fromkeys(CHECKS, "consistent"),
        "issues": [],
        "citations": finding["citations"],
    }
    result = obj.submit(task["child_id"], "review", json.dumps(value))
    assert result["status"] == "accepted", result
    assert (
        result["artifact"]["body"]["structured_review"]["report_sha256"]
        == scope["structured_report"]["sha256"]
    )
    obj.finish("root", task["child_id"], {"stopReason": "completed"})
    with pytest.raises(ValueError, match="exact-current"):
        obj.finalize("root", "candidate:1", "review:1")
    final = obj.finalize("root", "candidate:2", "review:1")
    assert final["finalized"]["body"]["report_sha256"] == scope["structured_report"]["sha256"]
    report = scope["structured_report"]
    assert render(report, result["artifact"]["id"]) == render(
        json.loads(json.dumps(report, sort_keys=True)), result["artifact"]["id"]
    )
