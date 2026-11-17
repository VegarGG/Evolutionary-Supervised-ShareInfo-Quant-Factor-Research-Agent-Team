import json
from pathlib import Path

import pytest
import yaml
from test_case_factor import panel, spec

from qfh.budget import BudgetRefused, ProviderAdmission
from qfh.case_factor import definition
from qfh.case_research import STAGES, CaseEpisode, CasePolicy, CaseResearch
from qfh.coding_plan import CodingPolicy
from qfh.research import Research
from qfh.shared_state import atomic_new, digest

ROOT = Path(__file__).parents[1]


def host(tmp_path, variant="adaptive", **overrides):
    (tmp_path / "OFFLINE_ONLY").write_text("Synthetic fixture; no provider requests.")
    research = Research(ROOT / "configs/research-trial.yaml", tmp_path)
    research.ledger.set_provider_admission(
        ProviderAdmission(providers=["glm_coding"], authority="Offline case test only.")
    )
    route = CodingPolicy.model_validate(
        yaml.safe_load((ROOT / "configs/glm-coding-unseen-2026-11-16.yaml").read_text())
    )
    research.activate_model_route(route)
    episode = CaseEpisode(
        episode_id="offline-case",
        synthetic_evidence=True,
        actors={
            "supervisor": "supervisor",
            **{f"{role}-{i}": role for i in range(1, 7) for role in ("author", "reviewer")},
        },
        sources={"prices": "Observed prices vary. No future outcome evidence."},
        initial=definition(spec(), ["600000.XSHG"], "Unproven hypothesis."),
        initial_spec=spec(),
        symbols=["600000.XSHG"],
        rows=panel(),
        data_snapshot_sha256=digest(panel()),
        start="2026-01-01",
        end="2026-01-31",
        policy={"max_events": 100, "max_findings": 12, "max_versions": 4, "max_text_length": 24000},
    )
    policy = CasePolicy(
        package_id="offline-case",
        study_id="offline",
        variant=variant,
        authority="Offline test only.",
        question="Inspect and revise only if supported.",
        route_id=route.id,
        episode=episode,
        max_tasks=6,
        supervisor_requests=12,
        worker_requests=5,
        total_requests=32,
        max_output_tokens=16384,
        max_inspections=6,
    )
    policy = CasePolicy.model_validate({**policy.model_dump(), **overrides})
    path = tmp_path / "package.json"
    atomic_new(path, policy.model_dump())
    result = CaseResearch(ROOT / "configs/research-trial.yaml", tmp_path, path)
    result.admit("root")
    return result


def analyze(obj):
    task = obj.begin("root", "analyze", "Inspect source evidence", [])
    current = obj.board.snapshot("supervisor")["head"]["id"]
    finding = {
        "candidate_id": current,
        "topic": "normalization",
        "statement": "Prices vary.",
        "status": "supported",
        "citations": [{"evidence_id": "prices", "quote": "Observed prices vary."}],
        "contradicts": [],
    }
    result = obj.submit(task["child_id"], "findings", json.dumps({"findings": [finding]}))
    assert result["status"] == "accepted"
    obj.finish("root", task["child_id"], {"stopReason": "completed"})
    return obj.board.snapshot("supervisor")["findings"][0]["id"]


def revision(obj, finding, configured=None):
    return {
        "parent_id": obj.board.snapshot("supervisor")["head"]["id"],
        "spec": (configured or spec(lookback=3)).model_dump(),
        "hypothesis": "Three-observation hypothesis, unproven.",
        "rationale": "Observe a longer past window.",
        "decisions": [
            {"finding_id": finding, "disposition": "adopt", "reason": "Research hypothesis."}
        ],
        "citations": [{"evidence_id": "prices", "quote": "Observed prices vary."}],
        "limitations": ["No evidence of improved performance."],
        "basis_review_id": None,
        "issue_resolutions": [],
    }


