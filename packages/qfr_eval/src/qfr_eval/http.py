"""Shared FastAPI plumbing for feedback-api and eval-admin-api: one static bearer token
per service (Section 16.9), request ids, a log line per request, ApiError bodies."""

import os
import secrets
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from qfr_core.correlation import bind, current, from_headers
from qfr_core.logging import JsonLogger
from qfr_core.registry_api import ApiError
from starlette.exceptions import HTTPException as StarletteHTTPException

from qfr_eval.configs import EvalError
from qfr_eval.runtime import ApiConfig

ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    code: {"model": ApiError} for code in (400, 401, 404, 409)
}


def error_response(status: int, code: str, message: str, details: Any = None) -> JSONResponse:
    body = ApiError(
        error=code,
        message=message,
        request_id=current().get("request_id", ""),
        details=details if isinstance(details, list) else ([details] if details else []),
    )
    return JSONResponse(body.model_dump(mode="json"), status_code=status)


def install(app: FastAPI, service: str, token: str, logger: JsonLogger, principal: str) -> None:
    """Bearer authentication on every route but /healthz, plus correlation and logging."""
    if not token:
        raise ValueError(f"{service} needs its bearer token")
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
                with bind(principal=principal if authorized else None):
                    response = await call_next(request)
            response.headers["X-Request-Id"] = current()["request_id"]
            logger.logger.info(
                "api_request_completed",
                outcome="ok" if response.status_code < 400 else "failed",
                principal=principal if authorized else "anonymous",
                payload={
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "duration_ms": round((time.monotonic() - started) * 1000, 2),
                },
            )
            return response

    @app.exception_handler(EvalError)
    async def eval_error(_: Request, error: EvalError) -> JSONResponse:
        return error_response(error.status, error.code, error.message, error.details)

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


def serve(app: FastAPI, config: ApiConfig, bind_env: str) -> None:
    host = os.environ.get(bind_env) or config.bind
    if host == "0.0.0.0" and not Path("/.dockerenv").exists():
        raise ValueError("non-loopback binding is permitted only inside a container")
    if host not in {"127.0.0.1", "::1", "0.0.0.0"}:
        raise ValueError("invalid bind address")
    uvicorn.run(app, host=host, port=config.port, access_log=False, log_config=None)
