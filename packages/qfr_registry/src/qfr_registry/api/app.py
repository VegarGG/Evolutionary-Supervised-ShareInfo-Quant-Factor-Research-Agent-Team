"""Registry HTTP publication; deny by default until a token authorizer is configured."""

from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from qfr_core.contracts.publication import PublicationRequest, PublicationResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from qfr_registry.publication import Principal, Registry, uuid7
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
    registry: Registry, *, authorize: Callable[[Request], Principal] = unavailable_authorizer
) -> FastAPI:
    app = FastAPI(title="QFR immutable registry", version="1")
    app.add_middleware(BodyLimit, limit=registry.policy.max_request_bytes)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, error: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={
                "detail": "invalid publication schema",
                "fields": [{"location": e["loc"], "type": e["type"]} for e in error.errors()],
            },
        )

    @app.get("/healthz")
    def health() -> dict[str, str]:
        return {"status": "alive"}

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
