"""Phase 0 MCP front door: exactly five read tools, with explicit partial status."""

import logging
import os
from pathlib import Path
from typing import Literal

import httpx
import uvicorn
from mcp.server.fastmcp import FastMCP
from pydantic import JsonValue
from qfr_core.config import RuntimeSettings, load_config, logging_config, mcp_config
from qfr_core.contracts import Contract
from qfr_core.correlation import current, to_headers
from qfr_core.log_reader import LogQuery, LogReader
from qfr_core.logging import JsonLogger, StdlibBridge

from qfr_mcp.audit import AuditStore, PostgresAudit
from qfr_mcp.boundary import MCPBoundary, record_downstream_request


class ToolResult(Contract):
    request_id: str
    status: Literal["ok", "partial", "not_implemented_in_phase_0"]
    data: dict[str, JsonValue]


class BackendReader:
    def __init__(self, timeout: float, logger: JsonLogger) -> None:
        self.timeout, self.logger = timeout, logger

    async def get(self, env_name: str, path: str, token_env: str) -> dict[str, JsonValue]:
        base = os.environ.get(env_name)
        if not base:
            return {"status": "not_implemented_in_phase_0"}
        headers = to_headers() | {"Authorization": f"Bearer {os.environ.get(token_env, '')}"}
        record_downstream_request(headers["X-Request-Id"])
        try:
            async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
                response = await client.get(base.rstrip("/") + path, headers=headers)
                response.raise_for_status()
                result = response.json()
                if not isinstance(result, dict):
                    raise ValueError("backend returned a non-object")
                self.logger.logger.info(
                    "downstream_read_completed",
                    outcome="ok",
                    payload={"backend": env_name, "path": path},
                )
                return dict(result)
        except (httpx.HTTPError, ValueError):
            self.logger.logger.warning(
                "downstream_unavailable",
                outcome="failed",
                payload={"backend": env_name, "path": path},
            )
            return {"status": "unavailable", "implementation_phase": "later"}


