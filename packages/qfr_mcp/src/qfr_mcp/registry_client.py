"""The front door's registry-api client. It holds the control token only."""

from typing import Literal
from uuid import UUID

from qfr_core.contracts import FactorManifest, PoolStatus, StrategyManifest
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

from qfr_mcp.api_client import ApiClient, DownstreamRefused, DownstreamUnavailable

Pool = Literal["factor", "strategy"]


class RegistryUnavailable(DownstreamUnavailable):
    """The registry could not be reached or answered with something unreadable."""


class RegistryRefused(DownstreamRefused):
    """The registry answered with an ApiError (4xx)."""


class RegistryClient(ApiClient):
    backend = "registry-api"
    unavailable = RegistryUnavailable
    refused = RegistryRefused

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
