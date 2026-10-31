"""feedback-api (PLAN Section 16.6, INV-4): GET only, released reports only.

It connects as feedback_ro, which may read the five views in the feedback schema and
nothing else; every view shows only reports whose release time has passed. There is
no route that writes, triggers or prioritizes anything (BND-03). One feedback-reader
token serves the research zone; requests may narrow results to one program.
"""

import os
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import FastAPI, Query
from qfr_core.cards import card_sha256, compose_policy_card
from qfr_core.config import RuntimeSettings
from qfr_core.contracts import ReleasedReport
from qfr_core.eval_api import (
    ArtifactStatus,
    Card,
    LibraryEntry,
    LibraryPage,
    ReportPage,
    ReportType,
    TimelineEntry,
)
from qfr_core.logging import JsonLogger
from qfr_core.registry_api import Health
from sqlalchemy import text
from starlette.concurrency import run_in_threadpool

from qfr_eval.configs import EvalError
from qfr_eval.http import ERROR_RESPONSES, install, serve
from qfr_eval.runtime import ApiConfig, Database, eval_config, service_logger

SERVICE = "feedback-api"
PRINCIPAL = "feedback_reader"


def create_app(db: Database, token: str, config: ApiConfig, logger: JsonLogger) -> FastAPI:
    app = FastAPI(title="QFR feedback-api", version="1", docs_url=None, redoc_url=None)
    install(app, SERVICE, token, logger, PRINCIPAL)

    def reports(
        after_id: UUID | None,
        since: datetime | None,
        version_id: UUID | None,
        family_id: UUID | None,
        program_id: UUID | None,
        report_type: str | None,
        limit: int,
    ) -> ReportPage:
        clauses: list[str] = ["TRUE"]
        params: dict[str, Any] = {"limit": limit}
        with db.read() as conn:
            if after_id is not None:
                seq = conn.execute(
                    text(
                        "SELECT release_seq FROM feedback.released_reports_v WHERE report_id = :r"
                    ),
                    {"r": after_id},
                ).scalar()
                if seq is None:
                    raise EvalError(404, "REPORT_NOT_FOUND", "after_id is not a released report")
                clauses.append("release_seq > :seq")
                params["seq"] = seq
            for column, value in (
                ("version_id", version_id),
                ("family_id", family_id),
                ("program_id", program_id),
                ("report_type", report_type),
            ):
                if value is not None:
                    clauses.append(f"{column} = :{column}")
                    params[column] = value
            if since is not None:
                clauses.append("released_at >= :since")
                params["since"] = since
            rows = conn.execute(
                text(
                    "SELECT report_id, report FROM feedback.released_reports_v WHERE "
                    + " AND ".join(clauses)
                    + " ORDER BY release_seq LIMIT :limit"
                ),
                params,
            ).all()
        items = [ReleasedReport.model_validate(r.report) for r in rows]
        return ReportPage(
            items=items, next_after_id=rows[-1].report_id if len(rows) == limit else None
        )

    def report(report_id: UUID) -> ReleasedReport:
        with db.read() as conn:
            row = conn.execute(
                text("SELECT report FROM feedback.released_reports_v WHERE report_id = :r"),
                {"r": report_id},
            ).first()
        if row is None:
            raise EvalError(404, "REPORT_NOT_FOUND", "no released report with this id")
        return ReleasedReport.model_validate(row.report)

    def status(version_id: UUID) -> ArtifactStatus:
        with db.read() as conn:
            rows = conn.execute(
                text(
                    "SELECT report_id, report_type, report -> 'content' ->> 'status' AS status, "
                    "released_at FROM feedback.released_reports_v WHERE version_id = :v "
                    "ORDER BY release_seq"
                ),
                {"v": version_id},
            ).all()
            latest = conn.execute(
                text(
                    "SELECT report_type, status FROM feedback.artifact_status_v "
                    "WHERE version_id = :v"
                ),
                {"v": version_id},
            ).first()
        if not rows:
            raise EvalError(404, "VERSION_NOT_RELEASED", "no released report for this version")
        return ArtifactStatus(
            version_id=version_id,
            status=None if latest is None else (latest.status or "EVALUATED"),
            report_type=None if latest is None else latest.report_type,
            timeline=[
                TimelineEntry(
                    report_id=r.report_id,
                    report_type=r.report_type,
                    status=r.status or ("EVALUATED" if r.report_type == "w1" else None),
                    released_at=r.released_at,
                )
                for r in rows
            ],
        )

    def library() -> LibraryPage:
        with db.read() as conn:
            rows = conn.execute(
                text("SELECT version_id, pool, status FROM feedback.library_v ORDER BY version_id")
            ).all()
        return LibraryPage(
            items=[
                LibraryEntry(version_id=r.version_id, pool=r.pool, status=r.status) for r in rows
            ]
        )

    def card(kind: str) -> Card:
        view = "feedback.policy_card_v" if kind == "policy" else "feedback.protocol_card_v"
        with db.read() as conn:
            rows = {
                r.kind: r
                for r in conn.execute(text(f"SELECT * FROM {view}")).all()  # noqa: S608
            }
        main = rows.get(kind)
        if main is None:
            raise EvalError(404, "CARD_NOT_ACTIVE", f"no active {kind} card")
        content: dict[str, Any] = dict(main.content)
        ref = main.ref
        if kind == "policy":
            quotas = rows.get("quotas")
            content = compose_policy_card(content, None if quotas is None else dict(quotas.content))
            ref = main.ref if quotas is None else f"{main.ref}+quotas:{quotas.ref}"
        return Card(
            kind=kind,  # type: ignore[arg-type]
            ref=ref,
            sha256=card_sha256(content),
            activated_at=main.activated_at,
            card=content,
        )

    limit_query = Query(config.list_default, ge=1, le=config.list_max)

    @app.get("/healthz", response_model=Health)
    async def healthz() -> Health:
        healthy = await run_in_threadpool(
            db.healthy, "SELECT to_regclass('feedback.released_reports_v')"
        )
        return Health(status="ok" if healthy else "degraded", service=SERVICE, database=healthy)

    @app.get("/v1/reports", response_model=ReportPage, responses=ERROR_RESPONSES)
    async def list_reports(
        after_id: UUID | None = None,
        since: datetime | None = None,
        version_id: UUID | None = None,
        family_id: UUID | None = None,
        program_id: UUID | None = None,
        type: Annotated[ReportType | None, Query()] = None,  # noqa: A002
        limit: int = limit_query,
    ) -> ReportPage:
        return await run_in_threadpool(
            reports, after_id, since, version_id, family_id, program_id, type, limit
        )

    @app.get("/v1/reports/{report_id}", response_model=ReleasedReport, responses=ERROR_RESPONSES)
    async def get_report(report_id: UUID) -> ReleasedReport:
        return await run_in_threadpool(report, report_id)

    @app.get(
        "/v1/artifacts/{version_id}/status",
        response_model=ArtifactStatus,
        responses=ERROR_RESPONSES,
    )
    async def artifact_status(version_id: UUID) -> ArtifactStatus:
        return await run_in_threadpool(status, version_id)

    @app.get("/v1/library", response_model=LibraryPage, responses=ERROR_RESPONSES)
    async def get_library() -> LibraryPage:
        return await run_in_threadpool(library)

    @app.get("/v1/cards/policy", response_model=Card, responses=ERROR_RESPONSES)
    async def policy_card() -> Card:
        return await run_in_threadpool(card, "policy")

    @app.get("/v1/cards/protocol", response_model=Card, responses=ERROR_RESPONSES)
    async def protocol_card() -> Card:
        return await run_in_threadpool(card, "protocol")

    return app


def build(
    settings: RuntimeSettings, environ: dict[str, str], db: Database | None = None
) -> FastAPI:
    config = eval_config(settings.config_dir).apis["feedback"]
    url = environ.get("FEEDBACK_DB_URL", "")
    token = environ.get("FEEDBACK_READER_TOKEN", "")
    logger = service_logger(SERVICE, settings, [url, token])
    app = create_app(db or Database(url), token, config, logger)
    logger.logger.info("service_started", payload={"phase": 3})
    return app


def main() -> None:
    settings = RuntimeSettings(service=SERVICE, zone="eval")
    config = eval_config(settings.config_dir).apis["feedback"]
    serve(build(settings, dict(os.environ)), config, "QFR_FEEDBACK_BIND")


if __name__ == "__main__":
    main()
