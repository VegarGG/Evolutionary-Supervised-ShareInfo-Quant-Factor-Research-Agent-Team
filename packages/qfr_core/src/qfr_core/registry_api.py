"""Wire models of the Registry API (PLAN Section 16.5).

They live in qfr_core because every client of the registry (the front door now; the
research packager and the evaluator's scheduler later) validates the same payloads.
"""

from typing import Annotated, Literal, Self

from pydantic import UUID7, AwareDatetime, Field, JsonValue, StringConstraints, model_validator

from qfr_core.contracts import (
    ApprovalScope,
    Contract,
    Hash,
    Manifest,
    PoolEntry,
    PoolName,
    PoolStatus,
    Slug,
    Tag,
    Tier,
)

Kind = Literal["factor", "strategy"]
PublishKey = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._:-]{1,128}$")]
Note = Annotated[str, StringConstraints(min_length=1, max_length=2000)]

# Fields the registry assigns. A client that sends any of them is ignored (REG-04).
SERVER_FIELDS = frozenset(
    {
        "version_id",
        "version_no",
        "content_hash",
        "canonical_hash",
        "published_at",
        "published_seq",
        "publisher",
    }
)


class PublishRequest(Contract):
    """POST /v1/artifacts. publish_key makes a retried request safe (Section 16.5)."""

    publish_key: PublishKey
    manifest: Manifest


class VersionRecord(Contract):
    """A published version: the manifest as submitted plus the registry's fields."""

    version_id: UUID7
    family_id: UUID7
    version_no: int = Field(ge=1)
    kind: Kind
    name: Slug
    content_hash: Hash
    canonical_hash: Hash
    published_seq: int = Field(ge=1)
    published_at: AwareDatetime
    publisher: str
    # Server-side analysis: the DSL canonical form, complexity, fields and lookback for
    # factors; the normalized weights for strategies.
    analysis: dict[str, JsonValue]
    manifest: Manifest


class PublishResponse(Contract):
    created: bool
    version: VersionRecord


class VersionPage(Contract):
    items: list[VersionRecord]
    next_since_seq: int = Field(ge=0)


class VersionSummary(Contract):
    version_id: UUID7
    version_no: int = Field(ge=1)
    content_hash: Hash
    canonical_hash: Hash
    published_seq: int = Field(ge=1)
    published_at: AwareDatetime
    publisher: str


class FamilyView(Contract):
    family_id: UUID7
    kind: Kind
    name: Slug
    program_id: UUID7 | None
    job_id: UUID7 | None
    created_at: AwareDatetime
    created_by: str
    versions: list[VersionSummary]


class LineageNode(Contract):
    version_id: UUID7
    family_id: UUID7
    version_no: int = Field(ge=1)
    kind: Kind
    name: Slug
    operator: str
    canonical_hash: Hash
    # Negative for ancestors, positive for descendants, 0 for the requested version.
    distance: int


class LineageEdge(Contract):
    version_id: UUID7
    parent_version_id: UUID7
    relation: Literal["parent", "component"]
    # The deterministic edit script from parent to child; null on component edges.
    ast_diff: list[dict[str, JsonValue]] | None


class LineageView(Contract):
    version_id: UUID7
    depth: int = Field(ge=0)
    nodes: list[LineageNode]
    edges: list[LineageEdge]


class ApprovalRef(Contract):
    """The approval the front door holds for a pool write.

    The registry cannot read control_db (BND-01), so the caller passes the approval's
    id, decision and scope, and the registry checks that the scope covers the write.
    Only the front door holds the control token, and it creates approvals (Phase 6).
    """

    approval_id: UUID7
    decision: Literal["approve", "retire"]
    scope: ApprovalScope


class AddEntryRequest(Contract):
    """POST /v1/pools/{pool}/entries: an ADDED event with the entry's first status."""

    version_id: UUID7
    title: Annotated[str, StringConstraints(min_length=1, max_length=120)]
    status: Literal["seed", "approved"]
    approved_tier: Tier | None = None
    approval: ApprovalRef | None = None
    # Seed imports carry the setup reference instead of an approval.
    setup_ref: UUID7 | None = None
    tags: list[Tag] = Field(default_factory=list)
    note: Note | None = None

    @model_validator(mode="after")
    def authority(self) -> Self:
        if self.status == "seed":
            if self.setup_ref is None or self.approval is not None:
                raise ValueError("a seed entry carries a setup reference and no approval")
            if self.approved_tier is not None:
                raise ValueError("a seed entry has no approved tier")
        else:
            if self.approval is None or self.setup_ref is not None:
                raise ValueError("an approved entry requires an approval")
            if self.approved_tier is None:
                raise ValueError("an approved entry requires an evidence tier")
        return self


class AppendEventRequest(Contract):
    """POST /v1/pools/{pool}/entries/{entry_id}/events."""

    action: Literal["STATUS_CHANGED", "ANNOTATED"]
    to_status: Literal["approved", "retired"] | None = None
    approved_tier: Tier | None = None
    approval: ApprovalRef | None = None
    tags: list[Tag] = Field(default_factory=list)
    note: Note | None = None

    @model_validator(mode="after")
    def shape(self) -> Self:
        if self.action == "STATUS_CHANGED":
            if self.to_status is None or self.approval is None:
                raise ValueError("a status change requires a target status and an approval")
            if (self.to_status == "approved") != (self.approved_tier is not None):
                raise ValueError("an approved tier is required exactly when approving")
        else:
            if self.to_status or self.approval or self.approved_tier:
                raise ValueError("an annotation changes no status and needs no approval")
            if not self.tags and self.note is None:
                raise ValueError("an annotation needs tags or a note")
        return self


class PoolEvent(Contract):
    event_id: UUID7
    event_seq: int = Field(ge=1)
    entry_id: UUID7
    pool: PoolName
    version_id: UUID7
    at: AwareDatetime
    principal: str
    action: Literal["ADDED", "STATUS_CHANGED", "ANNOTATED"]
    from_status: PoolStatus | None
    to_status: PoolStatus | None
    approved_tier: Tier | None
    approval_id: UUID7 | None
    setup_ref: UUID7 | None
    tags: list[str]
    note: str | None
    request_id: str


class AddEntryResponse(Contract):
    created: bool
    entry: PoolEntry
    event: PoolEvent | None


class PoolPage(Contract):
    items: list[PoolEntry]
    next_cursor: str | None


class PoolEventPage(Contract):
    items: list[PoolEvent]
    next_since_seq: int = Field(ge=0)


class PoolEntryDetail(Contract):
    entry: PoolEntry
    events: list[PoolEvent]


class PoolCounts(Contract):
    """Current entries of one pool by status (pool_current_v)."""

    seed: int = Field(default=0, ge=0)
    approved: int = Field(default=0, ge=0)
    retired: int = Field(default=0, ge=0)
    total: int = Field(default=0, ge=0)


class RegistrySummary(Contract):
    """GET /v1/summary: counts for qfr.status, qfr.setup.status and the empty-start check."""

    factor_versions: int = Field(ge=0)
    strategy_versions: int = Field(ge=0)
    families: int = Field(ge=0)
    factor_pool: PoolCounts
    strategy_pool: PoolCounts
    last_published_seq: int = Field(ge=0)
    last_event_seq: int = Field(ge=0)

    @property
    def empty(self) -> bool:
        return self.factor_pool.total == 0 and self.strategy_pool.total == 0


class ApiError(Contract):
    error: str
    message: str
    request_id: str
    details: list[dict[str, JsonValue]] = Field(default_factory=list)


class Health(Contract):
    status: Literal["ok", "degraded"]
    service: str
    database: bool
