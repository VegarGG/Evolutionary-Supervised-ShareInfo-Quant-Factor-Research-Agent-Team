"""MCP front door: Phase 0 reads plus the Phase 2 setup, pool, DSL and artifact tools."""

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

import httpx
import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import JsonValue
from qfr_core.config import (
    RuntimeSettings,
    load_config,
    logging_config,
    mcp_config,
    public_protocol_section,
)
from qfr_core.contracts import Contract, PoolStatus
from qfr_core.correlation import current, to_headers
from qfr_core.dsl import DslLimits, canonicalize, parse, validate
from qfr_core.dsl.explain import explain
from qfr_core.log_reader import LogQuery, LogReader
from qfr_core.logging import JsonLogger, StdlibBridge
from qfr_core.pool_import import NO_DEFAULTS_NOTICE
from qfr_core.registry_api import RegistrySummary

from qfr_mcp.audit import AuditStore, PostgresAudit
from qfr_mcp.boundary import MCPBoundary, record_downstream_request
from qfr_mcp.control_store import SETUP_STEPS, ControlStore, PostgresControlStore, SetupState
from qfr_mcp.pool_importer import PoolImporter, pool_counts
from qfr_mcp.registry_client import RegistryClient, RegistryRefused, RegistryUnavailable

PHASE = 2
READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
WRITE = ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False
)
DONE_STATUSES = frozenset({"ok", "imported", "empty", "kept"})
# Steps whose implementation lands in a later phase; shown until a row records them.
DEFERRED_STEPS: dict[str, dict[str, JsonValue]] = {
    "providers": {
        "status": "deferred",
        "implementation_phase": 4,
        "next": "qfr llm probe arrives in Phase 4; setup cannot finish before it passes.",
    },
    "data": {
        "status": "deferred",
        "implementation_phase": 3,
        "next": (
            "Build snapshots with `just data-build --source synthetic` for a dry run or "
            "`--source cn`; eval-admin-api reports snapshot ids from Phase 3."
        ),
    },
}


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


def _state_view(state: SetupState) -> dict[str, JsonValue]:
    return {
        "status": state.status,
        "at": state.at.isoformat(),
        "state_id": str(state.state_id),
        "details": state.details,
    }


