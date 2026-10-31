"""Wire models of the research control API (PLAN Section 16.7).

They live in qfr_core because the MCP front door (which imports only core) and
research-api both validate them. Owner-grade evidence never appears here: research-api
serves deliverables without it, and the front door adds it from eval-admin-api.
"""

from typing import Annotated, Literal

from pydantic import UUID7, AwareDatetime, Field, JsonValue, StringConstraints

from qfr_core.contracts import (
    Contract,
    Deliverable,
    DeliverableCriteria,
    IterationHistory,
    JobBudget,
    ResearchBrief,
    Tier,
    TraceExport,
    TraceStep,
)

JobState = Literal[
    "SUBMITTED",
    "VALIDATED",
    "RUNNING",
    "WAITING_FOR_EVALUATION",
    "DELIVERABLE_READY",
    "DELIVERED",
    "CLOSED",
]
CloseDecision = Literal["approved", "rejected", "expired", "cancelled", "budget_exhausted"]
GenerationState = Literal[
    "PENDING",
    "SYNCING",
    "PROPOSING",
    "PLANNING",
    "DEVELOPING",
    "SELECTING",
    "PUBLISHING",
    "CLOSED",
    "FAILED",
    "ABORTED",
]
SteeringNote = Annotated[str, StringConstraints(min_length=1, max_length=2000)]


class BriefScan(Contract):
    """The owner-only scan's verdict (Section 9.6), computed by the front door.

    The scan compares the brief's text with the owner-only values of every referenced
    version. Those values never enter the research zone, so the front door scans and
    research-api stores only this verdict.
    """

    status: Literal["passed"]
    scanner: Literal["qfr-mcp"]
    referenced_version_ids: list[UUID7]
    numbers_in_text: int = Field(ge=0)
    values_compared: int = Field(ge=0)


class SubmitJobRequest(Contract):
    brief: ResearchBrief
    scan: BriefScan


class TimelineEstimate(Contract):
    tier: Tier
    first_reports: str
    first_deliverable: str


class JobView(Contract):
    job_id: UUID7
    short_code: Annotated[str, StringConstraints(pattern=r"^J-\d{4,}$")]
    title: str
    mode: str
    state: JobState
    paused: bool
    program_id: UUID7 | None
    parent_job_id: UUID7 | None
    submitted_at: AwareDatetime
    updated_at: AwareDatetime
    closed_at: AwareDatetime | None
    close_decision: CloseDecision | None
    stop_reason: str | None
    deliverable_criteria: DeliverableCriteria
    budget: JobBudget
    cost_cny: float = Field(ge=0)
    generations_run: int = Field(ge=0)
    publications: int = Field(ge=0)
    deliverables: int = Field(ge=0)
    seed_version_ids: list[UUID7]
    charter_version: int = Field(ge=0)
    next_generation_at: AwareDatetime | None


class SubmitJobResponse(Contract):
    created: bool
    job: JobView
    charter: dict[str, JsonValue]
    seed_version_ids: list[UUID7]
    timeline: TimelineEstimate


class JobPage(Contract):
    items: list[JobView]
    next_cursor: UUID7 | None


class JobEvent(Contract):
    event_id: UUID7
    job_id: UUID7
    seq: int = Field(ge=1)
    at: AwareDatetime
    kind: str
    payload: dict[str, JsonValue]


class JobEventPage(Contract):
    items: list[JobEvent]
    next_after_seq: int = Field(ge=0)


class JobWait(Contract):
    changed: bool
    waited_seconds: float = Field(ge=0)
    job: JobView


class SteerRequest(Contract):
    note: SteeringNote
    scan: BriefScan


class CloseRequest(Contract):
    """POST /v1/jobs/{id}/close: the approval-gated close arrives in Phase 6."""

    decision: Literal["approved", "rejected"]
    approval_id: UUID7


class DeliverableView(Contract):
    """A deliverable as research-api serves it: owner_evidence is always null here."""

    deliverable: Deliverable
    fetched_at: AwareDatetime | None


class DeliverablePage(Contract):
    items: list[DeliverableView]


class GenerationView(Contract):
    generation_id: UUID7
    program_id: UUID7
    seq: int = Field(ge=0)
    state: GenerationState
    plan_source: str | None
    started_at: AwareDatetime | None
    ended_at: AwareDatetime | None
    cost_cny: float = Field(ge=0)
    proposal: dict[str, JsonValue] | None
    plan: dict[str, JsonValue] | None
    summary: dict[str, JsonValue] | None


class GenerationPage(Contract):
    items: list[GenerationView]


class TraceView(Contract):
    """Steps of one version or candidate (and its ancestors), with agent runs inlined."""

    export: TraceExport
    trace_hash: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]


class TraceExportBundle(Contract):
    """qfr.trace.export (Section 14.5): a published version's trace/1 export with its
    trace_hash, its iteration history and the history's Markdown rendering. Research
    never holds owner-grade records; the front door adds them to its copy."""

    export: TraceExport
    trace_hash: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
    iteration_history: IterationHistory
    markdown: str


class TraceStepPage(Contract):
    items: list[TraceStep]


class LineageHop(Contract):
    child_version_id: UUID7
    parent_version_id: UUID7
    relation: str
    operator: str
    ast_diff: list[dict[str, JsonValue]] | None
    candidate_id: UUID7 | None
    generation_seq: int | None


class ResearchLineage(Contract):
    version_id: UUID7
    hops: list[LineageHop]
    reports: list[dict[str, JsonValue]]


class CostRow(Contract):
    key: dict[str, str | None]
    calls: int = Field(ge=0)
    tokens_in: int = Field(ge=0)
    tokens_out: int = Field(ge=0)
    tokens_cached: int = Field(ge=0)
    cost_cny: float = Field(ge=0)


class CostReport(Contract):
    group_by: list[str]
    start: AwareDatetime | None
    end: AwareDatetime | None
    rows: list[CostRow]
    total_cny: float = Field(ge=0)
    currency: str


class ModelProbe(Contract):
    provider: Literal["deepseek", "kimi", "glm"]
    model_id: str
    ok: bool
    checks: dict[str, Literal["pass", "fail", "skipped"]]
    detail: dict[str, JsonValue]


class RoleProbe(Contract):
    primary: str
    primary_ok: bool
    usable: list[str]
    ok: bool


class ProbeReport(Contract):
    probe_id: UUID7
    at: AwareDatetime
    trigger: Literal["setup", "daily", "job_start", "manual"]
    ok: bool
    models: list[ModelProbe]
    roles: dict[str, RoleProbe]
    notes: list[str]


class ResearchSummary(Contract):
    """GET /v1/summary: counts for qfr.status."""

    active_jobs: int = Field(ge=0)
    paused_programs: int = Field(ge=0)
    jobs_by_state: dict[str, int]
    cost_today_cny: float = Field(ge=0)
    daily_cap_cny: float = Field(ge=0)
    currency: str
    research_paused: bool
    last_probe: ProbeReport | None
