"""Public wire contracts. Private official measurement types belong in qfr_eval."""

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import (
    UUID7,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    JsonValue,
    StringConstraints,
    model_validator,
)

Hash = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_-]*$", max_length=64)]
ShortText = Annotated[str, StringConstraints(min_length=1, max_length=120)]
Sign = Literal[-1, 1]
Horizon = Literal[1, 5, 10, 20]
# JSON object keys are strings, so released horizon-keyed maps use the string forms.
HorizonKey = Literal["1", "5", "10", "20"]
Tier = Literal["w1_pass", "w2_pass", "advanced", "incubated"]
# Evidence tiers from weakest to strongest (Section 13.4).
TIER_ORDER: tuple[Tier, ...] = ("w1_pass", "w2_pass", "advanced", "incubated")
Operator = Literal[
    "explore", "llm_mutation", "syntactic_mutation", "crossover", "repair", "human_seed"
]
Outcome = Literal["ok", "failed", "retried", "skipped", "deferred", "fallback"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_default=True, allow_inf_nan=False)


class ReasonCode(StrEnum):
    SCHEMA_INVALID = "SCHEMA_INVALID"
    KIND_UNSUPPORTED = "KIND_UNSUPPORTED"
    PARSE_ERROR = "PARSE_ERROR"
    TYPE_ERROR = "TYPE_ERROR"
    COMPLEXITY_LIMIT = "COMPLEXITY_LIMIT"
    FORBIDDEN_CONSTRUCT = "FORBIDDEN_CONSTRUCT"
    DECLARATION_MISMATCH = "DECLARATION_MISMATCH"
    COMPONENT_INVALID = "COMPONENT_INVALID"
    DUPLICATE_OF = "DUPLICATE_OF"
    NEAR_DUPLICATE_OF = "NEAR_DUPLICATE_OF"
    QUOTA_DEFERRED = "QUOTA_DEFERRED"
    QUOTA_EXPIRED = "QUOTA_EXPIRED"
    LOW_COVERAGE = "LOW_COVERAGE"
    LOOKAHEAD_DETECTED = "LOOKAHEAD_DETECTED"
    RUNTIME_LIMIT = "RUNTIME_LIMIT"
    DEGENERATE = "DEGENERATE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class DiagnosticFlag(StrEnum):
    HIGH_TURNOVER = "HIGH_TURNOVER"
    LOW_MONOTONICITY = "LOW_MONOTONICITY"
    SIGN_MISMATCH = "SIGN_MISMATCH"
    CROWDED_WITH_LIBRARY = "CROWDED_WITH_LIBRARY"
    UNSTABLE_YEARLY = "UNSTABLE_YEARLY"
    DECAYS_FAST = "DECAYS_FAST"
    LOW_COVERAGE = "LOW_COVERAGE"
    WEAK_SIGNAL = "WEAK_SIGNAL"
    COST_DOMINATED = "COST_DOMINATED"
    HIGH_DRAWDOWN = "HIGH_DRAWDOWN"


class AgentRunRef(Contract):
    role: str
    provider: Literal["deepseek", "kimi", "glm"]
    model_id: str
    prompt_template_id: str
    prompt_sha256: Hash
    run_id: UUID7


class Provenance(Contract):
    job_id: UUID7 | None
    program_id: UUID7 | None
    generation_id: UUID7 | None
    island_id: Literal["I1", "I2", "I3", "I4", "I5", "I6"] | None
    operator: Operator
    parent_version_ids: list[UUID7]
    agent_runs: list[AgentRunRef]
    trace_ref: UUID7
    # Null only for setup imports: an owner's raw-pool factor was not developed on any
    # QFR snapshot, and the front door never reads research-zone data (MCP-02).
    research_snapshot_id: Hash | None
    qfr_core_version: Annotated[str, StringConstraints(pattern=r"^\d+\.\d+\.\d+$")]

    @model_validator(mode="after")
    def null_identifiers_only_for_import(self) -> Self:
        ids = (self.job_id, self.program_id, self.generation_id, self.island_id)
        if any(v is None for v in ids) and self.operator != "human_seed":
            raise ValueError("only setup imports may omit research identifiers")
        if self.research_snapshot_id is None and not self.is_setup_import:
            raise ValueError("only setup imports may omit the research snapshot")
        return self

    @property
    def is_setup_import(self) -> bool:
        return self.operator == "human_seed" and self.job_id is None


