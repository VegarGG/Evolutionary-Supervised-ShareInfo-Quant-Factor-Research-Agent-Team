"""Authentication, request limits, correlation and audit at the MCP HTTP edge."""

import asyncio
import hashlib
import json
import secrets
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from qfr_core.config import MCPConfig
from qfr_core.correlation import bind, from_headers
from qfr_core.ids import uuid7
from qfr_core.logging import JsonLogger
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from qfr_mcp.audit import AuditStore, MCPCall

_downstream: ContextVar[set[str] | None] = ContextVar("qfr_downstream_requests", default=None)


def record_downstream_request(request_id: str) -> None:
    requests = _downstream.get()
    if requests is not None:
        requests.add(request_id)


@contextmanager
def downstream_context() -> Iterator[None]:
    token = _downstream.set(set())
    try:
        yield
    finally:
        _downstream.reset(token)


class MCPBoundary:
    def __init__(
        self, app: ASGIApp, token: str, config: MCPConfig, audit: AuditStore, logger: JsonLogger
    ) -> None:
        if not token:
            raise ValueError("MCP token is required")
        self.app, self.token, self.config, self.audit, self.logger = (
            app,
            token,
            config,
            audit,
            logger,
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
        # A new id is generated per MCP call; job correlation may be propagated.
        context = from_headers(headers) | {"request_id": str(uuid4())}
        started = time.monotonic()
        authorized = secrets.compare_digest(
            headers.get("authorization", ""), f"Bearer {self.token}"
        )
        principal = "owner" if authorized else "unauthenticated"
        body = bytearray()
        status = 200
        error_code: str | None = None
        captured: list[Message] = []
        tool = "http_request"
        with bind(**context, principal=principal), downstream_context():
            if not authorized:
                status, error_code = 401, "UNAUTHORIZED"
            elif headers.get("origin") and headers["origin"] not in {
                f"http://127.0.0.1:{self.config.port}",
                f"http://localhost:{self.config.port}",
            }:
                status, error_code = 403, "ORIGIN_DENIED"
            else:
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        status, error_code = 400, "DISCONNECTED"
                        break
                    body.extend(message.get("body", b""))
                    if len(body) > self.config.request_body_bytes:
                        status, error_code = 413, "BODY_TOO_LARGE"
                        break
                    if not message.get("more_body", False):
                        break
            parsed: dict[str, Any] = {}
            if body and error_code is None:
                try:
                    decoded = json.loads(body)
                    if not isinstance(decoded, dict):
                        raise ValueError("JSON-RPC batching is not enabled")
                    parsed = decoded
                    tool = str(
                        parsed.get("params", {}).get("name", parsed.get("method", "unknown"))
                    )
                except (ValueError, AttributeError):
                    status, error_code = 400, "INVALID_REQUEST"
            if error_code is None:
                used = False

                async def replay() -> Message:
                    nonlocal used
                    if not used:
                        used = True
                        return {"type": "http.request", "body": bytes(body), "more_body": False}
                    return await receive()

                async def capture(message: Message) -> None:
                    captured.append(message)

                try:
                    await self.app(scope, replay, capture)
                    status = next(
                        (m["status"] for m in captured if m["type"] == "http.response.start"), 500
                    )
                except Exception:
                    status, error_code = 500, "INTERNAL_ERROR"
                    self.logger.logger.error(
                        "mcp_request_failed", error_code=error_code, exc_info=True
                    )
            if error_code:
                response = json.dumps(
                    {"error": error_code, "request_id": context["request_id"]}
                ).encode()
                captured = [
                    {
                        "type": "http.response.start",
                        "status": status,
                        "headers": [(b"content-type", b"application/json")],
                    },
                    {"type": "http.response.body", "body": response},
                ]
            result_size = sum(len(m.get("body", b"")) for m in captured)
            response_body = b"".join(m.get("body", b"") for m in captured)
            rpc_failed = False
            try:
                rpc_response = json.loads(response_body)
                rpc_failed = "error" in rpc_response or bool(
                    rpc_response.get("result", {}).get("isError", False)
                )
            except (ValueError, AttributeError):
                pass
            failed = status >= 400 or rpc_failed
            call = MCPCall(
                call_id=uuid7(),
                at=datetime.now(UTC),
                principal=principal,
                tool=tool,
                args_digest=hashlib.sha256(body).hexdigest(),
                args_size=len(body),
                result_size=result_size,
                duration_ms=(time.monotonic() - started) * 1000,
                outcome="failed" if failed else "ok",
                error_code=error_code or ("MCP_ERROR" if rpc_failed else None),
                downstream_request_ids=sorted(_downstream.get() or set()),
                request_id=context["request_id"],
            )
            try:
                await asyncio.to_thread(self.audit.append, call)
                self.logger.logger.info(
                    "mcp_tool_called",
                    duration_ms=call.duration_ms,
                    outcome=call.outcome,
                    payload={
                        "tool": tool,
                        "args_digest": call.args_digest,
                        "args_size": call.args_size,
                        "result_size": result_size,
                        "downstream_request_ids": call.downstream_request_ids,
                    },
                )
            except Exception:
                self.logger.logger.error(
                    "mcp_audit_failed", error_code="AUDIT_UNAVAILABLE", exc_info=True
                )
                captured = [
                    {
                        "type": "http.response.start",
                        "status": 503,
                        "headers": [(b"content-type", b"application/json")],
                    },
                    {"type": "http.response.body", "body": b'{"error":"AUDIT_UNAVAILABLE"}'},
                ]
            for message in captured:
                if message["type"] == "http.response.start":
                    message["headers"] = list(message.get("headers", [])) + [
                        (b"x-request-id", context["request_id"].encode())
                    ]
                await send(message)
