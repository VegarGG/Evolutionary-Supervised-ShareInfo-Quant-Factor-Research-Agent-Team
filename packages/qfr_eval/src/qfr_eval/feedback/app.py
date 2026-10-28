"""GET-only evaluator edge. No private database, queue or administrative routes."""

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime
from qfr_core.access import AuthenticationRequired, BearerAuthority, ServicePrincipal
from qfr_core.contracts.feedback import ArtifactFeedback, PublicCards, ReportKind, ReportPage
from qfr_core.contracts.reports import ReleasedReport
from starlette.responses import Response

from qfr_eval.feedback.reads import (
    FeedbackNotFound,
    FeedbackReader,
    FeedbackUnavailable,
    InvalidFeedbackRead,
)


def _log(value: dict[str, object]) -> None:
    logging.getLogger("qfr.feedback.requests").info(json.dumps(value, sort_keys=True))


def create_app(
    reader: FeedbackReader,
    *,
    authority: BearerAuthority | None = None,
    request_log: Callable[[dict[str, object]], None] = _log,
) -> FastAPI:
    if authority is not None and authority.config.audience != "feedback":
        raise ValueError("feedback requires its own token audience")
    app = FastAPI(title="QFR released feedback", version="1", docs_url=None, redoc_url=None)

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request.state.request_id = str(uuid4())
        request.state.principal = None
        response: Response
        if request.method != "GET":
            response = JSONResponse(
                {"detail": "feedback is GET only"}, status_code=405, headers={"Allow": "GET"}
            )
        elif (
            request.headers.get("content-length", "0") != "0"
            or "transfer-encoding" in request.headers
        ):
            response = JSONResponse(
                {"detail": "feedback does not accept request bodies"}, status_code=400
            )
        else:
            response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["Cache-Control"] = "no-store"
        route = request.scope.get("route")
        request_log(
            dict(
                request_id=request.state.request_id,
                principal=request.state.principal,
                method=request.method,
                route=getattr(route, "path", "<unmatched>"),
                status=response.status_code,
            )
        )
        return response

    def authorized(request: Request) -> ServicePrincipal:
        try:
            if authority is None:
                raise AuthenticationRequired()
            principal = authority.authenticate(
                request.headers.getlist("authorization"), audience="feedback"
            )
        except AuthenticationRequired:
            raise HTTPException(
                status_code=401,
                detail="feedback authentication required",
                headers={"WWW-Authenticate": "Bearer"},
            ) from None
        request.state.principal = principal.name
        return principal

    @app.exception_handler(FeedbackNotFound)
    async def not_found(request: Request, error: FeedbackNotFound) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": "released object unavailable"})

    @app.exception_handler(FeedbackUnavailable)
    async def unavailable(request: Request, error: FeedbackUnavailable) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": "released evidence unavailable"})

    @app.exception_handler(PermissionError)
    async def forbidden(request: Request, error: PermissionError) -> JSONResponse:
        return JSONResponse(status_code=403, content={"detail": "feedback access not authorized"})

    @app.exception_handler(InvalidFeedbackRead)
    async def invalid_read(request: Request, error: InvalidFeedbackRead) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": "invalid feedback read"})

    @app.exception_handler(RequestValidationError)
    async def invalid_schema(request: Request, error: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": "invalid feedback request schema"})

    @app.get("/healthz")
    def health() -> dict[str, str]:
        return {"status": "alive"}

    @app.get("/v1/reports", response_model=ReportPage)
    def reports(
        principal: Annotated[ServicePrincipal, Depends(authorized)],
        after_id: UUID | None = None,
        since: AwareDatetime | None = None,
        version_id: UUID | None = None,
        family_id: UUID | None = None,
        type: ReportKind | None = None,
        limit: Annotated[int, Query(ge=1)] = reader.policy.max_page_size,
    ) -> ReportPage:
        return reader.page(
            principal,
            after_id=after_id,
            since=since,
            version_id=version_id,
            family_id=family_id,
            kind=type,
            limit=limit,
        )

    @app.get("/v1/reports/{report_id}", response_model=ReleasedReport)
    def report(
        report_id: UUID, principal: Annotated[ServicePrincipal, Depends(authorized)]
    ) -> ReleasedReport:
        return reader.get(principal, report_id)

    @app.get("/v1/artifacts/{version_id}/status", response_model=ArtifactFeedback)
    def status(
        version_id: UUID,
        principal: Annotated[ServicePrincipal, Depends(authorized)],
        after_id: UUID | None = None,
        limit: Annotated[int, Query(ge=1)] = reader.policy.max_page_size,
    ) -> ArtifactFeedback:
        return reader.status(principal, version_id, after_id=after_id, limit=limit)

    @app.get("/v1/library", response_model=ReportPage)
    def library(
        principal: Annotated[ServicePrincipal, Depends(authorized)],
        after_id: UUID | None = None,
        limit: Annotated[int, Query(ge=1)] = reader.policy.max_page_size,
    ) -> ReportPage:
        return reader.page(principal, after_id=after_id, kind="library", limit=limit)

    @app.get("/v1/cards/policy", response_model=PublicCards)
    def policies(
        principal: Annotated[ServicePrincipal, Depends(authorized)], ref: str | None = None
    ) -> PublicCards:
        return reader.cards(principal, kind="policy", ref=ref)

    @app.get("/v1/cards/protocol", response_model=PublicCards)
    def protocols(
        principal: Annotated[ServicePrincipal, Depends(authorized)], ref: str | None = None
    ) -> PublicCards:
        return reader.cards(principal, kind="protocol", ref=ref)

    return app