class Rationale(Contract):
    hypothesis_id: UUID7
    summary: Annotated[str, StringConstraints(min_length=1, max_length=1500)]
    mechanism: Annotated[str, StringConstraints(min_length=1, max_length=1500)]
    falsification: Annotated[str, StringConstraints(min_length=1, max_length=600)]
    change_summary: Annotated[str, StringConstraints(min_length=1, max_length=600)] | None = None


class StrategyRationale(Rationale):
    composition_rationale: Annotated[str, StringConstraints(min_length=1, max_length=1000)]


class Review(Contract):
    verdict_id: UUID7
    rounds: int = Field(ge=0)


class ResearchAssessment(Contract):
    visibility: Literal["research_non_official"]
    window: Literal["W0"]
    metrics: dict[str, FiniteFloat | None]


class FactorImplementation(Contract):
    language: Literal["qfr-dsl/1"]
    expression: Annotated[str, StringConstraints(min_length=1, max_length=1000)]


class Declaration(Contract):
    expected_sign: Sign
    horizon_days: Horizon


class FactorDeclaration(Declaration):
    fields_used: list[str] = Field(min_length=1)
    max_lookback_days: int = Field(ge=0)


class FactorManifest(Contract):
    schema_version: Literal["1"]
    kind: Literal["factor"]
    family_id: UUID7 | None
    name: Slug
    title: ShortText
    implementation: FactorImplementation
    declared: FactorDeclaration
    rationale: Rationale
    provenance: Provenance
    self_assessment: ResearchAssessment | None = None
    review: Review

    @model_validator(mode="after")
    def parent_change(self) -> Self:
        if self.provenance.parent_version_ids and not self.rationale.change_summary:
            raise ValueError("a parent requires a change summary")
        return self


class Component(Contract):
    version_id: UUID7
    sign: Sign
    weight: float = Field(gt=0, multiple_of=0.01)


class Portfolio(Contract):
    type: Literal["topk_dropout"]
    top_k: int = Field(ge=20, le=100)
    dropout: int = Field(ge=1, le=20)
    rebalance: Literal["daily"]
    long_only: Literal[True]


class StrategyImplementation(Contract):
    language: Literal["qfr-strategy/1"]
    components: list[Component] = Field(min_length=1, max_length=8)
    combination: Literal["zscore_weighted_sum"]
    portfolio: Portfolio

    @model_validator(mode="after")
    def unique_components(self) -> Self:
        ids = [c.version_id for c in self.components]
        if len(ids) != len(set(ids)):
            raise ValueError("components must name distinct versions")
        return self


class StrategyDeclaration(Declaration):
    expected_sign: Literal[1]


class StrategyManifest(Contract):
    schema_version: Literal["1"]
    kind: Literal["strategy"]
    family_id: UUID7 | None
    name: Slug
    title: ShortText
    implementation: StrategyImplementation
    declared: StrategyDeclaration
    rationale: StrategyRationale
    provenance: Provenance
    self_assessment: ResearchAssessment | None = None
    review: Review

    @model_validator(mode="after")
    def parents(self) -> Self:
        component_ids = {c.version_id for c in self.implementation.components}
        if not component_ids <= set(self.provenance.parent_version_ids):
            raise ValueError("component versions must appear in provenance parents")
        if self.provenance.parent_version_ids and not self.rationale.change_summary:
            raise ValueError("a parent requires a change summary")
        return self


Manifest = Annotated[FactorManifest | StrategyManifest, Field(discriminator="kind")]


class EvidenceRef(Contract):
    version_id: UUID7
    content_hash: Hash
    protocol_id: str
    protocol_version: str
    data_snapshot_id: Hash
    evaluator_code_version: str


class IntakeContent(Contract):
    type: Literal["intake", "screening"]
    status: Literal["PASS", "FAIL", "DUPLICATE", "DEFERRED"]
    reasons: list[ReasonCode]
    duplicate_of: UUID7 | None = None


