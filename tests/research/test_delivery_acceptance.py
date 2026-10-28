"""Research completion boundary, with explicit synthetic evidence and real signatures.

These tests do not establish financial acceptance. The independent checker and
the real Mac pilot flow supply that separate evidence.
"""

import hashlib
import json
import secrets
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from qfr_core.access import ServicePrincipal
from qfr_core.contracts.artifacts import ArtifactDefinition, ArtifactReference
from qfr_core.contracts.delivery import DeliveryProposal, DeliveryReceipt
from qfr_core.contracts.enums import JobState
from qfr_core.contracts.publication import PublishedArtifact
from qfr_core.contracts.reports import PublicProtocolCard, ReleasedReport
from qfr_core.contracts.research import (
    DeliveryProposalRequest,
    DeliveryReceiptRequest,
    HumanCheckpointAnswer,
    HumanCheckpointRequest,
)
from qfr_core.delivery_rules import content_sha256, gate_hash, job_config_hash
from qfr_core.signatures import SignatureRejected
from qfr_eval.signing import EvaluatorSigner
from qfr_research.api.deliveries import Deliveries
from qfr_research.api.errors import InvalidResearchRequest, ResearchConflict
from test_research_jobs import ROOT, SyntheticPublicEvidence, changed, control, setup_service

pytestmark = pytest.mark.database
SYNTHETIC_PAYLOAD = b'{"synthetic_fixture":true}'


def sample(name):
    return json.loads((ROOT / f"contracts/examples/{name}.valid.json").read_text())


def synthetic_artifact(program, report_id=None):
    value = sample("PublishedArtifact")
    manifest = value["manifest"]
    manifest["artifact_version_id"] = str(uuid4())
    manifest["provenance"]["program_id"] = str(program)
    manifest["payload_files"][0]["sha256"] = hashlib.sha256(SYNTHETIC_PAYLOAD).hexdigest()
    if report_id:
        manifest.update(
            kind="research_note",
            implementation=dict(type="document", asset_id="asset-example", format="markdown"),
            payload=dict(
                kind="research_note",
                document_asset_id="asset-example",
                citation_refs=[],
                released_report_refs=[report_id],
            ),
        )
    definition = {
        k: v
        for k, v in manifest.items()
        if k in ArtifactDefinition.model_fields and k != "family_id"
    }
    manifest["content_hash"] = value["payload_digest"] = content_sha256(
        dict(
            hash_spec="qfr-publication/1",
            profile=value["profile"],
            dsl_policy_hash=value["dsl_policy_hash"],
            manifest=definition,
        )
    )
    return PublishedArtifact.model_validate(value)


def reference(artifact):
    return ArtifactReference(
        artifact_version_id=artifact.manifest.artifact_version_id,
        content_hash=artifact.manifest.content_hash,
    )


class SyntheticSignedEvidence(SyntheticPublicEvidence):
    def __init__(self, program, dataset):
        self.program = program
        self.signer = EvaluatorSigner(
            secrets.token_bytes(32), purposes=["released_report", "delivery_receipt"]
        )
        self.verifier = self.signer.verifier(maximum_document_bytes=1048576)
        self.factor = synthetic_artifact(program)
        body = sample("ReleasedReport")
        body.pop("signature")
        body.update(
            program_id=str(program),
            report_id=str(uuid4()),
            protocol_card_ref="synthetic-protocol:1",
        )
        body["identity"].update(
            artifact_version_id=self.factor.manifest.artifact_version_id,
            content_hash=self.factor.manifest.content_hash,
            dataset_version_id=dataset,
            protocol_version="synthetic-protocol:1",
        )
        body["content"].update(not_for_selection=False, quality_flags=[])
        body["content"]["hurdle_flags"] = {k: "pass" for k in body["content"]["hurdle_flags"]}
        body["content"]["hurdle_flags"].update(overall="fail", net_result="fail")
        body["content"]["scalar"].update(
            origin_artifact_version_id=self.factor.manifest.artifact_version_id,
            measurement=dict(value=0.1, missing_reason=None),
            period_count=100,
        )
        self.signed_report = self.signer.seal(ReleasedReport, "released_report", body)
        self.note = synthetic_artifact(program, self.signed_report.report_id)
        self.card = PublicProtocolCard.model_validate(
            {**sample("PublicProtocolCard"), "protocol_version": "synthetic-protocol:1"}
        )
        self.receipt_value = None

    def artifact(self, program, ref):
        assert program == self.program
        result = next(
            v
            for v in [self.factor, self.note]
            if v.manifest.artifact_version_id == ref.artifact_version_id
        )
        assert result.manifest.content_hash == ref.content_hash
        return result

    def report(self, program, identity):
        assert program == self.program and str(identity) == self.signed_report.report_id
        return self.verifier.report(self.signed_report)

    def payload(self, program, artifact, asset_id):
        assert program == self.program and asset_id == "asset-example"
        return SYNTHETIC_PAYLOAD

    def protocol_card(self, program, ref):
        assert program == self.program and ref == "synthetic-protocol:1"
        return self.card

    def receipt(self, program, identity):
        assert program == self.program and str(identity) == self.receipt_value.receipt_id
        return self.verifier.delivery(self.receipt_value)


