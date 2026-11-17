import copy
import json

import pytest
from test_case_factor import spec
from test_case_research import analyze, host

from qfh.case_audit import audit
from qfh.case_contract import encoded
from qfh.case_report import CHECKS, StructuredRevision, argument_issues, facts
from qfh.shared_state import digest


def proposed(obj, finding, *, retained=False):
    task = obj.begin("root", "design", "Inspect and propose", [finding])
    chosen = spec() if retained else spec(lookback=3)
    inspection = obj.inspect(task["child_id"], chosen.model_dump_json())
    body = {
        "parent_id": obj.scope("root")["head"]["id"],
        "inspection_id": inspection["inspection_id"],
        "facts_sha256": inspection["facts_sha256"],
        "hypothesis": {"text": "A longer window might capture persistence.", "fact_refs": ["spec"]},
        "rationale": {
            "text": "Explore persistence; benefit remains unproven.",
            "fact_refs": ["scope"],
        },
        "decisions": [
            {"finding_id": finding, "disposition": "adopt", "reason": "Explore the observation."}
        ],
        "citations": [{"evidence_id": "prices", "quote": "Observed prices vary."}],
        "basis_review_id": None,
        "issue_resolutions": [],
    }
    return task, body, inspection


def designed(obj, finding, **kwargs):
    task, body, inspection = proposed(obj, finding, **kwargs)
    result = obj.submit(task["child_id"], "revise", json.dumps(body))
    assert result["status"] == "accepted", result
    obj.finish("root", task["child_id"], {"stopReason": "completed"})
    return body, inspection


def review_payload(obj, body):
    report = obj.scope("root")["structured_report"]
    return {
        "candidate_id": report["body"]["candidate_id"],
        "report_sha256": report["sha256"],
        "verdict": "reviewed_with_limits",
        "checks": dict.fromkeys(CHECKS, "consistent"),
        "issues": [],
        "citations": body["citations"],
    }


@pytest.mark.parametrize("retained", [True, False])
def test_final_report_is_pinned_and_rendered_from_host_facts(tmp_path, retained):
    obj = host(tmp_path, protocol="structured-v3")
    finding = analyze(obj)
    body, inspection = designed(obj, finding, retained=retained)
    scope = obj.scope("root")
    report = scope["structured_report"]
    assert report["sha256"] == digest(report["body"])
    assert report["body"]["facts"] == inspection["facts"]
    assert report["body"]["facts"]["units"]["raw_return"] == "dimensionless"
    assert report["body"]["facts"]["units"]["normalized_return"] == "dimensionless"
    assert report["body"]["facts"]["timing"]["tradability"] == "not_established"
    assert report["body"]["calculation_provenance"]["requested_by"] == "author-2"
    task = obj.begin("root", "review", "Review whole report", [finding])
    view = json.loads(task["prompt"])["scope"]
    assert view["structured_report"]["inline"] == report
    review = obj.submit(task["child_id"], "review", json.dumps(review_payload(obj, body)))
    assert review["status"] == "accepted", review
    obj.finish("root", task["child_id"], {"stopReason": "completed"})
    receipt = obj.finalize("root", scope["head"]["id"], review["artifact"]["id"])
    assert len(encoded(receipt)) < obj.policy.max_tool_bytes
    assert "both dimensionless" in receipt["report_text"]
    assert "team totals belong in the post-run audit" in receipt["report_text"]
    assert "requested by author-2" in receipt["report_text"]
    assert json.loads((obj.directory / "FINAL_REPORT.json").read_bytes()) == report
    assert receipt["finalized"]["body"]["substantive_change"] is not retained
    audited = audit(obj.directory)
    assert audited["structured_report"]["status"] == "pass"
    assert (
        audited["calculations"][0]["changed_rows_from_initial"]
        == report["body"]["facts"]["changed_rows_from_initial"]
    )
    corrupted = copy.deepcopy(report)
    key = next(k for k in corrupted["body"]["facts"]["metrics"] if k.endswith("mean_score"))
    corrupted["body"]["facts"]["metrics"][key]["value"] += 1e-14
    (obj.directory / "FINAL_REPORT.json").write_text(json.dumps(corrupted))
    with pytest.raises(AssertionError):
        audit(obj.directory)


@pytest.mark.parametrize(
    "mutation", ["facts", "inspection", "metric", "unit", "tradability", "reference"]
)
def test_recorded_semantic_failures_and_forged_bindings_are_rejected(tmp_path, mutation):
    obj = host(tmp_path, protocol="structured-v3")
    finding = analyze(obj)
    task, body, _ = proposed(obj, finding)
    if mutation == "facts":
        body["facts_sha256"] = "f" * 64
    elif mutation == "inspection":
        body["inspection_id"] = "f" * 64
    elif mutation == "metric":
        body["rationale"]["text"] = "Mean score is -0.40783855957395996."
    elif mutation == "unit":
        body["rationale"]["text"] = "The scores are now dimensionless."
    elif mutation == "tradability":
        body["rationale"]["text"] = "All eligible signals are executable."
    else:
        body["rationale"]["fact_refs"] = ["imaginary_metric"]
    result = obj.submit(task["child_id"], "revise", json.dumps(body))
    assert result["status"] == "rejected"
    assert obj.scope("root")["head"]["kind"] == "initial_candidate"


