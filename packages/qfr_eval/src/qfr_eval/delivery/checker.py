"""Independent pilot delivery checks over immutable Registry/evaluator evidence.

The worker obtains context/proposal from the authenticated Research API. A
proposal carries references, never trusted check results or a supplied receipt.
Actual replay is a separate evaluator action; its immutable match audit is
required here. This checker does not schedule evaluation or spend a query.
"""

import hashlib
from datetime import datetime
from typing import Protocol
from uuid import UUID

from psycopg import Connection
from qfr_core.contracts.artifacts import ArtifactDefinition, ArtifactReference, ResearchNotePayload
from qfr_core.contracts.delivery import (
    AdmittedDeliveryContext,
    DeliveryCheck,
    DeliveryProposal,
    DeliveryReceipt,
    VersionReference,
)
from qfr_core.contracts.enums import Conclusion, JobState
from qfr_core.contracts.publication import PublishedArtifact
from qfr_core.contracts.reports import PilotRelease, PublicProtocolCard, ReleasedReport
from qfr_core.delivery_rules import (
    PILOT_DELIVERY_CHECKS,
    admission_hash,
    content_sha256,
    job_config_hash,
    pilot_checker_matches_gate,
    validate_pilot_assessment,
    validate_pilot_delivery_gate,
)
from qfr_core.signatures import EvidenceVerifier

from qfr_eval.artifact_store import EvidenceStore
from qfr_eval.delivery.models import PilotDeliveryPolicy
from qfr_eval.persistence import verify_receipt
from qfr_eval.records import EvaluationRequest, Measurement, OfficialRecord
from qfr_eval.scheduler.dedup import digest
from qfr_eval.signed_receipts import SignedMeasurementReceipt
from qfr_eval.signing import EvaluatorSigner


class RegistryEvidence(Protocol):
    def get(self, identity: UUID) -> PublishedArtifact: ...
    def payload(self, artifact: PublishedArtifact, asset_id: str) -> bytes: ...


def frozen_context_valid(context: AdmittedDeliveryContext, proposal: DeliveryProposal) -> bool:
    job, brief, bundle = context.job, context.brief, context.input_bundle
    try:
        validate_pilot_assessment(brief)
    except ValueError:
        return False
    return (
        job.job_id == proposal.job_id
        and job.project_id == brief.project_id
        and job.brief_id == brief.brief_id
        and job.input_bundle_id == brief.input_bundle_id == bundle.bundle_id
        and job.config_hash == brief.frozen_config_hash
        and job.config_hash == job_config_hash(bundle)
        and job.exit_gate == brief.exit_gate
        and job.payload_hash == admission_hash(bundle, brief)
        and job.state == JobState.VALIDATING_DELIVERY
        and job.reason is None
        and bundle.readiness == "ready"
        and set(bundle.data_refs) <= set(bundle.job_config.permitted_dataset_ids)
    )


def verify_artifact(
    artifact: PublishedArtifact, reference: ArtifactReference, program: str
) -> None:
    manifest = artifact.manifest
    raw = manifest.model_dump(mode="json")
    definition = {key: raw[key] for key in ArtifactDefinition.model_fields if key != "family_id"}
    expected = digest(
        dict(
            hash_spec="qfr-publication/1",
            profile=artifact.profile,
            dsl_policy_hash=artifact.dsl_policy_hash,
            manifest=definition,
        )
    )
    if (
        manifest.artifact_version_id != reference.artifact_version_id
        or manifest.content_hash != reference.content_hash
        or artifact.payload_digest != expected
        or manifest.content_hash != expected
        or manifest.provenance.program_id != program
    ):
        raise ValueError("delivery artifact binding differs")