def create_app(
    settings: RuntimeSettings,
    audit: AuditStore | None = None,
    control: ControlStore | None = None,
    registry_transport: httpx.AsyncBaseTransport | None = None,
) -> MCPBoundary:
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
    if control is None:
        if settings.control_db_url is None:
            raise ValueError("CONTROL_DB_URL is required")
        control = PostgresControlStore(settings.control_db_url.get_secret_value())
    store: ControlStore = control
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
    limits = DslLimits.from_protocol(public_protocol_section(settings.config_dir, "dsl"))
    registry: RegistryClient | None = None
    if os.environ.get("REGISTRY_API_URL"):
        registry = RegistryClient(
            os.environ["REGISTRY_API_URL"],
            os.environ.get("REGISTRY_CONTROL_TOKEN", ""),
            config.downstream_timeout_seconds,
            logger,
            registry_transport,
        )
    imports = os.environ.get("QFR_IMPORTS_DIR")
    importer = (
        PoolImporter(registry, store, limits, config, Path(imports) if imports else None, logger)
        if registry is not None
        else None
    )

    def require_registry() -> RegistryClient:
        if registry is None:
            raise RuntimeError("REGISTRY_UNCONFIGURED: REGISTRY_API_URL is not set")
        return registry

    async def summary_or_none() -> RegistrySummary | None:
        if registry is None:
            return None
        try:
            return await registry.summary()
        except (RegistryUnavailable, RegistryRefused):
            return None

    async def registry_health() -> dict[str, JsonValue]:
        if registry is None:
            return {"status": "not_configured"}
        try:
            return await registry.health()
        except (RegistryUnavailable, RegistryRefused):
            return {"status": "unavailable"}

    def counts_view(summary: RegistrySummary | None) -> dict[str, JsonValue] | None:
        if summary is None:
            return None
        return {k: v.model_dump(mode="json") for k, v in pool_counts(summary).items()}

    def notice_for(summary: RegistrySummary | None, pool: SetupState | None) -> str | None:
        empty = (
            summary.empty if summary is not None else pool is not None and pool.status == "empty"
        )
        return NO_DEFAULTS_NOTICE if empty else None

    def result(
        data: dict[str, JsonValue],
        status: Literal["ok", "partial", "not_implemented_in_phase_0"] = "ok",
    ) -> ToolResult:
        return ToolResult(request_id=current()["request_id"], status=status, data=data)

    @server.tool(
        name="qfr.status",
        description=(
            "Health of every service, setup state, registry and pool counts, and the "
            "no-defaults notice while the pools are empty. Services of later phases are "
            "reported as unavailable or not implemented, never guessed."
        ),
        annotations=READ,
    )
    async def status() -> ToolResult:
        services: dict[str, JsonValue] = {
            "qfr-mcp": {"status": "running"},
            "control_db": {"healthy": await asyncio.to_thread(store.healthy)},
        }
        for service, url, auth in (
            ("research-api", "RESEARCH_API_URL", "RESEARCH_CONTROL_TOKEN"),
            ("eval-admin-api", "EVAL_ADMIN_API_URL", "EVAL_OWNER_TOKEN"),
            ("feedback-api", "FEEDBACK_API_URL", "FEEDBACK_READER_TOKEN"),
        ):
            services[service] = await backend.get(url, "/healthz", auth)
        services["registry-api"] = await registry_health()
        states = await asyncio.to_thread(store.latest_setup_states)
        summary = await summary_or_none()
        return result(
            {
                "phase": PHASE,
                "services": services,
                "setup_complete": all(
                    s in states and states[s].status in DONE_STATUSES for s in SETUP_STEPS
                ),
                "setup": {step: _state_view(state) for step, state in states.items()},
                "pool_counts": counts_view(summary),
                "registry_counts": None
                if summary is None
                else {
                    "factor_versions": summary.factor_versions,
                    "strategy_versions": summary.strategy_versions,
                    "families": summary.families,
                },
                "active_jobs": None,
                "budgets": None,
                "data_freshness": None,
                "burn_meters": None,
                "alerts": None,
                "notice": notice_for(summary, states.get("pool")),
            },
            "partial",
        )

    @server.tool(
        name="qfr.setup.status",
        description=(
            "Setup state per step (pool, providers, data, token), pool counts and the "
            "no-defaults notice. Provider probes arrive in Phase 4 and snapshot ids in "
            "Phase 3; until then those steps read deferred."
        ),
        annotations=READ,
    )
    async def setup_status() -> ToolResult:
        states = await asyncio.to_thread(store.latest_setup_states)
        summary = await summary_or_none()
        steps: dict[str, JsonValue] = {}
        for step in SETUP_STEPS:
            if step in states:
                steps[step] = _state_view(states[step])
            elif step == "pool":
                steps[step] = {
                    "status": "not_started",
                    "next": (
                        "Place a pool_import/1 file (JSON, YAML or CSV) under imports/ and "
                        "call qfr.pool.import with file=<name>, or call it with "
                        "no_pool=true to start empty."
                    ),
                }
            elif step == "token":
                steps[step] = {
                    "status": "ok",
                    "detail": (
                        "This call authenticated with the owner token; `just mcp-config` "
                        "prints the host-agent snippets."
                    ),
                }
            else:
                steps[step] = DEFERRED_STEPS[step]
        done = all(isinstance(v, dict) and v.get("status") in DONE_STATUSES for v in steps.values())
        return result(
            {
                "phase": PHASE,
                "setup_complete": done,
                "steps": steps,
                "probe_results": None,
                "snapshot_ids": None,
                "pool_counts": counts_view(summary),
                "registry": "ok" if summary is not None else "unavailable",
                "notice": notice_for(summary, states.get("pool")),
            },
            "partial",
        )

    @server.tool(
        name="qfr.pool.import",
        description=(
            "Import a raw factor pool (pool_import/1). Give exactly one of: file (a name "
            "under imports/; JSON, YAML or CSV), entries (inline list of entries), or "
            "no_pool=true (start empty; records the no-defaults notice). Every expression "
            "is validated like an agent draft; valid entries become human_seed versions "
            "and seed pool entries. Returns a per-entry outcome with reason codes. "
            "Re-importing the same definitions is idempotent."
        ),
        annotations=WRITE,
    )
    async def pool_import(
        file: str | None = None,
        entries: list[dict[str, Any]] | None = None,
        no_pool: bool = False,
    ) -> ToolResult:
        if importer is None:
            raise RuntimeError("REGISTRY_UNCONFIGURED: REGISTRY_API_URL is not set")
        raw: list[JsonValue] | None = list(entries) if entries is not None else None
        report = await importer.run(file=file, entries=raw, no_pool=no_pool)
        clean = report.counts.invalid + report.counts.failed == 0
        return result(report.model_dump(mode="json"), "ok" if clean else "partial")

    @server.tool(
        name="qfr.pool.list",
        description=(
            "List current entries of the factor or strategy pool with status, approved "
            "tier and tags. Optional status filter (seed, approved, retired), limit "
            "(default 200, max 2000) and cursor from the previous page. Evidence tiers and "
            "released state come from the evaluator from Phase 3 and are null until then."
        ),
        annotations=READ,
    )
    async def pool_list(
        pool: Literal["factor", "strategy"],
        status: PoolStatus | None = None,
        limit: int | None = None,
        cursor: UUID | None = None,
    ) -> ToolResult:
        size = limit or config.list_default
        if not 1 <= size <= config.list_max:
            raise ValueError(f"LIMIT_INVALID: limit must be between 1 and {config.list_max}")
        page = await require_registry().pool_entries(pool, status, size, cursor)
        items: list[JsonValue] = [
            item.model_dump(mode="json") | {"evidence_tier": None, "released_state": None}
            for item in page.items
        ]
        return result(
            {
                "pool": pool,
                "items": items,
                "next_cursor": page.next_cursor,
                "evidence": "not_implemented_until_phase_3",
            },
            "partial",
        )

    @server.tool(
        name="qfr.pool.get",
        description=(
            "One pool entry with its full event history and the version it holds "
            "(manifest and server fields). Arguments: pool and entry_id."
        ),
        annotations=READ,
    )
    async def pool_get(pool: Literal["factor", "strategy"], entry_id: UUID) -> ToolResult:
        client = require_registry()
        detail = await client.pool_entry(pool, entry_id)
        version = await client.get_version(detail.entry.version_id)
        return result(
            {
                "entry": detail.entry.model_dump(mode="json"),
                "events": [e.model_dump(mode="json") for e in detail.events],
                "version": version.model_dump(mode="json"),
                "evidence_tier": None,
                "released_state": None,
                "evidence": "not_implemented_until_phase_3",
            },
            "partial",
        )

    @server.tool(
        name="qfr.dsl.validate",
        description=(
            "Parse, type-check and constrain one qfr-dsl/1 expression with the protocol "
            "card's limits. Returns ok, reason-coded errors, the canonical form and hash, "
            "complexity measures and a deterministic plain-language explanation. Runs in "
            "process; nothing is stored."
        ),
        annotations=READ,
    )
    def dsl_validate(expression: str) -> ToolResult:
        check = validate(expression, limits)
        data: dict[str, JsonValue] = {
            "ok": check.ok,
            "errors": [dict(e) for e in check.errors],
            "analysis": None,
            "explanation": None,
        }
        if check.analysis is not None:
            data["analysis"] = check.analysis.model_dump(mode="json")
            tree = canonicalize(parse(expression))
            data["explanation"] = explain(tree, check.analysis).model_dump(mode="json")
        return result(data)

    @server.tool(
        name="qfr.artifact.get",
        description="Manifest and server fields (hashes, family, version number, sequence) "
        "of one published version. Argument: version_id.",
        annotations=READ,
    )
    async def artifact_get(version_id: UUID) -> ToolResult:
        version = await require_registry().get_version(version_id)
        return result(version.model_dump(mode="json"))

    @server.tool(
        name="qfr.config.get",
        description=(
            "Read public configuration previews, or request owner-only "
            "configuration from the evaluator API."
        ),
        annotations=READ,
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
        annotations=READ,
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
        annotations=READ,
    )
    def logs_tail(service: str | None = None, n: int | None = None) -> ToolResult:
        return result(reader.tail(service, n).model_dump(mode="json"))

    @server.tool(
        name="qfr.logs.correlate",
        description=(
            "Read ordered log lines carrying an entity or request id, grouped "
            "by service, with a continuation cursor."
        ),
        annotations=READ,
    )
    def logs_correlate(id: str, id_kind: str, query: LogQuery) -> ToolResult:
        return result(reader.correlate(id, id_kind, query))

    logger.logger.info(
        "service_started",
        payload={
            "phase": PHASE,
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