def delivery_setup(
    research_connect, tmp_path, *, human=False, assessment=False, service_class=Deliveries
):
    case = setup_service(research_connect, tmp_path, service_class=service_class)
    evidence = SyntheticSignedEvidence(case.program, case.registration.dataset_version_id)
    case.service.evidence = evidence
    if human or assessment:
        gate = changed(case.admission.brief.exit_gate, human_signoff_required=human)
        if assessment:
            gate = changed(
                gate,
                schema_version="2",
                assessment_scope=dict(
                    schema_version="1",
                    assessed_artifact_refs=[reference(evidence.factor)],
                    reference_artifact_refs=[],
                ),
            )
            policy = type(case.service.policy).model_validate_json(
                (ROOT / "configs/research/api_v2.json").read_bytes()
            )
            case.service.storage.policy = policy
            case.service.policy = policy
        gate = changed(gate, spec_hash=gate_hash(gate))
        case.admission = changed(
            case.admission,
            brief=changed(
                case.admission.brief,
                exit_gate=gate,
                frozen_config_hash=job_config_hash(case.admission.input_bundle),
            ),
        )
    status = case.service.admit(case.principal, case.program, case.admission, uuid4())
    running = control(case, status, "start")
    proposal = DeliveryProposal(
        schema_version="1",
        proposal_id=str(uuid4()),
        job_id=status.job.job_id,
        conclusion="supported_negative",
        artifact_refs=[reference(evidence.factor), reference(evidence.note)],
        released_report_refs=[
            dict(
                reference_id=evidence.signed_report.report_id,
                sha256=content_sha256(evidence.signed_report.model_dump(mode="json")),
            )
        ],
        deliverables=[dict(name="research note", artifact=reference(evidence.note))],
        shortlist=[],
    )
    status = case.service.propose_delivery(
        case.principal,
        UUID(status.job.job_id),
        DeliveryProposalRequest(
            operation_key="proposal", expected_revision=running.revision, proposal=proposal
        ),
        uuid4(),
    )
    return SimpleNamespace(**vars(case), status=status, proposal=proposal, evidence=evidence)


def seal_receipt(case, **updates):
    candidate = case.service.delivery_candidate(
        case.principal, UUID(case.status.job.job_id), UUID(case.proposal.proposal_id)
    )
    job, brief, proposal = candidate.context.job, candidate.context.brief, candidate.proposal
    checker = (
        "pilot-research-delivery-v3"
        if job.exit_gate.schema_version == "2"
        else "pilot-research-delivery-v2"
    )
    config = {
        "input-bundle:" + candidate.context.input_bundle.bundle_id: content_sha256(
            candidate.context.input_bundle.model_dump(mode="json")
        ),
        "admission:" + job.job_id: job.payload_hash,
        "job-config:" + job.job_id: job.config_hash,
        "brief:" + brief.brief_id: content_sha256(brief.model_dump(mode="json")),
        "proposal:" + proposal.proposal_id: content_sha256(proposal.model_dump(mode="json")),
        checker: case.service.policy.trusted_delivery_checkers[checker],
    }
    common = [
        dict(
            reference_id="proposal:" + proposal.proposal_id,
            sha256=content_sha256(proposal.model_dump(mode="json")),
        )
    ]
    body = dict(
        schema_version="1",
        receipt_id=str(uuid4()),
        job_id=job.job_id,
        gate_spec_hash=job.exit_gate.spec_hash,
        artifact_refs=[r.model_dump(mode="json") for r in proposal.artifact_refs],
        dataset_refs=[
            dict(
                reference_id=case.registration.dataset_version_id,
                sha256=case.registration.dataset_version_id,
            )
        ],
        protocol_refs=[
            dict(
                reference_id="synthetic-protocol:1",
                sha256=content_sha256(case.evidence.card.model_dump(mode="json")),
            )
        ],
        config_refs=[dict(reference_id=k, sha256=v) for k, v in config.items()],
        released_report_refs=[r.model_dump(mode="json") for r in proposal.released_report_refs],
        checks=[
            dict(
                check_id=name,
                schema_ref="synthetic-binding-test",
                result="pass",
                evidence_refs=common,
            )
            for name in job.exit_gate.required_checks
        ],
        allowed_conclusions=[c.value for c in job.exit_gate.allowed_conclusions],
        conclusion=proposal.conclusion.value,
        result="pass",
        independent_checker=checker,
        human_signoff_ref=candidate.context.human_approval.approval_id
        if candidate.context.human_approval
        else None,
        created_at=datetime.now(UTC).isoformat(),
    )
    body.update(updates)
    case.evidence.receipt_value = case.evidence.signer.seal(
        DeliveryReceipt, "delivery_receipt", body
    )
    return case.evidence.receipt_value


