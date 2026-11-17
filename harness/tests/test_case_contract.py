import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest
from test_case_factor import spec
from test_case_research import analyze, host, revision

from qfh.budget import BudgetRefused, Usage
from qfh.case_contract import encoded, prose_checks
from qfh.coding_plan import CodingLedger
from qfh.workspace import isolated_workspace


def paid(ledger, obj, session, ident):
    step = obj.admit(session)
    ledger.reserve(ident, step, datetime.now(UTC), output_tokens=128)
    ledger.settle(ident, Usage(input_cached=0, input_uncached=1, input_cache_write=0, output=1))
    return step


def test_submission_at_last_work_request_gets_one_real_ack_not_fake_completion(tmp_path):
    obj = host(tmp_path, protocol="bounded-v2", worker_requests=1)
    ledger = CodingLedger(
        obj.research.ledger, obj.route, admission_check=obj.check_completion_reserve
    )
    task = obj.begin("root", "analyze", "Inspect", [])
    child = task["child_id"]
    paid(ledger, obj, child, "work")
    with pytest.raises(BudgetRefused, match="step request"):
        paid(ledger, obj, child, "extra-work")
    current = obj.board.snapshot("supervisor")["head"]["id"]
    payload = {
        "findings": [
            {
                "candidate_id": current,
                "topic": "coverage",
                "statement": "Observed prices vary.",
                "status": "supported",
                "citations": [{"evidence_id": "prices", "quote": "Observed prices vary."}],
                "contradicts": [],
            }
        ]
    }
    assert obj.submit(child, "findings", json.dumps(payload))["status"] == "accepted"
    assert paid(ledger, obj, child, "ack").endswith(":ack")
    with pytest.raises(BudgetRefused, match="step request"):
        paid(ledger, obj, child, "second-ack")
    result = obj.finish("root", child, {"stopReason": "error"})
    assert result["task"]["body"]["status"] == "failed"
    assert obj.scope("root")["next_fixed_stage"] is None
    assert obj.scope("root")["attempt"]["state"] == "closed"


def test_group_ack_slots_are_atomic_and_all_calls_stay_in_original_ledger(tmp_path):
    obj = host(tmp_path, protocol="bounded-v2", total_requests=5, supervisor_requests=5)
    ledger = CodingLedger(
        obj.research.ledger, obj.route, admission_check=obj.check_completion_reserve
    )
    for i in range(3):
        paid(ledger, obj, "root", str(i))
    before = ledger.snapshot()

    def attempt(i):
        try:
            paid(ledger, obj, "root", str(i))
        except BudgetRefused as error:
            return str(error)

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert all("terminal acknowledgements" in v for v in pool.map(attempt, [3, 4]))
    assert ledger.snapshot() == before


def test_large_board_is_losslessly_paged_and_receipt_is_bounded(tmp_path):
    obj = host(tmp_path, protocol="bounded-v2")
    finding = analyze(obj)
    task = obj.begin("root", "design", "Revise", [finding])
    payload = revision(obj, finding)
    inspection = obj.inspect(task["child_id"], json.dumps(payload["spec"]))
    payload.update(
        count_claims=inspection["count_facts"], rationale="量化\n" * 7000, limitations=["x" * 23000]
    )
    assert obj.submit(task["child_id"], "revise", json.dumps(payload))["status"] == "accepted"
    receipt = obj.finish("root", task["child_id"], {"stopReason": "completed"})
    assert len(encoded(receipt)) < 5000
    view = obj.view("root")
    assert len(encoded(view)) <= obj.policy.max_tool_bytes
    assert "inline" not in view["head"]
    ref = view["head"]
    pages = [obj.read("root", ref["resource_id"], i) for i in range(ref["pages"])]
    assert all(len(encoded(p)) < obj.policy.max_tool_bytes for p in pages)
    assert json.loads("".join(p["text"] for p in pages)) == obj.scope("root")["head"]
    with pytest.raises(ValueError):
        obj.read("root", "source:../../secret", 0)
    with pytest.raises(ValueError):
        obj.read("root", ref["resource_id"], -1)


def test_worker_prompt_preloads_evidence_and_paging_exposes_inspection_receipts(tmp_path):
    obj = host(tmp_path, protocol="bounded-v2")
    finding = analyze(obj)
    task = obj.begin("root", "design", "Revise", [finding])
    proposed = revision(obj, finding)
    inspected = obj.inspect(task["child_id"], json.dumps(proposed["spec"]))
    proposed.update(
        count_claims=inspected["count_facts"], rationale="r" * 16000, limitations=["l" * 16000]
    )
    obj.submit(task["child_id"], "revise", json.dumps(proposed))
    obj.finish("root", task["child_id"], {"stopReason": "completed"})
    compact, worker = obj.view("root"), obj.view("root", worker=True)
    assert "inline" not in compact["head"]
    assert worker["head"]["inline"] == obj.scope("root")["head"]
    assert all("inline" in resource for resource in worker["sources"])
    assert len(encoded(compact)) <= 24000 and len(encoded(worker)) <= 65536
    resource = "event:" + inspected["inspection_id"]
    ref = next(r for r in worker["inspections"] if r["resource_id"] == resource)
    content = "".join(obj.read("root", resource, i)["text"] for i in range(ref["pages"]))
    receipt = json.loads(content)
    assert receipt["body"]["spec"] == proposed["spec"]
    assert receipt["body"]["summary"] == inspected["summary"]
    review = obj.begin("root", "review", "Review", [finding])
    assert json.loads(review["prompt"])["scope"]["head"]["inline"]["id"] == worker["head"]["id"]


