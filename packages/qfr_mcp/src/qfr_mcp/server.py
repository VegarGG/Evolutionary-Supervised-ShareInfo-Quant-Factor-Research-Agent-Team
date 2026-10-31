"""MCP front door: Phase 0 reads, the Phase 2 setup, pool, DSL and artifact tools, the
Phase 3 evidence, report and evaluator-configuration tools, and the Phase 4 job,
deliverable, trace, lineage and cost tools with their resources and prompts."""

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
from qfr_core.contracts import PoolStatus
from qfr_core.correlation import current
from qfr_core.dsl import DslLimits, canonicalize, parse, validate
from qfr_core.dsl.explain import explain
from qfr_core.log_reader import LogQuery, LogReader
from qfr_core.logging import JsonLogger, StdlibBridge
from qfr_core.pool_import import NO_DEFAULTS_NOTICE
from qfr_core.registry_api import RegistrySummary
from qfr_core.research_api import ResearchSummary

from qfr_mcp.api_client import DownstreamRefused, DownstreamUnavailable
from qfr_mcp.audit import AuditStore, PostgresAudit
from qfr_mcp.boundary import MCPBoundary
from qfr_mcp.control_store import SETUP_STEPS, ControlStore, PostgresControlStore, SetupState
from qfr_mcp.eval_client import EvalAdminClient, FeedbackClient
from qfr_mcp.evidence_validation import validate_owner_evidence
from qfr_mcp.imports import ImportPathError, read_import
from qfr_mcp.job_tools import JobToolDeps
from qfr_mcp.job_tools import register as register_job_tools
from qfr_mcp.pool_importer import PoolImporter, pool_counts
from qfr_mcp.registry_client import RegistryClient, RegistryRefused, RegistryUnavailable
from qfr_mcp.research_client import ResearchClient
from qfr_mcp.resources import register as register_resources
from qfr_mcp.results import ToolResult

