"""Phase 7 operations tools (PLAN Sections 13.7, 15.5 and 17.4).

qfr.ops.alerts merges the three alert sources: the evaluator's (decay, staleness, burn,
ops), research's provider alerts (repeated fallbacks, failed probes) and the front
door's own operations alerts from the nightly job (disk guard, missing backups).
qfr.ops.acknowledge_alert records the owner's acknowledgement in control_db and, for
evaluation and research alerts, in the service that raised it. qfr.ops.pause_research
and qfr.ops.resume_research stop or restart every research program for an incident.
qfr.logs.export writes a filtered log slice to exports/logs/.
"""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import JsonValue
from qfr_core.contracts import AlertAckRequest
from qfr_core.correlation import current
from qfr_core.ids import uuid7
from qfr_core.log_reader import LogQuery, LogReader

from qfr_mcp.api_client import DownstreamRefused, DownstreamUnavailable
from qfr_mcp.control_store import AlertAck, AlertSource, ControlStore
from qfr_mcp.job_tools import JobToolDeps
from qfr_mcp.results import ToolResult

READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
WRITE = ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False
)
# Acknowledging twice returns the first acknowledgement; pausing twice stays paused.
OWNER = "owner"
AlertKind = Literal[
    "decay", "staleness", "burn", "ops", "provider_fallback", "probe_failed", "disk", "backup"
]
KINDS: dict[AlertSource, frozenset[str]] = {
    "evaluation": frozenset({"decay", "staleness", "burn", "ops"}),
    "research": frozenset({"provider_fallback", "probe_failed"}),
    "operations": frozenset({"disk", "backup"}),
}


def exported(root: Path, path: Path) -> str:
    """The path as the owner sees it on the Mac: under the repository's exports/."""
    return "exports/" + path.relative_to(root).as_posix()


