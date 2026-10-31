"""Wire models of feedback-api and eval-admin-api (PLAN Sections 16.6 and 16.8).

They live in qfr_core because the MCP front door reads both APIs and imports only core.
Owner-grade evidence is validated against the generated private JSON schema instead.
"""

from datetime import date
from typing import Annotated, Literal

from pydantic import UUID7, AwareDatetime, Field, JsonValue, StringConstraints

from qfr_core.contracts import ApprovalScope, Contract, Hash, ReleasedReport, Tier

ReportType = Literal["intake", "screening", "w1", "w2", "advancement", "sim", "decision", "library"]
ConfigKind = Literal["protocol", "policy", "quotas"]
EvidenceTier = Literal[
    "pending", "held", "deferred", "rejected", "duplicate", "screening_fail", "w1_fail",
    "w1_pass", "w2_fail", "w2_expired", "w2_pass", "not_advanced", "advanced", "incubated",
]  # fmt: skip
GateName = Literal[
    "G-W1", "G-W2", "G-HOLDOUT", "G-DSR", "G-PBO", "G-HLZ", "G-FWD", "G-NOVELTY", "G-OPS"
]
Rationale = Annotated[str, StringConstraints(min_length=1, max_length=4000)]


class ReportPage(Contract):
    items: list[ReleasedReport]
    next_after_id: UUID7 | None


class TimelineEntry(Contract):
    report_id: UUID7
    report_type: ReportType
    status: str | None
    released_at: AwareDatetime


class ArtifactStatus(Contract):
    version_id: UUID7
    status: str | None
    report_type: ReportType | None
    timeline: list[TimelineEntry]


class LibraryEntry(Contract):
    version_id: UUID7
    pool: Literal["factor", "strategy"]
    status: Literal["seed", "active", "retired"]


class LibraryPage(Contract):
    items: list[LibraryEntry]


class Card(Contract):
    kind: Literal["protocol", "policy"]
    ref: str
    sha256: Hash
    activated_at: AwareDatetime
    card: dict[str, JsonValue]


class CreateVersionRequest(Contract):
    yaml: str = Field(min_length=1, max_length=262144)


class ActivateRequest(Contract):
    approval_id: UUID7 | None = None


class ConfigVersionView(Contract):
    kind: ConfigKind
    id: str
    version: str
    sha256: Hash
    status: Literal["draft", "active", "retired"]
    created: bool | None = None
    activated_at: AwareDatetime | None = None
    activated_by: str | None = None
    approval_id: UUID7 | None = None


class VersionState(Contract):
    """The evaluator's state of one version, for pool listings in the front door."""

    version_id: UUID7
    evidence_tier: EvidenceTier
    # The highest pool tier reached, which qfr.pool.add records; None before a W1 pass.
    pool_tier: Tier | None = None
    intake_state: str
    reason_code: str | None
    released_state: str | None
    released_at: AwareDatetime | None


class VersionStatePage(Contract):
    items: list[VersionState]


# Phase 6: simulation, acceptance cases and alerts (Sections 10.2 to 10.4, 16.8). ----------


class CaseApprovalRef(Contract):
    """The approval the front door holds for an acceptance decision. eval-admin-api
    cannot read control_db, so the caller passes the approval's id, decision and scope,
    and the evaluator checks that the scope names the case."""

    approval_id: UUID7
    decision: Literal["accept_case", "reject_case"]
    scope: ApprovalScope


class CaseDecisionRequest(Contract):
    """POST /v1/acceptance/cases/{case_id}/decision."""

    decision: Literal["accept", "reject"]
    rationale: Rationale
    approval: CaseApprovalRef


class CaseGate(Contract):
    name: GateName
    passed: bool
    skipped: bool = False
    value: float | None
    threshold: float | None
    detail: dict[str, JsonValue]


class AcceptanceCase(Contract):
    """One acceptance case with its gate values (owner only)."""

    visibility: Literal["owner_only"]
    case_id: UUID7
    short_code: str
    version_id: UUID7
    kind: Literal["factor", "strategy"]
    sim_id: UUID7
    mode: Literal["forward", "replay"]
    opened_at: AwareDatetime
    recommendation: Literal["ACCEPT", "REJECT"]
    failing_gates: list[GateName]
    gates: list[CaseGate]
    state: Literal["open", "decided"]
    decision: Literal["accepted", "rejected"] | None
    reason: Literal["gate_failed", "owner_rejected", "incubation_failed", "gates_passed"] | None
    reason_gate: GateName | None
    rationale: str | None
    approval_id: UUID7 | None
    decided_at: AwareDatetime | None


class CasePage(Contract):
    items: list[AcceptanceCase]


class SimulationView(Contract):
    """A simulation's state, checkpoints and NAV (owner only)."""

    visibility: Literal["owner_only"]
    sim_id: UUID7
    version_id: UUID7
    kind: Literal["factor", "strategy"]
    purpose: Literal["incubation", "monitoring"]
    mode: Literal["forward", "replay"]
    status: Literal["waiting", "running", "paused", "completed", "failed", "stopped"]
    not_before: date
    start_date: date | None
    last_day: date | None
    days_done: int
    required_days: int | None
    capital: float
    cash: float | None
    error_code: str | None
    settings: dict[str, JsonValue]
    metrics: dict[str, float | None]
    checkpoints: list[dict[str, JsonValue]]
    events: list[dict[str, JsonValue]]
    nav: list[dict[str, JsonValue]]
    positions: list[dict[str, JsonValue]]


class AlertView(Contract):
    alert_id: UUID7
    kind: Literal["decay", "staleness", "burn", "ops"]
    version_id: UUID7 | None
    sim_id: UUID7 | None
    at: AwareDatetime
    details: dict[str, JsonValue]
    state: Literal["open", "acknowledged"]
    acknowledged_by: str | None
    acknowledged_at: AwareDatetime | None


class AlertPage(Contract):
    items: list[AlertView]
    open: int = Field(ge=0)
