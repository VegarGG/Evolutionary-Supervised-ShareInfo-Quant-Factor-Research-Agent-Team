"""A JSON client for one downstream API (registry-api, eval-admin-api, feedback-api).

Every call forwards the MCP call's request id (X-Request-Id), which the MCP boundary
records in mcp_calls.downstream_request_ids, so one id joins the audit row, the MCP log
line and the downstream service's request log.
"""

from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, JsonValue, ValidationError
from qfr_core.correlation import to_headers
from qfr_core.logging import JsonLogger

from qfr_mcp.boundary import record_downstream_request

M = TypeVar("M", bound=BaseModel)


class DownstreamUnavailable(RuntimeError):
    """The service could not be reached or answered with something unreadable."""


class DownstreamRefused(RuntimeError):
    """The service answered with an ApiError (4xx)."""

    def __init__(
        self, status: int, error: str, message: str, details: list[JsonValue], request_id: str
    ) -> None:
        super().__init__(f"{status} {error}: {message}")
        self.status, self.error, self.message = status, error, message
        self.details, self.request_id = details, request_id

    def as_dict(self) -> dict[str, JsonValue]:
        return {
            "status": self.status,
            "error": self.error,
            "message": self.message,
            "details": self.details,
        }


class ApiClient:
    backend = "downstream"
    unavailable: type[DownstreamUnavailable] = DownstreamUnavailable
    refused: type[DownstreamRefused] = DownstreamRefused

    def __init__(
        self,
        base_url: str,
        token: str,
        timeout: float,
        logger: JsonLogger,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not token:
            raise ValueError(f"a {self.backend} token is required")
        self.base_url, self.token, self.timeout = base_url.rstrip("/"), token, timeout
        self.logger, self.transport = logger, transport

    async def _call(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> tuple[int, Any]:
        headers = to_headers() | {"Authorization": f"Bearer {self.token}"}
        record_downstream_request(headers["X-Request-Id"])
        options: dict[str, Any] = {"timeout": timeout or self.timeout, "trust_env": False}
        if self.transport is not None:
            options["transport"] = self.transport
        query: list[tuple[str, str | int | float | bool | None]] = []
        for key, value in (params or {}).items():
            values = value if isinstance(value, list | tuple) else [value]
            query += [(key, str(v)) for v in values if v is not None]
        fields = {"backend": self.backend, "method": method, "path": path}
        try:
            async with httpx.AsyncClient(**options) as client:
                response = await client.request(
                    method, self.base_url + path, json=body, params=query, headers=headers
                )
            data = response.json()
        except (httpx.HTTPError, ValueError) as error:
            self.logger.logger.warning("downstream_unavailable", outcome="failed", payload=fields)
            raise self.unavailable(f"{self.backend} unavailable: {type(error).__name__}") from error
        if response.status_code >= 400:
            refusal = data if isinstance(data, dict) else {}
            self.logger.logger.warning(
                "downstream_refused",
                outcome="failed",
                error_code=str(refusal.get("error", "HTTP_ERROR")),
                payload=fields | {"status": response.status_code},
            )
            if response.status_code >= 500:
                raise self.unavailable(f"{self.backend} failed with {response.status_code}")
            raise self.refused(
                response.status_code,
                str(refusal.get("error", "HTTP_ERROR")),
                str(refusal.get("message", "")),
                list(refusal.get("details", [])),
                str(refusal.get("request_id", headers["X-Request-Id"])),
            )
        self.logger.logger.info(
            "downstream_call_completed",
            outcome="ok",
            payload=fields | {"status": response.status_code},
        )
        return response.status_code, data

    async def _model(self, model: type[M], method: str, path: str, **kw: Any) -> M:
        _, data = await self._call(method, path, **kw)
        try:
            return model.model_validate(data)
        except ValidationError as error:
            raise self.unavailable(
                f"{self.backend} returned an invalid {model.__name__}"
            ) from error

    async def health(self) -> dict[str, JsonValue]:
        _, data = await self._call("GET", "/healthz")
        return dict(data) if isinstance(data, dict) else {"status": "unreadable"}
