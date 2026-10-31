"""Phase 4 MCP tools: jobs, deliverables, traces, lineage and costs (PLAN Section 13.7).

Every tool here calls research-api with the control token, and the deliverable tools
add owner-grade evidence from eval-admin-api. None of them runs a research tool,
publishes, or reaches a model (INV-14). Briefs and steering notes pass the owner-only
scan before they leave the front door (Section 9.6).
"""

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import JsonValue, ValidationError
from qfr_core.config import MCPConfig
from qfr_core.contracts import ResearchBrief
from qfr_core.logging import JsonLogger
from qfr_core.research_api import (
    DeliverableView,
    JobState,
    SteerRequest,
    SubmitJobRequest,
)

from qfr_mcp.api_client import DownstreamRefused, DownstreamUnavailable
from qfr_mcp.eval_client import EvalAdminClient, FeedbackClient
from qfr_mcp.evidence_validation import validate_owner_evidence
from qfr_mcp.registry_client import RegistryClient
from qfr_mcp.research_client import ResearchClient
from qfr_mcp.scan import OwnerValueInText, text_of_brief, verdict

READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
WRITE = ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False
)
CONTROL = ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False
)
Result = Callable[..., Any]


@dataclass
class JobToolDeps:
    research: ResearchClient | None
    admin: EvalAdminClient | None
    feedback: FeedbackClient | None
    registry: RegistryClient | None
    config: MCPConfig
    config_dir: Path
    evidence_schema: Path
    logger: JsonLogger
    result: Result

    def require_research(self) -> ResearchClient:
        if self.research is None:
            raise RuntimeError("RESEARCH_UNCONFIGURED: RESEARCH_API_URL is not set")
        return self.research

    def size(self, limit: int | None) -> int:
        value = limit or self.config.list_default
        if not 1 <= value <= self.config.list_max:
            raise ValueError(f"LIMIT_INVALID: limit must be between 1 and {self.config.list_max}")
        return value

    async def rounding(self) -> dict[str, Any]:
        """The active release policy's rounding; the bundled card without feedback-api."""
        if self.feedback is not None:
            try:
                return dict((await self.feedback.card("policy")).card["rounding"])  # type: ignore[arg-type]
            except (DownstreamUnavailable, DownstreamRefused):
                pass
        cards = json.loads((self.config_dir / "public_cards.json").read_text())
        return dict(cards["policy"]["rounding"])

    async def scan(self, text: str, referenced: list[UUID]) -> Any:
        """Compare the text with every referenced version's owner-only values."""
        evidence: dict[str, dict[str, Any]] = {}
        if referenced:
            if self.admin is None:
                raise RuntimeError(
                    "SCAN_UNAVAILABLE: eval-admin-api is not configured, so owner-only values "
                    "of the referenced versions cannot be checked"
                )
            for version_id in referenced:
                try:
                    evidence[str(version_id)] = await self.admin.evidence(version_id)
                except DownstreamRefused as error:
                    if error.status != 404:
                        raise
                    evidence[str(version_id)] = {}  # not pulled by the evaluator yet
        try:
            return verdict(text, evidence, await self.rounding(), referenced)
        except OwnerValueInText as error:
            self.logger.logger.warning(
                "owner_only_scan_rejected",
                outcome="failed",
                error_code="OWNER_ONLY_VALUE",
                payload={"matches": error.matches, "version_ids": error.version_ids},
            )
            raise ValueError(str(error)) from None

    async def compose(self, view: DeliverableView) -> dict[str, JsonValue]:
        """Add owner-grade evidence and the evaluator's confirmation of each tier."""
        deliverable = view.deliverable
        ids = [item.version_id for item in deliverable.items]
        states: dict[str, Any] = {}
        evidence: dict[str, dict[str, JsonValue]] = {}
        status = "ok"
        if self.admin is None:
            status = "evaluator_not_configured"
        else:
            try:
                page = await self.admin.version_states(ids)
                states = {str(s.version_id): s for s in page.items}
                for version_id in ids:
                    document = await self.admin.evidence(version_id)
                    await asyncio.to_thread(
                        validate_owner_evidence, document, self.evidence_schema
                    )
                    evidence[str(version_id)] = document
            except (DownstreamUnavailable, DownstreamRefused):
                status = "evaluator_unavailable"
        items = []
        confirmation: dict[str, JsonValue] = {}
        for item in deliverable.items:
            key = str(item.version_id)
            items.append(item.model_copy(update={"owner_evidence": evidence.get(key)}))
            official = states.get(key)
            confirmed: bool | None = None
            if official is not None and item.tier_reached == "w1_pass":
                confirmed = official.evidence_tier == "w1_pass"
            confirmation[key] = {
                "research_tier": item.tier_reached,
                "official_evidence_tier": None if official is None else official.evidence_tier,
                "confirmed": confirmed,
            }
        composed = deliverable.model_copy(update={"items": items})
        return {
            "visibility": "owner_only",
            "deliverable": composed.model_dump(mode="json"),
            "fetched_at": None if view.fetched_at is None else view.fetched_at.isoformat(),
            "tier_confirmation": confirmation,
            "evidence": status,
            "hygiene": "Never copy owner-grade numbers into briefs or steering notes.",
        }