def test_frozen_assessment_is_verified_at_admission_and_survives_restart(
    research_connect, tmp_path
):
    case = delivery_setup(research_connect, tmp_path, assessment=True)
    original = case.status.job
    restarted = Deliveries(case.service.storage, case.evidence, case.service.research_root)
    actual = restarted.get_job(case.principal, UUID(original.job_id))
    assert actual.job.exit_gate == original.exit_gate
    assert actual.job.payload_hash == original.payload_hash
    assert actual.job.exit_gate.assessment_scope.assessed_artifact_refs == [
        reference(case.evidence.factor)
    ]
    # Reusing admission identity with changed role/hash cannot replace the original.
    gate = changed(
        case.admission.brief.exit_gate,
        assessment_scope=dict(
            schema_version="1",
            assessed_artifact_refs=[reference(case.evidence.note)],
            reference_artifact_refs=[],
        ),
    )
    gate = changed(gate, spec_hash=gate_hash(gate))
    changed_admission = changed(case.admission, brief=changed(case.admission.brief, exit_gate=gate))
    with pytest.raises(ResearchConflict):
        restarted.admit(case.principal, case.program, changed_admission, uuid4())
    fresh = changed(changed_admission, idempotency_key=str(uuid4()))
    with pytest.raises(InvalidResearchRequest, match="requires executables"):
        restarted.admit(case.principal, case.program, fresh, uuid4())


def test_matching_signature_cannot_relabel_checker_semantics(research_connect, tmp_path):
    case = delivery_setup(research_connect, tmp_path, assessment=True)
    receipt = seal_receipt(case)
    refs = [
        {
            "reference_id": "pilot-research-delivery-v2",
            "sha256": case.service.policy.trusted_delivery_checkers["pilot-research-delivery-v2"],
        }
        if ref.reference_id == "pilot-research-delivery-v3"
        else ref.model_dump()
        for ref in receipt.config_refs
    ]
    seal_receipt(case, independent_checker="pilot-research-delivery-v2", config_refs=refs)
    with pytest.raises(InvalidResearchRequest, match="frozen job"):
        accept(case)


def accept(case, *, key="accept"):
    request = DeliveryReceiptRequest(
        operation_key=key,
        expected_revision=case.status.revision,
        receipt_id=UUID(case.evidence.receipt_value.receipt_id),
        proposal_id=UUID(case.proposal.proposal_id),
    )
    return case.service.accept_receipt(
        case.principal, UUID(case.status.job.job_id), request, uuid4()
    )


def test_only_independent_exact_signed_receipt_completes_job(research_connect, tmp_path):
    case = delivery_setup(research_connect, tmp_path)
    assert case.status.job.state == JobState.VALIDATING_DELIVERY and case.status.job.receipt is None
    seal_receipt(case)
    accepted = accept(case)
    assert accepted.job.state == JobState.COMPLETED and accepted.job.receipt.signature_verified
    assert accept(case) == accepted
    with research_connect() as conn:
        assert conn.execute(
            "SELECT count(*) FROM research.delivery_refs WHERE program_id=%s", [case.program]
        ).fetchone() == (1,)
        assert conn.execute(
            "SELECT state FROM research.jobs WHERE program_id=%s", [case.program]
        ).fetchall() == [("cancelled",)]


