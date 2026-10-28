"""Propose delivery, then accept only independently signed, exactly bound evidence."""

from uuid import UUID

from qfr_core.access import ServicePrincipal
from qfr_core.contracts.delivery import DeliveryCandidate, DeliveryReceipt
from qfr_core.contracts.enums import JobState
from qfr_core.contracts.jobs import JobRecord, ReceiptReference
from qfr_core.contracts.research import DeliveryProposalRequest, DeliveryReceiptRequest, JobStatus
from qfr_core.delivery_rules import content_sha256, pilot_checker_matches_gate

from qfr_research.api.checkpoints import Checkpoints
from qfr_research.api.errors import InvalidResearchRequest, ResearchConflict
from qfr_research.api.storage import scope
from qfr_research.db import attributed


class Deliveries(Checkpoints):
    def propose_delivery(
        self,
        principal: ServicePrincipal,
        job_id: UUID,
        value: DeliveryProposalRequest,
        request_id: UUID,
    ) -> JobStatus:
        with self.storage.connection() as conn, attributed(conn, principal.name, request_id):
            context, revision, _ = self._context(conn, principal, job_id, lock=True)
            job, program, proposal = context.job, UUID(context.job.project_id), value.proposal
            scope(principal, program, "research_lead")
            body = value.model_dump(mode="json")
            action_scope = "delivery-proposal:" + str(job_id)
            previous = self.storage.operation(
                conn, program, action_scope, value.operation_key, body
            )
            if previous is not None:
                return JobStatus.model_validate(previous)
            if revision != value.expected_revision or job.state not in {
                JobState.RUNNING,
                JobState.AWAITING_EVALUATION,
                JobState.VALIDATING_DELIVERY,
            }:
                raise ResearchConflict("job cannot propose delivery in its current revision/state")
            if (
                proposal.job_id != str(job_id)
                or context.input_bundle.readiness != "ready"
                or proposal.conclusion not in job.exit_gate.allowed_conclusions
                or max(len(proposal.artifact_refs), len(proposal.released_report_refs))
                > self.policy.max_artifacts
            ):
                raise InvalidResearchRequest("delivery proposal differs from admitted scope")
            for artifact_ref in proposal.artifact_refs:
                self.evidence.artifact(program, artifact_ref)
            for report_ref in proposal.released_report_refs:
                report = self.evidence.report(program, UUID(report_ref.reference_id))
                if content_sha256(report.model_dump(mode="json")) != report_ref.sha256:
                    raise InvalidResearchRequest("proposal report hash differs")
            proposal_id = UUID(proposal.proposal_id)
            self.storage.insert(
                conn,
                "delivery_proposals",
                proposal.model_dump(mode="json"),
                principal.name,
                request_id,
                program,
                identity=proposal_id,
                research_job_id=job_id,
                sha256=content_sha256(proposal.model_dump(mode="json")),
            )
            conn.execute(
                "UPDATE research.research_jobs SET active_delivery_proposal_id=%s WHERE id=%s",
                [proposal_id, job_id],
            )
            updated = JobRecord.model_validate(
                {
                    **job.model_dump(),
                    "state": JobState.VALIDATING_DELIVERY,
                    "reason": None,
                    "receipt": None,
                }
            )
            result = self.save_job(conn, updated, revision)
            self.storage.remember(
                conn,
                program,
                action_scope,
                value.operation_key,
                body,
                result.model_dump(mode="json"),
                principal.name,
                request_id,
            )
            return result

    def delivery_candidate(
        self, principal: ServicePrincipal, job_id: UUID, proposal_id: UUID
    ) -> DeliveryCandidate:
        with self.storage.connection() as conn:
            context, _, _ = self._context(conn, principal, job_id)
            proposal = self.proposal(conn, context.job, proposal_id)
            context = type(context).model_validate(
                {
                    **context.model_dump(),
                    "human_approval": self.approval(conn, context.job, proposal_id),
                }
            )
            return DeliveryCandidate(schema_version="1", context=context, proposal=proposal)

    def verify_delivery_binding(
        self, candidate: DeliveryCandidate, receipt: DeliveryReceipt
    ) -> None:
        context, proposal = candidate.context, candidate.proposal
        job, brief, program = context.job, context.brief, UUID(context.job.project_id)
        self.evidence.verifier.delivery(receipt)
        expected_config = {
            "input-bundle:" + context.input_bundle.bundle_id: content_sha256(
                context.input_bundle.model_dump(mode="json")
            ),
            "admission:" + job.job_id: job.payload_hash,
            "job-config:" + job.job_id: job.config_hash,
            "brief:" + brief.brief_id: content_sha256(brief.model_dump(mode="json")),
            "proposal:" + proposal.proposal_id: content_sha256(proposal.model_dump(mode="json")),
            receipt.independent_checker: self.policy.trusted_delivery_checkers.get(
                receipt.independent_checker
            ),
        }
        if (
            None in expected_config.values()
            or len(receipt.config_refs) != len(expected_config)
            or {r.reference_id: r.sha256 for r in receipt.config_refs} != expected_config
            or receipt.job_id != job.job_id
            or receipt.gate_spec_hash != job.exit_gate.spec_hash
            or not pilot_checker_matches_gate(job.exit_gate, receipt.independent_checker)
            or receipt.allowed_conclusions != job.exit_gate.allowed_conclusions
            or receipt.conclusion != proposal.conclusion
            or receipt.created_at < job.created_at
            or sorted(c.check_id for c in receipt.checks) != sorted(job.exit_gate.required_checks)
        ):
            raise InvalidResearchRequest("signed receipt does not bind the frozen job and proposal")
        if receipt.result != "pass":
            return
        expected_artifacts = {r.artifact_version_id: r.content_hash for r in proposal.artifact_refs}
        if (
            len(receipt.artifact_refs) != len(expected_artifacts)
            or {r.artifact_version_id: r.content_hash for r in receipt.artifact_refs}
            != expected_artifacts
            or receipt.released_report_refs != proposal.released_report_refs
        ):
            raise InvalidResearchRequest("passing receipt evidence differs from proposal")
        reports = [
            self.evidence.report(program, UUID(ref.reference_id))
            for ref in receipt.released_report_refs
        ]
        if any(
            content_sha256(r.model_dump(mode="json")) != ref.sha256
            for r, ref in zip(reports, receipt.released_report_refs, strict=True)
        ):
            raise InvalidResearchRequest("released evidence differs from signed receipt")
        datasets = {r.identity.dataset_version_id for r in reports}
        if (
            not datasets
            or not datasets <= set(context.input_bundle.data_refs)
            or len(receipt.dataset_refs) != len(datasets)
            or {r.reference_id: r.sha256 for r in receipt.dataset_refs} != {d: d for d in datasets}
        ):
            raise InvalidResearchRequest("receipt dataset binding differs")
        cards = {
            r.protocol_card_ref: self.evidence.protocol_card(program, r.protocol_card_ref)
            for r in reports
        }
        if (
            len(receipt.protocol_refs) != len(cards)
            or {r.reference_id: r.sha256 for r in receipt.protocol_refs}
            != {key: content_sha256(card.model_dump(mode="json")) for key, card in cards.items()}
            or {r.identity.protocol_version for r in reports} != set(job.exit_gate.protocol_refs)
        ):
            raise InvalidResearchRequest("receipt public protocol binding differs")
        approval = context.human_approval
        if job.exit_gate.human_signoff_required and (
            approval is None
            or approval.decision != "approve"
            or receipt.human_signoff_ref != approval.approval_id
            or approval.gate_spec_hash != job.exit_gate.spec_hash
            or approval.proposal_sha256 != content_sha256(proposal.model_dump(mode="json"))
        ):
            raise InvalidResearchRequest("required human approval is absent or differs")

    def accept_receipt(
        self,
        principal: ServicePrincipal,
        job_id: UUID,
        value: DeliveryReceiptRequest,
        request_id: UUID,
    ) -> JobStatus:
        with self.storage.connection() as conn, attributed(conn, principal.name, request_id):
            context, revision, _ = self._context(conn, principal, job_id, lock=True)
            job, program = context.job, UUID(context.job.project_id)
            scope(principal, program, "research_lead")
            body = value.model_dump(mode="json")
            action_scope = "delivery-accept:" + str(job_id)
            previous = self.storage.operation(
                conn, program, action_scope, value.operation_key, body
            )
            if previous is not None:
                return JobStatus.model_validate(previous)
            if revision != value.expected_revision or job.state != JobState.VALIDATING_DELIVERY:
                raise ResearchConflict("job cannot accept delivery in its current revision/state")
            proposal = self.proposal(conn, job, value.proposal_id)
            context = type(context).model_validate(
                {
                    **context.model_dump(),
                    "human_approval": self.approval(conn, job, value.proposal_id),
                }
            )
            receipt = self.evidence.receipt(program, value.receipt_id)
            if receipt.receipt_id != str(value.receipt_id):
                raise InvalidResearchRequest("receipt identity differs")
            self.verify_delivery_binding(
                DeliveryCandidate(schema_version="1", context=context, proposal=proposal), receipt
            )
            receipt_sha = content_sha256(receipt.model_dump(mode="json"))
            delivery_id = self.storage.insert(
                conn,
                "delivery_refs",
                receipt.model_dump(mode="json"),
                principal.name,
                request_id,
                program,
                research_job_id=job_id,
                receipt_id=receipt.receipt_id,
                gate_spec_hash=receipt.gate_spec_hash,
                receipt_sha256=receipt_sha,
                result=receipt.result,
                verification_key_id=receipt.signature.key_id,
            )
            reference = ReceiptReference(
                receipt_id=receipt.receipt_id,
                job_id=job.job_id,
                gate_spec_hash=receipt.gate_spec_hash,
                result=receipt.result,
                independent_checker=receipt.independent_checker,
                receipt_sha256=receipt_sha,
                signature_verified=True,
            )
            updated = JobRecord.model_validate(
                {
                    **job.model_dump(),
                    "receipt": reference,
                    "state": JobState.COMPLETED
                    if receipt.result == "pass"
                    else JobState.VALIDATING_DELIVERY,
                }
            )
            result = self.save_job(conn, updated, revision, delivery_ref=delivery_id)
            self.storage.remember(
                conn,
                program,
                action_scope,
                value.operation_key,
                body,
                result.model_dump(mode="json"),
                principal.name,
                request_id,
            )
            return result
