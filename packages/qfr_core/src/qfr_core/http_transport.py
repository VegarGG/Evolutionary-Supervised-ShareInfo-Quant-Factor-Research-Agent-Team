"""Authenticate before parsing bounded JSON; never log credentials or request bodies."""

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from qfr_core.access import AuthenticationRequired, BearerAuthority
from qfr_core.data_layer.snapshots import canonical_json


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


Scope = dict[str, Any]
Message = dict[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


class BoundedServiceBoundary:
    def __init__(
        self,
        app: ASGIApp,
        *,
        authority: BearerAuthority | None,
        audience: str,
        maximum_bytes: int,
        timeout_seconds: int,
        request_log: Callable[[dict[str, object]], None],
        binary_route: Callable[[Scope], bool] | None = None,
    ):
        self.app, self.authority, self.audience = app, authority, audience
        self.maximum_bytes, self.timeout_seconds = maximum_bytes, timeout_seconds
        self.request_log, self.binary_route = request_log, binary_route

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        state = scope.setdefault("state", {})
        state.update(request_id=str(uuid4()), principal=None)
        status = 500
        started = False

        async def response(message: Message) -> None:
            nonlocal status, started
            if message["type"] == "http.response.start":
                status, started = message["status"], True
                message.setdefault("headers", []).extend(
                    [
                        (b"x-request-id", state["request_id"].encode()),
                        (b"cache-control", b"no-store"),
                        (b"x-content-type-options", b"nosniff"),
                    ]
                )
            await send(message)

        async def reject(code: int, detail: str) -> None:
            data = canonical_json({"detail": detail})
            await response(
                {
                    "type": "http.response.start",
                    "status": code,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(data)).encode()),
                    ],
                }
            )
            await response({"type": "http.response.body", "body": data})

        try:
            if not (scope["path"] == "/healthz" and scope["method"] == "GET"):
                try:
                    if self.authority is None:
                        raise AuthenticationRequired()
                    state["principal"] = self.authority.authenticate(
                        [
                            v.decode("latin-1")
                            for k, v in scope["headers"]
                            if k.lower() == b"authorization"
                        ],
                        audience=self.audience,
                    )
                except AuthenticationRequired:
                    await reject(401, "service authentication required")
                    return
            if scope["method"] not in {"GET", "POST"}:
                await reject(405, "unsupported service method")
                return
            lengths = [v for k, v in scope["headers"] if k.lower() == b"content-length"]
            if len(lengths) > 1 or (
                lengths
                and (
                    len(lengths[0]) > 20
                    or not lengths[0].isdigit()
                    or int(lengths[0]) > self.maximum_bytes
                )
            ):
                await reject(413, "service request size refused")
                return
            chunks: list[bytes] = []
            size = 0
            try:
                async with asyncio.timeout(self.timeout_seconds):
                    while True:
                        message = await receive()
                        if message["type"] == "http.disconnect":
                            return  # No operation has been admitted yet.
                        if message["type"] != "http.request":
                            await reject(400, "invalid service transport")
                            return
                        data = message.get("body", b"")
                        size += len(data)
                        if size > self.maximum_bytes:
                            await reject(413, "service request size refused")
                            return
                        chunks.append(data)
                        if not message.get("more_body", False):
                            break
            except TimeoutError:
                await reject(408, "service request body timed out")
                return
            raw = b"".join(chunks)
            if lengths and size != int(lengths[0]):
                await reject(400, "service request length differs")
                return
            if scope["method"] == "GET" and raw:
                await reject(400, "service reads do not accept bodies")
                return
            if scope["method"] == "POST" and self.binary_route and self.binary_route(scope):
                types = [v for k, v in scope["headers"] if k.lower() == b"content-type"]
                if types != [b"application/octet-stream"]:
                    await reject(400, "binary content type required")
                    return
            elif scope["method"] == "POST":
                types = [
                    v.split(b";", 1)[0].strip().lower()
                    for k, v in scope["headers"]
                    if k.lower() == b"content-type"
                ]
                try:
                    if types != [b"application/json"]:
                        raise ValueError()
                    value = json.loads(raw, object_pairs_hook=_object)
                    if not isinstance(value, dict):
                        raise ValueError()
                    canonical_json(value)
                except (ValueError, UnicodeError, RecursionError):
                    await reject(400, "invalid service JSON body")
                    return
            delivered = False

            async def body_once() -> Message:
                nonlocal delivered
                if delivered:
                    return await receive()
                delivered = True
                return {"type": "http.request", "body": raw, "more_body": False}

            try:
                await self.app(scope, body_once, response)
            except Exception:
                if started:
                    raise
                await reject(503, "service operation unavailable")
        finally:
            principal = state["principal"]
            route = scope.get("route")
            self.request_log(
                dict(
                    request_id=state["request_id"],
                    principal=principal.name if principal else None,
                    at=datetime.now(UTC).isoformat(),
                    method=scope["method"],
                    route=getattr(route, "path", "<unmatched>"),
                    status=status,
                )
            )
