import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from test_final_output import correction, episode, rejection

from qfh.adaptive_research import AdaptivePolicy, AdaptiveResearch
from qfh.budget import BudgetRefused, ProviderAdmission, Usage
from qfh.coding_plan import CodingLedger, CodingPolicy
from qfh.final_output import UnitClaims, unit_proof
from qfh.research import Research
from qfh.shared_state import atomic_new

ROOT = Path(__file__).parents[1]


def host(tmp_path, source_episode=None):
    config = ROOT / "configs/research-trial.yaml"
    research = Research(config, tmp_path)
    research.ledger.set_provider_admission(
        ProviderAdmission(
            providers=["glm_coding"],
            authority="Offline adaptive test fixture; no real provider requests.",
        )
    )
    raw = yaml.safe_load((ROOT / "configs/glm-coding-modular-2026-11-13.yaml").read_text())
    raw["starts_at"] = "2000-01-01T00:00:00Z"
    research.activate_model_route(CodingPolicy.model_validate(raw))
    policy = AdaptivePolicy(
        package_id="offline-adaptive",
        authority="Offline regression only.",
        episode=source_episode or episode(),
        route_id=raw["id"],
        max_tasks=3,
        supervisor_requests=6,
        worker_requests=4,
        total_requests=15,
    )
    package = tmp_path / "package.json"
    atomic_new(package, policy.model_dump())
    return AdaptiveResearch(config, tmp_path, package)


def test_native_task_followups_review_identity_and_no_replay(tmp_path):
    obj = host(tmp_path)
    obj.admit("root")
    assert "review_schema" not in obj.scope("root")
    assert "amendment_schema" not in obj.scope("root")
    with pytest.raises(BudgetRefused, match="one native supervisor"):
        obj.admit("other-root")
    with pytest.raises(ValueError, match="first task"):
        obj.begin("root", "author", "Fix things")
    first = obj.begin("root", "reviewer", "Review all explanations")
    assert "review_schema" in obj.scope(first["child_id"])
    assert "amendment_schema" not in obj.scope(first["child_id"])
    with pytest.raises(ValueError, match="active native task"):
        obj.begin("root", "reviewer", "Duplicate")
    with pytest.raises(ValueError, match="only the supervisor"):
        obj.begin(first["child_id"], "author", "Delegate")
    review = obj.submit(first["child_id"], "review", rejection(obj.board).model_dump_json())[
        "artifact"
    ]
    obj.finish("root", first["child_id"], {"stopReason": "completed", "output": []})
    with pytest.raises(BudgetRefused, match="finished"):
        obj.admit(first["child_id"])
    with pytest.raises(ValueError, match="already settled"):
        obj.finish("root", first["child_id"], {"stopReason": "completed"})
    with pytest.raises(ValueError, match="latest observed"):
        obj.begin("root", "author", "Fix", "0" * 64)
    second = obj.begin("root", "author", "Correct explanation", review["id"])
    assert "amendment_schema" in obj.scope(second["child_id"])
    assert "review_schema" not in obj.scope(second["child_id"])
    assert (
        obj.submit(second["child_id"], "amend", correction(obj.board, review).model_dump_json())[
            "status"
        ]
        == "accepted"
    )
    obj.finish("root", second["child_id"], {"stopReason": "completed"})
    with pytest.raises(ValueError, match="clean independent"):
        obj.finalize("root", obj.board.snapshot("supervisor")["head"]["id"], review["id"])
    third = obj.begin("root", "reviewer", "Review amended output", review["id"])
    clean = rejection(obj.board).model_copy(
        update={"verdict": "reviewed_with_limits", "issues": []}
    )
    final_review = obj.submit(third["child_id"], "review", clean.model_dump_json())["artifact"]
    obj.finish("root", third["child_id"], {"stopReason": "completed"})
    result = obj.finalize("root", clean.output_id, final_review["id"])
    assert result["finalized"]["body"]["evaluation_or_publication"] is False
    # One final native response is required after the tool result. No later turn can replay.
    step = obj.admit("root")
    ledger = CodingLedger(obj.research.ledger, obj.route)
    ledger.reserve("final-ack", step, datetime.now(UTC), output_tokens=128)
    ledger.settle(
        "final-ack",
        Usage(input_uncached=10, input_cached=0, input_cache_write=0, output=2),
        metadata={"cache_tokens_reported": True},
    )
    with pytest.raises(BudgetRefused, match="acknowledgment allowance"):
        obj.admit("root")
    snapshot = obj.board.snapshot("supervisor")
    assert len([x for x in snapshot["tasks"] if x["kind"] == "task_started"]) == 3
    assert snapshot["reviews"][0]["body"]["verdict"] == "needs_revision"
    assert len(obj.research.ledger.snapshot()["calls"]) == 1


def test_bad_submission_is_retained_and_can_be_repaired_in_same_native_task(tmp_path):
    obj = host(tmp_path)
    obj.admit("root")
    first = obj.begin("root", "reviewer", "Review")
    bad = rejection(obj.board).model_dump()
    bad["issues"][0]["quote"] = "invented quote"
    assert obj.submit(first["child_id"], "review", json.dumps(bad))["status"] == "rejected"
    assert (
        obj.submit(first["child_id"], "review", rejection(obj.board).model_dump_json())["status"]
        == "accepted"
    )
    with obj.board.locked() as events:
        assert any(
            x["kind"] == "submission_rejected" and "invented quote" in x["body"]["payload"]
            for x in events
        )
    with pytest.raises(ValueError, match="already submitted"):
        obj.submit(first["child_id"], "review", rejection(obj.board).model_dump_json())


def test_clean_initial_output_skips_author_followup(tmp_path):
    initial = episode()
    claims = UnitClaims.model_validate(
        unit_proof(initial.initial_output, initial.units)["expected_claims"]
    )
    initial = initial.model_copy(
        update={
            "initial_output": initial.initial_output.model_copy(
                update={
                    "rationale": "Raw magnitude is 10000 times target magnitude.",
                    "unit_claims": claims,
                }
            )
        }
    )
    obj = host(tmp_path, initial)
    obj.admit("root")
    task = obj.begin("root", "reviewer", "Review completed output")
    clean = rejection(obj.board).model_copy(
        update={"verdict": "reviewed_with_limits", "issues": []}
    )
    review = obj.submit(task["child_id"], "review", clean.model_dump_json())["artifact"]
    obj.finish("root", task["child_id"], {"stopReason": "completed"})
    with pytest.raises(ValueError, match="unresolved review"):
        obj.begin("root", "author", "Unnecessary rewrite", review["id"])
    obj.finalize("root", clean.output_id, review["id"])
    assert len(obj.board.snapshot("supervisor")["tasks"]) == 2  # One start and one finish.