PHASE = 4
READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
WRITE = ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False
)
DONE_STATUSES = frozenset({"ok", "imported", "empty", "kept"})
PROBE_NEXT = (
    "Run `docker compose exec research-worker qfr llm probe --trigger setup`; setup cannot "
    "finish before every role has a usable model."
)
DATA_NEXT = (
    "Build snapshots with `just data-build --source synthetic` for a dry run or "
    "`--source cn`; the evaluator registers the full snapshot and activates the epoch "
    "on its next tick."
)
ConfigFile = Literal["protocol", "policy", "quotas"]


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
    eval_transports: dict[str, httpx.AsyncBaseTransport] | None = None,
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
    transports = eval_transports or {}
    admin: EvalAdminClient | None = None
    if os.environ.get("EVAL_ADMIN_API_URL"):
        admin = EvalAdminClient(
            os.environ["EVAL_ADMIN_API_URL"],
            os.environ.get("EVAL_OWNER_TOKEN", ""),
            config.downstream_timeout_seconds,
            logger,
            transports.get("eval-admin-api"),
        )
    feedback: FeedbackClient | None = None
    if os.environ.get("FEEDBACK_API_URL"):
        feedback = FeedbackClient(
            os.environ["FEEDBACK_API_URL"],
            os.environ.get("FEEDBACK_READER_TOKEN", ""),
            config.downstream_timeout_seconds,
            logger,
            transports.get("feedback-api"),
        )
    research: ResearchClient | None = None
    if os.environ.get("RESEARCH_API_URL"):
        research = ResearchClient(
            os.environ["RESEARCH_API_URL"],
            os.environ.get("RESEARCH_CONTROL_TOKEN", ""),
            config.downstream_timeout_seconds,
            logger,
            transports.get("research-api"),
        )
    evidence_schema = Path(
        os.environ.get("QFR_OWNER_EVIDENCE_SCHEMA") or "schemas/private/owner_evidence.json"
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

    def require_admin() -> EvalAdminClient:
        if admin is None:
            raise RuntimeError("EVAL_ADMIN_UNCONFIGURED: EVAL_ADMIN_API_URL is not set")
        return admin

    def require_feedback() -> FeedbackClient:
        if feedback is None:
            raise RuntimeError("FEEDBACK_UNCONFIGURED: FEEDBACK_API_URL is not set")
        return feedback

    async def eval_summary() -> dict[str, JsonValue] | None:
        if admin is None:
            return None
        try:
            return await admin.summary()
        except (DownstreamUnavailable, DownstreamRefused):
            return None

    async def research_summary() -> ResearchSummary | None:
        if research is None:
            return None
        try:
            return await research.summary()
        except (DownstreamUnavailable, DownstreamRefused):
            return None

    def providers_step(summary: ResearchSummary | None) -> dict[str, JsonValue]:
        """The providers step from research's latest probe (Section 11.8)."""
        if research is None:
            return {"status": "not_configured", "next": PROBE_NEXT}
        if summary is None:
            return {"status": "unavailable", "next": "research-api did not answer."}
        probe = summary.last_probe
        if probe is None:
            return {"status": "not_started", "next": PROBE_NEXT}
        return {
            "status": "ok" if probe.ok else "failed",
            "at": probe.at.isoformat(),
            "trigger": probe.trigger,
            "probe_id": str(probe.probe_id),
            "roles_usable": [r for r, v in sorted(probe.roles.items()) if v.ok],
            "roles_unusable": [r for r, v in sorted(probe.roles.items()) if not v.ok],
            "next": None if probe.ok else PROBE_NEXT,
        }

    async def eval_health(
        client: EvalAdminClient | FeedbackClient | ResearchClient | None,
    ) -> dict[str, JsonValue]:
        if client is None:
            return {"status": "not_configured"}
        try:
            return await client.health()
        except (DownstreamUnavailable, DownstreamRefused):
            return {"status": "unavailable"}

    async def evidence_states(version_ids: list[UUID]) -> dict[str, dict[str, JsonValue]]:
        """Evidence tier and latest released state per version, from the evaluator."""
        if admin is None or not version_ids:
            return {}
        try:
            page = await admin.version_states(version_ids)
        except (DownstreamUnavailable, DownstreamRefused):
            return {}
        return {
            str(item.version_id): {
                "evidence_tier": item.evidence_tier,
                "released_state": item.released_state,
                "intake_state": item.intake_state,
                "reason_code": item.reason_code,
            }
            for item in page.items
        }

    def data_step(summary: dict[str, JsonValue] | None) -> dict[str, JsonValue]:
        if admin is None:
            return {"status": "not_configured", "next": DATA_NEXT}
        if summary is None:
            return {"status": "unavailable", "next": "eval-admin-api did not answer."}
        freshness, active = summary.get("data_freshness"), summary.get("active")
        if not isinstance(freshness, dict) or not isinstance(active, dict):
            return {"status": "not_started", "next": DATA_NEXT}
        return {
            "status": "ok",
            "detail": "The evaluator has a full snapshot and an active epoch.",
            "snapshot_ids": {
                "latest_full": freshness.get("latest_full_snapshot_id"),
                "epoch": active.get("epoch_snapshot_id"),
            },
        }

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
        services["research-api"] = await eval_health(research)
        services["eval-admin-api"] = await eval_health(admin)
        services["feedback-api"] = await eval_health(feedback)
        services["registry-api"] = await registry_health()
        states = await asyncio.to_thread(store.latest_setup_states)
        summary = await summary_or_none()
        evaluation = await eval_summary()
        researching = await research_summary()
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
                "active_jobs": None
                if researching is None
                else {
                    "active": researching.active_jobs,
                    "by_state": dict(researching.jobs_by_state),
                    "paused_programs": researching.paused_programs,
                    "research_paused": researching.research_paused,
                },
                "budgets": None
                if researching is None
                else {
                    "cost_today": researching.cost_today_cny,
                    "daily_cap": researching.daily_cap_cny,
                    "currency": researching.currency,
                },
                "evaluation": None
                if evaluation is None
                else {
                    k: evaluation.get(k) for k in ("ready", "active", "intake", "queue", "release")
                },
                "data_freshness": None if evaluation is None else evaluation.get("data_freshness"),
                "burn_meters": None if evaluation is None else evaluation.get("burn_meters"),
                "alerts": None,
                "notice": notice_for(summary, states.get("pool")),
            },
            "partial",
        )

    @server.tool(
        name="qfr.setup.status",
        description=(
            "Setup state per step (pool, providers, data, token), the latest provider probe "
            "per model and role, the evaluator's snapshot ids, pool counts and the "
            "no-defaults notice."
        ),
        annotations=READ,
    )
    async def setup_status() -> ToolResult:
        states = await asyncio.to_thread(store.latest_setup_states)
        summary = await summary_or_none()
        data = data_step(await eval_summary())
        researching = await research_summary()
        steps: dict[str, JsonValue] = {}
        for step in SETUP_STEPS:
            if step == "data" and step not in states:
                steps[step] = data
            elif step in states:
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
                steps[step] = providers_step(researching)
        done = all(isinstance(v, dict) and v.get("status") in DONE_STATUSES for v in steps.values())
        return result(
            {
                "phase": PHASE,
                "setup_complete": done,
                "steps": steps,
                "probe_results": None
                if researching is None or researching.last_probe is None
                else researching.last_probe.model_dump(mode="json"),
                "snapshot_ids": data.get("snapshot_ids"),
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
            "(default 200, max 2000) and cursor from the previous page. Each item carries "
            "the evaluator's evidence tier and latest released state (null while the "
            "evaluator has not pulled the version)."
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
        data = await pool_page(pool, status, size, cursor)
        return result(data, "ok" if admin is not None else "partial")

    async def pool_page(
        pool: Literal["factor", "strategy"],
        status: PoolStatus | None = None,
        size: int | None = None,
        cursor: UUID | None = None,
    ) -> dict[str, JsonValue]:
        page = await require_registry().pool_entries(
            pool, status, size or config.list_default, cursor
        )
        known = await evidence_states([item.version_id for item in page.items])
        items: list[JsonValue] = [
            item.model_dump(mode="json")
            | {
                "evidence_tier": known.get(str(item.version_id), {}).get("evidence_tier"),
                "released_state": known.get(str(item.version_id), {}).get("released_state"),
            }
            for item in page.items
        ]
        return {
            "pool": pool,
            "items": items,
            "next_cursor": page.next_cursor,
            "evidence": "ok" if admin is not None else "evaluator_not_configured",
        }

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
        known = (await evidence_states([detail.entry.version_id])).get(
            str(detail.entry.version_id), {}
        )
        return result(
            {
                "entry": detail.entry.model_dump(mode="json"),
                "events": [e.model_dump(mode="json") for e in detail.events],
                "version": version.model_dump(mode="json"),
                "evidence_tier": known.get("evidence_tier"),
                "released_state": known.get("released_state"),
                "evaluation": known or None,
                "evidence": "ok" if admin is not None else "evaluator_not_configured",
            },
            "ok" if admin is not None else "partial",
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
            data = await require_admin().private_config()
            return result({"visibility": "owner_only", "configuration": data})
        values: dict[str, JsonValue] = {"state": "preview_not_activated"}
        if feedback is not None:
            try:
                cards = {kind: await feedback.card(kind) for kind in ("protocol", "policy")}
                values = {
                    "state": "active",
                    "cards": {k: c.model_dump(mode="json") for k, c in cards.items()},
                }
            except (DownstreamUnavailable, DownstreamRefused):
                values = {"state": "preview_not_activated"}
        for kind in ("charter", "providers", "roles"):
            # Provider key environment names are non-secret; values are never resolved here.
            doc = load_config(kind, settings.config_dir)
            values[kind] = doc.values
        card_path = settings.config_dir / "public_cards.json"
        if "cards" not in values and card_path.exists():
            import json

            values["cards"] = json.loads(card_path.read_text())
        return result(values)

    @server.tool(
        name="qfr.evidence.get",
        description=(
            "Owner-grade evidence for one version at full precision, labelled owner_only: "
            "the evaluator's intake state, official records, gate values, series refs, "
            "reference strategy stats and library correlation. Never copy these numbers "
            "into briefs or steering notes. Argument: version_id."
        ),
        annotations=READ,
    )
    async def evidence_get(version_id: UUID) -> ToolResult:
        data = await require_admin().evidence(version_id)
        await asyncio.to_thread(validate_owner_evidence, data, evidence_schema)
        return result(data)

    @server.tool(
        name="qfr.report.list",
        description=(
            "Released reports exactly as research sees them (rounded, batched, reason codes "
            "only). Filters: version_id, family_id, program_id, type (intake, screening, w1, "
            "library), since (ISO time), after_id (cursor) and limit (default 200, max "
            "2000). Reports for a job arrive with the job tools in Phase 4."
        ),
        annotations=READ,
    )
    async def report_list(
        version_id: UUID | None = None,
        family_id: UUID | None = None,
        program_id: UUID | None = None,
        type: Literal["intake", "screening", "w1", "library"] | None = None,  # noqa: A002
        since: str | None = None,
        after_id: UUID | None = None,
        limit: int | None = None,
    ) -> ToolResult:
        size = limit or config.list_default
        if not 1 <= size <= config.list_max:
            raise ValueError(f"LIMIT_INVALID: limit must be between 1 and {config.list_max}")
        page = await require_feedback().reports(
            version_id=version_id, family_id=family_id, program_id=program_id, type=type,
            since=since, after_id=after_id, limit=size,
        )  # fmt: skip
        return result(page.model_dump(mode="json"))

    async def activate(kind: ConfigFile, file: str, approval_id: UUID | None) -> ToolResult:
        client = require_admin()
        try:
            data, source = await asyncio.to_thread(
                read_import, Path(imports) if imports else None, file, config.import_max_bytes
            )
        except ImportPathError as error:
            raise ValueError(f"{error.code}: {error.message}") from None
        try:
            text_value = data.decode("utf-8")
        except UnicodeDecodeError:
            raise ValueError("FILE_INVALID: the file is not UTF-8 YAML") from None
        created = await client.create_version(kind, text_value)
        active = await client.activate(kind, created.id, created.version, approval_id)
        logger.logger.info(
            "evaluator_config_activated",
            outcome="ok",
            payload={"kind": kind, "ref": f"{active.id}/{active.version}", "source": source},
        )
        return result(
            {
                "kind": kind,
                "created": bool(created.created),
                "version": active.model_dump(mode="json"),
                "source": source,
            }
        )

    @server.tool(
        name="qfr.ops.activate_protocol",
        description=(
            "Activate a new protocol version from a YAML file under imports/ (argument "
            "file; optional approval_id). The evaluator stores it immutably, retires the "
            "previous version and publishes the new protocol card. Re-sending the same "
            "file is idempotent; a changed file needs a new version string."
        ),
        annotations=WRITE,
    )
    async def activate_protocol(file: str, approval_id: UUID | None = None) -> ToolResult:
        return await activate("protocol", file, approval_id)

    @server.tool(
        name="qfr.ops.activate_policy",
        description=(
            "Activate a new release-policy version from a YAML file under imports/ "
            "(argument file; optional approval_id). Same rules as activate_protocol."
        ),
        annotations=WRITE,
    )
    async def activate_policy(file: str, approval_id: UUID | None = None) -> ToolResult:
        return await activate("policy", file, approval_id)

    @server.tool(
        name="qfr.ops.activate_quotas",
        description=(
            "Activate a new quota version from a YAML file under imports/ (argument file; "
            "optional approval_id). Same rules as activate_protocol."
        ),
        annotations=WRITE,
    )
    async def activate_quotas(file: str, approval_id: UUID | None = None) -> ToolResult:
        return await activate("quotas", file, approval_id)

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

    deps = JobToolDeps(
        research=research,
        admin=admin,
        feedback=feedback,
        registry=registry,
        config=config,
        config_dir=settings.config_dir,
        evidence_schema=evidence_schema,
        logger=logger,
        result=result,
    )
    register_job_tools(server, deps)
    register_resources(server, deps, pool_page)
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
