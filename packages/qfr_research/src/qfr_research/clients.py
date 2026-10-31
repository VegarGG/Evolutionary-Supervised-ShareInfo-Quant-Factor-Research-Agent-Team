"""The research zone's clients: registry-api with the publisher token, feedback-api with
the reader token (PLAN Sections 16.5, 16.6 and 16.9).

These are the only services research reaches. There is no client for eval-admin-api or
control_db, and research holds no token for them (BND-05). Every request forwards the
correlation ids, so the registry's and feedback-api's request lines carry the job id.
"""

from typing import Any, TypeVar
from uuid import UUID

import httpx
from pydantic import BaseModel, ValidationError
from qfr_core.contracts import FactorManifest, StrategyManifest
from qfr_core.correlation import to_headers
from qfr_core.eval_api import Card, ReportPage
from qfr_core.logging import JsonLogger
from qfr_core.registry_api import LineageView, PoolPage, PublishResponse, VersionRecord

M = TypeVar("M", bound=BaseModel)


class ServiceUnavailable(RuntimeError):
    pass


class ServiceRefused(RuntimeError):
    def __init__(self, status: int, error: str, message: str) -> None:
        super().__init__(f"{status} {error}: {message}")
        self.status, self.error, self.message = status, error, message


class _Client:
    backend = "downstream"

    def __init__(
        self,
        base_url: str,
        token: str,
        logger: JsonLogger,
        timeout: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        if not token:
            raise ValueError(f"a {self.backend} token is required")
        self.base_url, self.token, self.logger = base_url.rstrip("/"), token, logger
        self.client = client or httpx.Client(timeout=timeout, trust_env=False)

    def _call(
        self, method: str, path: str, *, body: Any = None, params: dict[str, Any] | None = None
    ) -> Any:
        headers = to_headers() | {"Authorization": f"Bearer {self.token}"}
        query = {k: str(v) for k, v in (params or {}).items() if v is not None}
        fields = {"backend": self.backend, "method": method, "path": path}
        try:
            response = self.client.request(
                method, self.base_url + path, json=body, params=query, headers=headers
            )
            data = response.json()
        except (httpx.HTTPError, ValueError) as error:
            self.logger.logger.warning("downstream_unavailable", outcome="failed", payload=fields)
            raise ServiceUnavailable(f"{self.backend}: {type(error).__name__}") from error
        if response.status_code >= 500:
            raise ServiceUnavailable(f"{self.backend} failed with {response.status_code}")
        if response.status_code >= 400:
            error = data if isinstance(data, dict) else {}
            self.logger.logger.warning(
                "downstream_refused",
                outcome="failed",
                error_code=str(error.get("error", "HTTP_ERROR")),
                payload=fields | {"status": response.status_code},
            )
            raise ServiceRefused(
                response.status_code,
                str(error.get("error", "HTTP_ERROR")),
                str(error.get("message", "")),
            )
        return data

    def _model(self, model: type[M], method: str, path: str, **kw: Any) -> M:
        try:
            return model.model_validate(self._call(method, path, **kw))
        except ValidationError as error:
            raise ServiceUnavailable(f"{self.backend} returned an invalid {model.__name__}") from error

    def healthy(self) -> bool:
        try:
            self._call("GET", "/healthz")
            return True
        except (ServiceUnavailable, ServiceRefused):
            return False


class RegistryClient(_Client):
    backend = "registry-api"

    def publish(
        self, manifest: FactorManifest | StrategyManifest, publish_key: str
    ) -> PublishResponse:
        body = {"publish_key": publish_key, "manifest": manifest.model_dump(mode="json")}
        return self._model(PublishResponse, "POST", "/v1/artifacts", body=body)

    def version(self, version_id: UUID) -> VersionRecord:
        return self._model(VersionRecord, "GET", f"/v1/artifacts/{version_id}")

    def lineage(self, version_id: UUID, depth: int = 5) -> LineageView:
        params = {"depth": depth}
        return self._model(LineageView, "GET", f"/v1/artifacts/{version_id}/lineage", params=params)

    def pool(self, pool: str, limit: int = 2000, cursor: str | None = None) -> PoolPage:
        params = {"limit": limit, "cursor": cursor}
        return self._model(PoolPage, "GET", f"/v1/pools/{pool}", params=params)


class FeedbackClient(_Client):
    backend = "feedback-api"

    def reports(self, **params: Any) -> ReportPage:
        return self._model(ReportPage, "GET", "/v1/reports", params=params)

    def card(self, kind: str) -> Card:
        return self._model(Card, "GET", f"/v1/cards/{kind}")
