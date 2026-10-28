"""Frozen reference roles are not evidence of an assessed candidate's success.

Financial and replay evidence here is explicitly synthetic; persistence,
signatures and checker decisions are real. Mac pilot acceptance remains separate.
"""

from uuid import uuid4

import pytest
from qfr_core.delivery_rules import admission_hash, gate_hash
from qfr_eval.delivery.models import PilotDeliveryPolicy
from test_delivery_checker import (
    ROOT,
    SyntheticRegistry,
    artifact,
    changed,
    check,
    delivery_case,
    failed,
    reference,
)

pytestmark = pytest.mark.database


def freeze(case, scope):
    gate = changed(case.context.job.exit_gate, schema_version="2", assessment_scope=scope)
    gate = changed(gate, spec_hash=gate_hash(gate))
    brief = changed(case.context.brief, exit_gate=gate)
    job = changed(
        case.context.job,
        exit_gate=gate,
        payload_hash=admission_hash(case.context.input_bundle, brief),
    )
    case.context = changed(case.context, job=job, brief=brief)


def assessment_case(factory, root, *, candidate=None, baseline=None):
    case = delivery_case(factory, root, **(candidate or {}))
    original = delivery_case(
        factory,
        root,
        program=case.context.job.project_id,
        signer=case.signer,
        **({"insufficient": True, "overall": "insufficient_data", **(baseline or {})}),
    )
    reports = [*case.proposal.released_report_refs, *original.proposal.released_report_refs]
    note, note_bytes = artifact(case.context.job.project_id, [r.reference_id for r in reports])
    refs = [reference(case.factor), reference(original.factor)]
    case.registry = SyntheticRegistry(
        [
            case.registry.values[case.factor.manifest.artifact_version_id],
            original.registry.values[original.factor.manifest.artifact_version_id],
            (note, note_bytes),
        ]
    )
    case.proposal = changed(
        case.proposal,
        artifact_refs=[*refs, reference(note)],
        released_report_refs=reports,
        deliverables=[dict(name="research note", artifact=reference(note))],
    )
    case.context = changed(
        case.context,
        brief=changed(
            case.context.brief, baseline_artifact_ids=[r.artifact_version_id for r in refs]
        ),
        input_bundle=changed(
            case.context.input_bundle, baseline_refs=[r.artifact_version_id for r in refs]
        ),
    )
    freeze(
        case,
        dict(schema_version="1", assessed_artifact_refs=refs[:1], reference_artifact_refs=refs[1:]),
    )
    case.policy = PilotDeliveryPolicy.model_validate_json(
        (ROOT / "configs/delivery/pilot_research_delivery_v3.json").read_bytes()
    )
    case.original = original
    return case


def test_dlv_03_frozen_reference_self_comparison_is_not_candidate_inference(eval_connect, tmp_path):
    case = assessment_case(eval_connect, tmp_path)
    receipt = check(eval_connect, case)
    assert receipt.result == "pass"
    assert receipt.independent_checker == "pilot-research-delivery-v3"
    assert receipt.artifact_refs == case.proposal.artifact_refs
    assert receipt.released_report_refs == case.proposal.released_report_refs
    assert case.original.report.content.hurdle_flags.overall == "insufficient_data"
    assert case.verifier.delivery(receipt) == receipt
    assert receipt.gate_spec_hash == case.context.job.exit_gate.spec_hash
    # The same unchanged observations cannot be accepted as two assessed candidates.
    scope = case.context.job.exit_gate.assessment_scope
    freeze(
        case,
        changed(
            scope,
            assessed_artifact_refs=[*scope.assessed_artifact_refs, *scope.reference_artifact_refs],
            reference_artifact_refs=[],
        ),
    )
    assert {"measurement_quality", "conclusion_support"} <= failed(check(eval_connect, case))


@pytest.mark.parametrize(
    "candidate,check_id",
    [
        ({"insufficient": True}, "measurement_quality"),
        ({"overall": "insufficient_data"}, "conclusion_support"),
        ({"replay": False}, "reproduction"),
        ({"overall": "pass"}, "conclusion_support"),
    ],
)
def test_assessed_candidate_requirements_are_unchanged(eval_connect, tmp_path, candidate, check_id):
    case = assessment_case(eval_connect, tmp_path, candidate=candidate)
    assert check_id in failed(check(eval_connect, case))


@pytest.mark.parametrize(
    "baseline,check_id",
    [
        ({"replay": False}, "reproduction"),
        ({"measured_updates": {"status": "failed"}}, "measurement_quality"),
        ({"measured_updates": {"period_count": 0}}, "measurement_quality"),
        (
            {"measured_updates": {"hurdle": {"overall": "insufficient_data", "coverage": "fail"}}},
            "measurement_quality",
        ),
    ],
)
def test_reference_still_needs_real_complete_coverage_and_replay(
    eval_connect, tmp_path, baseline, check_id
):
    case = assessment_case(eval_connect, tmp_path, baseline=baseline)
    assert check_id in failed(check(eval_connect, case))


@pytest.mark.parametrize("issue", ["missing_report", "different_hash", "unscoped", "role_change"])
def test_frozen_roles_and_all_reference_evidence_are_required(eval_connect, tmp_path, issue):
    case = assessment_case(eval_connect, tmp_path)
    scope = case.context.job.exit_gate.assessment_scope
    if issue == "missing_report":
        case.proposal = changed(
            case.proposal, released_report_refs=case.proposal.released_report_refs[:1]
        )
    elif issue == "different_hash":
        freeze(
            case,
            changed(
                scope,
                reference_artifact_refs=[
                    changed(scope.reference_artifact_refs[0], content_hash="f" * 64)
                ],
            ),
        )
    elif issue == "unscoped":
        extra, data = artifact(case.context.job.project_id)
        case.registry.values[extra.manifest.artifact_version_id] = (extra, data)
        case.proposal = changed(
            case.proposal, artifact_refs=[*case.proposal.artifact_refs, reference(extra)]
        )
    else:
        changed_gate = changed(
            case.context.job.exit_gate,
            assessment_scope=changed(
                scope,
                assessed_artifact_refs=scope.reference_artifact_refs,
                reference_artifact_refs=scope.assessed_artifact_refs,
            ),
        )
        # A client cannot relabel evidence without changing the frozen admission.
        case.context = changed(
            case.context, brief=changed(case.context.brief, exit_gate=changed_gate)
        )
    assert check(eval_connect, case).result == "fail"


def test_reference_cannot_be_shortlisted_or_provide_positive_support(eval_connect, tmp_path):
    case = assessment_case(
        eval_connect, tmp_path, baseline={"insufficient": False, "overall": "pass"}
    )
    assert check(eval_connect, case).result == "pass"  # Negative is about assessed scope only.
    proposal = changed(
        case.proposal, conclusion="supported_positive", shortlist=[reference(case.original.factor)]
    )
    assert "conclusion_support" in failed(check(eval_connect, case, proposal=proposal))


@pytest.mark.parametrize("policy_version,gate_version", [(1, 2), (2, 2), (3, 1)])
def test_checker_never_relabels_legacy_gate_semantics(
    eval_connect, tmp_path, policy_version, gate_version
):
    case = (
        assessment_case(eval_connect, tmp_path)
        if gate_version == 2
        else delivery_case(eval_connect, tmp_path)
    )
    policy = PilotDeliveryPolicy.model_validate_json(
        (ROOT / f"configs/delivery/pilot_research_delivery_v{policy_version}.json").read_bytes()
    )
    with pytest.raises(ValueError, match="gate versions differ"):
        check(eval_connect, case, policy=policy, receipt_id=uuid4())
