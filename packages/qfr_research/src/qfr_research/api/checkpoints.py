"""Durable questions and separately authorized human answers, without policy edits."""

from uuid import UUID

from psycopg import Connection
from psycopg.types.json import Jsonb
from qfr_core.access import ServicePrincipal
from qfr_core.contracts.delivery import DeliveryProposal, HumanDeliveryApproval
from qfr_core.contracts.jobs import JobRecord
from qfr_core.contracts.research import (
    HumanCheckpointAnswer,
    HumanCheckpointRecord,
    HumanCheckpointRequest,
)
from qfr_core.delivery_rules import content_sha256

from qfr_research.api.errors import InvalidResearchRequest, ResearchConflict, ResearchNotFound
from qfr_research.api.jobs import TERMINAL, Jobs
from qfr_research.api.storage import scope
from qfr_research.db import attributed


class Checkpoints(Jobs):
    @staticmethod
    def proposal(
        conn: Connection, job: JobRecord, identity: UUID, *, active: bool = True
    ) -> DeliveryProposal:
        row = conn.execute(
            "SELECT p.payload,p.sha256,j.active_delivery_proposal_id "
            "FROM research.delivery_proposals p JOIN research.research_jobs j "
            "ON (j.id,j.program_id)=(p.research_job_id,p.program_id) "
            "WHERE p.id=%s AND p.program_id=%s AND p.research_job_id=%s",
            [identity, UUID(job.project_id), UUID(job.job_id)],
        ).fetchone()
        if row is None:
            raise ResearchNotFound("delivery proposal unavailable")
        if active and row[2] != identity:
            raise ResearchConflict("delivery proposal was superseded")
        value = DeliveryProposal.model_validate(row[0])
        if content_sha256(value.model_dump(mode="json")) != row[1] or value.job_id != job.job_id:
            raise InvalidResearchRequest("stored delivery proposal failed verification")
        return value

    def open_checkpoint(
        self,
        principal: ServicePrincipal,
        job_id: UUID,
        value: HumanCheckpointRequest,
        request_id: UUID,
    ) -> HumanCheckpointRecord:
        with self.storage.connection() as conn, attributed(conn, principal.name, request_id):
            context, revision, paused = self._context(conn, principal, job_id, lock=True)
            program, job = UUID(context.job.project_id), context.job
            scope(principal, program, "research_lead")
            body = value.model_dump(mode="json")
            action_scope = "checkpoint-open:" + str(job_id)
            previous = self.storage.operation(
                conn, program, action_scope, str(value.checkpoint_id), body
            )
            if previous is not None:
                return HumanCheckpointRecord.model_validate(previous)
            if job.state in TERMINAL:
                raise ResearchConflict("terminal job cannot request a checkpoint")
            if value.proposal_id is not None:
                self.proposal(conn, job, value.proposal_id)
            record = HumanCheckpointRecord(
                request=value,
                job_id=job_id,
                state="open",
                created_by=principal.name,
                created_at=self.storage.now(conn),
                answer=None,
                answered_by=None,
                answered_at=None,
            )
            self.storage.insert(
                conn,
                "checkpoints",
                record.model_dump(mode="json"),
                principal.name,
                request_id,
                program,
                identity=value.checkpoint_id,
                research_job_id=job_id,
                state="open",
            )
            updated = JobRecord.model_validate(
                {
                    **job.model_dump(),
                    "checkpoint_refs": [*job.checkpoint_refs, str(value.checkpoint_id)],
                }
            )
            self.save_job(conn, updated, revision, paused_from=paused)
            self.storage.remember(
                conn,
                program,
                action_scope,
                str(value.checkpoint_id),
                body,
                record.model_dump(mode="json"),
                principal.name,
                request_id,
            )
            return record

    def get_checkpoint(
        self, principal: ServicePrincipal, job_id: UUID, identity: UUID
    ) -> HumanCheckpointRecord:
        with self.storage.connection() as conn:
            context, _, _ = self._context(conn, principal, job_id)
            row = conn.execute(
                "SELECT payload FROM research.checkpoints "
                "WHERE id=%s AND research_job_id=%s AND program_id=%s",
                [identity, job_id, UUID(context.job.project_id)],
            ).fetchone()
            if row is None:
                raise ResearchNotFound("checkpoint unavailable")
            return HumanCheckpointRecord.model_validate(row[0])

    def answer_checkpoint(
        self,
        principal: ServicePrincipal,
        job_id: UUID,
        identity: UUID,
        value: HumanCheckpointAnswer,
        request_id: UUID,
    ) -> HumanCheckpointRecord:
        with self.storage.connection() as conn, attributed(conn, principal.name, request_id):
            context, _, _ = self._context(conn, principal, job_id, lock=True)
            job, program = context.job, UUID(context.job.project_id)
            scope(principal, program, "human_reviewer")
            action_scope = "checkpoint-answer:" + str(identity)
            body = value.model_dump(mode="json")
            previous = self.storage.operation(
                conn, program, action_scope, value.operation_key, body
            )
            if previous is not None:
                return HumanCheckpointRecord.model_validate(previous)
            if job.state in TERMINAL:
                raise ResearchConflict("terminal job cannot accept a new answer")
            row = conn.execute(
                "SELECT payload FROM research.checkpoints "
                "WHERE id=%s AND research_job_id=%s AND program_id=%s FOR UPDATE",
                [identity, job_id, program],
            ).fetchone()
            if row is None:
                raise ResearchNotFound("checkpoint unavailable")
            record = HumanCheckpointRecord.model_validate(row[0])
            if record.state != "open":
                raise ResearchConflict("checkpoint answer is immutable")
            approval = None
            stamp = self.storage.now(conn)
            if record.request.proposal_id is not None:
                if value.decision is None:
                    raise InvalidResearchRequest("human delivery decision required")
                proposal = self.proposal(conn, job, record.request.proposal_id)
                approval = HumanDeliveryApproval(
                    approval_id=str(identity),
                    gate_spec_hash=job.exit_gate.spec_hash,
                    proposal_sha256=content_sha256(proposal.model_dump(mode="json")),
                    decision=value.decision,
                    principal=principal.name,
                    recorded_at=stamp,
                )
            elif value.decision is not None:
                raise InvalidResearchRequest("clarification is not delivery approval")
            updated = HumanCheckpointRecord.model_validate(
                {
                    **record.model_dump(),
                    "state": "answered",
                    "answer": value,
                    "answered_by": principal.name,
                    "answered_at": stamp,
                }
            )
            self.storage.insert(
                conn,
                "checkpoint_answers",
                dict(
                    record=updated.model_dump(mode="json"),
                    approval=approval.model_dump(mode="json") if approval else None,
                ),
                principal.name,
                request_id,
                program,
                checkpoint_id=identity,
            )
            conn.execute(
                "UPDATE research.checkpoints SET payload=%s,state='answered' WHERE id=%s",
                [Jsonb(updated.model_dump(mode="json")), identity],
            )
            self.storage.remember(
                conn,
                program,
                action_scope,
                value.operation_key,
                body,
                updated.model_dump(mode="json"),
                principal.name,
                request_id,
            )
            return updated

    @staticmethod
    def approval(
        conn: Connection, job: JobRecord, proposal_id: UUID
    ) -> HumanDeliveryApproval | None:
        rows = conn.execute(
            "SELECT a.payload FROM research.checkpoint_answers a "
            "JOIN research.checkpoints c ON (c.id,c.program_id)=(a.checkpoint_id,a.program_id) "
            "WHERE c.research_job_id=%s AND c.program_id=%s "
            "AND c.payload#>>'{request,proposal_id}'=%s "
            "AND c.payload#>>'{request,kind}'='delivery_approval'",
            [UUID(job.job_id), UUID(job.project_id), str(proposal_id)],
        ).fetchall()
        if not rows:
            return None
        if len(rows) != 1:
            raise ResearchConflict("ambiguous human approval")
        return HumanDeliveryApproval.model_validate(rows[0][0]["approval"])
