"""Wire models of feedback-api and eval-admin-api (PLAN Sections 16.6 and 16.8).

They live in qfr_core because the MCP front door reads both APIs and imports only core.
Owner-grade evidence is validated against the generated private JSON schema instead.
"""

from typing import Literal

from pydantic import UUID7, AwareDatetime, Field, JsonValue

from qfr_core.contracts import Contract, Hash, ReleasedReport

ReportType = Literal["intake", "screening", "w1", "library"]
ConfigKind = Literal["protocol", "policy", "quotas"]


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
    evidence_tier: Literal[
        "pending", "held", "deferred", "rejected", "duplicate", "screening_fail", "w1_fail",
        "w1_pass",
    ]  # fmt: skip
    intake_state: str
    reason_code: str | None
    released_state: str | None
    released_at: AwareDatetime | None


class VersionStatePage(Contract):
    items: list[VersionState]
