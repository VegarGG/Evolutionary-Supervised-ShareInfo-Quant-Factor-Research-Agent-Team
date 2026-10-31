"""Phase 6 MCP tools: approvals, pool curation, job close and acceptance (PLAN Sections
10.4, 10.5, 13.5 and 13.7). The alert tools moved to ops_tools in Phase 7.

qfr.approval.record turns the owner's verbatim confirmation into an insert-only approval
record in control_db. The approval-gated tools (qfr.pool.add, qfr.pool.set_status,
qfr.job.close and qfr.acceptance.decide) look the record up, check that its decision and
scope cover the call, and pass the approval to the service that owns the change; that
service checks the scope again (POOL-01, ACC-03). One approval-gated write runs at a time.
qfr.pool.annotate changes no status and needs no approval.
"""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import JsonValue, ValidationError
from qfr_core.contracts import ApprovalRecord, PoolEntry, Tier, TraceStep
from qfr_core.correlation import bind, current
from qfr_core.eval_api import CaseApprovalRef, CaseDecisionRequest
from qfr_core.ids import uuid7
from qfr_core.registry_api import AddEntryRequest, AppendEventRequest, ApprovalRef
from qfr_core.research_api import CloseRequest

from qfr_mcp.api_client import DownstreamRefused, DownstreamUnavailable
from qfr_mcp.approvals import ApprovalRefused, Decision, Resolver, entry_code, match
from qfr_mcp.control_store import ControlStore
from qfr_mcp.job_tools import JobToolDeps
from qfr_mcp.results import ToolResult

READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
WRITE = ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False
)
# Approval-gated tools change what the owner keeps; a retirement is undone only by a new
# approval, so they are marked destructive for host agents that ask before such calls.
GATED = ToolAnnotations(
    readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False
)
Pool = Literal["factor", "strategy"]


def _now() -> datetime:
    return datetime.now(UTC)