def _report_evidence(
    conn: Connection,
    reference: VersionReference,
    context: AdmittedDeliveryContext,
    policy: PilotDeliveryPolicy,
    verifier: EvidenceVerifier,
    evidence_store: EvidenceStore,
) -> tuple[ReleasedReport, Measurement, PublicProtocolCard, bool]:
    row = conn.execute(
        "SELECT r.payload,q.source_id,q.policy_sha256,o.payload,s.payload,s.payload_sha256 "
        "FROM eval.released_reports r JOIN eval.release_publications p ON p.id=r.id "
        "JOIN eval.release_queue q ON q.id=p.queue_id AND q.published_report_id=r.id "
        "JOIN eval.official_records o ON o.id=q.official_record_id "
        "JOIN eval.signed_measurement_receipts s ON s.official_record_id=o.id "
        "WHERE r.id=%s AND q.state='published' AND q.eligible_at<=clock_timestamp() "
        "AND q.program_id=%s AND q.policy_sha256=%s AND q.payload->>'stage'='pilot'",
        [UUID(reference.reference_id), context.job.project_id, policy.release_policy_sha256],
    ).fetchone()
    if row is None or digest(row[0]) != reference.sha256:
        raise ValueError("required released report unavailable")
    report = verifier.report(ReleasedReport.model_validate(row[0]))
    record = OfficialRecord.model_validate(row[3]["record"])
    request = EvaluationRequest.model_validate(row[3]["request"])
    measured = Measurement.model_validate(row[3]["measurement"])
    wrapper = SignedMeasurementReceipt.model_validate(row[4])
    verifier.verify_payload(
        "measurement_receipt",
        wrapper.model_dump(mode="json", exclude={"signature"}),
        wrapper.signature,
    )
    verify_receipt(wrapper.receipt, evidence_store)
    if (
        report.report_id != reference.reference_id
        or report.program_id != context.job.project_id
        or not isinstance(report.content, PilotRelease)
        or report.identity != record.identity
        or report.identity.protocol_version not in context.job.exit_gate.protocol_refs
        or report.identity.dataset_version_id not in context.input_bundle.data_refs
        or request.program_id != context.job.project_id
        or request.variant != policy.required_execution
        or request.sha256 != record.request_hash
        or measured.results_hash != record.results_hash
        or wrapper.receipt.record_id != record.record_id
        or wrapper.receipt.identity != record.identity
        or wrapper.receipt.request_hash != record.request_hash
        or wrapper.receipt.results_hash != record.results_hash
        or digest(row[4]) != row[5]
    ):
        raise ValueError("released measurement binding differs")
    card_row = conn.execute(
        "SELECT payload,content_sha256 FROM eval.public_protocol_cards WHERE card_ref=%s",
        [report.protocol_card_ref],
    ).fetchone()
    if card_row is None or digest(card_row[0]) != card_row[1]:
        raise ValueError("required public protocol card unavailable")
    card = PublicProtocolCard.model_validate(card_row[0])
    if (
        card.protocol_version != report.identity.protocol_version
        or (card.card_ref or card.protocol_version) != report.protocol_card_ref
        or card.release_policy_ref != report.release_policy_ref
    ):
        raise ValueError("public protocol card binding differs")
    replay = conn.execute(
        "SELECT EXISTS(SELECT 1 FROM eval.events WHERE payload->>'action'='reproduction_match' "
        "AND payload->>'entity_type'='official_records' AND payload->>'entity_id'=%s "
        "AND payload->>'results_hash'=%s)",
        [record.record_id, record.results_hash],
    ).fetchone()
    return report, measured, card, bool(replay and replay[0])


