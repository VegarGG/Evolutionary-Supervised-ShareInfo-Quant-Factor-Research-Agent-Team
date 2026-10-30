"""registry-api (PLAN Section 16.5): FastAPI routes, role tokens, request ids and logs.

The only mutation routes are POST /v1/artifacts and the two pool POST routes (BND-09).
There is no PUT, PATCH or DELETE route, and the database refuses them anyway (REG-01).
"""

import logging
import os
import time
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Annotated, Any, TypeVar
from uuid import UUID

import uvicorn
from fastapi import Body, Depends, FastAPI, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from qfr_core.config import (
    RegistryConfig,
    RuntimeSettings,
    load_config,
    logging_config,
    public_protocol_section,
    registry_config,
)
from qfr_core.contracts import PoolName, PoolStatus
from qfr_core.correlation import bind, current, from_headers
from qfr_core.dsl import DslLimits
from qfr_core.logging import JsonLogger, StdlibBridge
from qfr_core.registry_api import (
    SERVER_FIELDS,
    AddEntryRequest,
    AddEntryResponse,
    ApiError,
    AppendEventRequest,
    FamilyView,
    Health,
    LineageView,
    PoolEntryDetail,
    PoolEvent,
    PoolEventPage,
    PoolPage,
    PublishRequest,
    PublishResponse,
    RegistrySummary,
    VersionPage,
    VersionRecord,
)
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from qfr_registry.auth import ROLES, Role, TokenAuth
from qfr_registry.db import Database
from qfr_registry.service import RegistryError, RegistryService

SERVICE = "registry-api"
T = TypeVar("T")
ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    code: {"model": ApiError} for code in (400, 401, 403, 404, 409, 413)
}


def _with_ok(model: type[Any]) -> dict[int | str, dict[str, Any]]:
    """Error responses plus a 200 answer (idempotent repeats of a 201 route)."""
    ok: dict[int | str, dict[str, Any]] = {200: {"model": model}}
    return ok | ERROR_RESPONSES


def _error(status: int, code: str, message: str, details: list[Any] | None = None) -> JSONResponse:
    body = ApiError(
        error=code,
        message=message,
        request_id=current().get("request_id", ""),
        details=details or [],
    )
    return JSONResponse(body.model_dump(mode="json"), status_code=status)


def _validation_details(errors: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "field": ".".join(str(p) for p in e.get("loc", ()) if p != "body"),
            "message": str(e.get("msg")),
            "type": str(e.get("type")),
        }
        for e in errors
    ]


