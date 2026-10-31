"""research-api: the research control API (P4.10, PLAN Section 16.7), called only by qfr-mcp.

It accepts only the control token. It reads and writes research_db, publishes seeds
through registry-api with the publisher token, and reads released reports through the
cache; none of its routes reaches the evaluation zone, and it holds no provider key
(BND-05, BND-07). Deliverables are served without owner-grade evidence: the front door
adds it.
"""

import asyncio
import json
import os
import secrets
import time
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime, timedelta
from datetime import time as dtime
from pathlib import Path
from typing import Annotated, Any, Literal, TypeVar
from uuid import UUID

import uvicorn
from fastapi import FastAPI, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from qfr_core.config import RuntimeSettings
from qfr_core.correlation import bind, current, from_headers
from qfr_core.logging import JsonLogger
from qfr_core.registry_api import ApiError, Health
from qfr_core.research_api import (
    CostReport,
    CostRow,
    DeliverablePage,
    DeliverableView,
    GenerationPage,
    GenerationView,
    JobEventPage,
    JobPage,
    JobView,
    JobWait,
    LineageHop,
    ProbeReport,
    ResearchLineage,
    ResearchSummary,
    SteerRequest,
    SubmitJobRequest,
    SubmitJobResponse,
    TraceView,
)
from sqlalchemy import text
from sqlalchemy.engine import Connection
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from qfr_research.charter import BriefRejected
from qfr_research.db import dumps
from qfr_research.env import ResearchEnv
from qfr_research.feedback import reports_for
from qfr_research.jobs import JobConflict, JobNotFound, JobService
from qfr_research.monitor import JobMonitor
from qfr_research.store import audit
from qfr_research.traces import TraceNotFound, ancestors, export, trace_hash

SERVICE = "research-api"
PRINCIPAL = "control"
T = TypeVar("T")
ERRORS: dict[int | str, dict[str, Any]] = {c: {"model": ApiError} for c in (400, 401, 404, 409)}
GROUPS = {
    "job": "job_id::text",
    "generation": "generation_id::text",
    "provider": "provider",
    "model": "model",
    "role": "role",
    "day": "to_char(at AT TIME ZONE 'UTC', 'YYYY-MM-DD')",
}


class Failure(Exception):
    def __init__(self, status: int, code: str, message: str, details: Any = None) -> None:
        super().__init__(f"{code}: {message}")
        self.status, self.code, self.message, self.details = status, code, message, details


def error_response(status: int, code: str, message: str, details: Any = None) -> JSONResponse:
    if details is None:
        items: list[Any] = []
    elif isinstance(details, list):
        items = [d if isinstance(d, dict) else {"detail": str(d)} for d in details]
    else:
        items = [details if isinstance(details, dict) else {"detail": str(details)}]
    body = ApiError(
        error=code, message=message, request_id=current().get("request_id", ""), details=items
    )
    return JSONResponse(body.model_dump(mode="json"), status_code=status)


def install(app: FastAPI, token: str, logger: JsonLogger) -> None:
    """Bearer authentication on every route but /healthz, correlation and a log line."""
    if not token:
        raise ValueError("research-api needs RESEARCH_CONTROL_TOKEN")
    expected = f"Bearer {token}".encode()

    @app.middleware("http")
    async def correlate(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        context = from_headers(dict(request.headers))
        started = time.monotonic()
        with bind(**context):
            presented = (request.headers.get("authorization") or "").encode()
            authorized = secrets.compare_digest(presented, expected)
            if request.url.path != "/healthz" and not authorized:
                response: Response = error_response(
                    401, "UNAUTHORIZED", "a valid token is required"
                )
            else:
                with bind(principal=PRINCIPAL if authorized else None):
                    response = await call_next(request)
            response.headers["X-Request-Id"] = current()["request_id"]
            logger.logger.info(
                "api_request_completed",
                outcome="ok" if response.status_code < 400 else "failed",
                principal=PRINCIPAL if authorized else "anonymous",
                payload={
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "duration_ms": round((time.monotonic() - started) * 1000, 2),
                },
            )
            return response

    @app.exception_handler(Failure)
    async def failure(_: Request, error: Failure) -> JSONResponse:
        return error_response(error.status, error.code, error.message, error.details)

    @app.exception_handler(BriefRejected)
    async def rejected(_: Request, error: BriefRejected) -> JSONResponse:
        return error_response(400, error.code, error.message, error.details)

    @app.exception_handler(JobNotFound)
    async def missing(_: Request, error: JobNotFound) -> JSONResponse:
        return error_response(404, "JOB_NOT_FOUND", str(error))

    @app.exception_handler(TraceNotFound)
    async def no_trace(_: Request, error: TraceNotFound) -> JSONResponse:
        return error_response(404, "TRACE_NOT_FOUND", str(error))

    @app.exception_handler(JobConflict)
    async def conflict(_: Request, error: JobConflict) -> JSONResponse:
        return error_response(409, error.code, error.message)

    @app.exception_handler(RequestValidationError)
    async def invalid(_: Request, error: RequestValidationError) -> JSONResponse:
        details = [
            {"field": ".".join(str(p) for p in e.get("loc", ())), "message": str(e.get("msg"))}
            for e in error.errors()
        ]
        return error_response(400, "REQUEST_INVALID", "the request is invalid", details)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, error: StarletteHTTPException) -> JSONResponse:
        code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(error.status_code, "HTTP_ERROR")
        return error_response(error.status_code, code, str(error.detail))