class W1Content(Contract):
    type: Literal["w1"]
    rankic_mean: FiniteFloat
    rankic_ir: FiniteFloat
    nw_t_bucket: Literal["below_1", "1_to_2", "2_to_3", "above_3"]
    hit_ratio: float = Field(ge=0, le=1)
    decay_profile: dict[HorizonKey, FiniteFloat]
    ls_net_sharpe: FiniteFloat
    monotonicity: float = Field(ge=-1, le=1)
    top_turnover: float = Field(ge=0, le=1)
    rank_autocorrelation: float = Field(ge=-1, le=1)
    max_library_correlation: float | None = Field(ge=0, le=1)
    library_version_id: UUID7 | None
    library_empty: bool
    yearly_rankic: dict[str, FiniteFloat]
    coverage_bucket: Literal["FAIL", "PASS"]
    size_neutral_rankic: FiniteFloat | None
    complexity: int = Field(ge=0)
    flags: list[DiagnosticFlag]
    strategy_net_sharpe: FiniteFloat | None = None
    strategy_ir: FiniteFloat | None = None
    strategy_drawdown_bucket: FiniteFloat | None = None


class W2Content(Contract):
    type: Literal["w2"]
    status: Literal["PASS", "FAIL"]
    ladder_status: Literal["IMPROVED", "UNCHANGED"]
    family_best_rankic: FiniteFloat | None


class AdvancementContent(Contract):
    type: Literal["advancement"]
    status: Literal["ADVANCED", "NOT_ADVANCED"]


class SimulationContent(Contract):
    type: Literal["sim"]
    status: Literal["COMPLETED", "FAILED"]
    forward_rankic_bucket: Literal["negative", "0_to_0.01", "0.01_to_0.03", "above_0.03"]
    forward_sharpe_bucket: FiniteFloat


class DecisionContent(Contract):
    type: Literal["decision"]
    status: Literal["ACCEPTED", "REJECTED"]
    reason: Literal["gate_failed", "owner_rejected", "incubation_failed", "gates_passed"]
    gate: (
        Literal[
            "G-W1", "G-W2", "G-HOLDOUT", "G-DSR", "G-PBO", "G-HLZ", "G-FWD", "G-NOVELTY", "G-OPS"
        ]
        | None
    ) = None


class LibraryContent(Contract):
    type: Literal["library"]
    status: Literal["seed", "active", "retired"]


ReleasedContent = Annotated[
    IntakeContent
    | W1Content
    | W2Content
    | AdvancementContent
    | SimulationContent
    | DecisionContent
    | LibraryContent,
    Field(discriminator="type"),
]


class ReleasedReport(EvidenceRef):
    schema_version: Literal["1"]
    report_id: UUID7
    family_id: UUID7
    program_id: UUID7 | None
    policy_ref: str
    protocol_card_ref: str
    released_at: AwareDatetime
    content: ReleasedContent


class SeedExpression(Contract):
    name: Slug
    expression: Annotated[str, StringConstraints(min_length=1, max_length=1000)]
    expected_sign: Sign
    horizon_days: Horizon
    rationale: Annotated[str, StringConstraints(min_length=1, max_length=1500)]


class BriefSeeds(Contract):
    pool_entry_ids: list[UUID7]
    version_ids: list[UUID7]
    expressions: list[SeedExpression]
    notes: Annotated[str, StringConstraints(max_length=8000)]


class BriefConstraints(Contract):
    fields_allowed: list[str]
    operators_allowed: list[str]
    max_nodes: int = Field(gt=0)
    max_lookback_days: int = Field(ge=0)


class StrategySpec(Contract):
    top_k: int = Field(ge=20, le=100)
    dropout: int = Field(ge=1, le=20)
    max_components: int = Field(ge=1, le=8)


class DeliverableCriteria(Contract):
    tier: Tier
    min_count: int = Field(gt=0)
    max_candidates: int = Field(gt=0)

    @model_validator(mode="after")
    def counts(self) -> Self:
        if self.min_count > self.max_candidates:
            raise ValueError("minimum count exceeds maximum candidates")
        return self


class JobBudget(Contract):
    max_cost: float = Field(gt=0)
    max_generations: int = Field(gt=0)
    max_wall_clock_days: int = Field(gt=0)


