"""Authenticated data-only intake edge; metadata reads, no evaluation capability."""

import json
import logging
import sqlite3
from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from qfr_core.access import BearerAuthority, ServicePrincipal
from qfr_core.contracts.data import SourceAsset
from qfr_core.contracts.transfers import (
    AssetPage,
    FinalizeUpload,
    MountedImportRequest,
    UploadDeclaration,
    UploadStatus,
)
from qfr_core.http_transport import BoundedServiceBoundary

from qfr_eval.ingest.quarantine import Quarantine, TransferConflict, TransferNotFound


def _log(value: dict[str, object]) -> None:
    logging.getLogger("qfr.intake.requests").info(json.dumps(value, sort_keys=True))


def principal(request: Request) -> ServicePrincipal:
    value = request.state.principal
    if not isinstance(value, ServicePrincipal):
        raise PermissionError("intake authentication required")
    return value


Principal = Annotated[ServicePrincipal, Depends(principal)]


def create_app(
    store: Quarantine,
    *,
    authority: BearerAuthority | None = None,
    request_log: Callable[[dict[str, object]], None] = _log,
) -> FastAPI:
    if authority is not None and authority.config.audience != "intake":
        raise ValueError("intake requires its own audience")
    app = FastAPI(title="QFR quarantine transport", version="1", docs_url=None, redoc_url=None)
    app.add_middleware(
        BoundedServiceBoundary,
        authority=authority,
        audience="intake",
        maximum_bytes=max(store.policy.chunk_bytes, store.policy.max_metadata_bytes),
        timeout_seconds=store.policy.request_timeout_seconds,
        request_log=request_log,
        binary_route=lambda scope: scope["path"].endswith("/chunks"),
    )

    async def invalid(request: Request, error: Exception) -> JSONResponse:
        return JSONResponse({"detail": "invalid or unsafe source transport"}, status_code=400)

    async def missing(request: Request, error: Exception) -> JSONResponse:
        return JSONResponse({"detail": "source unavailable"}, status_code=404)

    async def conflict(request: Request, error: Exception) -> JSONResponse:
        return JSONResponse(
            {"detail": "source state, reservation or operation conflict"}, status_code=409
        )

    async def forbidden(request: Request, error: Exception) -> JSONResponse:
        return JSONResponse({"detail": "source operation not authorized"}, status_code=403)

    async def unavailable(request: Request, error: Exception) -> JSONResponse:
        return JSONResponse({"detail": "source storage unavailable"}, status_code=503)

    error: type[Exception]
    for error in (ValueError, RequestValidationError):
        app.add_exception_handler(error, invalid)
    app.add_exception_handler(TransferNotFound, missing)
    app.add_exception_handler(TransferConflict, conflict)
    app.add_exception_handler(PermissionError, forbidden)
    for error in (sqlite3.Error, OSError):
        app.add_exception_handler(error, unavailable)

    @app.get("/healthz")
    def health() -> dict[str, str]:
        return {"status": "alive"}

    @app.post("/v1/programs/{program_id}/uploads", response_model=UploadStatus)
    def create(
        program_id: UUID, value: UploadDeclaration, caller: Principal, request: Request
    ) -> UploadStatus:
        return store.create(caller, program_id, value, UUID(request.state.request_id))

    @app.post("/v1/programs/{program_id}/uploads/{upload_id}/chunks", response_model=UploadStatus)
    async def chunk(
        program_id: UUID, upload_id: UUID, caller: Principal, request: Request
    ) -> UploadStatus:
        from starlette.concurrency import run_in_threadpool

        offsets, hashes = (
            request.headers.getlist("x-chunk-offset"),
            request.headers.getlist("x-chunk-sha256"),
        )
        if (
            len(offsets) != 1
            or len(hashes) != 1
            or len(offsets[0]) > 20
            or not offsets[0].isdigit()
        ):
            raise ValueError("explicit unique chunk headers required")
        return await run_in_threadpool(
            store.chunk,
            caller,
            program_id,
            upload_id,
            int(offsets[0]),
            await request.body(),
            hashes[0],
            UUID(request.state.request_id),
        )

    @app.post("/v1/programs/{program_id}/uploads/{upload_id}/finalize", response_model=UploadStatus)
    def finalize(
        program_id: UUID,
        upload_id: UUID,
        value: FinalizeUpload,
        caller: Principal,
        request: Request,
    ) -> UploadStatus:
        return store.finalize(
            caller, program_id, upload_id, value.sha256, UUID(request.state.request_id)
        )

    @app.get("/v1/programs/{program_id}/uploads/{upload_id}", response_model=UploadStatus)
    def status(program_id: UUID, upload_id: UUID, caller: Principal) -> UploadStatus:
        return store.status(caller, program_id, upload_id)

    @app.post("/v1/programs/{program_id}/imports", response_model=UploadStatus)
    def mounted_import(
        program_id: UUID, value: MountedImportRequest, caller: Principal, request: Request
    ) -> UploadStatus:
        return store.import_file(caller, program_id, value, UUID(request.state.request_id))

    @app.post("/v1/programs/{program_id}/assets/verify", response_model=SourceAsset)
    def verify(program_id: UUID, value: SourceAsset, caller: Principal) -> SourceAsset:
        return store.verify(caller, program_id, value)

    @app.get("/v1/programs/{program_id}/assets", response_model=AssetPage)
    def page(
        program_id: UUID, caller: Principal, after_id: UUID | None = None, limit: int = 20
    ) -> AssetPage:
        return store.page(caller, program_id, after=after_id, limit=limit)

    return app