def test_adaptive_revision_is_executable_versioned_and_no_replay(tmp_path):
    obj = host(tmp_path)
    finding = analyze(obj)
    with pytest.raises(ValueError, match="cite observed"):
        obj.begin("root", "design", "Revise", [])
    task = obj.begin("root", "design", "Revise from observed evidence", [finding])
    proposed = revision(obj, finding)
    assert obj.submit(task["child_id"], "revise", json.dumps(proposed))["status"] == "rejected"
    obj.inspect(task["child_id"], json.dumps(proposed["spec"]))
    assert obj.submit(task["child_id"], "revise", json.dumps(proposed))["status"] == "accepted"
    obj.finish("root", task["child_id"], {"stopReason": "completed"})
    current = obj.board.snapshot("supervisor")["head"]
    assert (
        current["body"]["change_kind"] == "factor"
        and current["body"]["changed_rows_from_parent"] > 0
    )
    assert current["body"]["peer_finding_ids"] == [finding]
    task = obj.begin("root", "review", "Review exact version", [finding])
    review = {
        "candidate_id": current["id"],
        "verdict": "reviewed_with_limits",
        "checks": {
            k: "Offline evidence inspected."
            for k in ("evidence_support", "spec_and_prose", "timing", "scope_and_limits")
        },
        "issues": [],
        "citations": proposed["citations"],
        "limitations": ["No performance conclusion."],
    }
    result = obj.submit(task["child_id"], "review", json.dumps(review))
    obj.finish("root", task["child_id"], {"stopReason": "completed"})
    obj.finalize("root", current["id"], result["artifact"]["id"])
    assert obj.board.snapshot("supervisor")["finalized"]["body"]["substantive_change"]
    with pytest.raises(BudgetRefused):
        obj.admit("another-root")
    with pytest.raises(ValueError, match="finalized"):
        obj.inspect("root", json.dumps(proposed["spec"]))


def test_fixed_assignment_cannot_adapt_and_retained_candidate_is_not_factor_change(tmp_path):
    obj = host(tmp_path, "fixed")
    finding = analyze(obj)
    with pytest.raises(ValueError, match="fixed workflow"):
        obj.begin("root", "analyze", "Extra task", [])
    task = obj.begin("root", "design", "Ignore data and do something else", [])
    assert task["assignment"] == STAGES["design"]
    proposed = revision(obj, finding, spec())
    obj.inspect(task["child_id"], json.dumps(proposed["spec"]))
    result = obj.submit(task["child_id"], "revise", json.dumps(proposed))
    assert result["artifact"]["body"]["change_kind"] == "explanation_or_retained"
    with pytest.raises(ValueError, match="already submitted"):
        obj.submit(task["child_id"], "revise", json.dumps(proposed))


def test_wrong_roles_and_synthetic_live_package_are_refused(tmp_path):
    obj = host(tmp_path)
    with pytest.raises(ValueError, match="assigned native stage"):
        obj.submit("root", "revise", "{}")
    (tmp_path / "OFFLINE_ONLY").unlink()
    with pytest.raises(ValueError, match="offline-only"):
        CaseResearch(ROOT / "configs/research-trial.yaml", tmp_path, tmp_path / "package.json")


def test_failed_native_task_cannot_be_replayed(tmp_path):
    obj = host(tmp_path)
    task = obj.begin("root", "analyze", "Inspect sources", [])
    obj.finish("root", task["child_id"], {"stopReason": "error"})
    with pytest.raises(ValueError, match="failed native task"):
        obj.begin("root", "analyze", "Retry", [])


def test_explicit_32k_package_preserves_other_bounds_and_rejects_larger_cap(tmp_path):
    original = host(tmp_path).policy
    value = {**original.model_dump(), "max_output_tokens": 32768}
    expanded = CasePolicy.model_validate(value)
    assert expanded.total_requests == original.total_requests == 32
    assert expanded.episode == original.episode
    with pytest.raises(ValueError, match="32768"):
        CasePolicy.model_validate({**value, "max_output_tokens": 32769})


def test_independent_calculator_detects_corrupted_result(tmp_path):
    from qfh.case_audit import audit

    obj = host(tmp_path)
    for chosen in [
        spec(lookback=3),
        spec(normalization="realized_volatility", volatility_window=5),
    ]:
        obj.inspect("root", chosen.model_dump_json())
    assert audit(obj.directory)["status"] == "pass"
    path = next(obj.directory.glob("calculation-*.json"))
    corrupted = json.loads(path.read_bytes())
    next(r for r in corrupted["rows"] if r["score"] is not None)["score"] += 1
    path.write_text(json.dumps(corrupted))
    with pytest.raises(AssertionError):
        audit(obj.directory)