class ResearchBrief(Contract):
    schema_version: Literal["brief/1"]
    title: ShortText
    objective: Annotated[str, StringConstraints(min_length=1, max_length=2000)]
    mode: Literal[
        "new_factors", "improve_factors", "new_strategy", "improve_strategy", "review_and_iterate"
    ]
    seeds: BriefSeeds
    islands: Literal["auto"] | list[Literal["I1", "I2", "I3", "I4", "I5", "I6"]]
    constraints: BriefConstraints
    strategy_spec: StrategySpec | None
    deliverable: DeliverableCriteria
    budget: JobBudget
    parent_job_id: UUID7 | None
    priority: Literal["normal", "low"]

    @model_validator(mode="after")
    def strategy_mode(self) -> Self:
        if self.mode in {"new_strategy", "improve_strategy"} and self.strategy_spec is None:
            raise ValueError("strategy modes require strategy_spec")
        return self


class TraceStep(Contract):
    schema_version: Literal["trace_step/1"]
    step_id: UUID7
    at: AwareDatetime
    job_id: UUID7 | None
    program_id: UUID7 | None
    generation_id: UUID7 | None
    task_id: UUID7 | None
    candidate_id: UUID7 | None
    version_id: UUID7 | None
    step_type: Literal[
        "BRIEF_RECEIVED",
        "SEEDS_PUBLISHED",
        "CHARTER_DERIVED",
        "GENERATION_STARTED",
        "GENERATION_STATE_CHANGED",
        "PROPOSAL_EMITTED",
        "PLAN_WRITTEN",
        "PLAN_VALIDATED",
        "HYPOTHESIS_PROPOSED",
        "PARENT_SELECTED",
        "PROMPT_SENT",
        "MODEL_RESPONDED",
        "PROVIDER_FALLBACK",
        "DRAFT_CREATED",
        "DSL_VALIDATED",
        "WORKBENCH_EVALUATED",
        "SIMILARITY_CHECKED",
        "CRITIC_REVIEWED",
        "REVISION_REQUESTED",
        "REVISED",
        "PRESCREEN_EVALUATED",
        "SELECTED",
        "NOT_SELECTED",
        "TRACE_CHECKED",
        "PUBLISHED",
        "REPORT_RECEIVED",
        "INTERPRETED",
        "INTERPRETATION_CHALLENGED",
        "KNOWLEDGE_ADDED",
        "MUTATION_APPLIED",
        "CROSSOVER_APPLIED",
        "SYNTACTIC_MUTATION_APPLIED",
        "REPAIR_APPLIED",
        "STRATEGY_COMPOSED",
        "DELIVERABLE_CRITERIA_EVALUATED",
        "DELIVERABLE_ASSEMBLED",
        "DELIVERED",
        "STEERING_ADDED",
        "JOB_STATE_CHANGED",
        "TOOL_CALLED",
        "APPROVAL_RECORDED",
        "POOL_EVENT",
    ]
    actor_kind: Literal["owner", "host_agent", "llm", "deterministic", "evaluator"]
    actor: str
    provider: Literal["deepseek", "kimi", "glm"] | None = None
    model_id: str | None = None
    prompt_template_id: str | None = None
    prompt_sha256: Hash | None = None
    run_id: UUID7 | None = None
    inputs: dict[str, JsonValue]
    payload: dict[str, JsonValue]
    outcome: Literal["ok", "failed", "retried", "fallback"]
    request_id: str

    @model_validator(mode="after")
    def llm_attribution(self) -> Self:
        if self.actor_kind == "llm" and any(
            v is None
            for v in (
                self.provider,
                self.model_id,
                self.prompt_template_id,
                self.prompt_sha256,
                self.run_id,
            )
        ):
            raise ValueError("LLM steps require complete provider and prompt attribution")
        return self


class TraceAgentRun(Contract):
    """One agent_runs row inlined in a trace export (Section 14.3)."""

    run_id: UUID7
    step_id: UUID7 | None
    role: str
    provider: Literal["deepseek", "kimi", "glm"] | None
    model_id: str
    prompt_template_id: str
    prompt_sha256: Hash
    request_messages: list[JsonValue]
    response_text: str
    response_json: JsonValue
    usage: dict[str, JsonValue]
    settings: dict[str, JsonValue]
    status: Literal["ok", "failed", "fallback"]
    latency_ms: float = Field(ge=0)


class TraceLineageEdge(Contract):
    child_version_id: UUID7
    parent_version_id: UUID7
    relation: str
    operator: str
    ast_diff: list[dict[str, JsonValue]] | None