def strip_server_fields(body: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """REG-04: the registry computes every server field and ignores client copies."""
    ignored = sorted(k for k in body if k in SERVER_FIELDS)
    cleaned = {k: v for k, v in body.items() if k not in SERVER_FIELDS}
    manifest = cleaned.get("manifest")
    if isinstance(manifest, dict):
        ignored += sorted(f"manifest.{k}" for k in manifest if k in SERVER_FIELDS)
        cleaned["manifest"] = {k: v for k, v in manifest.items() if k not in SERVER_FIELDS}
    return cleaned, ignored


def create_app(
    db: Database,
    auth: TokenAuth,
    config: RegistryConfig,
    limits: DslLimits,
    logger: JsonLogger,
) -> FastAPI:
    service = RegistryService(db, limits, config, logger)
    app = FastAPI(title="QFR registry-api", version="1", docs_url=None, redoc_url=None)

    def roles(*allowed: Role) -> Callable[[Request], Awaitable[Role]]:
        async def dependency(request: Request) -> Role:
            role = auth.role(request.headers.get("authorization"))
            if role is None:
                raise RegistryError(401, "UNAUTHORIZED", "a valid registry token is required")
            request.state.principal = role
            if role not in allowed:
                raise RegistryError(
                    403, "FORBIDDEN_ROLE", f"the {role} token may not call this route"
                )
            return role

        return dependency

    anyone = roles(*ROLES)

    async def run(role: Role, fn: Callable[..., T], *args: Any) -> T:
        with bind(principal=role):
            return await run_in_threadpool(fn, *args)

    @app.middleware("http")
    async def correlate(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        context = from_headers(dict(request.headers))
        started = time.monotonic()
        request.state.principal = None
        with bind(**context):
            length = request.headers.get("content-length", "0")
            if not length.isdigit() or int(length) > config.request_body_bytes:
                response: Response = _error(413, "BODY_TOO_LARGE", "the request body is too large")
            else:
                try:
                    response = await call_next(request)
                except Exception:
                    logger.logger.error(
                        "api_request_failed", error_code="INTERNAL_ERROR", exc_info=True
                    )
                    response = _error(500, "INTERNAL_ERROR", "the registry failed")
            status = response.status_code
            route = request.scope.get("route")
            fields: dict[str, Any] = {
                "duration_ms": (time.monotonic() - started) * 1000,
                "outcome": "ok" if status < 400 else "failed",
                "payload": {
                    "method": request.method,
                    "path": request.url.path,
                    "route": getattr(route, "path", None),
                    "status": status,
                },
            }
            if request.state.principal:
                fields["principal"] = request.state.principal
            if status < 400:
                logger.logger.info("api_request_completed", **fields)
            elif status < 500:
                logger.logger.warning("api_request_completed", **fields)
            else:
                logger.logger.error("api_request_completed", **fields)
            response.headers["X-Request-Id"] = context["request_id"]
            return response

    @app.exception_handler(RegistryError)
    async def registry_error(_: Request, error: RegistryError) -> JSONResponse:
        logger.logger.warning(
            "registry_request_rejected",
            error_code=error.code,
            payload={"status": error.status, "message": error.message, "details": error.details},
        )
        return _error(error.status, error.code, error.message, error.details)

    @app.exception_handler(RequestValidationError)
    async def invalid(_: Request, error: RequestValidationError) -> JSONResponse:
        details = _validation_details(list(error.errors()))
        logger.logger.warning(
            "registry_validation_failed",
            error_code="SCHEMA_INVALID",
            payload={"fields": [d["field"] for d in details]},
        )
        return _error(400, "SCHEMA_INVALID", "the request failed validation", details)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, error: StarletteHTTPException) -> JSONResponse:
        code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(error.status_code, "HTTP_ERROR")
        return _error(error.status_code, code, str(error.detail))

    @app.get("/healthz", response_model=Health)
    async def healthz() -> Health:
        healthy = await run_in_threadpool(db.healthy)
        return Health(status="ok" if healthy else "degraded", service=SERVICE, database=healthy)

    @app.get("/v1/summary", response_model=RegistrySummary, responses=ERROR_RESPONSES)
    async def summary(role: Annotated[Role, Depends(anyone)]) -> RegistrySummary:
        return await run(role, service.summary)

    @app.post(
        "/v1/artifacts",
        status_code=201,
        response_model=PublishResponse,
        responses=_with_ok(PublishResponse),
    )
    async def publish(
        role: Annotated[Role, Depends(roles("publisher", "control"))],
        response: Response,
        body: Annotated[dict[str, Any], Body()],
    ) -> PublishResponse:
        cleaned, ignored = strip_server_fields(body)
        if ignored:
            logger.logger.warning(
                "client_server_fields_ignored", principal=role, payload={"fields": ignored}
            )
        try:
            request = PublishRequest.model_validate(cleaned)
        except ValidationError as error:
            raise RegistryError(
                400,
                "SCHEMA_INVALID",
                "the manifest failed schema validation",
                _validation_details(list(error.errors())),
            ) from None
        result = await run(role, service.publish, request, role, current()["request_id"])
        response.status_code = 201 if result.created else 200
        return result

    @app.get("/v1/artifacts/{version_id}", response_model=VersionRecord, responses=ERROR_RESPONSES)
    async def get_version(
        role: Annotated[Role, Depends(roles("reader", "evaluator", "publisher", "control"))],
        version_id: UUID,
    ) -> VersionRecord:
        return await run(role, service.get_version, version_id)

    @app.get("/v1/artifacts", response_model=VersionPage, responses=ERROR_RESPONSES)
    async def list_versions(
        role: Annotated[Role, Depends(roles("evaluator", "reader", "control"))],
        since_seq: int = Query(0, ge=0),
        limit: int = Query(config.list_default, ge=1, le=config.list_max),
    ) -> VersionPage:
        return await run(role, service.list_versions, since_seq, limit)

    @app.get("/v1/families/{family_id}", response_model=FamilyView, responses=ERROR_RESPONSES)
    async def get_family(role: Annotated[Role, Depends(anyone)], family_id: UUID) -> FamilyView:
        return await run(role, service.get_family, family_id)

    @app.get(
        "/v1/artifacts/{version_id}/lineage",
        response_model=LineageView,
        responses=ERROR_RESPONSES,
    )
    async def lineage(
        role: Annotated[Role, Depends(anyone)],
        version_id: UUID,
        depth: int = Query(config.lineage_depth_default, ge=0, le=config.lineage_depth_max),
    ) -> LineageView:
        return await run(role, service.lineage, version_id, depth)

    @app.get("/v1/pools/{pool}", response_model=PoolPage, responses=ERROR_RESPONSES)
    async def pool_entries(
        role: Annotated[Role, Depends(anyone)],
        pool: PoolName,
        status: PoolStatus | None = None,
        limit: int = Query(config.list_default, ge=1, le=config.list_max),
        cursor: UUID | None = None,
    ) -> PoolPage:
        return await run(role, service.pool_entries, pool, status, limit, cursor)

    @app.get("/v1/pools/{pool}/events", response_model=PoolEventPage, responses=ERROR_RESPONSES)
    async def pool_events(
        role: Annotated[Role, Depends(roles("evaluator", "reader", "control"))],
        pool: PoolName,
        since_seq: int = Query(0, ge=0),
        limit: int = Query(config.list_default, ge=1, le=config.list_max),
    ) -> PoolEventPage:
        return await run(role, service.pool_events, pool, since_seq, limit)

    @app.get(
        "/v1/pools/{pool}/entries/{entry_id}",
        response_model=PoolEntryDetail,
        responses=ERROR_RESPONSES,
    )
    async def pool_entry(
        role: Annotated[Role, Depends(anyone)],
        pool: PoolName,
        entry_id: UUID,
    ) -> PoolEntryDetail:
        return await run(role, service.pool_entry, pool, entry_id)

    @app.post(
        "/v1/pools/{pool}/entries",
        status_code=201,
        response_model=AddEntryResponse,
        responses=_with_ok(AddEntryResponse),
    )
    async def add_entry(
        role: Annotated[Role, Depends(roles("control"))],
        pool: PoolName,
        request: AddEntryRequest,
        response: Response,
    ) -> AddEntryResponse:
        result = await run(role, service.add_entry, pool, request, role, current()["request_id"])
        response.status_code = 201 if result.created else 200
        return result

    @app.post(
        "/v1/pools/{pool}/entries/{entry_id}/events",
        status_code=201,
        response_model=PoolEvent,
        responses=ERROR_RESPONSES,
    )
    async def append_event(
        role: Annotated[Role, Depends(roles("control"))],
        pool: PoolName,
        entry_id: UUID,
        request: AppendEventRequest,
    ) -> PoolEvent:
        return await run(
            role, service.append_event, pool, entry_id, request, role, current()["request_id"]
        )

    return app


def build(
    settings: RuntimeSettings, environ: Mapping[str, str], db: Database | None = None
) -> FastAPI:
    """Assemble the service from configuration and the environment."""
    auth = TokenAuth.from_env(environ)
    config = registry_config(settings.config_dir)
    log_config = logging_config(settings.config_dir)
    if settings.log_level:
        log_config = log_config.model_copy(update={"level": settings.log_level})
    url = environ.get("REGISTRY_DB_URL", "")
    logger = JsonLogger(
        SERVICE, "registry", settings.log_dir, log_config, secrets=auth.secrets() + [url]
    )
    logging.getLogger().handlers = [StdlibBridge(logger)]
    logging.getLogger().setLevel(log_config.level)
    limits = DslLimits.from_protocol(public_protocol_section(settings.config_dir, "dsl"))
    app = create_app(db or Database(url or None), auth, config, limits, logger)
    logger.logger.info(
        "service_started",
        payload={
            "phase": 2,
            "configuration_digest": load_config("registry", settings.config_dir).sha256,
            "dsl_limits": limits.model_dump(mode="json"),
        },
    )
    return app


def main() -> None:
    settings = RuntimeSettings(service=SERVICE, zone="registry")
    config = registry_config(settings.config_dir)
    host = os.environ.get("QFR_REGISTRY_BIND") or config.bind
    # Inside the Compose networks it listens on the container interface; registry-api
    # publishes no host port. Direct launches stay on loopback.
    if host == "0.0.0.0" and not Path("/.dockerenv").exists():
        raise ValueError("non-loopback binding is permitted only inside a container")
    if host not in {"127.0.0.1", "::1", "0.0.0.0"}:
        raise ValueError("invalid registry bind address")
    uvicorn.run(
        build(settings, os.environ),
        host=host,
        port=config.port,
        access_log=False,
        log_config=None,
    )


if __name__ == "__main__":
    main()
