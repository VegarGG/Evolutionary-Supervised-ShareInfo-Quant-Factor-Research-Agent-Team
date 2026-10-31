"""The evaluator's registry reader (PLAN INV-3, Section 8.3). Pull-only, evaluator token.

The scheduler polls versions by published_seq and pool events by event_seq. There is
no inbound route anywhere in the evaluation zone through which the registry, research
or the front door could trigger evaluation (EVL-01).
"""

from typing import Any

import httpx
from qfr_core.correlation import to_headers
from qfr_core.logging import JsonLogger


class RegistryUnavailable(RuntimeError):
    pass


class RegistryReader:
    def __init__(
        self,
        base_url: str,
        token: str,
        logger: JsonLogger,
        client: httpx.Client | None = None,
        timeout: float = 10.0,
    ) -> None:
        if not token:
            raise ValueError("REGISTRY_EVALUATOR_TOKEN is required")
        self.base_url, self.token, self.logger = base_url.rstrip("/"), token, logger
        self.client = client or httpx.Client(timeout=timeout, trust_env=False)

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        headers = to_headers() | {"Authorization": f"Bearer {self.token}"}
        try:
            response = self.client.get(self.base_url + path, params=params, headers=headers)
            data = response.json()
        except (httpx.HTTPError, ValueError) as error:
            self.logger.logger.warning(
                "registry_unavailable", outcome="failed", payload={"path": path}
            )
            raise RegistryUnavailable(type(error).__name__) from error
        if response.status_code != 200 or not isinstance(data, dict):
            self.logger.logger.warning(
                "registry_refused",
                outcome="failed",
                payload={"path": path, "status": response.status_code},
            )
            raise RegistryUnavailable(f"registry answered {response.status_code}")
        return data

    def versions(self, since_seq: int, limit: int) -> tuple[list[dict[str, Any]], int]:
        """Raw version records after since_seq; each is validated by the scheduler."""
        data = self._get("/v1/artifacts", {"since_seq": since_seq, "limit": limit})
        return list(data.get("items", [])), int(data.get("next_since_seq", since_seq))

    def pool_events(
        self, pool: str, since_seq: int, limit: int
    ) -> tuple[list[dict[str, Any]], int]:
        data = self._get(f"/v1/pools/{pool}/events", {"since_seq": since_seq, "limit": limit})
        return list(data.get("items", [])), int(data.get("next_since_seq", since_seq))

    def healthy(self) -> bool:
        try:
            response = self.client.get(self.base_url + "/healthz")
            return response.status_code == 200
        except httpx.HTTPError:
            return False