class TraceExport(Contract):
    """trace/1: every step for a version and its ancestors, ordered by (at, step_id), with
    agent runs inlined, lineage edges and the released reports research saw (Section 14.5).

    The research export never holds owner-grade evidence; the front door's owner export
    adds official records under owner_records (labelled owner_only). trace_hash is the
    SHA-256 of the canonical JSON of the export without owner_records.
    """

    schema_version: Literal["trace/1"]
    version_id: UUID7 | None
    candidate_id: UUID7 | None
    job_id: UUID7 | None
    ancestors: list[UUID7]
    steps: list[TraceStep]
    agent_runs: list[TraceAgentRun]
    lineage: list[TraceLineageEdge]
    released_reports: list[ReleasedReport]
    owner_records: dict[str, JsonValue] | None = None

    @model_validator(mode="after")
    def subject(self) -> Self:
        if self.version_id is None and self.candidate_id is None:
            raise ValueError("a trace export names a version or a candidate")
        return self


class HistoryHop(Contract):
    from_version_ids: list[UUID7]
    to_version_id: UUID7 | None
    candidate_id: UUID7 | None
    generation_seq: int = Field(ge=0)
    operator: str
    targeted_flags: list[DiagnosticFlag]
    hypothesis_title: str
    change_summary: str
    expression_before: list[str]
    expression_after: str
    ast_diff: list[dict[str, JsonValue]]
    engineer: AgentRunRef | None
    critic: dict[str, JsonValue] | None
    workbench: ResearchAssessment | None
    evaluation: list[ReleasedReport]
    owner_grade: dict[str, JsonValue] | None
    outcome: str

    @model_validator(mode="after")
    def target(self) -> Self:
        if self.to_version_id is None and self.candidate_id is None:
            raise ValueError("a history hop must identify its destination")
        return self


class IterationHistory(Contract):
    schema_version: Literal["iteration_history/1"]
    version_id: UUID7
    job_id: UUID7 | None
    generated_at: AwareDatetime
    trace_hash: Hash
    roots: list[UUID7]
    hops: list[HistoryHop]
    discarded: list[dict[str, JsonValue]]
    totals: dict[str, JsonValue]


class DeliverableItem(Contract):
    version_id: UUID7
    kind: Literal["factor", "strategy"]
    manifest: Manifest
    # None only in a best_effort deliverable: the version reached no tier (Section 13.3).
    tier_reached: Tier | None
    iteration_history: IterationHistory
    trace_ref: UUID7
    trace_hash: Hash
    released_reports: list[ReleasedReport]
    # qfr_mcp additionally validates against qfr_eval's published JSON Schema.
    owner_evidence: dict[str, JsonValue] | None
    caveats: list[str] = Field(min_length=1)


class Deliverable(Contract):
    schema_version: Literal["deliverable/1"]
    deliverable_id: UUID7
    job_id: UUID7
    created_at: AwareDatetime
    status: Literal["complete", "best_effort"]
    items: list[DeliverableItem]
    summary: str
    costs: dict[str, JsonValue]
    short_codes: list[str]

    @model_validator(mode="after")
    def tiers(self) -> Self:
        if self.status == "complete" and any(i.tier_reached is None for i in self.items):
            raise ValueError("every item of a complete deliverable has reached a tier")
        return self


class ApprovalScope(Contract):
    job_id: UUID7 | None
    deliverable_id: UUID7 | None
    version_ids: list[UUID7]
    pool: Literal["factor", "strategy"] | None
    tier: Tier | None
    case_id: UUID7 | None
    entry_ids: list[UUID7]


class ApprovalRecord(Contract):
    schema_version: Literal["approval/1"]
    approval_id: UUID7
    created_at: AwareDatetime
    decision: Literal["approve", "reject", "retire", "accept_case", "reject_case", "rollover_epoch"]
    scope: ApprovalScope
    owner_confirmation: Annotated[str, StringConstraints(min_length=1, max_length=2000)]
    rationale: Annotated[str, StringConstraints(min_length=1)]
    short_codes_matched: list[str] = Field(min_length=1)
    principal: str
    request_id: str


Tag = Annotated[str, StringConstraints(min_length=1, max_length=64)]
PoolName = Literal["factor", "strategy"]
PoolStatus = Literal["seed", "approved", "retired"]