def register(server: FastMCP, deps: JobToolDeps, control: ControlStore, reader: LogReader) -> None:
    result = deps.result
    logger = deps.logger.logger

    async def downstream[T](fn: Callable[[], Awaitable[T]]) -> T:
        try:
            return await fn()
        except DownstreamRefused as error:
            raise ValueError(f"{error.error}: {error.message}") from None
        except DownstreamUnavailable as error:
            raise RuntimeError(f"DOWNSTREAM_UNAVAILABLE: {error}") from None

    def operations_items(state: str | None, kind: str | None, limit: int) -> dict[str, Any]:
        alerts = control.ops_alerts(limit if state is None else deps.config.list_max)
        acks = control.acks("operations", [a.alert_id for a in alerts])
        items: list[dict[str, Any]] = []
        for alert in alerts:
            ack = acks.get(alert.alert_id)
            item = {
                "source": "operations",
                "alert_id": str(alert.alert_id),
                "kind": alert.kind,
                "at": alert.at.isoformat(),
                "details": alert.details,
                "state": "acknowledged" if ack else "open",
                "acknowledged_by": ack.principal if ack else None,
                "acknowledged_at": ack.at.isoformat() if ack else None,
                "note": ack.note if ack else None,
            }
            if (state is None or item["state"] == state) and (kind is None or alert.kind == kind):
                items.append(item)
        return {"items": items[:limit], "open": sum(1 for a in alerts if a.alert_id not in acks)}

    async def gather(
        source: AlertSource, state: str | None, kind: str | None, limit: int
    ) -> tuple[str, dict[str, Any]]:
        """One source's alerts and open count, or why it could not be read."""
        if kind is not None and kind not in KINDS[source]:
            return "skipped", {"items": [], "open": None}
        try:
            if source == "operations":
                page = await asyncio.to_thread(operations_items, state, kind, limit)
                return "ok", page
            if source == "evaluation":
                if deps.admin is None:
                    return "not_configured", {"items": [], "open": None}
                data = (await deps.admin.alerts(state, kind, limit)).model_dump(mode="json")
            else:
                if deps.research is None:
                    return "not_configured", {"items": [], "open": None}
                data = (await deps.research.alerts(state, kind, limit)).model_dump(mode="json")
        except (DownstreamUnavailable, DownstreamRefused):
            return "unavailable", {"items": [], "open": None}
        data["items"] = [{"source": source} | item for item in data["items"]]
        return "ok", data

    @server.tool(
        name="qfr.ops.alerts",
        description=(
            "Alerts from every zone, newest first, each with its source: evaluation (decay "
            "of monitored pool entries, data staleness, burn meters, evaluator failures), "
            "research (repeated provider fallbacks, failed provider probes) and operations "
            "(the nightly disk guard and backup check). Optional filters: state (open or "
            "acknowledged), source, kind and limit (default 200, max 2000). Returns the open "
            "count per source; a source that cannot be read is named, never guessed."
        ),
        annotations=READ,
    )
    async def ops_alerts(
        state: Literal["open", "acknowledged"] | None = None,
        source: AlertSource | None = None,
        kind: AlertKind | None = None,
        limit: int | None = None,
    ) -> ToolResult:
        size = deps.size(limit)
        sources: list[AlertSource] = (
            [source] if source else ["evaluation", "research", "operations"]
        )
        found = await asyncio.gather(*(gather(s, state, kind, size) for s in sources))
        items: list[dict[str, Any]] = []
        status: dict[str, JsonValue] = {}
        open_counts: dict[str, JsonValue] = {}
        for name, (outcome, page) in zip(sources, found, strict=True):
            status[name] = outcome
            open_counts[name] = page["open"]
            items += page["items"]
        items.sort(key=lambda i: (str(i["at"]), str(i["alert_id"])), reverse=True)
        complete = all(v in ("ok", "skipped") for v in status.values())
        return result(
            {
                "items": items[:size],
                "open": open_counts,
                "sources": status,
                "acknowledge_with": "qfr.ops.acknowledge_alert",
            },
            "ok" if complete else "partial",
        )

    @server.tool(
        name="qfr.ops.acknowledge_alert",
        description=(
            "Acknowledge one alert the owner has seen. Arguments: source (evaluation, "
            "research or operations, as qfr.ops.alerts lists it), alert_id and an optional "
            "note in the owner's words. The service that raised the alert marks it "
            "acknowledged and control_db records who acknowledged it and when. "
            "Acknowledging again returns the first acknowledgement. An acknowledgement "
            "changes no evaluation, research or pool state."
        ),
        annotations=WRITE,
    )
    async def acknowledge_alert(
        source: AlertSource, alert_id: UUID, note: str | None = None
    ) -> ToolResult:
        request = AlertAckRequest(by=OWNER, note=note)
        alert: dict[str, Any]
        if source == "evaluation":
            if deps.admin is None:
                raise RuntimeError("EVAL_ADMIN_UNCONFIGURED: EVAL_ADMIN_API_URL is not set")
            admin = deps.admin
            view = await downstream(lambda: admin.acknowledge_alert(alert_id, request))
            alert = view.model_dump(mode="json")
        elif source == "research":
            research = deps.require_research()
            raised = await downstream(lambda: research.acknowledge_alert(alert_id, request))
            alert = raised.model_dump(mode="json")
        else:
            known = await asyncio.to_thread(control.ops_alerts, deps.config.list_max)
            match = next((a for a in known if a.alert_id == alert_id), None)
            if match is None:
                raise ValueError("ALERT_NOT_FOUND: no operations alert with this id")
            alert = match.model_dump(mode="json")
        ack = await asyncio.to_thread(
            control.acknowledge,
            AlertAck(
                ack_id=uuid7(), source=source, alert_id=alert_id, at=datetime.now(UTC),
                note=note, principal=OWNER, request_id=current()["request_id"],
            ),
        )  # fmt: skip
        logger.info(
            "alert_acknowledged",
            outcome="ok",
            payload={"source": source, "alert_id": str(alert_id), "ack_id": str(ack.ack_id)},
        )
        return result(
            {
                "source": source,
                "alert": alert,
                "acknowledgement": ack.model_dump(mode="json"),
            }
        )

    async def control_research(paused: bool, reason: str | None) -> ToolResult:
        research = deps.require_research()
        answer = await downstream(lambda: research.control_all(paused))
        logger.warning(
            "research_paused_by_owner" if paused else "research_resumed_by_owner",
            outcome="ok",
            payload={"reason": reason},
        )
        summary = await downstream(research.summary)
        return result(
            {
                "research_paused": answer.get("research_paused"),
                "paused_programs": summary.paused_programs,
                "active_jobs": summary.active_jobs,
                "reason": reason,
            }
        )

    @server.tool(
        name="qfr.ops.pause_research",
        description=(
            "Pause every research program at once, for an incident (for example a "
            "failed boundary check in `just doctor`). Running generations stop at their next "
            "step and no new LLM call starts; evaluation keeps running. Optional reason in "
            "the owner's words. Undo with qfr.ops.resume_research."
        ),
        annotations=WRITE,
    )
    async def pause_research(reason: str | None = None) -> ToolResult:
        return await control_research(True, reason)

    @server.tool(
        name="qfr.ops.resume_research",
        description=(
            "Resume research after qfr.ops.pause_research. Jobs the owner paused one by one "
            "with qfr.job.pause stay paused. Optional reason."
        ),
        annotations=WRITE,
    )
    async def resume_research(reason: str | None = None) -> ToolResult:
        return await control_research(False, reason)

    @server.tool(
        name="qfr.logs.export",
        description=(
            "Write a filtered log slice as compressed JSON lines (.jsonl.gz) to "
            "exports/logs/ with the same filters as qfr.logs.search (from, to, services, "
            "levels, events, ids, text). Without dates the last 24 hours are exported. At "
            "most logging.yaml's export_max_lines lines are written; when the cap stops the "
            "export, truncated is true and next_cursor continues it in a second export. "
            "Returns the path under exports/, the line count, the size and the SHA-256."
        ),
        annotations=WRITE,
    )
    async def logs_export(query: LogQuery) -> ToolResult:
        if deps.exports_dir is None:
            raise RuntimeError("EXPORTS_UNCONFIGURED: QFR_EXPORTS_DIR is not set")
        root = deps.exports_dir
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        target = root / "logs" / f"{stamp}-{current()['request_id'][:8]}.jsonl.gz"
        written = await asyncio.to_thread(reader.export, query, target)
        logger.info(
            "logs_exported",
            outcome="ok",
            payload={"path": exported(root, target), "lines": written["lines"]},
        )
        return result({"path": exported(root, target)} | written)