def create_app(env: ResearchEnv, token: str) -> FastAPI:
    jobs = JobService(env)
    monitor = JobMonitor(env, jobs)
    service = env.config.service.api
    app = FastAPI(title="QFR research-api", version="1", docs_url=None, redoc_url=None)
    install(app, token, env.logger)

    async def run(fn: Callable[..., T], *args: Any) -> T:
        return await run_in_threadpool(fn, *args)

    def read(fn: Callable[[Connection], T]) -> T:
        with env.db.read() as conn:
            return fn(conn)

    def size(limit: int | None) -> int:
        value = limit or service.list_default
        if not 1 <= value <= service.list_max:
            raise Failure(400, "LIMIT_INVALID", f"limit must be between 1 and {service.list_max}")
        return value

    @app.get("/healthz", response_model=Health)
    async def healthz() -> Health:
        healthy = await run(env.db.healthy)
        return Health(status="ok" if healthy else "degraded", service=SERVICE, database=healthy)

    # Jobs --------------------------------------------------------------------------------

    @app.post("/v1/jobs", response_model=SubmitJobResponse, responses=ERRORS)
    async def submit(body: SubmitJobRequest, response: Response) -> SubmitJobResponse:
        try:
            result = await run(jobs.submit, body.brief, body.scan, PRINCIPAL)
        except RuntimeError as error:
            if str(error).startswith("SNAPSHOT_UNAVAILABLE"):
                raise Failure(409, "SNAPSHOT_UNAVAILABLE", str(error)) from error
            raise
        response.status_code = 201 if result.created else 200
        return result

    @app.get("/v1/jobs", response_model=JobPage, responses=ERRORS)
    async def list_jobs(
        state: str | None = None, limit: int | None = None, cursor: UUID | None = None
    ) -> JobPage:
        n = size(limit)
        items = await run(read, lambda c: jobs.list_jobs(c, state, n + 1, cursor))
        return JobPage(items=items[:n], next_cursor=items[n - 1].job_id if len(items) > n else None)

    @app.get("/v1/jobs/{job_id}", response_model=JobView, responses=ERRORS)
    async def get_job(job_id: UUID) -> JobView:
        return await run(read, lambda c: jobs.get(c, job_id))

    @app.get("/v1/jobs/{job_id}/versions", responses=ERRORS)
    async def job_versions(job_id: UUID) -> dict[str, Any]:
        """Seed and published version ids of a job, for the front door's owner-only scan."""

        def load(conn: Connection) -> dict[str, Any]:
            job = jobs.get(conn, job_id)
            rows = conn.execute(
                text(
                    "SELECT v.version_id FROM candidate_versions v JOIN candidates c ON "
                    "c.candidate_id = v.candidate_id WHERE c.program_id = :p ORDER BY "
                    "v.published_at"
                ),
                {"p": job.program_id},
            ).all()
            published = [str(r.version_id) for r in rows]
            seeds = [str(v) for v in job.seed_version_ids]
            return {"job_id": str(job_id), "version_ids": list(dict.fromkeys(seeds + published))}

        return await run(read, load)

    @app.get("/v1/jobs/{job_id}/events", response_model=JobEventPage, responses=ERRORS)
    async def job_events(
        job_id: UUID, after_seq: int = 0, limit: int | None = None
    ) -> JobEventPage:
        n = size(limit)
        return await run(read, lambda c: jobs.events(c, job_id, after_seq, n))

    @app.get("/v1/jobs/{job_id}/wait", response_model=JobWait, responses=ERRORS)
    async def wait(job_id: UUID, timeout_s: float = 30.0, state: str | None = None) -> JobWait:
        """Long-poll until the job's state differs from `state` (default: its state now)."""
        if not 0 <= timeout_s <= service.wait_max_seconds:
            raise Failure(
                400,
                "TIMEOUT_INVALID",
                f"timeout_s must be between 0 and {service.wait_max_seconds}",
            )
        started = time.monotonic()
        job = await run(read, lambda c: jobs.get(c, job_id))
        seen = state or job.state
        while job.state == seen and time.monotonic() - started < timeout_s:
            await asyncio.sleep(min(service.wait_poll_seconds, timeout_s))
            job = await run(read, lambda c: jobs.get(c, job_id))
        return JobWait(
            changed=job.state != seen,
            waited_seconds=round(time.monotonic() - started, 3),
            job=job,
        )

    @app.post("/v1/jobs/{job_id}/steer", response_model=JobView, responses=ERRORS)
    async def steer(job_id: UUID, body: SteerRequest) -> JobView:
        return await run(jobs.steer, job_id, body.note, body.scan, PRINCIPAL)

    @app.post("/v1/jobs/{job_id}/pause", response_model=JobView, responses=ERRORS)
    async def pause(job_id: UUID) -> JobView:
        return await run(jobs.pause, job_id, True, PRINCIPAL)

    @app.post("/v1/jobs/{job_id}/resume", response_model=JobView, responses=ERRORS)
    async def resume(job_id: UUID) -> JobView:
        return await run(jobs.pause, job_id, False, PRINCIPAL)

    @app.post("/v1/jobs/{job_id}/cancel", response_model=JobView, responses=ERRORS)
    async def cancel(job_id: UUID) -> JobView:
        return await run(jobs.cancel, job_id, PRINCIPAL)

    # Deliverables ------------------------------------------------------------------------

    @app.get("/v1/jobs/{job_id}/deliverables", response_model=DeliverablePage, responses=ERRORS)
    async def job_deliverables(job_id: UUID) -> DeliverablePage:
        def load(conn: Connection) -> DeliverablePage:
            jobs.get(conn, job_id)
            return DeliverablePage(items=monitor.deliverables(conn, job_id))

        return await run(read, load)

    @app.get("/v1/deliverables/{deliverable_id}", response_model=DeliverableView, responses=ERRORS)
    async def deliverable(deliverable_id: UUID, mark_fetched: bool = False) -> DeliverableView:
        if mark_fetched:
            found = await run(monitor.mark_fetched, deliverable_id, PRINCIPAL)
        else:
            found = await run(read, lambda c: monitor.deliverable(c, deliverable_id))
        if found is None:
            raise Failure(404, "DELIVERABLE_NOT_FOUND", f"no deliverable {deliverable_id}")
        return found

    # Research views ----------------------------------------------------------------------

    def generation_view(row: Any) -> GenerationView:
        return GenerationView(
            generation_id=row.generation_id,
            program_id=row.program_id,
            seq=row.seq,
            state=row.state,
            plan_source=row.plan_source,
            started_at=row.started_at,
            ended_at=row.ended_at,
            cost_cny=float(row.cost_cny),
            proposal=row.proposal,
            plan=row.plan,
            summary=row.summary,
        )

    @app.get("/v1/programs/{program_id}/generations", response_model=GenerationPage)
    async def generations(program_id: UUID) -> GenerationPage:
        rows = await run(
            read,
            lambda c: c.execute(
                text("SELECT * FROM generations WHERE program_id = :p ORDER BY seq"),
                {"p": program_id},
            ).all(),
        )
        return GenerationPage(items=[generation_view(r) for r in rows])

    @app.get("/v1/generations/{generation_id}", response_model=GenerationView, responses=ERRORS)
    async def generation(generation_id: UUID) -> GenerationView:
        row = await run(
            read,
            lambda c: c.execute(
                text("SELECT * FROM generations WHERE generation_id = :g"), {"g": generation_id}
            ).first(),
        )
        if row is None:
            raise Failure(404, "GENERATION_NOT_FOUND", f"no generation {generation_id}")
        return generation_view(row)

    def rows_view(rows: Sequence[Any]) -> list[dict[str, Any]]:
        return [dict(json.loads(dumps(dict(r._mapping)))) for r in rows]

    @app.get("/v1/programs/{program_id}/population")
    async def population(program_id: UUID, island: str | None = None) -> dict[str, Any]:
        rows = await run(
            read,
            lambda c: c.execute(
                text(
                    "SELECT * FROM population_members WHERE program_id = :p AND "
                    "(CAST(:i AS text) IS NULL OR island_key = :i) ORDER BY island_key, member_id"
                ),
                {"p": program_id, "i": island},
            ).all(),
        )
        return {"program_id": str(program_id), "items": rows_view(rows)}

    @app.get("/v1/programs/{program_id}/archive")
    async def archive(program_id: UUID) -> dict[str, Any]:
        rows = await run(
            read,
            lambda c: c.execute(
                text("SELECT * FROM archive_cells WHERE program_id = :p ORDER BY cell_key"),
                {"p": program_id},
            ).all(),
        )
        return {"program_id": str(program_id), "items": rows_view(rows)}

    @app.get("/v1/hypotheses")
    async def hypotheses(
        program_id: UUID, status: str | None = None, limit: int | None = None
    ) -> dict[str, Any]:
        n = size(limit)
        rows = await run(
            read,
            lambda c: c.execute(
                text(
                    "SELECT * FROM hypotheses WHERE program_id = :p AND (CAST(:s AS text) IS NULL "
                    "OR status = :s) ORDER BY created_at LIMIT :n"
                ),
                {"p": program_id, "s": status, "n": n},
            ).all(),
        )
        return {"items": rows_view(rows)}

    @app.get("/v1/candidates/{candidate_id}", responses=ERRORS)
    async def candidate(candidate_id: UUID) -> dict[str, Any]:
        def load(conn: Connection) -> dict[str, Any] | None:
            row = conn.execute(
                text("SELECT * FROM candidates WHERE candidate_id = :c"), {"c": candidate_id}
            ).first()
            if row is None:
                return None
            reviews = conn.execute(
                text("SELECT * FROM reviews WHERE candidate_id = :c ORDER BY round"),
                {"c": candidate_id},
            ).all()
            return {"candidate": rows_view([row])[0], "reviews": rows_view(reviews)}

        found: dict[str, Any] | None = await run(read, load)
        if found is None:
            raise Failure(404, "CANDIDATE_NOT_FOUND", f"no candidate {candidate_id}")
        return found

    @app.get("/v1/interpretations")
    async def interpretations(program_id: UUID, limit: int | None = None) -> dict[str, Any]:
        n = size(limit)
        rows = await run(
            read,
            lambda c: c.execute(
                text(
                    "SELECT * FROM interpretations WHERE program_id = :p ORDER BY created_at "
                    "LIMIT :n"
                ),
                {"p": program_id, "n": n},
            ).all(),
        )
        return {"items": rows_view(rows)}

    # Traces and lineage ------------------------------------------------------------------

    def trace_view(version_id: UUID | None, candidate_id: UUID | None) -> TraceView:
        with env.db.read() as conn:
            exported = export(conn, version_id=version_id, candidate_id=candidate_id)
        return TraceView(export=exported, trace_hash=trace_hash(exported))

    @app.get("/v1/trace/candidates/{candidate_id}", response_model=TraceView, responses=ERRORS)
    async def candidate_trace(candidate_id: UUID) -> TraceView:
        return await run(trace_view, None, candidate_id)

    @app.get("/v1/trace/{version_id}", response_model=TraceView, responses=ERRORS)
    async def version_trace(version_id: UUID) -> TraceView:
        return await run(trace_view, version_id, None)

    @app.get("/v1/trace/{version_id}/export", response_model=TraceView, responses=ERRORS)
    async def version_export(version_id: UUID) -> TraceView:
        return await run(trace_view, version_id, None)

    @app.get("/v1/lineage/{version_id}", response_model=ResearchLineage, responses=ERRORS)
    async def lineage(version_id: UUID) -> ResearchLineage:
        def load(conn: Connection) -> ResearchLineage:
            versions = [version_id] + ancestors(conn, version_id)
            rows = conn.execute(
                text(
                    "SELECT e.*, g.seq FROM lineage_edges e LEFT JOIN candidates c ON "
                    "c.candidate_id = e.candidate_id LEFT JOIN generations g ON "
                    "g.generation_id = c.generation_id WHERE e.child_version_id = ANY(:v) "
                    "ORDER BY e.created_at"
                ),
                {"v": versions},
            ).all()
            hops = [
                LineageHop(
                    child_version_id=r.child_version_id,
                    parent_version_id=r.parent_version_id,
                    relation=r.relation,
                    operator=r.operator,
                    ast_diff=r.ast_diff,
                    candidate_id=r.candidate_id,
                    generation_seq=r.seq,
                )
                for r in rows
            ]
            reports = [r.model_dump(mode="json") for r in reports_for(conn, version_id)]
            return ResearchLineage(version_id=version_id, hops=hops, reports=reports)

        return await run(read, load)

    # Costs, summary and control ----------------------------------------------------------

    @app.get("/v1/costs", response_model=CostReport, responses=ERRORS)
    async def costs(
        start: Annotated[datetime | None, Query(alias="from")] = None,
        end: Annotated[datetime | None, Query(alias="to")] = None,
        group_by: Annotated[list[str] | None, Query()] = None,
        job_id: UUID | None = None,
    ) -> CostReport:
        groups = group_by or ["provider", "model", "role"]
        unknown = sorted(set(groups) - set(GROUPS))
        if unknown:
            raise Failure(
                400, "GROUP_BY_INVALID", f"unknown group_by {unknown}", {"allowed": sorted(GROUPS)}
            )
        columns = ", ".join(f"{GROUPS[g]} AS g_{g}" for g in groups)
        sql = (
            f"SELECT {columns}, count(*) AS calls, coalesce(sum(tokens_in), 0) AS tin, "
            "coalesce(sum(tokens_out), 0) AS tout, coalesce(sum(tokens_cached), 0) AS tc, "
            "coalesce(sum(cost_cny), 0) AS cost FROM budget_ledger WHERE "
            "(CAST(:s AS timestamptz) IS NULL OR at >= :s) AND "
            "(CAST(:e AS timestamptz) IS NULL OR at < :e) AND "
            "(CAST(:j AS uuid) IS NULL OR job_id = :j) "
            f"GROUP BY {', '.join(f'g_{g}' for g in groups)} ORDER BY cost DESC"
        )
        rows = await run(
            read, lambda c: c.execute(text(sql), {"s": start, "e": end, "j": job_id}).all()
        )
        items = [
            CostRow(
                key={g: getattr(r, f"g_{g}") for g in groups},
                calls=int(r.calls),
                tokens_in=int(r.tin),
                tokens_out=int(r.tout),
                tokens_cached=int(r.tc),
                cost_cny=round(float(r.cost), 6),
            )
            for r in rows
        ]
        return CostReport(
            group_by=groups,
            start=start,
            end=end,
            rows=items,
            total_cny=round(sum(i.cost_cny for i in items), 6),
            currency="CNY",
        )

    def latest_probe(conn: Connection) -> ProbeReport | None:
        report = conn.execute(
            text("SELECT report FROM llm_probes ORDER BY at DESC LIMIT 1")
        ).scalar()
        return None if report is None else ProbeReport.model_validate(report)

    @app.get("/v1/probes/latest", response_model=ProbeReport | None)
    async def probe() -> ProbeReport | None:
        return await run(read, latest_probe)

    @app.get("/v1/summary", response_model=ResearchSummary)
    async def summary() -> ResearchSummary:
        def load(conn: Connection) -> ResearchSummary:
            now = env.clock.now()
            day = datetime.combine(now.astimezone(UTC).date(), dtime(0), tzinfo=UTC)
            states = {
                r.state: int(r.n)
                for r in conn.execute(
                    text("SELECT state, count(*) AS n FROM research_jobs GROUP BY state")
                ).all()
            }
            paused: int = conn.execute(
                text("SELECT count(*) FROM programs WHERE status = 'paused'")
            ).scalar_one()
            spent: Any = conn.execute(
                text(
                    "SELECT coalesce(sum(cost_cny), 0) FROM budget_ledger WHERE at >= :a "
                    "AND at < :b"
                ),
                {"a": day, "b": day + timedelta(days=1)},
            ).scalar_one()
            halted = conn.execute(text("SELECT paused FROM research_control WHERE id = 1")).scalar()
            return ResearchSummary(
                active_jobs=sum(n for s, n in states.items() if s != "CLOSED"),
                paused_programs=int(paused),
                jobs_by_state=states,
                cost_today_cny=round(float(spent), 6),
                daily_cap_cny=float(env.ledger.global_daily_cap),
                currency="CNY",
                research_paused=bool(halted),
                last_probe=latest_probe(conn),
            )

        return await run(read, load)

    def set_paused(paused: bool) -> dict[str, Any]:
        with env.db.transaction(lock=True) as conn:
            conn.execute(
                text(
                    "INSERT INTO research_control (id, paused, updated_at, principal, reason) "
                    "VALUES (1, :p, :now, :by, :r) ON CONFLICT (id) DO UPDATE SET paused = "
                    "EXCLUDED.paused, updated_at = EXCLUDED.updated_at, principal = "
                    "EXCLUDED.principal, reason = EXCLUDED.reason"
                ),
                {
                    "p": paused,
                    "now": env.clock.now(),
                    "by": PRINCIPAL,
                    "r": "incident pause" if paused else "resumed",
                },
            )
            audit(
                conn,
                env.clock,
                PRINCIPAL,
                "research.pause_all" if paused else "research.resume_all",
                "research_control",
                1,
                {"paused": paused},
            )
        env.logger.logger.warning("research_paused" if paused else "research_resumed", outcome="ok")
        return {"research_paused": paused}

    @app.post("/v1/programs/pause_all")
    async def pause_all() -> dict[str, Any]:
        return await run(set_paused, True)

    @app.post("/v1/programs/resume_all")
    async def resume_all() -> dict[str, Any]:
        return await run(set_paused, False)

    return app


