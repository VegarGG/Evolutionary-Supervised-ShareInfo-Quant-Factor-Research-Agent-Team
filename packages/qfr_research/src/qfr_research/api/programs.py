"""Program context, immutable registrations and manual blackboard records."""

from pathlib import Path
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb
from qfr_core.access import ServicePrincipal
from qfr_core.contracts.blackboard import BlackboardRecord, ResearchProgram
from qfr_core.contracts.data import ResearchDatasetRegistration
from qfr_core.contracts.publication import PublishedArtifact
from qfr_core.contracts.research import (
    BaselineRegistrationRequest,
    BlackboardPage,
    DatasetRegistrationRequest,
    ProgramCreate,
    ProgramPage,
    ProtocolProposal,
    ResearchApiPolicy,
)
from qfr_core.data_layer.catalog import read_registration, registered_snapshot
from qfr_core.delivery_rules import content_sha256

from qfr_research.api.errors import InvalidResearchRequest, ResearchConflict, ResearchNotFound
from qfr_research.api.evidence import EvidenceGateway
from qfr_research.api.storage import Storage, scope
from qfr_research.db import attributed


def program_record(row: tuple[Any, ...]) -> ResearchProgram:
    return ResearchProgram(
        schema_version="1",
        program_id=str(row[0]),
        name=row[1],
        status=row[2],
        charter=row[3],
        charter_revision=row[4],
        created_by=row[5],
        created_at=row[6],
    )