def register(server: FastMCP, deps: JobToolDeps, control: ControlStore) -> None:
    result = deps.result
    lock = asyncio.Lock()  # mcp.yaml approval_concurrency: 1
    resolver = Resolver(deps.research, deps.admin, deps.registry)
    pattern = deps.config.confirmation_pattern
    logger = deps.logger.logger

    async def downstream[T](fn: Callable[[], Awaitable[T]]) -> T:
        try:
            return await fn()
        except DownstreamRefused as error:
            raise ValueError(f"{error.error}: {error.message}") from None
        except DownstreamUnavailable as error:
            raise RuntimeError(f"DOWNSTREAM_UNAVAILABLE: {error}") from None

    def refused(code: str, message: str, **payload: JsonValue) -> ValueError:
        logger.warning(
            "approval_refused", outcome="failed", error_code=code, payload={"message": message}
            | payload,
        )  # fmt: skip
        return ValueError(f"{code}: {message}")

    async def approval_for(approval_id: UUID, decisions: tuple[str, ...]) -> ApprovalRecord:
        record = await asyncio.to_thread(control.get_approval, approval_id)
        if record is None:
            raise refused("APPROVAL_NOT_FOUND", f"no approval {approval_id}")
        if record.decision not in decisions:
            raise refused(
                "APPROVAL_DECISION_MISMATCH",
                f"approval {approval_id} records {record.decision}, not {' or '.join(decisions)}",
            )
        return record

    async def trace(
        step_type: Literal["APPROVAL_RECORDED", "POOL_EVENT"],
        version_id: UUID | None,
        job_id: UUID | None,
        inputs: dict[str, JsonValue],
        payload: dict[str, JsonValue],
    ) -> None:
        context = current()
        step = TraceStep(
            schema_version="trace_step/1",
            step_id=uuid7(),
            at=_now(),
            job_id=job_id,
            program_id=None,
            generation_id=None,
            task_id=None,
            candidate_id=None,
            version_id=version_id,
            step_type=step_type,
            actor_kind="owner" if step_type == "APPROVAL_RECORDED" else "host_agent",
            actor=context.get("principal", "owner"),
            inputs=inputs,
            payload=payload,
            outcome="ok",
            request_id=context["request_id"],
        )
        await asyncio.to_thread(control.append_trace_step, step)

    # ---------------------------------------------------------------- approvals

    @server.tool(
        name="qfr.approval.record",
        description=(
            "Record the owner's decision from their own words (read the qfr.approval prompt "
            "when available). Arguments: decision (approve, reject, retire, accept_case, "
            "reject_case), owner_confirmation (the owner's words exactly as received, at "
            "most 2,000 characters), rationale (your one-paragraph summary of why, as "
            "discussed with the owner) and the scope: job_id and deliverable_id for a "
            "deliverable, version_ids (default: every item of the deliverable), pool, tier "
            "(default: the tier the evaluator confirms), case_id for a case decision, and "
            "entry_ids with pool for pool entries. The confirmation must contain the short "
            "code of every item in scope (for example APPROVE J-0042 F-1 F-2, ACCEPT C-0003, "
            "RETIRE E-3fa9c1). Never record an approval the owner did not state. Returns the "
            "approval id that the approval-gated tools require."
        ),
        annotations=WRITE,
    )
    async def approval_record(
        decision: Decision,
        owner_confirmation: str,
        rationale: str,
        job_id: UUID | None = None,
        deliverable_id: UUID | None = None,
        version_ids: list[UUID] | None = None,
        pool: Pool | None = None,
        tier: Tier | None = None,
        case_id: UUID | None = None,
        entry_ids: list[UUID] | None = None,
    ) -> ToolResult:
        async with lock:
            try:
                resolved = await resolver.resolve(
                    decision,
                    job_id=job_id,
                    deliverable_id=deliverable_id,
                    version_ids=list(version_ids or []),
                    pool=pool,
                    tier=tier,
                    case_id=case_id,
                    entry_ids=list(entry_ids or []),
                )
            except ApprovalRefused as error:
                raise refused(error.code, error.message) from None
            matched, missing = match(resolved.codes, owner_confirmation, pattern)
            if missing:
                raise refused(
                    "SHORT_CODE_MISSING",
                    "the owner's confirmation does not contain the short code of every item "
                    f"in scope; missing: {', '.join(missing)}. Ask the owner to confirm with "
                    "the codes.",
                    missing=list(missing),
                )
            context = current()
            try:
                record = ApprovalRecord(
                    schema_version="approval/1",
                    approval_id=uuid7(),
                    created_at=_now(),
                    decision=decision,
                    scope=resolved.scope,
                    owner_confirmation=owner_confirmation,
                    rationale=rationale,
                    short_codes_matched=matched,
                    principal=context.get("principal", "owner"),
                    request_id=context["request_id"],
                )
            except ValidationError as error:
                raise refused("APPROVAL_INVALID", str(error.errors(include_url=False))) from None
            await asyncio.to_thread(control.append_approval, record)
            scope = record.scope
            inputs: dict[str, JsonValue] = {
                "decision": decision,
                "short_codes_matched": list(matched),
            }
            payload: dict[str, JsonValue] = {
                "approval_id": str(record.approval_id),
                "scope": scope.model_dump(mode="json"),
            }
            targets: list[UUID | None] = list(scope.version_ids) or [None]
            for version_id in targets:
                await trace("APPROVAL_RECORDED", version_id, scope.job_id, inputs, payload)
            with bind(job_id=None if scope.job_id is None else str(scope.job_id)):
                logger.info(
                    "approval_recorded",
                    outcome="ok",
                    payload={
                        "approval_id": str(record.approval_id),
                        "decision": decision,
                        "scope": scope.model_dump(mode="json"),
                        "short_codes_matched": list(matched),
                    },
                )
            return result(
                {"approval": record.model_dump(mode="json"), "approval_id": str(record.approval_id)}
            )

    # ---------------------------------------------------------------- pools

    def entry_view(entry: PoolEntry) -> dict[str, JsonValue]:
        view: dict[str, JsonValue] = entry.model_dump(mode="json")
        return view | {"short_code": entry_code(entry.entry_id)}

    @server.tool(
        name="qfr.pool.add",
        description=(
            "Add an approved version to its pool (factor or strategy, from the version's "
            "kind) with the tier the approval fixed. Arguments: approval_id (an approve "
            "approval whose scope names the version), version_id, and optional title "
            "(default: the manifest's), tags and note. A version that already has an entry "
            "changes status with qfr.pool.set_status instead."
        ),
        annotations=GATED,
    )
    async def pool_add(
        approval_id: UUID,
        version_id: UUID,
        title: str | None = None,
        tags: list[str] | None = None,
        note: str | None = None,
    ) -> ToolResult:
        registry = deps.registry
        if registry is None:
            raise RuntimeError("REGISTRY_UNCONFIGURED: REGISTRY_API_URL is not set")
        async with lock:
            record = await approval_for(approval_id, ("approve",))
            scope = record.scope
            if version_id not in scope.version_ids or scope.tier is None:
                raise refused(
                    "APPROVAL_SCOPE_MISMATCH",
                    "the approval does not name this version with a tier",
                    approval_id=str(approval_id),
                )
            version = await downstream(lambda: registry.get_version(version_id))
            pool: Pool = version.kind
            try:
                request = AddEntryRequest(
                    version_id=version_id,
                    title=title or version.manifest.title,
                    status="approved",
                    approved_tier=scope.tier,
                    approval=ApprovalRef(approval_id=approval_id, decision="approve", scope=scope),
                    tags=list(tags or []),
                    note=note,
                )
            except ValidationError as error:
                raise ValueError(f"ARGUMENT_INVALID: {error.errors(include_url=False)}") from None
            added = await downstream(lambda: registry.add_entry(pool, request))
            entry = added.entry
            await trace(
                "POOL_EVENT", version_id, scope.job_id,
                {"tool": "qfr.pool.add", "approval_id": str(approval_id)},
                {"pool": pool, "entry_id": str(entry.entry_id), "action": "ADDED",
                 "to_status": "approved", "approved_tier": scope.tier},
            )  # fmt: skip
            return result(
                {
                    "pool": pool,
                    "entry": entry_view(entry),
                    "event": None if added.event is None else added.event.model_dump(mode="json"),
                }
            )

    @server.tool(
        name="qfr.pool.set_status",
        description=(
            "Change a pool entry's status by appending an event: retired (with a retire "
            "approval naming the entry) or approved again (with an approve approval naming "
            "the entry or its version; the approval's tier is recorded). Arguments: pool, "
            "entry_id, status, approval_id and an optional note. Retiring removes the entry "
            "from the evaluator's library and research parents; versions stay published."
        ),
        annotations=GATED,
    )
    async def pool_set_status(
        pool: Pool,
        entry_id: UUID,
        status: Literal["approved", "retired"],
        approval_id: UUID,
        note: str | None = None,
    ) -> ToolResult:
        registry = deps.registry
        if registry is None:
            raise RuntimeError("REGISTRY_UNCONFIGURED: REGISTRY_API_URL is not set")
        async with lock:
            decision: Literal["approve", "retire"] = "approve" if status == "approved" else "retire"
            record = await approval_for(approval_id, (decision,))
            scope = record.scope
            detail = await downstream(lambda: registry.pool_entry(pool, entry_id))
            covered = entry_id in scope.entry_ids or detail.entry.version_id in scope.version_ids
            if not covered or (status == "approved" and scope.tier is None):
                raise refused(
                    "APPROVAL_SCOPE_MISMATCH",
                    "the approval does not name this entry (or, to approve, a tier)",
                    approval_id=str(approval_id),
                )
            try:
                request = AppendEventRequest(
                    action="STATUS_CHANGED",
                    to_status=status,
                    approved_tier=scope.tier if status == "approved" else None,
                    approval=ApprovalRef(approval_id=approval_id, decision=decision, scope=scope),
                    note=note,
                )
            except ValidationError as error:
                raise ValueError(f"ARGUMENT_INVALID: {error.errors(include_url=False)}") from None
            event = await downstream(lambda: registry.append_event(pool, entry_id, request))
            await trace(
                "POOL_EVENT", detail.entry.version_id, scope.job_id,
                {"tool": "qfr.pool.set_status", "approval_id": str(approval_id)},
                {"pool": pool, "entry_id": str(entry_id), "action": "STATUS_CHANGED",
                 "from_status": event.from_status, "to_status": event.to_status,
                 "approved_tier": event.approved_tier},
            )  # fmt: skip
            current_entry = (await downstream(lambda: registry.pool_entry(pool, entry_id))).entry
            return result(
                {"pool": pool, "entry": entry_view(current_entry),
                 "event": event.model_dump(mode="json")}
            )  # fmt: skip

    @server.tool(
        name="qfr.pool.annotate",
        description=(
            "Append tags and a note to a pool entry. It changes no status and needs no "
            "approval. Arguments: pool, entry_id, tags and/or note."
        ),
        annotations=WRITE,
    )
    async def pool_annotate(
        pool: Pool, entry_id: UUID, tags: list[str] | None = None, note: str | None = None
    ) -> ToolResult:
        registry = deps.registry
        if registry is None:
            raise RuntimeError("REGISTRY_UNCONFIGURED: REGISTRY_API_URL is not set")
        try:
            request = AppendEventRequest(action="ANNOTATED", tags=list(tags or []), note=note)
        except ValidationError as error:
            raise ValueError(f"ARGUMENT_INVALID: {error.errors(include_url=False)}") from None
        event = await downstream(lambda: registry.append_event(pool, entry_id, request))
        await trace(
            "POOL_EVENT", event.version_id, None, {"tool": "qfr.pool.annotate"},
            {"pool": pool, "entry_id": str(entry_id), "action": "ANNOTATED",
             "tags": list(event.tags), "note": event.note},
        )  # fmt: skip
        return result({"pool": pool, "event": event.model_dump(mode="json")})

    # ---------------------------------------------------------------- jobs

    @server.tool(
        name="qfr.job.close",
        description=(
            "Close a delivered job as approved or rejected with the owner's words. "
            "Arguments: job_id, decision (approved or rejected) and approval_id (an approve "
            "or reject approval whose scope names the job). Closing stops the job's "
            "research; published versions are still evaluated. After a rejection you may "
            "submit a follow-up brief with parent_job_id and the owner's feedback as steering."
        ),
        annotations=GATED,
    )
    async def job_close(
        job_id: UUID, decision: Literal["approved", "rejected"], approval_id: UUID
    ) -> ToolResult:
        research = deps.require_research()
        async with lock:
            wanted = "approve" if decision == "approved" else "reject"
            record = await approval_for(approval_id, (wanted,))
            if record.scope.job_id != job_id:
                raise refused(
                    "APPROVAL_SCOPE_MISMATCH",
                    "the approval does not name this job",
                    approval_id=str(approval_id),
                )
            request = CloseRequest(decision=decision, approval_id=approval_id)
            with bind(job_id=str(job_id)):
                job = await downstream(lambda: research.close(job_id, request))
                logger.info(
                    "job_closed",
                    outcome="ok",
                    payload={"decision": decision, "approval_id": str(approval_id)},
                )
            return result(job.model_dump(mode="json"))

    # ---------------------------------------------------------------- acceptance

    @server.tool(
        name="qfr.acceptance.list_cases",
        description=(
            "Acceptance cases opened by the evaluator after incubation, open and decided, "
            "with every gate's value, threshold and pass, the recommendation and the "
            "decision (owner_only). Optional filters: state (open or decided), version_id "
            "and case_id."
        ),
        annotations=READ,
    )
    async def acceptance_list(
        state: Literal["open", "decided"] | None = None,
        version_id: UUID | None = None,
        case_id: UUID | None = None,
    ) -> ToolResult:
        admin = deps.admin
        if admin is None:
            raise RuntimeError("EVAL_ADMIN_UNCONFIGURED: EVAL_ADMIN_API_URL is not set")
        page = await downstream(lambda: admin.cases(state, version_id, case_id))
        items: list[JsonValue] = [c.model_dump(mode="json") for c in page.items]
        return result(
            {
                "visibility": "owner_only",
                "items": items,
                "hygiene": "Never copy owner-grade numbers into briefs or steering notes.",
            }
        )

    @server.tool(
        name="qfr.acceptance.decide",
        description=(
            "Accept or reject an acceptance case. Arguments: case_id, decision (accept or "
            "reject), approval_id (an accept_case or reject_case approval naming the case) "
            "and an optional rationale (default: the approval's). In v1 a case with a "
            "failed gate cannot be accepted. Accepting releases the decision report; add "
            "the version to its pool with qfr.pool.add and an approve approval."
        ),
        annotations=GATED,
    )
    async def acceptance_decide(
        case_id: UUID,
        decision: Literal["accept", "reject"],
        approval_id: UUID,
        rationale: str | None = None,
    ) -> ToolResult:
        admin = deps.admin
        if admin is None:
            raise RuntimeError("EVAL_ADMIN_UNCONFIGURED: EVAL_ADMIN_API_URL is not set")
        async with lock:
            wanted: Literal["accept_case", "reject_case"] = (
                "accept_case" if decision == "accept" else "reject_case"
            )
            record = await approval_for(approval_id, (wanted,))
            if record.scope.case_id != case_id:
                raise refused(
                    "APPROVAL_SCOPE_MISMATCH",
                    "the approval does not name this case",
                    approval_id=str(approval_id),
                )
            try:
                request = CaseDecisionRequest(
                    decision=decision,
                    rationale=rationale or record.rationale,
                    approval=CaseApprovalRef(
                        approval_id=approval_id, decision=wanted, scope=record.scope
                    ),
                )
            except ValidationError as error:
                raise ValueError(f"ARGUMENT_INVALID: {error.errors(include_url=False)}") from None
            case = await downstream(lambda: admin.decide(case_id, request))
            logger.info(
                "case_decision_sent",
                outcome="ok",
                version_id=str(case.version_id),
                payload={
                    "case_id": str(case_id),
                    "decision": case.decision,
                    "approval_id": str(approval_id),
                },
            )
            return result(case.model_dump(mode="json"))
