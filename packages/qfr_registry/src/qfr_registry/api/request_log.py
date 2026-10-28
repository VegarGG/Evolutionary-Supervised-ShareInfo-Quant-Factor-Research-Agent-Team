"""Request attribution without credentials, query strings or uploaded content."""

import json
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from qfr_registry.publication import uuid7

RequestLog = dict[str, object]


def log_request(record: RequestLog) -> None:
    # An embedding application's default WARNING log level must not silently
    # discard mandatory request attribution. Container stderr is the log sink.
    print(json.dumps(record, sort_keys=True), file=sys.stderr, flush=True)


class RequestContext:
    def __init__(self, app: ASGIApp, sink: Callable[[RequestLog], None]):
        self.app = app
        self.sink = sink

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = Headers(scope=scope).getlist("x-request-id")
        valid_id = True
        try:
            if len(headers) > 1:
                raise ValueError("duplicate request id")
            identity = UUID(headers[0]) if headers else uuid7()
        except ValueError:
            valid_id = False
            identity = uuid7()
        state = scope.setdefault("state", {})
        state["request_id"] = identity
        state["principal"] = "anonymous"
        status = 500

        async def attributed_send(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                response_headers = [
                    (key, value)
                    for key, value in message.get("headers", [])
                    if key.lower() != b"x-request-id"
                ]
                message = {
                    **message,
                    "headers": [
                        *response_headers,
                        (b"x-request-id", str(identity).encode("ascii")),
                    ],
                }
            await send(message)

        try:
            if not valid_id:
                await JSONResponse({"detail": "invalid request id"}, status_code=400)(
                    scope, receive, attributed_send
                )
            else:
                await self.app(scope, receive, attributed_send)
        finally:
            self.sink(
                {
                    "event": "registry_request",
                    "request_id": str(identity),
                    "at": datetime.now(UTC).isoformat(),
                    "principal": state["principal"],
                    "method": scope["method"],
                    "route": getattr(scope.get("route"), "path", "unmatched"),
                    "status": status,
                }
            )
