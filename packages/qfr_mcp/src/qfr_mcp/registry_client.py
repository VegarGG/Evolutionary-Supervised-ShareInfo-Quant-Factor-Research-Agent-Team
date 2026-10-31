"""The front door's registry-api client. It holds the control token only.

Every call forwards the MCP call's request id (X-Request-Id), which the MCP boundary
records in mcp_calls.downstream_request_ids, so one id joins the audit row, the MCP log
line and the registry's request log.
"""

from typing import Any, Literal, TypeVar
from uuid import UUID

import httpx
from pydantic import BaseModel, JsonValue, ValidationError
from qfr_core.contracts import FactorManifest, PoolStatus, StrategyManifest
from qfr_core.correlation import to_headers
from qfr_core.logging import JsonLogger
from qfr_core.registry_api import (
    AddEntryRequest,
    AddEntryResponse,
    AppendEventRequest,
    PoolEntryDetail,
    PoolEvent,
    PoolPage,
    PublishResponse,
    RegistrySummary,
    VersionRecord,
)

from qfr_mcp.boundary import record_downstream_request

Pool = Literal["factor", "strategy"]
M = TypeVar("M", bound=BaseModel)


class RegistryUnavailable(RuntimeError):
    """The registry could not be reached or answered with something unreadable."""


class RegistryRefused(RuntimeError):
    """The registry answered with an ApiError (4xx)."""

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


class RegistryClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        timeout: float,
        logger: JsonLogger,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not token:
            raise ValueError("REGISTRY_CONTROL_TOKEN is required")
        self.base_url, self.token, self.timeout = base_url.rstrip("/"), token, timeout
        self.logger, self.transport = logger, transport

    async def _call(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> tuple[int, Any]:
        headers = to_headers() | {"Authorization": f"Bearer {self.token}"}
        record_downstream_request(headers["X-Request-Id"])
        options: dict[str, Any] = {"timeout": self.timeout, "trust_env": False}
        if self.transport is not None:
            options["transport"] = self.transport
        query = {k: str(v) for k, v in (params or {}).items() if v is not None}
        fields = {"backend": "registry-api", "method": method, "path": path}
        try:
            async with httpx.AsyncClient(**options) as client:
                response = await client.request(
                    method, self.base_url + path, json=body, params=query, headers=headers
                )
            data = response.json()
        except (httpx.HTTPError, ValueError) as error:
            self.logger.logger.warning("downstream_unavailable", outcome="failed", payload=fields)
            raise RegistryUnavailable(
                f"registry-api unavailable: {type(error).__name__}"
            ) from error
        if response.status_code >= 400:
            refusal = data if isinstance(data, dict) else {}
            self.logger.logger.warning(
                "downstream_refused",
                outcome="failed",
                error_code=str(refusal.get("error", "HTTP_ERROR")),
                payload=fields | {"status": response.status_code},
            )
            if response.status_code >= 500:
                raise RegistryUnavailable(f"registry-api failed with {response.status_code}")
            raise RegistryRefused(
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
            raise RegistryUnavailable(
                f"registry-api returned an invalid {model.__name__}"
            ) from error

    async def health(self) -> dict[str, JsonValue]:
        _, data = await self._call("GET", "/healthz")
        return dict(data) if isinstance(data, dict) else {"status": "unreadable"}

    async def summary(self) -> RegistrySummary:
        return await self._model(RegistrySummary, "GET", "/v1/summary")

    async def publish(
        self, manifest: FactorManifest | StrategyManifest, publish_key: str
    ) -> PublishResponse:
        body = {"publish_key": publish_key, "manifest": manifest.model_dump(mode="json")}
        return await self._model(PublishResponse, "POST", "/v1/artifacts", body=body)

    async def get_version(self, version_id: UUID) -> VersionRecord:
        return await self._model(VersionRecord, "GET", f"/v1/artifacts/{version_id}")

    async def add_entry(self, pool: Pool, request: AddEntryRequest) -> AddEntryResponse:
        body = request.model_dump(mode="json")
        return await self._model(AddEntryResponse, "POST", f"/v1/pools/{pool}/entries", body=body)

    async def append_event(
        self, pool: Pool, entry_id: UUID, request: AppendEventRequest
    ) -> PoolEvent:
        path = f"/v1/pools/{pool}/entries/{entry_id}/events"
        return await self._model(PoolEvent, "POST", path, body=request.model_dump(mode="json"))

    async def pool_entries(
        self, pool: Pool, status: PoolStatus | None, limit: int, cursor: UUID | None
    ) -> PoolPage:
        params = {"status": status, "limit": limit, "cursor": cursor}
        return await self._model(PoolPage, "GET", f"/v1/pools/{pool}", params=params)

    async def pool_entry(self, pool: Pool, entry_id: UUID) -> PoolEntryDetail:
        return await self._model(PoolEntryDetail, "GET", f"/v1/pools/{pool}/entries/{entry_id}")
