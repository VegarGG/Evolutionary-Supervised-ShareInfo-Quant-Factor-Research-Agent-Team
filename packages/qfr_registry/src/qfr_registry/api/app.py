"""Registry HTTP publication; deny by default until a token authorizer is configured."""

from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from qfr_core.contracts.publication import (
    ArtifactLineage,
    ArtifactPage,
    FamilyPage,
    PublicationRequest,
    PublicationResponse,
    PublishedArtifact,
)
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from qfr_registry.policy import RegistryReadPolicy
from qfr_registry.publication import Principal, Registry, uuid7
from qfr_registry.reads import RegistryNotFound, RegistryReader
from qfr_registry.validation import InvalidPublication, PublicationConflict


class BodyLimit:
    def __init__(self, app: ASGIApp, limit: int) -> None:
        self.app = app
        self.limit = limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] != "POST":
            return await self.app(scope, receive, send)
        chunks: list[Message] = []
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            size += len(message.get("body", b""))
            if size > self.limit:
                return await JSONResponse({"detail": "publication size limit"}, status_code=413)(
                    scope, receive, send
                )
            chunks.append(message)
            if not message.get("more_body", False):
                break
        iterator = iter(chunks)

        async def replay() -> Message:
            return next(iterator, {"type": "http.disconnect"})

        await self.app(scope, replay, send)


def unavailable_authorizer(request: Request) -> Principal:
    raise HTTPException(status_code=401, detail="registry authentication required")


def create_app(
    registry: Registry,
    *,
    authorize: Callable[[Request], Principal] = unavailable_authorizer,
    read_policy: RegistryReadPolicy | None = None,
) -> FastAPI:
    app = FastAPI(title="QFR immutable registry", version="1")
    app.add_middleware(BodyLimit, limit=registry.policy.max_request_bytes)

    def reader() -> RegistryReader:
        if read_policy is None:
            raise HTTPException(status_code=503, detail="registry read policy not configured")
        return RegistryReader(registry.connect, registry.store, read_policy)

    @app.exception_handler(RegistryNotFound)
    async def not_found(request: Request, error: RegistryNotFound) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": "registry object unavailable"})

    @app.exception_handler(InvalidPublication)
    async def invalid_bounds(request: Request, error: InvalidPublication) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(error)})

    @app.exception_handler(PermissionError)
    async def forbidden(request: Request, error: PermissionError) -> JSONResponse:
        return JSONResponse(status_code=403, content={"detail": "registry access not authorized"})

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, error: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={
                "detail": "invalid registry request schema",
                "fields": [{"location": e["loc"], "type": e["type"]} for e in error.errors()],
            },
        )

    @app.get("/healthz")
    def health() -> dict[str, str]:
        return {"status": "alive"}

    @app.get("/v1/artifacts", response_model=ArtifactPage)
    def list_artifacts(
        principal: Annotated[Principal, Depends(authorize)],
        since_seq: Annotated[int, Query(ge=0)],
        limit: Annotated[int, Query(ge=1)],
    ) -> ArtifactPage:
        return reader().page(principal, since_seq=since_seq, limit=limit)

    @app.get("/v1/artifacts/{version_id}", response_model=PublishedArtifact)
    def get_artifact(
        version_id: UUID, principal: Annotated[Principal, Depends(authorize)]
    ) -> PublishedArtifact:
        return reader().get(version_id, principal)

    @app.get("/v1/families/{family_id}", response_model=FamilyPage)
    def get_family(
        family_id: UUID,
        principal: Annotated[Principal, Depends(authorize)],
        since_seq: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int | None, Query(ge=1)] = None,
    ) -> FamilyPage:
        service = reader()
        return service.family(
            family_id,
            principal,
            since_seq=since_seq,
            limit=service.policy.max_page_size if limit is None else limit,
        )

    @app.get("/v1/artifacts/{version_id}/lineage", response_model=ArtifactLineage)
    def get_lineage(
        version_id: UUID,
        principal: Annotated[Principal, Depends(authorize)],
        depth: Annotated[int, Query(ge=0)],
    ) -> ArtifactLineage:
        return reader().lineage(version_id, principal, depth=depth)

    @app.get("/v1/artifacts/{version_id}/payload")
    def get_payload(
        version_id: UUID, asset_id: str, principal: Annotated[Principal, Depends(authorize)]
    ) -> Response:
        data, media_type, digest = reader().payload(version_id, asset_id, principal)
        return Response(
            data,
            media_type=media_type,
            headers={
                "etag": '"' + digest + '"',
                "content-disposition": "attachment",
                "x-content-type-options": "nosniff",
            },
        )

    @app.post("/v1/artifacts", response_model=PublicationResponse)
    def publish(
        body: PublicationRequest,
        request: Request,
        response: Response,
        principal: Annotated[Principal, Depends(authorize)],
    ) -> PublicationResponse:
        try:
            request_id = (
                UUID(request.headers["x-request-id"])
                if "x-request-id" in request.headers
                else uuid7()
            )
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid request id") from None
        response.headers["x-request-id"] = str(request_id)
        try:
            result = registry.publish(body, principal, request_id)
        except PermissionError:
            raise HTTPException(status_code=403, detail="publication not authorized") from None
        except InvalidPublication as error:
            raise HTTPException(status_code=400, detail=str(error)) from None
        except PublicationConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from None
        response.status_code = 201 if result.created else 200
        return result

    return app