@pytest.mark.parametrize(
    "text,valid",
    [
        ("59 observations minus 6 required trailing observations leaves 54.", False),
        ("59 observations minus 6 required trailing observations plus 1 yields 54.", True),
        ("59 - 6 = 54", False),
        ("59 - 6 + 1 = 54", True),
        ("59 - 5 = 54", True),
        ("The raw five-observation return is defined on every observed date.", False),
        ("The return is not defined on every observed date.", True),
        ("The return is defined on every observed date after the warmup.", True),
        ("There is a close on every observed date.", True),
        ("Only 56 of 57 eligible signals per symbol are executable.", False),
        ("56 signals are tradable.", False),
        ("56 signals have a next observed close; tradability is not established.", True),
        ("The factor expression is executable from six observed closes.", True),
    ],
)
def test_count_prose_counterexamples(text, valid):
    proof = prose_checks({"rationale": text}, {"symbol": {"warmup_exclusions": 5}})
    assert proof["recognized_prose_ok"] is valid


def test_count_claims_and_clean_review_cannot_ignore_known_false_prose(tmp_path):
    obj = host(tmp_path, protocol="bounded-v2")
    finding = analyze(obj)
    task = obj.begin("root", "design", "Propose", [finding])
    proposed = revision(obj, finding)
    result = obj.inspect(task["child_id"], json.dumps(proposed["spec"]))
    assert obj.submit(task["child_id"], "revise", json.dumps(proposed))["status"] == "rejected"
    proposed["count_claims"] = result["count_facts"]
    proposed["rationale"] = "59 - 6 = 54"
    assert obj.submit(task["child_id"], "revise", json.dumps(proposed))["status"] == "accepted"
    obj.finish("root", task["child_id"], {"stopReason": "completed"})
    task = obj.begin("root", "review", "Review", [finding])
    review = {
        "candidate_id": obj.scope("root")["head"]["id"],
        "verdict": "reviewed_with_limits",
        "checks": {
            k: "Read." for k in ("evidence_support", "spec_and_prose", "timing", "scope_and_limits")
        },
        "issues": [],
        "citations": proposed["citations"],
        "limitations": ["No alpha proof."],
    }
    result = obj.submit(task["child_id"], "review", json.dumps(review))
    assert result["status"] == "rejected" and "host count/prose" in result["error"]
    review.update(verdict="needs_revision", issues=["Correct the subtraction."])
    assert obj.submit(task["child_id"], "review", json.dumps(review))["status"] == "accepted"


def test_workspace_git_status_does_not_attribute_parent_edits(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    private = tmp_path / "private"
    base = isolated_workspace(private)
    work = base / "deepseek-harness/default-workspace"
    (tmp_path / "codex-change.txt").write_text("Outside native session.")
    assert subprocess.check_output(["git", "status", "--porcelain"], cwd=work) == b""
    assert isolated_workspace(private) == base
    (work / "agent-change.txt").write_text("Inside native session.")
    assert b"agent-change.txt" in subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=work
    )


@pytest.mark.parametrize("cited", [True, False])
def test_exploratory_hypothesis_can_motivate_change_but_needs_cited_peer_context(tmp_path, cited):
    obj = host(tmp_path, protocol="bounded-v2")
    task = obj.begin("root", "analyze", "Propose hypotheses", [])
    body = {
        "candidate_id": obj.scope("root")["head"]["id"],
        "topic": "interpretation",
        "statement": "A different trailing window is an untested research hypothesis.",
        "status": "hypothesis",
        "citations": [{"evidence_id": "prices", "quote": "Observed prices vary."}] if cited else [],
        "contradicts": [],
    }
    obj.submit(task["child_id"], "findings", json.dumps({"findings": [body]}))
    obj.finish("root", task["child_id"], {"stopReason": "completed"})
    finding = obj.scope("root")["findings"][0]["id"]
    task = obj.begin("root", "design", "Inspect motivated proposal", [finding])
    proposed = revision(obj, finding, spec(lookback=3))
    proposed["count_claims"] = obj.inspect(task["child_id"], json.dumps(proposed["spec"]))[
        "count_facts"
    ]
    result = obj.submit(task["child_id"], "revise", json.dumps(proposed))
    assert result["status"] == ("accepted" if cited else "rejected")
    if cited:
        assert result["artifact"]["body"]["peer_hypothesis_ids"] == [finding]
        assert result["artifact"]["body"]["adoption_scope"] == "exploratory_research_only"
