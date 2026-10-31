"""Research jobs (P4.10, PLAN Sections 11.1 and 13.3).

A job is one owner brief: validated, seeds published as human_seed versions (generation
0), a charter derived deterministically and one program started. The front door has
already run the owner-only scan; research-api stores its verdict. Job states persist in
research_jobs and every change is a job event, a JOB_STATE_CHANGED trace step and a log
line bound to the job id.
"""

import hashlib
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from qfr_core.config import canonical_json
from qfr_core.contracts import FactorManifest, ResearchBrief, SeedExpression
from qfr_core.correlation import bind, current
from qfr_core.dsl import validate
from qfr_core.ids import uuid7
from qfr_core.research_api import (
    BriefScan,
    JobEvent,
    JobEventPage,
    JobView,
    SubmitJobResponse,
    TimelineEstimate,
)
from sqlalchemy import text
from sqlalchemy.engine import Connection

from qfr_research.charter import BriefRejected, check_constraints, derive_charter, select_islands
from qfr_research.clients import ServiceRefused, ServiceUnavailable
from qfr_research.db import RESEARCH_LOCK, dumps
from qfr_research.env import QFR_CORE_VERSION, ResearchEnv
from qfr_research.store import Ctx, audit, job_event

OPEN_STATES = (
    "SUBMITTED",
    "VALIDATED",
    "RUNNING",
    "WAITING_FOR_EVALUATION",
    "DELIVERABLE_READY",
    "DELIVERED",
)


class JobNotFound(LookupError):
    pass