Mode = Literal["api", "worker"]


def build_env(settings: RuntimeSettings, environ: dict[str, str], mode: Mode) -> ResearchEnv:
    """Wire the services one research process needs from configs/ and the environment."""
    from qfr_research.clients import FeedbackClient, RegistryClient
    from qfr_research.db import Database, SystemClock
    from qfr_research.prompts import PromptLibrary
    from qfr_research.providers import ProviderModels
    from qfr_research.settings import ResearchConfig, prompts_dir, research_logger

    config = ResearchConfig.load(settings.config_dir)
    secret_values = [
        v
        for k, v in environ.items()
        if any(w in k.upper() for w in ("TOKEN", "PASSWORD", "SECRET", "API_KEY", "DB_URL"))
    ]
    service = "research-api" if mode == "api" else "research-worker"
    logger = research_logger(service, settings, secret_values)
    url = environ.get("RESEARCH_DB_URL")
    if not url:
        raise ValueError("RESEARCH_DB_URL is required")
    registry = RegistryClient(
        environ.get("REGISTRY_API_URL", ""), environ.get("REGISTRY_PUBLISHER_TOKEN", ""), logger
    )
    feedback = None
    if environ.get("FEEDBACK_API_URL"):
        feedback = FeedbackClient(
            environ["FEEDBACK_API_URL"], environ.get("FEEDBACK_READER_TOKEN", ""), logger
        )
    if mode == "worker" and feedback is None:
        raise ValueError("research-worker needs FEEDBACK_API_URL: generations sync reports")
    snapshot = environ.get("QFR_RESEARCH_SNAPSHOT_DIR")
    # Only research-worker reads provider keys; research-api gets an empty environment
    # for them, so a model built there would fail before any request (BND-07).
    keys = environ if mode == "worker" else {}
    return ResearchEnv(
        config=config,
        db=Database(url),
        clock=SystemClock(),
        logger=logger,
        registry=registry,
        feedback=feedback,
        models=ProviderModels(config.providers, keys),
        prompts=PromptLibrary(prompts_dir(environ)),
        research_snapshot_dir=Path(snapshot) if snapshot else None,
    )


def main() -> None:
    settings = RuntimeSettings(service=SERVICE, zone="research")
    environ = dict(os.environ)
    env = build_env(settings, environ, "api")
    host = environ.get("QFR_RESEARCH_BIND") or env.config.service.api.bind
    if host == "0.0.0.0" and not Path("/.dockerenv").exists():
        raise ValueError("non-loopback binding is permitted only inside a container")
    if host not in {"127.0.0.1", "::1", "0.0.0.0"}:
        raise ValueError("invalid research-api bind address")
    app = create_app(env, environ.get("RESEARCH_CONTROL_TOKEN", ""))
    env.logger.logger.info(
        "service_started", outcome="ok", payload={"configuration_digests": env.config.digests}
    )
    uvicorn.run(app, host=host, port=env.config.service.api.port, access_log=False, log_config=None)


if __name__ == "__main__":
    main()
