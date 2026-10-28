"""Private versioned release rules and unsigned projections, never public evidence."""

import hashlib
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    Field,
    NonNegativeInt,
    PositiveFloat,
    PositiveInt,
    SerializerFunctionWrapHandler,
    model_serializer,
    model_validator,
)
from qfr_core.contracts.base import Contract, Sha256, Text
from qfr_core.contracts.enums import DiagnosticFlag, ReasonCode
from qfr_core.contracts.reports import (
    EvidenceIdentity,
    MetricValue,
    PlanningDetectability,
    ReleasedContent,
    ReleasedScalar,
)
from qfr_core.data_layer.snapshots import canonical_json


class PilotReleasePolicy(Contract):
    schema_version: Literal["1"]
    policy_id: Text
    version: PositiveInt
    profile: Literal["pilot_industry_v1"]
    scope: Literal["P0_P1_verification_only"]
    protocol_sha256: Sha256
    approval_ref: Text
    fitness_profile: Literal["pilot_single_scalar_flags_v1"]
    release_window: Literal["validation"]
    release_cycle: Literal["weekly"]
    primary_metric: Literal["extreme_macro_recall"]
    ladder_step: PositiveFloat
    rounding: Literal["floor_to_step"]
    ladder_reference: Literal["last_accepted_unrounded_score"]
    retain_origin_version: Literal[True]
    feedback_versions_per_lineage_generation: Literal[3]
    confirmation_queries_per_protocol: Literal[1]
    confirmation_authorization: Literal["separate_explicit_owner_action"]
    batch_hours: PositiveInt = Field(le=24)
    secondary_metrics: Literal["withheld_pending_separate_family_summary"]
    rank_bucket_rule: Literal["frozen_family_midrank_tertiles"]
    automatic_campaign: Literal[False]
    planning_detectability: PlanningDetectability | None = None

    @model_validator(mode="after")
    def whole_utc_batches(self) -> Self:
        if 24 % self.batch_hours:
            raise ValueError("release batches must divide a UTC day")
        if (self.version == 1) != (self.planning_detectability is None):
            raise ValueError("planning disclosure requires a new policy revision")
        return self

    @model_serializer(mode="wrap")
    def preserve_legacy_policy(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        value: dict[str, Any] = handler(self)
        if self.planning_detectability is None:
            value.pop("planning_detectability", None)
        return value

    @property
    def sha256(self) -> str:
        return hashlib.sha256(canonical_json(self.model_dump(mode="json"))).hexdigest()


class StockReleaseQuotas(Contract):
    family_w1_per_24h: PositiveInt
    family_w2_per_7d: PositiveInt
    program_w1_per_day: PositiveInt
    program_w2_per_week: PositiveInt
    global_w1_per_day: PositiveInt
    global_w2_per_epoch: PositiveInt
    deferral_expiry_days: PositiveInt
    burn_w1_amber: PositiveInt
    burn_w1_red: PositiveInt


class StockRounding(Contract):
    rank_ic: PositiveFloat
    ir: PositiveFloat
    sharpe: PositiveFloat
    shares: PositiveFloat
    correlations: PositiveFloat
    w2_best_rank_ic: PositiveFloat


class StockReleasePolicy(Contract):
    schema_version: Literal["1"]
    policy_id: Text
    version: PositiveInt
    profile: Literal["stock_daily_v1"]
    fitness_profile: Literal["stock_multi_metric_v1"]
    w1_batch_hours: PositiveInt = Field(le=24)
    w2_batch: Literal["Monday 00:00 UTC"]
    advancement_delay_days: PositiveInt
    rounding: StockRounding
    rounding_rule: Literal["nearest_half_away_from_zero"]
    ladder_eta: PositiveFloat
    ladder_reference: Literal["last_accepted_unrounded_score"]
    quotas: StockReleaseQuotas
    w3_metrics_released: Literal[False]
    raw_series_released: Literal[False]
    diagnostics: Literal["enum_codes_only"]
    automatic_campaign: Literal[False]

    @model_validator(mode="after")
    def consistent_limits(self) -> Self:
        if 24 % self.w1_batch_hours:
            raise ValueError("release batches must divide a UTC day")
        if self.quotas.burn_w1_red <= self.quotas.burn_w1_amber:
            raise ValueError("red burn threshold must exceed amber")
        return self

    @property
    def sha256(self) -> str:
        return hashlib.sha256(canonical_json(self.model_dump(mode="json"))).hexdigest()


ReleasePolicy = Annotated[PilotReleasePolicy | StockReleasePolicy, Field(discriminator="profile")]


class ReleaseSource(Contract):
    schema_version: Literal["1"]
    source_kind: Literal["official_record", "intake_transition"]
    source_id: UUID
    source_sha256: Sha256
    policy_sha256: Sha256
    program_id: Text
    family_id: Text
    epoch_id: Text
    stage: Literal["intake", "screening", "pilot", "w1", "w2"]
    completed_at: AwareDatetime
    eligible_at: AwareDatetime

    @model_validator(mode="after")
    def no_early_release(self) -> Self:
        if self.eligible_at < self.completed_at:
            raise ValueError("release cannot precede source completion")
        return self


class QuotaSubject(Contract):
    schema_version: Literal["1"]
    profile: Literal["stock_daily_v1"]
    artifact_version_id: UUID
    program_id: Text
    # Bound by evaluation's canonical lineage map, never research's display name.
    family_id: Text
    epoch_id: Text
    stage: Literal["w1", "w2"]

    @property
    def sha256(self) -> str:
        return hashlib.sha256(canonical_json(self.model_dump(mode="json"))).hexdigest()


class QuotaDecision(Contract):
    schema_version: Literal["1"]
    subject_sha256: Sha256
    state: Literal["admitted", "deferred", "expired"]
    reason: Literal["QUOTA_DEFERRED", "QUOTA_EXPIRED"] | None
    admission_id: UUID | None
    next_eligible_at: AwareDatetime | None

    @model_validator(mode="after")
    def disposition(self) -> Self:
        if (self.state == "admitted") != (self.admission_id is not None):
            raise ValueError("only an admitted request has a quota allocation")
        if (
            self.reason
            != {"admitted": None, "deferred": "QUOTA_DEFERRED", "expired": "QUOTA_EXPIRED"}[
                self.state
            ]
        ):
            raise ValueError("quota reason differs from disposition")
        if self.state != "deferred" and self.next_eligible_at is not None:
            raise ValueError("terminal quota result cannot promise a retry time")
        return self


class LadderBest(Contract):
    schema_version: Literal["1"]
    scope_sha256: Sha256
    unrounded_score: float
    scalar: ReleasedScalar

    @model_validator(mode="after")
    def measured(self) -> Self:
        if self.scalar.measurement.value is None:
            raise ValueError("a missing score cannot become a lineage best")
        return self


class StockReleaseRecord(Contract):
    """Stock release adapter input; this does not perform stock measurement.

    Stored only by an evaluator producer with its paired trial. The pilot's
    historical OfficialRecord and trading-unit semantics are not reinterpreted.
    """

    schema_version: Literal["1"]
    stage: Literal["stock_measurement"]
    record_id: UUID
    identity: EvidenceIdentity
    program_id: Text
    family_id: Text
    economic_lineage_id: Text
    generation_id: Text
    epoch_id: Text
    window: Literal["W1", "W2"]
    sampling_unit: Literal["trading_date"]
    period_count: NonNegativeInt
    status: Literal["complete", "failed", "withheld"]
    metrics: dict[Text, MetricValue]
    yearly_rank_ic: dict[Annotated[str, Field(pattern=r"^[0-9]{4}$")], MetricValue]
    decay_profile: dict[Literal["1", "5", "10", "20"], MetricValue]
    library_artifact_version_id: Text | None
    coverage_bucket: Literal["low", "adequate", "high", "unavailable"]
    complexity: NonNegativeInt
    cost_basis_ref: Text
    baseline_version_id: Text | None
    gate_passed: bool
    reason_codes: list[ReasonCode]
    flags: list[DiagnosticFlag]
    created_at: AwareDatetime

    @model_validator(mode="after")
    def no_missing_pass(self) -> Self:
        metric = self.metrics.get("rank_ic_mean")
        if self.gate_passed and (
            self.status != "complete"
            or self.period_count == 0
            or metric is None
            or metric.value is None
        ):
            raise ValueError("missing or failed stock evidence cannot pass")
        return self


class PreparedRelease(Contract):
    """Not an official released report; signing and atomic publication are required."""

    schema_version: Literal["1"]
    visibility: Literal["private_unsigned"]
    report_id: UUID
    source_id: UUID
    source_kind: Literal["official_record", "intake_transition", "owner_event"]
    identity: EvidenceIdentity
    family_id: Text
    program_id: Text
    epoch_id: Text
    generation_id: Text
    # Pre-evaluation intake decisions may not yet have an owner-resolved root.
    # Any measured pilot projection requires actual reservation rows instead.
    lineage_ids: list[Text]
    release_policy_ref: Text
    release_policy_sha256: Sha256
    protocol_card_ref: Text
    profile: Literal["pilot_industry_v1", "stock_daily_v1"]
    content: ReleasedContent
    reason_codes: list[ReasonCode]
    flags: list[DiagnosticFlag]
    eligible_at: AwareDatetime
    numeric_values: NonNegativeInt
    ladder_updates: dict[Text, LadderBest]

    @property
    def sha256(self) -> str:
        return hashlib.sha256(canonical_json(self.model_dump(mode="json"))).hexdigest()


class BurnSummary(Contract):
    schema_version: Literal["1"]
    epoch_id: Text
    window: Literal["development", "validation", "W1", "W2"]
    trials: NonNegativeInt
    released_values: NonNegativeInt
    queries_used: NonNegativeInt
    query_budget: PositiveInt | None
    status: Literal["green", "amber", "red", "unthresholded"]