def check_delivery(
    conn: Connection,
    context: AdmittedDeliveryContext,
    proposal: DeliveryProposal,
    registry: RegistryEvidence,
    policy: PilotDeliveryPolicy,
    verifier: EvidenceVerifier,
    signer: EvaluatorSigner,
    evidence_store: EvidenceStore,
    *,
    receipt_id: UUID,
    at: datetime,
) -> DeliveryReceipt:
    """Internal checker engine. Only the independent worker may invoke/sign it."""
    context = AdmittedDeliveryContext.model_validate(context.model_dump())
    proposal = DeliveryProposal.model_validate(proposal.model_dump())
    gate = context.job.exit_gate
    validate_pilot_delivery_gate(gate)
    if not pilot_checker_matches_gate(gate, policy.checker_id):
        raise ValueError("delivery checker and frozen assessment gate versions differ")
    if proposal.job_id != context.job.job_id or proposal.conclusion not in gate.allowed_conclusions:
        raise ValueError("proposal differs from frozen job or allowed conclusion")
    if len(proposal.artifact_refs) > policy.maximum_artifacts or (
        len(proposal.released_report_refs) > policy.maximum_reports
    ):
        raise ValueError("delivery evidence exceeds configured bounds")
    outcomes = dict.fromkeys(PILOT_DELIVERY_CHECKS, False)
    outcomes["frozen_context"] = frozen_context_valid(context, proposal)
    artifacts: dict[str, PublishedArtifact] = {}
    reports: list[ReleasedReport] = []
    cards: dict[str, PublicProtocolCard] = {}
    measurements: list[Measurement] = []
    replays: list[bool] = []
    assessed_ids: set[str] = set()
    total_bytes = 0
    try:
        for ref in proposal.artifact_refs:
            artifact = registry.get(UUID(ref.artifact_version_id))
            verify_artifact(artifact, ref, context.job.project_id)
            for file in artifact.manifest.payload_files:
                data = registry.payload(artifact, file.asset_id)
                total_bytes += len(data)
                if total_bytes > policy.maximum_payload_bytes or (
                    hashlib.sha256(data).hexdigest() != file.sha256
                ):
                    raise ValueError("delivery payload size or hash differs")
            artifacts[ref.artifact_version_id] = artifact
        outcomes["artifact_integrity"] = (
            set(context.brief.baseline_artifact_ids) <= artifacts.keys()
        )
    except (ValueError, KeyError, OSError, RuntimeError):
        outcomes["artifact_integrity"] = False
    bindings = {
        binding.name: binding.artifact.artifact_version_id for binding in proposal.deliverables
    }
    declared = {item.name: item for item in gate.required_deliverables}
    note_reports: set[str] = set()
    deliverables_ok = set(bindings) <= declared.keys()
    for name, requirement in declared.items():
        if name not in bindings:
            deliverables_ok &= not requirement.required
            continue
        bound_artifact = artifacts.get(bindings[name])
        if bound_artifact is None:
            deliverables_ok = False
            continue
        if requirement.schema_ref == "ResearchNotePayload":
            note = bound_artifact.manifest.payload
            if not isinstance(note, ResearchNotePayload):
                deliverables_ok = False
                continue
            note_reports.update(note.released_report_refs)
            if requirement.evidence_refs_required and not note.released_report_refs:
                deliverables_ok = False
    outcomes["required_deliverables"] = deliverables_ok
    try:
        for report_ref in proposal.released_report_refs:
            report, measured, card, replay = _report_evidence(
                conn, report_ref, context, policy, verifier, evidence_store
            )
            if report.identity.artifact_version_id not in artifacts or (
                artifacts[report.identity.artifact_version_id].manifest.content_hash
                != report.identity.content_hash
            ):
                raise ValueError("report artifact outside the declared delivery")
            reports.append(report)
            measurements.append(measured)
            cards[report.protocol_card_ref] = card
            replays.append(replay)
        executable_ids = {
            key
            for key, artifact in artifacts.items()
            if artifact.manifest.kind.value in {"factor", "model", "strategy"}
        }
        assessed_ids = executable_ids
        scope = gate.assessment_scope
        if scope is not None:
            assessed_ids = {ref.artifact_version_id for ref in scope.assessed_artifact_refs}
            scoped = [*scope.assessed_artifact_refs, *scope.reference_artifact_refs]
            outcomes["artifact_integrity"] &= {
                ref.artifact_version_id for ref in scoped
            } == executable_ids and all(
                ref.artifact_version_id in artifacts
                and artifacts[ref.artifact_version_id].manifest.content_hash == ref.content_hash
                for ref in scoped
            )
        outcomes["released_evidence"] = (
            bool(reports)
            and {r.identity.artifact_version_id for r in reports} == executable_ids
            and note_reports == {r.report_id for r in reports}
            and {r.identity.protocol_version for r in reports} == set(gate.protocol_refs)
            and all(
                isinstance(r.content, PilotRelease)
                and r.content.scalar.origin_artifact_version_id in executable_ids
                for r in reports
            )
            and all(
                not requirement.evidence_refs_required
                or requirement.schema_ref == "ResearchNotePayload"
                or bindings.get(name) in {r.identity.artifact_version_id for r in reports}
                for name, requirement in declared.items()
                if name in bindings
            )
        )
        if scope is not None:
            outcomes["released_evidence"] &= all(
                any(
                    r.identity.artifact_version_id == identity
                    and r.identity.protocol_version == protocol
                    for r in reports
                )
                for identity in assessed_ids
                for protocol in gate.protocol_refs
            )
    except (ValueError, KeyError, TypeError, OSError):
        outcomes["released_evidence"] = False
    outcomes["measurement_quality"] = outcomes["released_evidence"] and all(
        isinstance(report.content, PilotRelease)
        and not report.content.not_for_selection
        and not report.reason_codes
        and report.content.hurdle_flags.coverage == "pass"
        and measured.status == "complete"
        and (
            (measured.uncertainty is not None and measured.uncertainty.status == "estimated")
            if report.identity.artifact_version_id in assessed_ids
            else (
                gate.assessment_scope is not None
                and measured.period_count > 0
                and not measured.reason_codes
                and report.content.scalar.measurement.value is not None
            )
        )
        for report, measured in zip(reports, measurements, strict=True)
    )
    outcomes["reproduction"] = outcomes["released_evidence"] and all(replays)
    passing = {
        report.identity.artifact_version_id
        for report in reports
        if isinstance(report.content, PilotRelease)
        and report.identity.artifact_version_id in assessed_ids
        and report.content.hurdle_flags.overall == "pass"
    }
    resolved = all(
        isinstance(report.content, PilotRelease)
        and report.content.hurdle_flags.overall in {"pass", "fail"}
        for report in reports
        if report.identity.artifact_version_id in assessed_ids
    )
    outcomes["conclusion_support"] = (
        outcomes["measurement_quality"]
        and resolved
        and (
            {item.artifact_version_id for item in proposal.shortlist} <= passing
            if proposal.conclusion == Conclusion.POSITIVE
            else not passing
        )
    )
    approval = context.human_approval
    human_ok = (
        approval is not None
        and approval.decision == "approve"
        and bool(approval.principal.strip())
        and approval.gate_spec_hash == gate.spec_hash
        and approval.proposal_sha256 == digest(proposal.model_dump(mode="json"))
        and context.job.created_at <= approval.recorded_at <= at
    )
    outcomes["human_signoff"] = not gate.human_signoff_required or human_ok
    common_evidence = [
        VersionReference(reference_id=gate.gate_id, sha256=gate.spec_hash),
        *[
            VersionReference(reference_id=r.report_id, sha256=digest(r.model_dump(mode="json")))
            for r in reports
        ],
    ]
    checks = [
        DeliveryCheck(
            check_id=name,
            schema_ref=(
                policy.checker_id if policy.schema_version == "3" else "pilot-research-delivery-v1"
            )
            + ":"
            + name,
            result="pass" if outcomes[name] else "fail",
            evidence_refs=common_evidence,
        )
        for name in PILOT_DELIVERY_CHECKS
    ]
    receipt = signer.seal(
        DeliveryReceipt,
        "delivery_receipt",
        dict(
            schema_version="1",
            receipt_id=str(receipt_id),
            job_id=context.job.job_id,
            gate_spec_hash=gate.spec_hash,
            artifact_refs=[
                ref for ref in proposal.artifact_refs if ref.artifact_version_id in artifacts
            ],
            dataset_refs=[
                VersionReference(reference_id=value, sha256=value)
                for value in sorted({r.identity.dataset_version_id for r in reports})
            ],
            protocol_refs=[
                VersionReference(reference_id=ref, sha256=digest(card.model_dump(mode="json")))
                for ref, card in sorted(cards.items())
            ],
            config_refs=[
                *(
                    [
                        VersionReference(
                            reference_id="input-bundle:" + context.input_bundle.bundle_id,
                            sha256=content_sha256(context.input_bundle.model_dump(mode="json")),
                        ),
                        VersionReference(
                            reference_id="admission:" + context.job.job_id,
                            sha256=context.job.payload_hash,
                        ),
                    ]
                    if policy.schema_version in {"2", "3"}
                    else []
                ),
                VersionReference(
                    reference_id="job-config:" + context.job.job_id, sha256=context.job.config_hash
                ),
                VersionReference(
                    reference_id="brief:" + context.brief.brief_id,
                    sha256=content_sha256(context.brief.model_dump(mode="json")),
                ),
                VersionReference(
                    reference_id="proposal:" + proposal.proposal_id,
                    sha256=digest(proposal.model_dump(mode="json")),
                ),
                VersionReference(
                    reference_id=policy.checker_id, sha256=digest(policy.model_dump(mode="json"))
                ),
            ],
            released_report_refs=[
                VersionReference(reference_id=r.report_id, sha256=digest(r.model_dump(mode="json")))
                for r in reports
            ],
            checks=checks,
            allowed_conclusions=gate.allowed_conclusions,
            conclusion=proposal.conclusion,
            result="pass" if all(outcomes.values()) else "fail",
            independent_checker=policy.checker_id,
            human_signoff_ref=approval.approval_id if human_ok and approval else None,
            created_at=at,
        ),
    )
    return verifier.delivery(receipt)
