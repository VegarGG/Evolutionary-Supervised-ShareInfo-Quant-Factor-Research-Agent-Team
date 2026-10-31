"""The front door's clients for eval-admin-api (owner token) and feedback-api (reader token).

qfr-mcp imports no evaluator code: requests and responses use the shared contracts in
qfr_core.eval_api, and owner-grade evidence is checked against the private JSON schema.
"""

from typing import Any
from uuid import UUID

from pydantic import JsonValue
from qfr_core.eval_api import (
    ActivateRequest,
    ArtifactStatus,
    Card,
    ConfigKind,
    ConfigVersionView,
    CreateVersionRequest,
    ReportPage,
    VersionStatePage,
)

from qfr_mcp.api_client import ApiClient

ROUTES: dict[ConfigKind, str] = {"protocol": "protocols", "policy": "policies", "quotas": "quotas"}


class EvalAdminClient(ApiClient):
    backend = "eval-admin-api"

    async def summary(self) -> dict[str, JsonValue]:
        _, data = await self._call("GET", "/v1/summary")
        return dict(data)

    async def evidence(self, version_id: UUID) -> dict[str, JsonValue]:
        _, data = await self._call("GET", f"/v1/evidence/{version_id}")
        return dict(data)

    async def private_config(self) -> dict[str, JsonValue]:
        _, data = await self._call("GET", "/v1/config/private")
        return dict(data)

    async def version_states(self, version_ids: list[UUID]) -> VersionStatePage:
        if not version_ids:
            return VersionStatePage(items=[])
        params: dict[str, Any] = {"version_id": [str(v) for v in version_ids]}
        return await self._model(VersionStatePage, "GET", "/v1/versions/state", params=params)

    async def create_version(self, kind: ConfigKind, yaml_text: str) -> ConfigVersionView:
        body = CreateVersionRequest(yaml=yaml_text).model_dump(mode="json")
        return await self._model(ConfigVersionView, "POST", f"/v1/{ROUTES[kind]}", body=body)

    async def activate(
        self, kind: ConfigKind, config_id: str, version: str, approval_id: UUID | None
    ) -> ConfigVersionView:
        body = ActivateRequest(approval_id=approval_id).model_dump(mode="json")
        path = f"/v1/{ROUTES[kind]}/{config_id}/{version}/activate"
        return await self._model(ConfigVersionView, "POST", path, body=body)


class FeedbackClient(ApiClient):
    backend = "feedback-api"

    async def reports(self, **params: Any) -> ReportPage:
        return await self._model(ReportPage, "GET", "/v1/reports", params=params)

    async def status(self, version_id: UUID) -> ArtifactStatus:
        return await self._model(ArtifactStatus, "GET", f"/v1/artifacts/{version_id}/status")

    async def card(self, kind: str) -> Card:
        return await self._model(Card, "GET", f"/v1/cards/{kind}")