@pytest.mark.parametrize(
    "issue",
    [
        "signature",
        "job",
        "gate",
        "config",
        "checks",
        "artifacts",
        "dataset",
        "reports",
        "protocol",
        "checker",
    ],
)
def test_signed_wrong_or_tampered_evidence_never_completes(research_connect, tmp_path, issue):
    case = delivery_setup(research_connect, tmp_path)
    receipt = seal_receipt(case)
    body = receipt.model_dump(mode="json", exclude={"signature"})
    if issue == "signature":
        case.evidence.receipt_value = changed(receipt, job_id=str(uuid4()))
    else:
        change = {
            "job": {"job_id": str(uuid4())},
            "gate": {"gate_spec_hash": "a" * 64},
            "config": {"config_refs": receipt.config_refs[:-1]},
            "checks": {"checks": receipt.checks[:-1]},
            "artifacts": {"artifact_refs": []},
            "dataset": {"dataset_refs": []},
            "reports": {"released_report_refs": []},
            "protocol": {"protocol_refs": []},
            "checker": {"independent_checker": "research-self-approval"},
        }[issue]
        case.evidence.receipt_value = case.evidence.signer.seal(
            DeliveryReceipt, "delivery_receipt", {**body, **change}
        )
    with pytest.raises((InvalidResearchRequest, SignatureRejected)):
        accept(case)
    actual = case.service.get_job(case.principal, UUID(case.status.job.job_id))
    assert actual.job.state == JobState.VALIDATING_DELIVERY and actual.job.receipt is None


def test_failed_receipt_remains_failed_and_old_proposal_cannot_finish(research_connect, tmp_path):
    case = delivery_setup(research_connect, tmp_path)
    receipt = seal_receipt(case)
    checks = [changed(v, result="fail") if n == 0 else v for n, v in enumerate(receipt.checks)]
    seal_receipt(case, result="fail", checks=checks)
    failed = accept(case)
    assert failed.job.state == JobState.VALIDATING_DELIVERY and failed.job.receipt.result == "fail"
    new = changed(case.proposal, proposal_id=str(uuid4()))
    next_status = case.service.propose_delivery(
        case.principal,
        UUID(case.status.job.job_id),
        DeliveryProposalRequest(
            operation_key="revised", expected_revision=failed.revision, proposal=new
        ),
        uuid4(),
    )
    with pytest.raises(ResearchConflict, match="superseded"):
        case.service.delivery_candidate(
            case.principal, UUID(next_status.job.job_id), UUID(case.proposal.proposal_id)
        )


def test_human_signoff_is_separate_scoped_and_immutable(research_connect, tmp_path):
    case = delivery_setup(research_connect, tmp_path, human=True)
    checkpoint = HumanCheckpointRequest(
        checkpoint_id=uuid4(),
        kind="delivery_approval",
        question="Review exact proposed delivery",
        proposal_id=UUID(case.proposal.proposal_id),
    )
    case.service.open_checkpoint(case.principal, UUID(case.status.job.job_id), checkpoint, uuid4())
    case.status = case.service.get_job(case.principal, UUID(case.status.job.job_id))
    seal_receipt(case)
    with pytest.raises(InvalidResearchRequest, match="human"):
        accept(case)
    answer = HumanCheckpointAnswer(
        operation_key="human-answer", answer="Reviewed synthetic fixture", decision="approve"
    )
    with pytest.raises(PermissionError):
        case.service.answer_checkpoint(
            case.principal, UUID(case.status.job.job_id), checkpoint.checkpoint_id, answer, uuid4()
        )
    human = ServicePrincipal(
        "synthetic-human", "research", frozenset({"human_reviewer"}), case.principal.programs
    )
    record = case.service.answer_checkpoint(
        human, UUID(case.status.job.job_id), checkpoint.checkpoint_id, answer, uuid4()
    )
    assert record.state == "answered" and record.answered_by == human.name
    assert (
        case.service.answer_checkpoint(
            human, UUID(case.status.job.job_id), checkpoint.checkpoint_id, answer, uuid4()
        )
        == record
    )
    with pytest.raises(ResearchConflict):
        case.service.answer_checkpoint(
            human,
            UUID(case.status.job.job_id),
            checkpoint.checkpoint_id,
            changed(answer, decision="reject"),
            uuid4(),
        )
    seal_receipt(case)
    assert accept(case).job.state == JobState.COMPLETED