class PoolEntry(Contract):
    """One row of pool_current_v: the entry with its current status (latest status event)."""

    schema_version: Literal["pool_entry/1"]
    entry_id: UUID7
    pool: PoolName
    version_id: UUID7
    title: ShortText
    created_at: AwareDatetime
    created_by: str
    approval_id: UUID7 | None
    setup_ref: UUID7 | None
    status: PoolStatus
    approved_tier: Tier | None
    tags: list[str]
    last_event_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def authority(self) -> Self:
        if self.status == "seed" and self.setup_ref is None and self.approval_id is None:
            raise ValueError("seed imports require a setup reference")
        if self.status != "seed" and self.approval_id is None:
            raise ValueError("pool changes require approval")
        if self.status == "approved" and self.approved_tier is None:
            raise ValueError("approved entries require an evidence tier")
        return self


class ImportComponent(Contract):
    name: Slug
    sign: Sign
    weight: float = Field(gt=0, multiple_of=0.01)


class ImportStrategy(Contract):
    components: list[ImportComponent] = Field(min_length=1, max_length=8)
    combination: Literal["zscore_weighted_sum"]
    portfolio: Portfolio

    @model_validator(mode="after")
    def unique_components(self) -> Self:
        names = [c.name for c in self.components]
        if len(names) != len(set(names)):
            raise ValueError("components must name distinct factor entries")
        return self


class PoolImportEntry(Contract):
    """One raw-pool row: a factor (expression) or a strategy over factor rows (strategy)."""

    name: Slug
    title: ShortText
    expression: Annotated[str, StringConstraints(min_length=1, max_length=1000)] | None = None
    expected_sign: Sign
    horizon_days: Horizon
    tags: list[Tag] = Field(default_factory=list)
    # The notes become the seed hypothesis's mechanism, which is limited to 1,500 chars.
    notes: Annotated[str, StringConstraints(min_length=1, max_length=1500)] | None = None
    strategy: ImportStrategy | None = None

    @model_validator(mode="after")
    def one_kind(self) -> Self:
        if (self.expression is None) == (self.strategy is None):
            raise ValueError("an entry needs exactly one of expression (factor) or strategy")
        if self.strategy is not None and self.expected_sign != 1:
            raise ValueError("a strategy's direction is always +1 after component signs")
        return self

    @property
    def kind(self) -> Literal["factor", "strategy"]:
        return "factor" if self.expression is not None else "strategy"


class PoolImport(Contract):
    schema_version: Literal["pool_import/1"]
    entries: list[PoolImportEntry]

    @model_validator(mode="after")
    def unique_names(self) -> Self:
        names = [entry.name for entry in self.entries]
        if len(names) != len(set(names)):
            raise ValueError("import names must be unique")
        factors = {entry.name for entry in self.entries if entry.expression is not None}
        for entry in self.entries:
            if entry.strategy and any(c.name not in factors for c in entry.strategy.components):
                raise ValueError("import strategy references an unknown factor entry")
        return self


class LogLine(Contract):
    ts: AwareDatetime
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    service: str
    zone: Literal["control", "research", "registry", "eval"]
    event: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")]
    request_id: Annotated[str, StringConstraints(min_length=1)]
    principal: str | None = None
    job_id: str | None = None
    program_id: str | None = None
    generation_id: str | None = None
    task_id: str | None = None
    run_id: str | None = None
    candidate_id: str | None = None
    version_id: str | None = None
    family_id: str | None = None
    record_id: str | None = None
    report_id: str | None = None
    case_id: str | None = None
    sim_id: str | None = None
    step_id: str | None = None
    duration_ms: float | None = Field(default=None, ge=0)
    outcome: Outcome | None = None
    error_code: str | None = None
    error_type: str | None = None
    stack: str | None = None
    payload: dict[str, JsonValue] | None = None


class AlertAckRequest(Contract):
    """The owner's acknowledgement of one alert, sent by the front door to the service
    that raised it (eval-admin-api or research-api)."""

    by: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    note: Annotated[str, StringConstraints(min_length=1, max_length=2000)] | None = None


PUBLIC_CONTRACTS: dict[str, type[Contract]] = {
    "factor_manifest": FactorManifest,
    "strategy_manifest": StrategyManifest,
    "released_report": ReleasedReport,
    "research_brief": ResearchBrief,
    "deliverable": Deliverable,
    "iteration_history": IterationHistory,
    "trace_step": TraceStep,
    "trace_export": TraceExport,
    "approval_record": ApprovalRecord,
    "pool_entry": PoolEntry,
    "pool_import": PoolImport,
    "log_line": LogLine,
}