class Programs:
    def __init__(self, storage: Storage, evidence: EvidenceGateway, research_root: Path):
        self.storage, self.evidence, self.research_root = storage, evidence, research_root
        self.policy: ResearchApiPolicy = storage.policy

    def create(
        self, principal: ServicePrincipal, request: ProgramCreate, request_id: UUID
    ) -> ResearchProgram:
        program = request.program_id
        scope(principal, program, "research_lead")
        with self.storage.connection() as conn, attributed(conn, principal.name, request_id):
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                ["research-program:" + str(program)],
            )
            original = conn.execute(
                "SELECT payload FROM research.programs WHERE id=%s", [program]
            ).fetchone()
            body = request.model_dump(mode="json")
            if original is not None and original[0] != body:
                raise ResearchConflict("program ID already binds a different charter")
            if original is None:
                conn.execute(
                    "INSERT INTO research.programs(id,payload,created_by,request_id,"
                    "name,status,charter,charter_revision) "
                    "VALUES(%s,%s,%s,%s,%s,'active',%s,1)",
                    [
                        program,
                        Jsonb(body),
                        principal.name,
                        request_id,
                        request.name,
                        Jsonb(request.charter),
                    ],
                )
                self.storage.insert(
                    conn,
                    "program_revisions",
                    body,
                    principal.name,
                    request_id,
                    program,
                    revision=1,
                    sha256=content_sha256(body),
                )
            return program_record(self.storage.program(conn, program))

    def get(self, principal: ServicePrincipal, program: UUID) -> ResearchProgram:
        scope(principal, program)
        with self.storage.connection() as conn:
            return program_record(self.storage.program(conn, program))

    def programs(
        self, principal: ServicePrincipal, *, after: UUID | None, limit: int
    ) -> ProgramPage:
        if principal.audience != "research":
            raise PermissionError("research authentication required")
        if not 1 <= limit <= self.policy.max_page_size:
            raise InvalidResearchRequest("invalid page size")
        with self.storage.connection() as conn:
            if after is not None:
                scope(principal, after)
                self.storage.program(conn, after)
            rows = conn.execute(
                "SELECT id,name,status,charter,charter_revision,created_by,created_at "
                "FROM research.programs WHERE id::text=ANY(%s) "
                + ("AND id>%s " if after is not None else "")
                + "ORDER BY id LIMIT %s",
                [sorted(principal.programs), *([after] if after is not None else []), limit + 1],
            ).fetchall()
        selected = rows[:limit]
        result = ProgramPage(
            items=[program_record(row) for row in selected],
            next_after_id=selected[-1][0] if selected else after,
            has_more=len(rows) > limit,
        )
        if len(result.model_dump_json().encode()) > self.policy.max_page_bytes:
            raise InvalidResearchRequest("page exceeds size bound; request fewer records")
        return result

    def registered_dataset(
        self, principal: ServicePrincipal, program: UUID, identity: str
    ) -> ResearchDatasetRegistration:
        scope(principal, program)
        with self.storage.connection() as conn:
            self.storage.program(conn, program)
            row = conn.execute(
                "SELECT payload FROM research.dataset_registrations "
                "WHERE program_id=%s AND dataset_version_id=%s",
                [program, identity],
            ).fetchone()
        if row is None:
            raise ResearchNotFound("registered dataset unavailable")
        return ResearchDatasetRegistration.model_validate(row[0])

    def registered_baseline(
        self, principal: ServicePrincipal, program: UUID, identity: UUID
    ) -> PublishedArtifact:
        scope(principal, program)
        with self.storage.connection() as conn:
            self.storage.program(conn, program)
            row = conn.execute(
                "SELECT payload FROM research.baseline_registrations "
                "WHERE program_id=%s AND artifact_version_id=%s",
                [program, identity],
            ).fetchone()
        if row is None:
            raise ResearchNotFound("registered baseline unavailable")
        return PublishedArtifact.model_validate(row[0])

    def dataset(
        self,
        principal: ServicePrincipal,
        program: UUID,
        request: DatasetRegistrationRequest,
        request_id: UUID,
    ) -> ResearchDatasetRegistration:
        scope(principal, program, "research_lead")
        value = read_registration(self.research_root, request.registration_id, str(program))
        registered_snapshot(self.research_root, value)
        body = value.model_dump(mode="json")
        with self.storage.connection() as conn, attributed(conn, principal.name, request_id):
            self.storage.program(conn, program, lock=True)
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                [f"research-dataset:{program}:{value.dataset_version_id}"],
            )
            old = conn.execute(
                "SELECT payload FROM research.dataset_registrations "
                "WHERE program_id=%s AND dataset_version_id=%s",
                [program, value.dataset_version_id],
            ).fetchone()
            if old is not None and old[0] != body:
                raise ResearchConflict("dataset identity already binds a different research slice")
            if old is None:
                self.storage.insert(
                    conn,
                    "dataset_registrations",
                    body,
                    principal.name,
                    request_id,
                    program,
                    registration_id=value.registration_id,
                    dataset_version_id=value.dataset_version_id,
                )
        return value

    def baseline(
        self,
        principal: ServicePrincipal,
        program: UUID,
        request: BaselineRegistrationRequest,
        request_id: UUID,
    ) -> PublishedArtifact:
        scope(principal, program, "research_lead")
        value = self.evidence.artifact(program, request.artifact)
        body = value.model_dump(mode="json")
        with self.storage.connection() as conn, attributed(conn, principal.name, request_id):
            self.storage.program(conn, program, lock=True)
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                [f"research-baseline:{program}:{request.artifact.artifact_version_id}"],
            )
            old = conn.execute(
                "SELECT payload FROM research.baseline_registrations "
                "WHERE program_id=%s AND artifact_version_id=%s",
                [program, UUID(request.artifact.artifact_version_id)],
            ).fetchone()
            if old is not None and old[0] != body:
                raise ResearchConflict("baseline reference changed")
            if old is None:
                self.storage.insert(
                    conn,
                    "baseline_registrations",
                    body,
                    principal.name,
                    request_id,
                    program,
                    artifact_version_id=UUID(request.artifact.artifact_version_id),
                )
        return value

    def propose_protocol(
        self,
        principal: ServicePrincipal,
        program: UUID,
        request: ProtocolProposal,
        request_id: UUID,
    ) -> ProtocolProposal:
        scope(principal, program, "research_lead")
        if request.program_id != program:
            raise InvalidResearchRequest("proposal program differs")
        with self.storage.connection() as conn, attributed(conn, principal.name, request_id):
            self.storage.program(conn, program, lock=True)
            key = str(request.proposal_id)
            body = request.model_dump(mode="json")
            previous = self.storage.operation(conn, program, "protocol-proposal", key, body)
            if previous is None:
                self.storage.insert(
                    conn,
                    "protocol_proposals",
                    body,
                    principal.name,
                    request_id,
                    program,
                    identity=request.proposal_id,
                )
                self.storage.remember(
                    conn, program, "protocol-proposal", key, body, body, principal.name, request_id
                )
        return request

    def note(
        self,
        principal: ServicePrincipal,
        program: UUID,
        request: BlackboardRecord,
        request_id: UUID,
    ) -> BlackboardRecord:
        scope(principal, program, "research_lead")
        if request.project_id != str(program) or request.author_role != "human":
            raise InvalidResearchRequest("manual blackboard requires program and human attribution")
        identity = UUID(request.record_id)
        # Cited public evidence is resolved before recording a factual reference.
        for identity_ref in request.released_report_refs:
            self.evidence.report(program, UUID(identity_ref))
        services = self.evidence.services(program) if request.artifact_version_refs else None
        for identity_ref in request.artifact_version_refs:
            assert services is not None
            artifact = services.registry.get(UUID(identity_ref))
            if artifact.manifest.provenance.program_id != str(program):
                raise ResearchNotFound("blackboard artifact unavailable")
        with self.storage.connection() as conn, attributed(conn, principal.name, request_id):
            self.storage.program(conn, program, lock=True)
            body = request.model_dump(mode="json")
            previous = self.storage.operation(conn, program, "blackboard-note", str(identity), body)
            if previous is None:
                for parent in request.parent_record_refs:
                    if (
                        conn.execute(
                            "SELECT 1 FROM research.manual_records WHERE id=%s AND program_id=%s",
                            [UUID(parent), program],
                        ).fetchone()
                        is None
                    ):
                        raise ResearchNotFound("blackboard parent unavailable")
                self.storage.insert(
                    conn,
                    "manual_records",
                    body,
                    principal.name,
                    request_id,
                    program,
                    identity=identity,
                )
                self.storage.remember(
                    conn,
                    program,
                    "blackboard-note",
                    str(identity),
                    body,
                    body,
                    principal.name,
                    request_id,
                )
        return request

    def notes(
        self, principal: ServicePrincipal, program: UUID, *, after: UUID | None, limit: int
    ) -> BlackboardPage:
        scope(principal, program)
        if not 1 <= limit <= self.policy.max_page_size:
            raise InvalidResearchRequest("invalid page size")
        with self.storage.connection() as conn:
            self.storage.program(conn, program)
            cursor = None
            if after is not None:
                cursor = conn.execute(
                    "SELECT created_at,id FROM research.manual_records "
                    "WHERE id=%s AND program_id=%s",
                    [after, program],
                ).fetchone()
                if cursor is None:
                    raise ResearchNotFound("blackboard cursor unavailable")
            rows = conn.execute(
                "SELECT id,payload FROM research.manual_records WHERE program_id=%s "
                + ("AND (created_at,id)>(%s,%s) " if cursor else "")
                + "ORDER BY created_at,id LIMIT %s",
                [program, *(cursor or ()), limit + 1],
            ).fetchall()
        selected = rows[:limit]
        value = BlackboardPage(
            items=[BlackboardRecord.model_validate(row[1]) for row in selected],
            next_after_id=selected[-1][0] if selected else after,
            has_more=len(rows) > limit,
        )
        if len(value.model_dump_json().encode()) > self.policy.max_page_bytes:
            raise InvalidResearchRequest("page exceeds size bound; request fewer records")
        return value