def create_app(settings: RuntimeSettings, audit: AuditStore | None = None) -> MCPBoundary:
    config = mcp_config(settings.config_dir)
    log_config = logging_config(settings.config_dir)
    if settings.log_level:
        log_config = log_config.model_copy(update={"level": settings.log_level})
    if settings.mcp_token is None:
        raise ValueError("QFR_MCP_TOKEN is required")
    token = settings.mcp_token.get_secret_value()
    if audit is None:
        if settings.control_db_url is None:
            raise ValueError("CONTROL_DB_URL is required")
        audit = PostgresAudit(settings.control_db_url.get_secret_value())
    secret_values = [
        v
        for k, v in os.environ.items()
        if any(word in k.upper() for word in ("TOKEN", "PASSWORD", "SECRET", "API_KEY", "DB_URL"))
    ]
    logger = JsonLogger(
        "qfr-mcp", "control", settings.log_dir, log_config, secrets=secret_values + [token]
    )
    logging.getLogger().handlers = [StdlibBridge(logger)]
    logging.getLogger().setLevel(log_config.level)
    server = FastMCP(
        "qfr-mcp", stateless_http=True, json_response=True, streamable_http_path=config.path
    )
    reader = LogReader(
        Path(os.environ.get("QFR_LOG_READ_DIR", settings.log_dir)), log_config, config
    )
    backend = BackendReader(config.downstream_timeout_seconds, logger)

    def result(
        data: dict[str, JsonValue],
        status: Literal["ok", "partial", "not_implemented_in_phase_0"] = "ok",
    ) -> ToolResult:
        return ToolResult(request_id=current()["request_id"], status=status, data=data)

    @server.tool(
        name="qfr.status",
        description="Phase 0 readiness and API availability. Unimplemented services are explicit.",
    )
    async def status() -> ToolResult:
        services: dict[str, JsonValue] = {
            "qfr-mcp": {"status": "running"},
            "control_db": {"healthy": audit.healthy()},
        }
        for service, url, auth in (
            ("research-api", "RESEARCH_API_URL", "RESEARCH_CONTROL_TOKEN"),
            ("registry-api", "REGISTRY_API_URL", "REGISTRY_CONTROL_TOKEN"),
            ("eval-admin-api", "EVAL_ADMIN_API_URL", "EVAL_OWNER_TOKEN"),
            ("feedback-api", "FEEDBACK_API_URL", "FEEDBACK_READER_TOKEN"),
        ):
            services[service] = await backend.get(url, "/healthz", auth)
        return result(
            {
                "phase": 0,
                "services": services,
                "setup_complete": False,
                "pool_counts": None,
                "active_jobs": None,
                "budgets": None,
                "data_freshness": None,
                "burn_meters": None,
                "alerts": None,
                "notice": (
                    "No default factors. No default strategies. Research will start "
                    "from exploration only. Library-correlation and novelty checks "
                    "are vacuous until the pool has entries."
                ),
            },
            "partial",
        )

    @server.tool(
        name="qfr.config.get",
        description=(
            "Read public configuration previews, or request owner-only "
            "configuration from the evaluator API."
        ),
    )
    async def config_get(owner_only: bool = False) -> ToolResult:
        if owner_only:
            data = await backend.get("EVAL_ADMIN_API_URL", "/v1/config/private", "EVAL_OWNER_TOKEN")
            return result({"visibility": "owner_only", "configuration": data}, "partial")
        values: dict[str, JsonValue] = {"state": "preview_not_activated"}
        for kind in ("charter", "providers", "roles"):
            # Provider key environment names are non-secret; values are never resolved here.
            doc = load_config(kind, settings.config_dir)
            values[kind] = doc.values
        card_path = settings.config_dir / "public_cards.json"
        if card_path.exists():
            import json

            values["cards"] = json.loads(card_path.read_text())
        return result(values)

    @server.tool(
        name="qfr.logs.search",
        description=(
            "Search redacted JSON lines by time, services, levels, events, ids "
            "or text. Uses bounded cursor pagination."
        ),
    )
    def logs_search(query: LogQuery) -> ToolResult:
        page = reader.search(query)
        return result(page.model_dump(mode="json"))

    @server.tool(
        name="qfr.logs.tail",
        description=(
            "Return the last n redacted log lines for one service or all "
            "services, up to the configured maximum."
        ),
    )
    def logs_tail(service: str | None = None, n: int | None = None) -> ToolResult:
        return result(reader.tail(service, n).model_dump(mode="json"))

    @server.tool(
        name="qfr.logs.correlate",
        description=(
            "Read ordered log lines carrying an entity or request id, grouped "
            "by service, with a continuation cursor."
        ),
    )
    def logs_correlate(id: str, id_kind: str, query: LogQuery) -> ToolResult:
        return result(reader.correlate(id, id_kind, query))

    logger.logger.info(
        "service_started",
        payload={
            "phase": 0,
            "configuration_digest": load_config("mcp", settings.config_dir).sha256,
        },
    )
    return MCPBoundary(server.streamable_http_app(), token, config, audit, logger)


def main() -> None:
    settings = RuntimeSettings()
    config = mcp_config(settings.config_dir)
    host = settings.mcp_bind or config.bind
    # Inside the isolated Docker network it must listen on the container interface;
    # Compose publishes only 127.0.0.1 on the Mac. Direct launches remain loopback.
    if host == "0.0.0.0" and not Path("/.dockerenv").exists():
        raise ValueError("non-loopback binding is permitted only inside a container")
    if host not in {"127.0.0.1", "::1", "0.0.0.0"}:
        raise ValueError("invalid MCP bind address")
    uvicorn.run(
        create_app(settings), host=host, port=config.port, access_log=False, log_config=None
    )


if __name__ == "__main__":
    main()