def register(server: FastMCP, deps: JobToolDeps) -> None:
    result = deps.result

    async def call(fn: Callable[[], Awaitable[Any]]) -> Any:
        try:
            return await fn()
        except DownstreamRefused as error:
            raise ValueError(f"{error.error}: {error.message}") from None

    @server.tool(
        name="qfr.job.submit",
        description=(
            "Submit a research brief (brief/1; read the qfr.brief prompt first). The front "
            "door scans the text for owner-only numbers of the referenced versions, then "
            "research-api validates it, publishes the seed expressions as human_seed "
            "versions, derives the charter deterministically and starts the program. "
            "Returns the job (short code J-nnnn), the charter, the seed version ids and a "
            "timeline estimate. Resubmitting the same brief returns the same job."
        ),
        annotations=WRITE,
    )
    async def job_submit(brief: dict[str, Any]) -> Any:
        client = deps.require_research()
        try:
            parsed = ResearchBrief.model_validate(brief)
        except ValidationError as error:
            raise ValueError(f"BRIEF_INVALID: {error.errors(include_url=False)}") from None
        referenced = list(parsed.seeds.version_ids)
        if parsed.seeds.pool_entry_ids and deps.registry is not None:
            for entry_id in parsed.seeds.pool_entry_ids:
                for pool in ("factor", "strategy"):
                    try:
                        detail = await deps.registry.pool_entry(pool, entry_id)  # type: ignore[arg-type]
                        referenced.append(detail.entry.version_id)
                        break
                    except DownstreamRefused:
                        continue
        referenced = list(dict.fromkeys(referenced))
        scan = await deps.scan(text_of_brief(parsed.model_dump(mode="json")), referenced)
        response = await call(lambda: client.submit(SubmitJobRequest(brief=parsed, scan=scan)))
        return result(response.model_dump(mode="json"))

    @server.tool(
        name="qfr.job.list",
        description=(
            "List research jobs, newest first. Optional state filter, limit (default 200, "
            "max 2000) and cursor from the previous page."
        ),
        annotations=READ,
    )
    async def job_list(
        state: JobState | None = None, limit: int | None = None, cursor: UUID | None = None
    ) -> Any:
        page = await call(lambda: deps.require_research().jobs(state, deps.size(limit), cursor))
        return result(page.model_dump(mode="json"))

    @server.tool(
        name="qfr.job.get",
        description=(
            "One job: state, charter version, costs, publications, deliverables, the next "
            "generation time, and its generations with their summaries."
        ),
        annotations=READ,
    )
    async def job_get(job_id: UUID) -> Any:
        client = deps.require_research()
        job = await call(lambda: client.job(job_id))
        generations = (
            await call(lambda: client.generations(job.program_id))
            if job.program_id is not None
            else None
        )
        return result(
            {
                "job": job.model_dump(mode="json"),
                "generations": []
                if generations is None
                else [g.model_dump(mode="json") for g in generations.items],
            }
        )

    @server.tool(
        name="qfr.job.events",
        description="A job's events in order, after after_seq (default 0); limit up to 2000.",
        annotations=READ,
    )
    async def job_events(job_id: UUID, after_seq: int = 0, limit: int | None = None) -> Any:
        page = await call(
            lambda: deps.require_research().events(job_id, after_seq, deps.size(limit))
        )
        return result(page.model_dump(mode="json"))

    @server.tool(
        name="qfr.job.wait",
        description=(
            "Long-poll until the job's state differs from `state` (default: its state now) "
            "or timeout_s (at most 600) passes. Returns whether it changed and the job."
        ),
        annotations=READ,
    )
    async def job_wait(job_id: UUID, timeout_s: float = 60.0, state: JobState | None = None) -> Any:
        if not 0 <= timeout_s <= deps.config.long_poll_seconds:
            raise ValueError(
                f"TIMEOUT_INVALID: timeout_s must be between 0 and {deps.config.long_poll_seconds}"
            )
        waited = await call(lambda: deps.require_research().wait(job_id, timeout_s, state))
        return result(waited.model_dump(mode="json"))

    @server.tool(
        name="qfr.job.steer",
        description=(
            "Append the owner's guidance to the job's charter for the next generation. The "
            "note is scanned like a brief: owner-only numbers of the job's versions are "
            "rejected. Never paste evidence; refer to versions by id."
        ),
        annotations=WRITE,
    )
    async def job_steer(job_id: UUID, note: str) -> Any:
        client = deps.require_research()
        referenced = await call(lambda: client.versions(job_id))
        scan = await deps.scan(note, referenced)
        try:
            request = SteerRequest(note=note, scan=scan)
        except ValidationError as error:
            raise ValueError(f"NOTE_INVALID: {error.errors(include_url=False)}") from None
        job = await call(lambda: client.steer(job_id, request))
        return result(job.model_dump(mode="json"))

    def control(action: Literal["pause", "resume", "cancel"], text: str) -> None:
        async def tool(job_id: UUID) -> Any:
            job = await call(lambda: deps.require_research().control(job_id, action))
            return result(job.model_dump(mode="json"))

        server.tool(name=f"qfr.job.{action}", description=text, annotations=CONTROL)(tool)

    control(
        "pause",
        "Stop starting generations and spending on this job. Evaluation of versions already "
        "published continues: neither research nor the host agent can stop the evaluator.",
    )
    control("resume", "Restart a paused job; the next generation starts on the next tick.")
    control(
        "cancel",
        "Close the job as cancelled. A running generation stops at its next step; published "
        "versions stay published and are still evaluated.",
    )

    @server.tool(
        name="qfr.deliverable.list",
        description=(
            "The deliverables of a job: status, short codes, items with the tier research "
            "read and the evaluator's confirmation of it. Use qfr.deliverable.get for the "
            "full deliverable with owner-grade evidence."
        ),
        annotations=READ,
    )
    async def deliverable_list(job_id: UUID) -> Any:
        page = await call(lambda: deps.require_research().deliverables(job_id))
        items: list[JsonValue] = []
        for view in page.items:
            composed = await deps.compose(view)
            document = view.deliverable
            items.append(
                {
                    "deliverable_id": str(document.deliverable_id),
                    "status": document.status,
                    "created_at": document.created_at.isoformat(),
                    "fetched_at": composed["fetched_at"],
                    "short_codes": list(document.short_codes),
                    "summary": document.summary,
                    "items": [
                        {"version_id": str(i.version_id), "kind": i.kind,
                         "tier_reached": i.tier_reached}
                        for i in document.items
                    ],
                    "tier_confirmation": composed["tier_confirmation"],
                }
            )  # fmt: skip
        return result({"job_id": str(job_id), "items": items})

    @server.tool(
        name="qfr.deliverable.get",
        description=(
            "One deliverable (deliverable/1) with every item's iteration history, released "
            "reports, caveats and owner-grade evidence (owner_only), plus the evaluator's "
            "confirmation of each tier. The first fetch marks the job DELIVERED. Report the "
            "tier first, then the evidence, the caveats verbatim and the short codes "
            "(see the qfr.report_deliverable prompt)."
        ),
        annotations=READ,
    )
    async def deliverable_get(deliverable_id: UUID) -> Any:
        view = await call(lambda: deps.require_research().deliverable(deliverable_id, True))
        return result(await deps.compose(view))

    @server.tool(
        name="qfr.trace.get",
        description=(
            "The development trace (trace/1) of a published version or a candidate: every "
            "step from the brief to publication with actors, inputs, full prompts and "
            "responses of the agent runs, deterministic check results, lineage and the "
            "released reports research saw; with its trace_hash. Give version_id or "
            "candidate_id."
        ),
        annotations=READ,
    )
    async def trace_get(version_id: UUID | None = None, candidate_id: UUID | None = None) -> Any:
        if (version_id is None) == (candidate_id is None):
            raise ValueError("ARGUMENT_INVALID: give exactly one of version_id or candidate_id")
        view = await call(lambda: deps.require_research().trace(version_id, candidate_id))
        return result(view.model_dump(mode="json"))

    @server.tool(
        name="qfr.lineage.get",
        description=(
            "Parents and children of a version to a depth (registry), with research's hops "
            "(operator, AST diff, generation) and the released reports of the version."
        ),
        annotations=READ,
    )
    async def lineage_get(version_id: UUID, depth: int = 5) -> Any:
        data: dict[str, JsonValue] = {"version_id": str(version_id)}
        if deps.registry is not None:
            graph = await call(lambda: deps.registry.lineage(version_id, depth))  # type: ignore[union-attr]
            data["registry"] = graph.model_dump(mode="json")
        if deps.research is not None:
            try:
                data["research"] = (await deps.research.lineage(version_id)).model_dump(mode="json")
            except DownstreamRefused as error:
                data["research"] = {"status": error.error}
        return result(data)

    @server.tool(
        name="qfr.ops.costs",
        description=(
            "Research LLM cost in CNY over a period, grouped by any of job, generation, "
            "provider, model, role and day (default provider, model, role). Optional from "
            "and to (ISO times) and job_id."
        ),
        annotations=READ,
    )
    async def ops_costs(
        start: datetime | None = None,
        end: datetime | None = None,
        group_by: list[Literal["job", "generation", "provider", "model", "role", "day"]]
        | None = None,
        job_id: UUID | None = None,
    ) -> Any:
        groups = list(group_by) if group_by else None
        report = await call(lambda: deps.require_research().costs(start, end, groups, job_id))
        return result(report.model_dump(mode="json"))
