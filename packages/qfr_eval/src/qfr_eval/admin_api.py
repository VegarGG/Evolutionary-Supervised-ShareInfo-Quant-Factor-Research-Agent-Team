"""eval-admin-api (PLAN Section 16.8): the owner's door into the evaluation zone.

Called only by qfr-mcp with the eval-owner token. It creates and activates protocol,
policy and quota versions, and serves intake, runs, official records, owner-grade
evidence, series files, burn meters, quota usage, the library and private configuration.
Simulation, acceptance, alerts and epoch rollover arrive with Phases 6 and 8.
"""

import os
from datetime import timedelta
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from fastapi import FastAPI, Query, Response
from pydantic import JsonValue
from qfr_core.config import RuntimeSettings
from qfr_core.correlation import current
from qfr_core.eval_api import (
    ActivateRequest,
    ConfigKind,
    ConfigVersionView,
    CreateVersionRequest,
    VersionState,
    VersionStatePage,
)
from qfr_core.logging import JsonLogger
from qfr_core.registry_api import Health
from sqlalchemy import text
from starlette.concurrency import run_in_threadpool

from qfr_eval import evidence
from qfr_eval.configs import TABLES, EvalError, activate_version, create_version
from qfr_eval.contracts import OfficialRecord, OwnerEvidence
from qfr_eval.http import ERROR_RESPONSES, install, serve
from qfr_eval.runtime import ApiConfig, Clock, Database, SystemClock, eval_config, service_logger
from qfr_eval.store import ArtifactStore

SERVICE = "eval-admin-api"
PRINCIPAL = "eval_owner"
ROUTE_KINDS: dict[str, ConfigKind] = {
    "protocols": "protocol",
    "policies": "policy",
    "quotas": "quotas",
}


def _view(row: Any, kind: ConfigKind, created: bool | None = None) -> ConfigVersionView:
    return ConfigVersionView(
        kind=kind,
        id=row.id,
        version=row.version,
        sha256=row.sha256,
        status=row.status,
        created=created,
        activated_at=row.activated_at,
        activated_by=row.activated_by,
        approval_id=row.approval_id,
    )