class JobConflict(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code, self.message = code, message


JOB_VIEW_SQL = (
    "SELECT j.*, p.status AS program_status, p.charter_version, "
    "(SELECT count(*) FROM generations g WHERE g.program_id = j.program_id AND g.seq > 0 "
    "AND g.state = 'CLOSED') AS generations_run, "
    "(SELECT count(*) FROM candidate_versions v JOIN candidates c ON c.candidate_id = "
    "v.candidate_id WHERE c.program_id = j.program_id AND c.operator <> 'human_seed') "
    "AS publications, "
    "(SELECT count(*) FROM deliverables d WHERE d.job_id = j.job_id) AS deliverable_count "
    "FROM research_jobs j LEFT JOIN programs p ON p.program_id = j.program_id"
)


def job_view(row: Any) -> JobView:
    return JobView(
        job_id=row.job_id,
        short_code=row.short_code,
        title=row.brief["title"],
        mode=row.brief["mode"],
        state=row.state,
        paused=row.program_status == "paused",
        program_id=row.program_id,
        parent_job_id=row.parent_job_id,
        submitted_at=row.submitted_at,
        updated_at=row.updated_at,
        closed_at=row.closed_at,
        close_decision=row.close_decision,
        stop_reason=row.stop_reason,
        deliverable_criteria=row.deliverable_criteria,
        budget=row.budget,
        cost_cny=float(row.cost_cny),
        generations_run=int(row.generations_run or 0),
        publications=int(row.publications or 0),
        deliverables=int(row.deliverable_count or 0),
        seed_version_ids=row.seed_version_ids,
        charter_version=int(row.charter_version or 0),
        next_generation_at=row.next_generation_at,
    )


class JobService:
    def __init__(self, env: ResearchEnv) -> None:
        self.env = env

    # Reads -------------------------------------------------------------------------------

    def get(self, conn: Connection, job_id: UUID) -> JobView:
        row = conn.execute(text(JOB_VIEW_SQL + " WHERE j.job_id = :j"), {"j": job_id}).first()
        if row is None:
            raise JobNotFound(f"no job {job_id}")
        return job_view(row)

    def list_jobs(
        self, conn: Connection, state: str | None, limit: int, cursor: UUID | None
    ) -> list[JobView]:
        rows = conn.execute(
            text(
                JOB_VIEW_SQL + " WHERE (CAST(:s AS text) IS NULL OR j.state = :s) AND "
                "(CAST(:c AS uuid) IS NULL OR j.job_id < :c) ORDER BY j.job_id DESC LIMIT :n"
            ),
            {"s": state, "c": cursor, "n": limit},
        ).all()
        return [job_view(r) for r in rows]

    def events(self, conn: Connection, job_id: UUID, after_seq: int, limit: int) -> JobEventPage:
        self.get(conn, job_id)
        rows = conn.execute(
            text(
                "SELECT event_id, job_id, seq, at, kind, payload FROM job_events WHERE "
                "job_id = :j AND seq > :s ORDER BY seq LIMIT :n"
            ),
            {"j": job_id, "s": after_seq, "n": limit},
        ).all()
        items = [JobEvent.model_validate(dict(r._mapping)) for r in rows]
        return JobEventPage(items=items, next_after_seq=items[-1].seq if items else after_seq)

    # State changes -----------------------------------------------------------------------

    def set_state(
        self,
        conn: Connection,
        job_id: UUID,
        state: str,
        *,
        reason: str,
        close_decision: str | None = None,
        principal: str = "research",
    ) -> None:
        env = self.env
        previous = conn.execute(
            text("SELECT state, program_id FROM research_jobs WHERE job_id = :j FOR UPDATE"),
            {"j": job_id},
        ).one()
        if previous.state == state:
            return
        now = env.clock.now()
        conn.execute(
            text(
                "UPDATE research_jobs SET state = :s, updated_at = :now, closed_at = CASE WHEN "
                ":s = 'CLOSED' THEN :now ELSE closed_at END, close_decision = coalesce(:d, "
                "close_decision), stop_reason = CASE WHEN :s = 'CLOSED' THEN :r ELSE stop_reason "
                "END WHERE job_id = :j"
            ),
            {"s": state, "now": now, "d": close_decision, "r": reason, "j": job_id},
        )
        if state == "CLOSED" and previous.program_id is not None:
            conn.execute(
                text(
                    "UPDATE programs SET status = 'closed', updated_at = :now WHERE program_id = :p"
                ),
                {"now": now, "p": previous.program_id},
            )
        job_event(
            conn,
            env.clock,
            job_id,
            "state_changed",
            {
                "from": previous.state,
                "to": state,
                "reason": reason,
                "close_decision": close_decision,
            },
        )
        env.trace.step(
            conn,
            "JOB_STATE_CHANGED",
            Ctx(job_id=job_id, program_id=previous.program_id),
            actor=principal,
            inputs={"from": previous.state},
            payload={"to": state, "reason": reason, "close_decision": close_decision},
        )
        env.logger.logger.info(
            "job_state_changed",
            outcome="ok",
            job_id=str(job_id),
            payload={"from": previous.state, "to": state, "reason": reason},
        )

    # Submission --------------------------------------------------------------------------

    def submit(self, brief: ResearchBrief, scan: BriefScan, principal: str) -> SubmitJobResponse:
        env = self.env
        body = brief.model_dump(mode="json")
        submit_key = hashlib.sha256(canonical_json(body).encode()).hexdigest()
        with env.db.read() as conn:
            existing = conn.execute(
                text("SELECT job_id FROM research_jobs WHERE submit_key = :k"), {"k": submit_key}
            ).scalar()
            if existing is not None:
                return self._response(conn, existing, created=False)
        check_constraints(brief, env.limits)
        expected = {str(v) for v in brief.seeds.version_ids}
        if not expected <= {str(v) for v in scan.referenced_version_ids}:
            raise BriefRejected("SCAN_INCOMPLETE", "the scan did not cover every seed version")
        for seed in brief.seeds.expressions:
            check = validate(seed.expression, env.limits)
            if not check.ok:
                raise BriefRejected("SEED_INVALID", f"seed {seed.name} is invalid", check.errors)
        seed_versions = self._resolve_seeds(brief)
        if brief.parent_job_id is not None:
            with env.db.read() as conn:
                if (
                    conn.execute(
                        text("SELECT 1 FROM research_jobs WHERE job_id = :j"),
                        {"j": brief.parent_job_id},
                    ).first()
                    is None
                ):
                    raise BriefRejected("PARENT_JOB_UNKNOWN", "parent_job_id names no job")
        job_id, program_id, generation_id = uuid7(), uuid7(), uuid7()
        islands = select_islands(brief, env.config.service)
        now = env.clock.now()
        with bind(job_id=str(job_id), program_id=str(program_id)):
            env.logger.logger.info(
                "job_submit_received",
                outcome="ok",
                payload={"mode": brief.mode, "seeds": len(brief.seeds.expressions)},
            )
            with env.db.transaction(lock=True) as conn:
                seq: int = conn.execute(
                    text("SELECT nextval('research_job_short_code_seq')")
                ).scalar_one()
                conn.execute(
                    text(
                        "INSERT INTO research_jobs (job_id, short_code, submit_key, brief, scan, "
                        "state, program_id, parent_job_id, deliverable_criteria, budget, "
                        "seed_version_ids, timeline, submitted_at, updated_at, deadline_at, "
                        "principal, request_id) VALUES (:j, :sc, :k, CAST(:b AS jsonb), "
                        "CAST(:scan AS jsonb), 'SUBMITTED', NULL, :parent, CAST(:dc AS jsonb), "
                        "CAST(:bud AS jsonb), '[]'::jsonb, CAST(:tl AS jsonb), :now, :now, :dl, "
                        ":pr, :r)"
                    ),
                    {
                        "j": job_id,
                        "sc": f"J-{seq:04d}",
                        "k": submit_key,
                        "b": dumps(body),
                        "scan": dumps(scan.model_dump(mode="json")),
                        "parent": brief.parent_job_id,
                        "dc": dumps(brief.deliverable.model_dump(mode="json")),
                        "bud": dumps(brief.budget.model_dump(mode="json")),
                        "tl": dumps(self.timeline(brief).model_dump(mode="json")),
                        "now": now,
                        "dl": now + timedelta(days=brief.budget.max_wall_clock_days),
                        "pr": principal,
                        "r": current().get("request_id", str(job_id)),
                    },
                )
                job_event(conn, env.clock, job_id, "submitted", {"title": brief.title})
                env.trace.step(
                    conn,
                    "BRIEF_RECEIVED",
                    Ctx(job_id=job_id),
                    actor_kind="host_agent",
                    actor=principal,
                    inputs={"submit_key": submit_key},
                    payload={"brief": body, "scan": scan.model_dump(mode="json")},
                )
                audit(conn, env.clock, principal, "job.submit", "job", job_id, {"mode": brief.mode})
            # Seeds are published outside the database transaction (an HTTP call), then
            # recorded; a retried submission republishes idempotently by publish key.
            published = self._publish_seeds(brief, job_id, program_id, generation_id, islands)
            seed_ids = [str(v) for v in seed_versions] + [str(p["version_id"]) for p in published]
            charter = derive_charter(
                brief, env.charter_defaults, env.config.service, islands, seed_ids
            )
            with env.db.transaction(lock=True) as conn:
                self._start_program(
                    conn,
                    brief,
                    job_id,
                    program_id,
                    generation_id,
                    charter,
                    islands,
                    published,
                    seed_ids,
                    principal,
                )
                self.set_state(
                    conn,
                    job_id,
                    "VALIDATED",
                    reason="brief, scan and seeds accepted",
                    principal=principal,
                )
                self.set_state(
                    conn, job_id, "RUNNING", reason="program started", principal=principal
                )
            with env.db.read() as conn:
                return self._response(conn, job_id, created=True)

    def _response(self, conn: Connection, job_id: UUID, created: bool) -> SubmitJobResponse:
        job = self.get(conn, job_id)
        charter = (
            conn.execute(
                text("SELECT charter FROM programs WHERE job_id = :j"), {"j": job_id}
            ).scalar()
            or {}
        )
        timeline: dict[str, Any] = conn.execute(
            text("SELECT timeline FROM research_jobs WHERE job_id = :j"), {"j": job_id}
        ).scalar_one()
        return SubmitJobResponse(
            created=created,
            job=job,
            charter=charter,
            seed_version_ids=job.seed_version_ids,
            timeline=TimelineEstimate.model_validate(timeline),
        )

    def timeline(self, brief: ResearchBrief) -> TimelineEstimate:
        text_ = self.env.config.service.timeline[brief.deliverable.tier]
        return TimelineEstimate(
            tier=brief.deliverable.tier,
            first_reports=text_.first_reports,
            first_deliverable=text_.first_deliverable,
        )

    def _resolve_seeds(self, brief: ResearchBrief) -> list[UUID]:
        registry = self.env.registry
        found: list[UUID] = []
        try:
            for entry_id in brief.seeds.pool_entry_ids:
                for pool in ("factor", "strategy"):
                    try:
                        detail = registry._call("GET", f"/v1/pools/{pool}/entries/{entry_id}")
                        found.append(UUID(detail["entry"]["version_id"]))
                        break
                    except ServiceRefused:
                        continue
                else:
                    raise BriefRejected("POOL_ENTRY_UNKNOWN", f"no pool entry {entry_id}")
            for version_id in brief.seeds.version_ids:
                try:
                    registry.version(version_id)
                except ServiceRefused:
                    raise BriefRejected(
                        "VERSION_UNKNOWN", f"no published version {version_id}"
                    ) from None
                found.append(version_id)
        except ServiceUnavailable as error:
            raise BriefRejected("REGISTRY_UNAVAILABLE", str(error)) from error
        return list(dict.fromkeys(found))

    def _publish_seeds(
        self,
        brief: ResearchBrief,
        job_id: UUID,
        program_id: UUID,
        generation_id: UUID,
        islands: list[str],
    ) -> list[dict[str, Any]]:
        env = self.env
        published = []
        snapshot = env.snapshot_id if brief.seeds.expressions else None
        for seed in brief.seeds.expressions:
            hypothesis_id, candidate_id = uuid7(), uuid7()
            island = islands[0] if len(islands) == 1 else "I6" if "I6" in islands else islands[0]
            manifest = seed_manifest(
                seed,
                job_id,
                program_id,
                generation_id,
                island,
                hypothesis_id,
                candidate_id,
                snapshot or "",
                env.limits,
            )
            try:
                response = env.registry.publish(manifest, f"seed:{job_id}:{seed.name}")
            except ServiceRefused as error:
                raise BriefRejected("SEED_REFUSED", f"{seed.name}: {error.message}") from error
            except ServiceUnavailable as error:
                raise BriefRejected("REGISTRY_UNAVAILABLE", str(error)) from error
            published.append(
                {
                    "seed": seed,
                    "manifest": manifest,
                    "version": response.version,
                    "version_id": response.version.version_id,
                    "hypothesis_id": hypothesis_id,
                    "candidate_id": candidate_id,
                    "island": island,
                }
            )
        return published

    def _start_program(
        self,
        conn: Connection,
        brief: ResearchBrief,
        job_id: UUID,
        program_id: UUID,
        generation_id: UUID,
        charter: dict[str, Any],
        islands: list[str],
        published: list[dict[str, Any]],
        seed_ids: list[str],
        principal: str,
    ) -> None:
        env, now = self.env, self.env.clock.now()
        snapshot = env.snapshot_id
        conn.execute(
            text(
                "INSERT INTO programs (program_id, job_id, name, status, charter, charter_version, "
                "research_snapshot_id, created_at, updated_at, created_by) VALUES (:p, :j, :n, "
                "'active', CAST(:c AS jsonb), 1, :snap, :now, :now, :by)"
            ),
            {
                "p": program_id,
                "j": job_id,
                "n": brief.title,
                "c": dumps(charter),
                "snap": snapshot,
                "now": now,
                "by": principal,
            },
        )
        sha = hashlib.sha256(canonical_json(charter).encode()).hexdigest()
        conn.execute(
            text(
                "INSERT INTO program_charters (program_id, version, charter, sha256, reason, "
                "created_at, principal, request_id) VALUES (:p, 1, CAST(:c AS jsonb), :s, "
                "'derived from the brief', :now, :by, :r)"
            ),
            {
                "p": program_id,
                "c": dumps(charter),
                "s": sha,
                "now": now,
                "by": principal,
                "r": current().get("request_id", ""),
            },
        )
        for key in islands:
            conn.execute(
                text(
                    "INSERT INTO islands (island_id, program_id, island_key, theme, status) "
                    "VALUES (:i, :p, :k, :t, 'active')"
                ),
                {"i": uuid7(), "p": program_id, "k": key, "t": env.config.service.islands[key]},  # type: ignore[index]
            )
        # The seeds are generation 0: the first generation starts once their feedback is
        # complete (the monitor checks), at the latest after max_wait_hours; at once
        # without seeds.
        wait = timedelta(hours=float(charter["cadence"]["max_wait_hours"]))
        first = now + wait if seed_ids else now
        conn.execute(
            text(
                "INSERT INTO generations (generation_id, program_id, seq, state, charter_version, "
                "plan_source, created_at, started_at, ended_at, updated_at, summary) VALUES (:g, "
                ":p, 0, 'CLOSED', 1, 'seeds', :now, :now, :now, :now, CAST(:s AS jsonb))"
            ),
            {
                "g": generation_id,
                "p": program_id,
                "now": now,
                "s": dumps({"seeds_published": [str(p["version_id"]) for p in published]}),
            },
        )
        conn.execute(
            text(
                "UPDATE research_jobs SET program_id = :p, seed_version_ids = CAST(:s AS jsonb), "
                "next_generation_at = :next, updated_at = :now WHERE job_id = :j"
            ),
            {"p": program_id, "s": dumps(seed_ids), "next": first, "now": now, "j": job_id},
        )
        ctx = Ctx(job_id=job_id, program_id=program_id, generation_id=generation_id)
        self._record_seeds(conn, ctx, published, now)
        env.trace.step(
            conn,
            "SEEDS_PUBLISHED",
            Ctx(job_id=job_id, program_id=program_id),
            actor="research-api",
            inputs={
                "pool_entry_ids": [str(i) for i in brief.seeds.pool_entry_ids],
                "version_ids": [str(i) for i in brief.seeds.version_ids],
            },
            payload={
                "seed_version_ids": seed_ids,
                "published": [str(p["version_id"]) for p in published],
            },
        )
        env.trace.step(
            conn,
            "CHARTER_DERIVED",
            Ctx(job_id=job_id, program_id=program_id),
            actor="research-api",
            inputs={
                "brief_sha256": hashlib.sha256(
                    canonical_json(brief.model_dump(mode="json")).encode()
                ).hexdigest()
            },
            payload={"charter_version": 1, "charter": charter, "sha256": sha},
        )
        job_event(
            conn,
            env.clock,
            job_id,
            "program_started",
            {"program_id": str(program_id), "islands": islands, "seeds": seed_ids},
        )

    def _record_seeds(
        self, conn: Connection, ctx: Ctx, published: list[dict[str, Any]], now: datetime
    ) -> None:
        """A seed hypothesis and candidate per published seed, so traces and lineage work
        like for any other version (Section 14.5, human_seed)."""
        env = self.env
        if not published:
            return
        task_id = uuid7()
        conn.execute(
            text(
                "INSERT INTO tasks (task_id, generation_id, ordinal, type, island_key, brief, "
                "parent_version_ids, max_candidates, state, created_at, updated_at) VALUES (:t, "
                ":g, 0, 'explore', :i, 'Owner seeds from the brief', '[]'::jsonb, 1, 'done', "
                ":now, :now)"
            ),
            {"t": task_id, "g": ctx.generation_id, "i": published[0]["island"], "now": now},
        )
        for item in published:
            seed: SeedExpression = item["seed"]
            manifest: FactorManifest = item["manifest"]
            cctx = ctx.with_(task_id=task_id, candidate_id=item["candidate_id"])
            conn.execute(
                text(
                    "INSERT INTO hypotheses (hypothesis_id, program_id, island_key, task_id, "
                    "payload, status, source, created_at, updated_at) VALUES (:h, :p, :i, :t, "
                    "CAST(:pl AS jsonb), 'open', 'seed', :now, :now)"
                ),
                {
                    "h": item["hypothesis_id"],
                    "p": ctx.program_id,
                    "i": item["island"],
                    "t": task_id,
                    "pl": dumps(
                        {
                            "title": seed.name,
                            "mechanism": seed.rationale,
                            "falsification": manifest.rationale.falsification,
                        }
                    ),
                    "now": now,
                },
            )
            analysis = validate(seed.expression, env.limits).analysis
            assert analysis is not None
            conn.execute(
                text(
                    "INSERT INTO candidates (candidate_id, program_id, generation_id, task_id, "
                    "hypothesis_id, island_key, kind, operator, expression, canonical_hash, "
                    "payload, analysis, state, created_at, updated_at) VALUES (:c, :p, :g, :t, :h, "
                    ":i, 'factor', 'human_seed', :e, :ch, CAST(:pl AS jsonb), CAST(:a AS jsonb), "
                    "'published', :now, :now)"
                ),
                {
                    "c": item["candidate_id"],
                    "p": ctx.program_id,
                    "g": ctx.generation_id,
                    "t": task_id,
                    "h": item["hypothesis_id"],
                    "i": item["island"],
                    "e": seed.expression,
                    "ch": analysis.canonical_hash,
                    "pl": dumps(seed.model_dump(mode="json") | {"parent_version_ids": []}),
                    "a": dumps(analysis.model_dump(mode="json")),
                    "now": now,
                },
            )
            env.trace.step(
                conn,
                "DSL_VALIDATED",
                cctx,
                actor="research-api",
                inputs={"expression": seed.expression},
                payload={"ok": True, "analysis": analysis.model_dump(mode="json")},
            )
            version = item["version"]
            step_id = env.trace.step(
                conn,
                "PUBLISHED",
                cctx,
                actor="research-api",
                version_id=version.version_id,
                inputs={"publish_key": f"seed:{ctx.job_id}:{seed.name}", "operator": "human_seed"},
                payload={
                    "version_id": str(version.version_id),
                    "family_id": str(version.family_id),
                    "version_no": version.version_no,
                    "content_hash": version.content_hash,
                    "canonical_hash": version.canonical_hash,
                    "manifest": manifest.model_dump(mode="json"),
                },
            )
            conn.execute(
                text(
                    "INSERT INTO candidate_versions (candidate_id, version_id, family_id, "
                    "content_hash, published_at, step_id) VALUES (:c, :v, :f, :h, :at, :s)"
                ),
                {
                    "c": item["candidate_id"],
                    "v": version.version_id,
                    "f": version.family_id,
                    "h": version.content_hash,
                    "at": version.published_at,
                    "s": step_id,
                },
            )

    # Owner controls ----------------------------------------------------------------------

    def steer(self, job_id: UUID, note: str, scan: BriefScan, principal: str) -> JobView:
        env = self.env
        with env.db.transaction(lock=True) as conn:
            job = self.get(conn, job_id)
            if job.state == "CLOSED" or job.program_id is None:
                raise JobConflict("JOB_CLOSED", "a closed job cannot be steered")
            charter: dict[str, Any] = conn.execute(
                text("SELECT charter FROM programs WHERE program_id = :p FOR UPDATE"),
                {"p": job.program_id},
            ).scalar_one()
            version = job.charter_version + 1
            charter["steering"] = list(charter.get("steering", [])) + [
                {"at": env.clock.now().isoformat(), "note": note, "version": version}
            ]
            sha = hashlib.sha256(canonical_json(charter).encode()).hexdigest()
            conn.execute(
                text(
                    "UPDATE programs SET charter = CAST(:c AS jsonb), charter_version = :v, "
                    "updated_at = :now WHERE program_id = :p"
                ),
                {"c": dumps(charter), "v": version, "now": env.clock.now(), "p": job.program_id},
            )
            conn.execute(
                text(
                    "INSERT INTO program_charters (program_id, version, charter, sha256, reason, "
                    "created_at, principal, request_id) VALUES (:p, :v, CAST(:c AS jsonb), :s, "
                    "'steering note', :now, :by, :r)"
                ),
                {
                    "p": job.program_id,
                    "v": version,
                    "c": dumps(charter),
                    "s": sha,
                    "now": env.clock.now(),
                    "by": principal,
                    "r": current().get("request_id", ""),
                },
            )
            job_event(conn, env.clock, job_id, "steered", {"charter_version": version})
            env.trace.step(
                conn,
                "STEERING_ADDED",
                Ctx(job_id=job_id, program_id=job.program_id),
                actor_kind="host_agent",
                actor=principal,
                inputs={"scan": scan.model_dump(mode="json")},
                payload={"note": note, "charter_version": version},
            )
            audit(conn, env.clock, principal, "job.steer", "job", job_id, {"version": version})
            return self.get(conn, job_id)

    def pause(self, job_id: UUID, paused: bool, principal: str) -> JobView:
        env = self.env
        with env.db.transaction(lock=True) as conn:
            job = self.get(conn, job_id)
            if job.state == "CLOSED" or job.program_id is None:
                raise JobConflict("JOB_CLOSED", "a closed job cannot be paused or resumed")
            conn.execute(
                text("UPDATE programs SET status = :s, updated_at = :now WHERE program_id = :p"),
                {
                    "s": "paused" if paused else "active",
                    "now": env.clock.now(),
                    "p": job.program_id,
                },
            )
            if not paused:
                conn.execute(
                    text(
                        "UPDATE research_jobs SET next_generation_at = "
                        "coalesce(next_generation_at, :now), updated_at = :now WHERE job_id = :j"
                    ),
                    {"now": env.clock.now(), "j": job_id},
                )
            kind = "paused" if paused else "resumed"
            job_event(conn, env.clock, job_id, kind, {})
            audit(
                conn,
                env.clock,
                principal,
                f"job.{'pause' if paused else 'resume'}",
                "job",
                job_id,
                {},
            )
            env.logger.logger.info(f"job_{kind}", outcome="ok", job_id=str(job_id))
            return self.get(conn, job_id)

    def cancel(self, job_id: UUID, principal: str) -> JobView:
        env = self.env
        with env.db.transaction(lock=True) as conn:
            job = self.get(conn, job_id)
            if job.state == "CLOSED":
                return job
            self.set_state(
                conn,
                job_id,
                "CLOSED",
                reason="cancelled by the owner",
                close_decision="cancelled",
                principal=principal,
            )
            audit(conn, env.clock, principal, "job.cancel", "job", job_id, {})
            return self.get(conn, job_id)


def seed_manifest(
    seed: SeedExpression,
    job_id: UUID,
    program_id: UUID,
    generation_id: UUID,
    island: str,
    hypothesis_id: UUID,
    candidate_id: UUID,
    snapshot_id: str,
    limits: Any,
) -> FactorManifest:
    analysis = validate(seed.expression, limits).analysis
    assert analysis is not None
    return FactorManifest.model_validate(
        {
            "schema_version": "1",
            "kind": "factor",
            "family_id": None,
            "name": seed.name,
            "title": seed.name.replace("_", " ")[:120],
            "implementation": {"language": "qfr-dsl/1", "expression": seed.expression},
            "declared": {
                "expected_sign": seed.expected_sign,
                "horizon_days": seed.horizon_days,
                "fields_used": analysis.fields,
                "max_lookback_days": analysis.max_lookback_days,
            },
            "rationale": {
                "hypothesis_id": str(hypothesis_id),
                "summary": seed.rationale[:1500],
                "mechanism": seed.rationale[:1500],
                "falsification": "No relation with forward returns in the declared direction.",
                "change_summary": None,
            },
            "provenance": {
                "job_id": str(job_id),
                "program_id": str(program_id),
                "generation_id": str(generation_id),
                "island_id": island,
                "operator": "human_seed",
                "parent_version_ids": [],
                "agent_runs": [],
                "trace_ref": str(candidate_id),
                "research_snapshot_id": snapshot_id,
                "qfr_core_version": QFR_CORE_VERSION,
            },
            "review": {"verdict_id": str(uuid7()), "rounds": 0},
        }
    )


def lock(conn: Connection) -> None:
    conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": RESEARCH_LOCK})
