"""Durable human-driven jobs; client connections never own their lifecycle."""

from uuid import UUID

from psycopg import Connection
from psycopg.types.json import Jsonb
from qfr_core.access import ServicePrincipal
from qfr_core.contracts.artifacts import ArtifactReference
from qfr_core.contracts.data import ResearchDatasetRegistration
from qfr_core.contracts.delivery import AdmittedDeliveryContext
from qfr_core.contracts.enums import JobState
from qfr_core.contracts.intake import InputBundle
from qfr_core.contracts.jobs import JobRecord, ResearchBrief
from qfr_core.contracts.publication import PublishedArtifact
from qfr_core.contracts.research import (
    InputValidation,
    JobAdmission,
    JobControl,
    JobPage,
    JobStatus,
    NextAction,
)
from qfr_core.data_layer.catalog import registered_snapshot
from qfr_core.delivery_rules import (
    admission_hash,
    content_sha256,
    job_config_hash,
    validate_pilot_delivery_gate,
)
from qfr_core.identifiers import uuid7

from qfr_research.api.errors import InvalidResearchRequest, ResearchConflict, ResearchNotFound
from qfr_research.api.programs import Programs
from qfr_research.api.storage import scope
from qfr_research.db import attributed
from qfr_research.db.queue import enqueue

TERMINAL = {JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED}