def create_app(
    db: Database,
    token: str,
    config: ApiConfig,
    store: ArtifactStore,
    logger: JsonLogger,
    clock: Clock | None = None,
) -> FastAPI:
    app = FastAPI(title="QFR eval-admin-api", version="1", docs_url=None, redoc_url=None)
    install(app, SERVICE, token, logger, PRINCIPAL)
    clock = clock or SystemClock()
    log = logger.logger

    def version_row(kind: ConfigKind, config_id: str, version: str) -> Any:
        with db.read() as conn:
            return conn.execute(
                text(
                    f"SELECT id, version, sha256, status, activated_at, activated_by, approval_id "
                    f"FROM eval.{TABLES[kind]} WHERE id = :id AND version = :v"
                ),
                {"id": config_id, "v": version},
            ).first()

    def create(kind: ConfigKind, body: CreateVersionRequest) -> ConfigVersionView:
        with db.transaction() as conn:
            version, created = create_version(
                conn, kind, body.yaml, PRINCIPAL, current()["request_id"], clock.now()
            )
        log.info(
            "config_version_created",
            outcome="ok",
            payload={"kind": kind, "ref": version.ref, "sha256": version.sha256, "new": created},
        )
        return _view(version_row(kind, version.id, version.version), kind, created)

    def activate(
        kind: ConfigKind, config_id: str, version: str, body: ActivateRequest
    ) -> ConfigVersionView:
        with db.transaction() as conn:
            activate_version(
                conn, kind, config_id, version, PRINCIPAL, body.approval_id,
                current()["request_id"], clock.now(),
            )  # fmt: skip
        log.info(
            "config_version_activated",
            outcome="ok",
            payload={
                "kind": kind,
                "ref": f"{config_id}/{version}",
                "approval_id": str(body.approval_id) if body.approval_id else None,
            },
        )
        return _view(version_row(kind, config_id, version), kind)

    def versions(kind: ConfigKind) -> list[ConfigVersionView]:
        with db.read() as conn:
            rows = conn.execute(
                text(
                    f"SELECT id, version, sha256, status, activated_at, activated_by, approval_id "
                    f"FROM eval.{TABLES[kind]} ORDER BY created_at"
                )
            ).all()
        return [_view(r, kind) for r in rows]

    def rows_as_json(sql: str, params: dict[str, Any]) -> list[dict[str, JsonValue]]:
        with db.read() as conn:
            rows = conn.execute(text(sql), params).mappings().all()
        out = []
        for row in rows:
            item: dict[str, JsonValue] = {}
            for key, value in row.items():
                if isinstance(value, UUID):
                    item[key] = str(value)
                elif hasattr(value, "isoformat"):
                    item[key] = value.isoformat()
                elif isinstance(value, list):
                    item[key] = [str(v) for v in value]
                else:
                    item[key] = value
            out.append(item)
        return out

    limit_query = Query(config.list_default, ge=1, le=config.list_max)

    @app.get("/healthz", response_model=Health)
    async def healthz() -> Health:
        healthy = await run_in_threadpool(db.healthy)
        return Health(status="ok" if healthy else "degraded", service=SERVICE, database=healthy)

    for route, kind in ROUTE_KINDS.items():

        def register(route: str = route, kind: ConfigKind = kind) -> None:
            @app.post(
                f"/v1/{route}",
                status_code=201,
                response_model=ConfigVersionView,
                responses=ERROR_RESPONSES,
                name=f"create_{kind}",
            )
            async def create_route(
                body: CreateVersionRequest, response: Response
            ) -> ConfigVersionView:
                view = await run_in_threadpool(create, kind, body)
                response.status_code = 201 if view.created else 200
                return view

            @app.get(
                f"/v1/{route}",
                response_model=list[ConfigVersionView],
                responses=ERROR_RESPONSES,
                name=f"list_{kind}",
            )
            async def list_route() -> list[ConfigVersionView]:
                return await run_in_threadpool(versions, kind)

            @app.post(
                f"/v1/{route}/{{config_id}}/{{version}}/activate",
                response_model=ConfigVersionView,
                responses=ERROR_RESPONSES,
                name=f"activate_{kind}",
            )
            async def activate_route(
                config_id: str, version: str, body: ActivateRequest
            ) -> ConfigVersionView:
                return await run_in_threadpool(activate, kind, config_id, version, body)

        register()

    @app.get("/v1/intake", responses=ERROR_RESPONSES)
    async def intake(
        state: str | None = None, after_seq: int = Query(0, ge=0), limit: int = limit_query
    ) -> dict[str, JsonValue]:
        items = await run_in_threadpool(
            rows_as_json,
            "SELECT version_id, published_seq, family_id, program_id, job_id, kind, state, "
            "reason_code, duplicate_of, similarity, hold_reason, w1_passed, discovered_at, "
            "deferred_at, enqueued_at, decided_at FROM eval.intake WHERE published_seq > :after "
            "AND (CAST(:state AS text) IS NULL OR state = :state) ORDER BY published_seq "
            "LIMIT :limit",
            {"after": after_seq, "state": state, "limit": limit},
        )
        return {"items": items}  # type: ignore[dict-item]

    @app.get("/v1/versions/state", response_model=VersionStatePage, responses=ERROR_RESPONSES)
    async def states(
        version_id: Annotated[list[UUID], Query(max_length=2000)],
    ) -> VersionStatePage:
        def read() -> VersionStatePage:
            with db.read() as conn:
                rows = evidence.version_states(conn, version_id)
            return VersionStatePage(items=[VersionState.model_validate(r) for r in rows])

        return await run_in_threadpool(read)

    @app.get("/v1/runs", responses=ERROR_RESPONSES)
    async def runs(
        version_id: UUID | None = None, limit: int = limit_query
    ) -> dict[str, JsonValue]:
        items = await run_in_threadpool(
            rows_as_json,
            "SELECT run_id, version_id, stage, window_name, protocol_ref, epoch_id, snapshot_id, "
            "code_version, image_digest, seed, status, started_at, finished_at, error_code, "
            "resources FROM eval.runs WHERE (CAST(:v AS uuid) IS NULL OR version_id = :v) "
            "ORDER BY started_at DESC LIMIT :limit",
            {"v": version_id, "limit": limit},
        )
        return {"items": items}  # type: ignore[dict-item]

    @app.get(
        "/v1/records/{version_id}", response_model=list[OfficialRecord], responses=ERROR_RESPONSES
    )
    async def records(version_id: UUID) -> list[OfficialRecord]:
        def read() -> list[OfficialRecord]:
            with db.read() as conn:
                return evidence.official_records(conn, version_id)

        return await run_in_threadpool(read)

    @app.get("/v1/evidence/{version_id}", response_model=OwnerEvidence, responses=ERROR_RESPONSES)
    async def owner_evidence(version_id: UUID) -> OwnerEvidence:
        def read() -> OwnerEvidence:
            with db.read() as conn:
                return evidence.owner_evidence(conn, version_id)

        result = await run_in_threadpool(read)
        log.info(
            "owner_evidence_read",
            outcome="ok",
            payload={"version_id": str(version_id), "records": len(result.official_records)},
        )
        return result

    @app.get("/v1/series/{run_id}/{kind}", responses=ERROR_RESPONSES)
    async def series(run_id: UUID, kind: str) -> Response:
        def read() -> bytes:
            with db.read() as conn:
                row = conn.execute(
                    text(
                        "SELECT uri, sha256 FROM eval.series_files WHERE run_id = :r "
                        "AND kind = :k AND kind <> 'factor_values'"
                    ),
                    {"r": run_id, "k": kind},
                ).first()
            if row is None:
                raise EvalError(404, "SERIES_NOT_FOUND", "no series file for this run and kind")
            return store.read(row.uri, row.sha256)

        data = await run_in_threadpool(read)
        media = "application/octet-stream"
        return Response(content=data, media_type=media)

    @app.get("/v1/burn", responses=ERROR_RESPONSES)
    async def burn() -> dict[str, JsonValue]:
        items = await run_in_threadpool(
            rows_as_json, "SELECT * FROM eval.burn_meters ORDER BY epoch_id, window_name", {}
        )
        return {"items": items}  # type: ignore[dict-item]

    @app.get("/v1/quotas/usage", responses=ERROR_RESPONSES)
    async def quota_usage() -> dict[str, JsonValue]:
        items = await run_in_threadpool(
            rows_as_json,
            "SELECT scope, key, window_name, count(*) AS used_24h FROM eval.quota_usage "
            "WHERE used_at > :since GROUP BY scope, key, window_name ORDER BY scope, key",
            {"since": clock.now() - timedelta(hours=24)},
        )
        return {"items": items}  # type: ignore[dict-item]

    @app.get("/v1/library", responses=ERROR_RESPONSES)
    async def library() -> dict[str, JsonValue]:
        items = await run_in_threadpool(
            rows_as_json,
            "SELECT version_id, pool, entry_id, status, approved_tier, effective_from, "
            "last_event_seq, updated_at FROM eval.library ORDER BY version_id",
            {},
        )
        return {"items": items}  # type: ignore[dict-item]

    @app.get("/v1/config/private", responses=ERROR_RESPONSES)
    async def private() -> dict[str, JsonValue]:
        def read() -> dict[str, JsonValue]:
            with db.read() as conn:
                return evidence.private_config(conn)

        return await run_in_threadpool(read)

    @app.get("/v1/summary", responses=ERROR_RESPONSES)
    async def summary() -> dict[str, JsonValue]:
        def read() -> dict[str, JsonValue]:
            with db.read() as conn:
                return evidence.summary(conn)

        return await run_in_threadpool(read)

    return app


def build(
    settings: RuntimeSettings, environ: dict[str, str], db: Database | None = None
) -> FastAPI:
    config = eval_config(settings.config_dir).apis["admin"]
    url = environ.get("EVAL_DB_URL", "")
    token = environ.get("EVAL_OWNER_TOKEN", "")
    logger = service_logger(SERVICE, settings, [url, token])
    store = ArtifactStore(Path(environ.get("QFR_EVAL_STORE_DIR") or "data/eval-store"))
    app = create_app(db or Database(url), token, config, store, logger)
    logger.logger.info("service_started", payload={"phase": 3})
    return app


def main() -> None:
    settings = RuntimeSettings(service=SERVICE, zone="eval")
    config = eval_config(settings.config_dir).apis["admin"]
    serve(build(settings, dict(os.environ)), config, "QFR_EVAL_ADMIN_BIND")


if __name__ == "__main__":
    main()