def test_review_cannot_retype_metrics_or_bind_stale_report(tmp_path):
    obj = host(tmp_path, protocol="structured-v3")
    finding = analyze(obj)
    body, _ = designed(obj, finding)
    task = obj.begin("root", "review", "Review", [finding])
    payload = review_payload(obj, body)
    bad = copy.deepcopy(payload)
    bad["checks"]["timing"] = "56 of 57 signals are executable."
    assert obj.submit(task["child_id"], "review", json.dumps(bad))["status"] == "rejected"
    bad = {**payload, "report_sha256": "f" * 64}
    assert obj.submit(task["child_id"], "review", json.dumps(bad))["status"] == "rejected"
    assert not obj.scope("root")["reviews"]
    assert obj.submit(task["child_id"], "review", json.dumps(payload))["status"] == "accepted"


def test_negative_evidence_and_qualitative_research_are_not_blocked(tmp_path):
    obj = host(tmp_path, protocol="structured-v3")
    finding = analyze(obj)
    _, body, inspection = proposed(obj, finding)
    body["rationale"]["text"] = (
        "Signals are not necessarily tradable. Both returns are dimensionless."
    )
    assert not argument_issues(StructuredRevision.model_validate(body), inspection["facts"])
    pinned = facts(obj.board.episode, obj.board.calculation(spec()))
    assert all(v["unit"] in ("dimensionless", "count") for v in pinned["metrics"].values())


def test_report_hash_covers_qualitative_reasoning_and_decisions(tmp_path):
    obj = host(tmp_path, protocol="structured-v3")
    finding = analyze(obj)
    designed(obj, finding)
    scope = obj.scope("root")
    report = scope["structured_report"]
    changed = copy.deepcopy(report["body"])
    changed["model_proposal"]["decisions"][0]["reason"] = "Different interpretation."
    assert digest(changed) != report["sha256"]


@pytest.mark.parametrize("field", ["rationale", "decision"])
def test_ambiguous_live_dispersion_claim_requires_a_named_measure(tmp_path, field):
    obj = host(tmp_path, protocol="structured-v3")
    finding = analyze(obj)
    task, body, _ = proposed(obj, finding)
    if field == "rationale":
        body["rationale"]["text"] = (
            "Score dispersion across the names remains about as wide, its ordering inverts."
        )
    else:
        body["decisions"][0]["reason"] = (
            "Cross-name score spread stays as wide with inverted ordering."
        )
    result = obj.submit(task["child_id"], "revise", json.dumps(body))
    assert result["status"] == "rejected" and "comparison measure" in result["error"]
    assert obj.scope("root")["head"]["kind"] == "initial_candidate"
    # Removing the unsupported comparison permits the same computation, rather
    # than forcing a factor change or rewriting the model's research decision.
    if field == "rationale":
        body["rationale"]["text"] = "The inspected alternative remains exploratory."
    else:
        body["decisions"][0]["reason"] = "Explore the observed difference without superiority."
    assert obj.submit(task["child_id"], "revise", json.dumps(body))["status"] == "accepted"


def test_named_dispersion_comparison_still_requires_independent_review(tmp_path):
    obj = host(tmp_path, protocol="structured-v3")
    finding = analyze(obj)
    _, body, inspection = proposed(obj, finding)
    body["rationale"]["text"] = (
        "Using the ratio of maximum to minimum SD, dispersion remains about as wide."
    )
    # A named measure removes this ambiguity; it does not prove the comparison.
    assert not argument_issues(StructuredRevision.model_validate(body), inspection["facts"])


def test_live_unit_heterogeneity_heading_rejected_before_finding_acceptance(tmp_path):
    obj = host(tmp_path, protocol="structured-v3")
    task = obj.begin("root", "analyze", "Inspect units", [])
    finding = {
        "candidate_id": obj.scope("root")["head"]["id"],
        "topic": "units",
        "status": "supported",
        "statement": "Units and scale are heterogeneous across the fixed universe.",
        "citations": [{"evidence_id": "prices", "quote": "Observed prices vary."}],
        "contradicts": [],
    }
    result = obj.submit(task["child_id"], "findings", json.dumps({"findings": [finding]}))
    assert result["status"] == "rejected" and "not their units" in result["error"]
    assert not obj.scope("root")["findings"]
    finding["statement"] = (
        "Close units are shared and returns are dimensionless; observed magnitudes vary."
    )
    assert (
        obj.submit(task["child_id"], "findings", json.dumps({"findings": [finding]}))["status"]
        == "accepted"
    )


@pytest.mark.parametrize("field", ["spec_sha256", "changed_rows_from_initial"])
def test_independent_audit_rejects_consistently_hashed_report_builder_error(
    tmp_path, monkeypatch, field
):
    import qfh.case_report as reports
    import qfh.case_research as cases

    correct = reports.facts

    def buggy_facts(*args):
        value = correct(*args)
        value[field] = "f" * 64 if field == "spec_sha256" else 999
        return value

    # Simulate a builder error shared by inspection facts and report rendering.
    # All report/review hashes remain consistent, so identity checks alone pass.
    monkeypatch.setattr(reports, "facts", buggy_facts)
    monkeypatch.setattr(cases, "facts", buggy_facts)
    obj = host(tmp_path, protocol="structured-v3")
    finding = analyze(obj)
    body, _ = designed(obj, finding)
    task = obj.begin("root", "review", "Review", [finding])
    result = obj.submit(task["child_id"], "review", json.dumps(review_payload(obj, body)))
    assert result["status"] == "accepted"
    obj.finish("root", task["child_id"], {"stopReason": "completed"})
    obj.finalize("root", obj.scope("root")["head"]["id"], result["artifact"]["id"])
    with pytest.raises(AssertionError):
        audit(obj.directory)