class Jobs(Programs):
    def intent(self, program: UUID, value: JobAdmission) -> None:
        bundle, brief = value.input_bundle, value.brief
        validate_pilot_delivery_gate(brief.exit_gate)
        if (
            brief.project_id != str(program)
            or brief.input_bundle_id != bundle.bundle_id
            or brief.objective != bundle.objective
            or brief.frozen_config_hash != job_config_hash(bundle)
            or bundle.job_config.proposed_exit_gate_ref != brief.exit_gate.gate_id
            or set(brief.baseline_artifact_ids) != set(bundle.baseline_refs)
            or set(bundle.requested_deliverables)
            != {d.name for d in brief.exit_gate.required_deliverables}
            or not set(bundle.data_refs) <= set(bundle.job_config.permitted_dataset_ids)
            or brief.role_profiles != bundle.job_config.role_profile_refs
        ):
            raise InvalidResearchRequest("input, brief, permission or frozen configuration differs")
        for key in (
            "authorized_spend_ref",
            "authorized_cost_usd",
            "max_wall_clock_seconds",
            "max_generations",
        ):
            if getattr(brief.budgets, key) != getattr(bundle.job_config, key):
                raise InvalidResearchRequest("brief and input budgets differ")
        if (
            len(bundle.source_assets) > self.policy.max_source_assets
            or max(
                len(bundle.data_refs), len(bundle.baseline_refs), len(brief.exit_gate.protocol_refs)
            )
            > self.policy.max_artifacts
        ):
            raise InvalidResearchRequest("admission exceeds configured reference bounds")
        if len(set(bundle.data_refs)) != len(bundle.data_refs) or len(
            set(bundle.baseline_refs)
        ) != len(bundle.baseline_refs):
            raise InvalidResearchRequest("duplicate admission reference")

    def validate_input(
        self, principal: ServicePrincipal, program: UUID, value: JobAdmission
    ) -> InputValidation:
        scope(principal, program, "research_lead")
        self.intent(program, value)
        with self.storage.connection() as conn:
            self.storage.program(conn, program)
            return self._validation(conn, program, value)

    def _validation(self, conn: Connection, program: UUID, value: JobAdmission) -> InputValidation:
        bundle, brief = value.input_bundle, value.brief
        unresolved = list(bundle.unresolved_requirements)
        for requirement in bundle.data_requirements:
            unresolved.extend(requirement.unresolved)
        data, baselines, assets = [], [], []
        for identity in bundle.data_refs:
            row = conn.execute(
                "SELECT payload FROM research.dataset_registrations "
                "WHERE program_id=%s AND dataset_version_id=%s",
                [program, identity],
            ).fetchone()
            if row is None:
                unresolved.append("dataset_not_registered:" + identity)
            else:
                registration = ResearchDatasetRegistration.model_validate(row[0])
                registered_snapshot(self.research_root, registration)
                data.append(identity)
        for identity in bundle.baseline_refs:
            row = conn.execute(
                "SELECT payload FROM research.baseline_registrations "
                "WHERE program_id=%s AND artifact_version_id=%s",
                [program, UUID(identity)],
            ).fetchone()
            if row is None:
                unresolved.append("baseline_not_registered:" + identity)
            else:
                artifact = PublishedArtifact.model_validate(row[0])
                self.evidence.artifact(
                    program,
                    ArtifactReference(
                        artifact_version_id=identity, content_hash=artifact.manifest.content_hash
                    ),
                )
                baselines.append(identity)
        for asset in bundle.source_assets:
            self.evidence.source(program, asset)
            assets.append(asset.asset_id)
        if bundle.readiness == "ready":
            for reference in brief.exit_gate.protocol_refs:
                self.evidence.protocol_exists(program, reference)
        ready = bundle.readiness == "ready" and not unresolved
        waiting = bundle.readiness == "waiting_for_data" or any(
            v.startswith("dataset_not_registered:") for v in unresolved
        )
        return InputValidation(
            readiness="ready" if ready else "waiting_for_data" if waiting else "needs_input",
            unresolved_requirements=list(dict.fromkeys(unresolved)),
            data_refs_verified=data,
            baseline_refs_verified=baselines,
            source_assets_verified=assets,
            runnable=ready,
        )

    def _context(
        self, conn: Connection, principal: ServicePrincipal, identity: UUID, *, lock: bool = False
    ) -> tuple[AdmittedDeliveryContext, int, str | None]:
        row = conn.execute(
            "SELECT j.payload,j.revision,j.program_id,j.state,j.config_hash,j.payload_hash,"
            "j.gate_spec_hash,b.payload,i.payload,j.paused_from_state "
            "FROM research.research_jobs j "
            "JOIN research.briefs b ON (b.id,b.program_id)=(j.brief_id,j.program_id) "
            "JOIN research.input_bundles i ON (i.id,i.program_id)=(j.input_bundle_id,j.program_id) "
            "WHERE j.id=%s" + (" FOR UPDATE OF j" if lock else ""),
            [identity],
        ).fetchone()
        if row is None:
            raise ResearchNotFound("research job unavailable")
        scope(principal, row[2])
        job, brief, bundle = (
            JobRecord.model_validate(row[0]),
            ResearchBrief.model_validate(row[7]),
            InputBundle.model_validate(row[8]),
        )
        if (
            job.job_id != str(identity)
            or job.project_id != str(row[2])
            or job.state.value != row[3]
            or job.config_hash != row[4]
            or job.payload_hash != row[5]
            or job.exit_gate.spec_hash != row[6]
            or job_config_hash(bundle) != job.config_hash
            or admission_hash(bundle, brief) != job.payload_hash
        ):
            raise InvalidResearchRequest("stored research intent failed verification")
        return (
            AdmittedDeliveryContext(
                schema_version="1", job=job, brief=brief, input_bundle=bundle, human_approval=None
            ),
            row[1],
            row[9],
        )

    def status(self, job: JobRecord, revision: int) -> JobStatus:
        actions: dict[JobState, NextAction] = {
            JobState.READY: "start",
            JobState.RUNNING: "manual_research",
            JobState.AWAITING_EVALUATION: "poll_released_feedback",
            JobState.VALIDATING_DELIVERY: "request_delivery_check",
            JobState.COMPLETED: "export",
            JobState.NEEDS_INPUT: "supply_new_intent",
            JobState.WAITING_FOR_DATA: "register_data",
            JobState.PAUSED: "resume",
            JobState.BUDGET_PAUSED: "budget_authorization",
            JobState.FAILED: "inspect_failure",
            JobState.CANCELLED: "none",
        }
        return JobStatus(
            job=job,
            revision=revision,
            next_action=actions.get(job.state, "none"),
            polling_seconds=self.policy.polling_seconds,
        )

    def get_job(self, principal: ServicePrincipal, identity: UUID) -> JobStatus:
        with self.storage.connection() as conn:
            context, revision, _ = self._context(conn, principal, identity)
            return self.status(context.job, revision)

    def admit(
        self, principal: ServicePrincipal, program: UUID, value: JobAdmission, request_id: UUID
    ) -> JobStatus:
        scope(principal, program, "research_lead")
        self.intent(program, value)
        body = value.model_dump(mode="json")
        with self.storage.connection() as conn, attributed(conn, principal.name, request_id):
            previous = self.storage.operation(
                conn, program, "job-admission", value.idempotency_key, body
            )
            if previous is not None:
                context, revision, _ = self._context(conn, principal, UUID(previous["job_id"]))
                return self.status(context.job, revision)
            if self.storage.program(conn, program, lock=True)[2] != "active":
                raise ResearchConflict("program is not active")
            validation = self._validation(conn, program, value)
            bundle, brief = value.input_bundle, value.brief
            stamp = self.storage.now(conn)
            if brief.exit_gate.frozen_at > stamp:
                raise InvalidResearchRequest("exit gate is dated in the future")
            bundle_sha = content_sha256(bundle.model_dump(mode="json"))
            # Serialize reused bundle keys across different submit keys.
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                [f"research-bundle:{program}:{bundle.bundle_id}"],
            )
            original = conn.execute(
                "SELECT id,sha256 FROM research.input_bundles "
                "WHERE program_id=%s AND bundle_key=%s",
                [program, bundle.bundle_id],
            ).fetchone()
            if original is not None and original[1] != bundle_sha:
                raise ResearchConflict("input bundle identity already binds different bytes")
            bundle_id = (
                original[0]
                if original
                else self.storage.insert(
                    conn,
                    "input_bundles",
                    bundle.model_dump(mode="json"),
                    principal.name,
                    request_id,
                    program,
                    bundle_key=bundle.bundle_id,
                    sha256=bundle_sha,
                )
            )
            for asset in sorted(bundle.source_assets, key=lambda v: v.asset_id):
                conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                    [f"research-source:{program}:{asset.asset_id}"],
                )
                existing = conn.execute(
                    "SELECT payload FROM research.source_assets "
                    "WHERE program_id=%s AND asset_key=%s",
                    [program, asset.asset_id],
                ).fetchone()
                if existing is not None and existing[0] != asset.model_dump(mode="json"):
                    raise ResearchConflict("source identity changed")
                if existing is None:
                    self.storage.insert(
                        conn,
                        "source_assets",
                        asset.model_dump(mode="json"),
                        principal.name,
                        request_id,
                        program,
                        asset_key=asset.asset_id,
                        sha256=asset.sha256,
                        size_bytes=asset.bytes,
                    )
            brief_id = self.storage.insert(
                conn,
                "briefs",
                brief.model_dump(mode="json"),
                principal.name,
                request_id,
                program,
                input_bundle_id=bundle_id,
                sha256=content_sha256(brief.model_dump(mode="json")),
            )
            identity = uuid7()
            state = JobState(validation.readiness)
            job = JobRecord(
                schema_version="1",
                job_id=str(identity),
                project_id=str(program),
                idempotency_key=value.idempotency_key,
                payload_hash=admission_hash(bundle, brief),
                input_bundle_id=bundle.bundle_id,
                brief_id=brief.brief_id,
                config_hash=job_config_hash(bundle),
                provider_profiles_ref="human-driven-stage4-no-model-calls",
                public_protocol_card_ref=brief.exit_gate.protocol_refs[0],
                authorized_spend_ref=bundle.job_config.authorized_spend_ref,
                exit_gate=brief.exit_gate,
                state=state,
                generation_id=None,
                evaluator_status_ref=None,
                checkpoint_refs=[],
                reason="blocked_on_data"
                if state == JobState.WAITING_FOR_DATA
                else "required_input_missing"
                if state == JobState.NEEDS_INPUT
                else None,
                receipt=None,
                created_at=stamp,
                updated_at=stamp,
            )
            self.storage.insert(
                conn,
                "research_jobs",
                job.model_dump(mode="json"),
                principal.name,
                request_id,
                program,
                identity=identity,
                input_bundle_id=bundle_id,
                brief_id=brief_id,
                idempotency_key=value.idempotency_key,
                payload_hash=job.payload_hash,
                config_hash=job.config_hash,
                gate_spec_hash=job.exit_gate.spec_hash,
                state=state.value,
                updated_at=stamp,
            )
            enqueue(
                conn,
                {"mode": "human-driven", "job_id": str(identity)},
                program_id=program,
                research_job_id=identity,
                queue="manual-research",
                enqueue_key="admitted:" + str(identity),
                principal=principal.name,
                request_id=request_id,
                run_after=stamp,
            )
            self.storage.remember(
                conn,
                program,
                "job-admission",
                value.idempotency_key,
                body,
                {"job_id": str(identity)},
                principal.name,
                request_id,
            )
            return self.status(job, 1)

    def save_job(
        self,
        conn: Connection,
        job: JobRecord,
        revision: int,
        *,
        delivery_ref: UUID | None = None,
        paused_from: str | None = None,
    ) -> JobStatus:
        job = JobRecord.model_validate(
            {
                **job.model_dump(),
                "updated_at": self.storage.now(conn),
            }
        )
        row = conn.execute(
            "UPDATE research.research_jobs SET payload=%s,state=%s,"
            "revision=revision+1,updated_at=%s,"
            "delivery_ref_id=coalesce(%s,delivery_ref_id),paused_from_state=%s "
            "WHERE id=%s AND revision=%s RETURNING revision",
            [
                Jsonb(job.model_dump(mode="json")),
                job.state.value,
                job.updated_at,
                delivery_ref,
                paused_from,
                UUID(job.job_id),
                revision,
            ],
        ).fetchone()
        if row is None:
            raise ResearchConflict("job revision changed")
        if job.state in TERMINAL:
            conn.execute(
                "UPDATE research.jobs SET state='cancelled',locked_by=NULL,"
                "lease_until=NULL,fence=fence+1 "
                "WHERE research_job_id=%s AND program_id=%s AND state IN ('queued','running')",
                [UUID(job.job_id), UUID(job.project_id)],
            )
        return self.status(job, row[0])

    def control(
        self, principal: ServicePrincipal, identity: UUID, value: JobControl, request_id: UUID
    ) -> JobStatus:
        with self.storage.connection() as conn, attributed(conn, principal.name, request_id):
            context, revision, paused = self._context(conn, principal, identity, lock=True)
            job, program = context.job, UUID(context.job.project_id)
            scope(principal, program, "research_lead")
            body = value.model_dump(mode="json")
            previous = self.storage.operation(
                conn, program, "job-control:" + str(identity), value.operation_key, body
            )
            if previous is not None:
                return JobStatus.model_validate(previous)
            if value.expected_revision != revision or job.state in TERMINAL:
                raise ResearchConflict("job is terminal or revision changed")
            state, reason, paused_from = job.state, job.reason, None
            if value.action == "cancel":
                state, reason = JobState.CANCELLED, None
            elif value.action == "pause" and job.state not in {
                JobState.PAUSED,
                JobState.BUDGET_PAUSED,
            }:
                paused_from, state, reason = job.state.value, JobState.PAUSED, "operator_pause"
            elif value.action == "start" and job.state == JobState.READY:
                state, reason = JobState.RUNNING, None
            elif value.action == "await_evaluation" and job.state == JobState.RUNNING:
                state, reason = JobState.AWAITING_EVALUATION, None
            elif value.action == "resume" and job.state == JobState.PAUSED and paused:
                state = JobState(paused)
                reason = (
                    "blocked_on_data"
                    if state == JobState.WAITING_FOR_DATA
                    else "required_input_missing"
                    if state == JobState.NEEDS_INPUT
                    else None
                )
            elif value.action == "resume" and job.state == JobState.WAITING_FOR_DATA:
                validation = self._validation(
                    conn,
                    program,
                    JobAdmission(
                        idempotency_key=job.idempotency_key,
                        input_bundle=context.input_bundle,
                        brief=context.brief,
                    ),
                )
                if not validation.runnable:
                    raise ResearchConflict("required data or input remains unresolved")
                state, reason = JobState.READY, None
            else:
                raise ResearchConflict("job action is not valid in its current state")
            if (
                state in {JobState.READY, JobState.RUNNING}
                and self.storage.program(conn, program, lock=True)[2] != "active"
            ):
                raise ResearchConflict("program is not active")
            updated = JobRecord.model_validate(
                {**job.model_dump(), "state": state, "reason": reason}
            )
            result = self.save_job(conn, updated, revision, paused_from=paused_from)
            self.storage.remember(
                conn,
                program,
                "job-control:" + str(identity),
                value.operation_key,
                body,
                result.model_dump(mode="json"),
                principal.name,
                request_id,
            )
            return result

    def jobs(
        self, principal: ServicePrincipal, program: UUID, *, after: UUID | None, limit: int
    ) -> JobPage:
        scope(principal, program)
        if not 1 <= limit <= self.policy.max_page_size:
            raise InvalidResearchRequest("invalid job page size")
        with self.storage.connection() as conn:
            self.storage.program(conn, program)
            cursor = None
            if after is not None:
                cursor = conn.execute(
                    "SELECT created_at,id FROM research.research_jobs "
                    "WHERE id=%s AND program_id=%s",
                    [after, program],
                ).fetchone()
                if cursor is None:
                    raise ResearchNotFound("job cursor unavailable")
            rows = conn.execute(
                "SELECT id FROM research.research_jobs WHERE program_id=%s "
                + ("AND (created_at,id)>(%s,%s) " if cursor else "")
                + "ORDER BY created_at,id LIMIT %s",
                [program, *(cursor or ()), limit + 1],
            ).fetchall()
            selected = rows[:limit]
            contexts = [self._context(conn, principal, row[0]) for row in selected]
            result = JobPage(
                items=[self.status(c.job, v) for c, v, _ in contexts],
                next_after_id=selected[-1][0] if selected else after,
                has_more=len(rows) > limit,
            )
            if len(result.model_dump_json().encode()) > self.policy.max_page_bytes:
                raise InvalidResearchRequest("page exceeds size bound; request fewer jobs")
            return result
