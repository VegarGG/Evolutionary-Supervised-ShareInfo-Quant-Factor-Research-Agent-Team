"""Strict released-only projection; there is no private holdout metric field."""

from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, NonNegativeInt, model_validator

from qfr_core.contracts.base import Contract, Sha256, Text
from qfr_core.contracts.enums import DiagnosticFlag, ReasonCode


class EvidenceIdentity(Contract):
    artifact_version_id: Text
    content_hash: Sha256
    protocol_version: Text
    dataset_version_id: Text
    evaluator_version: Text


class MetricValue(Contract):
    value: float | None
    missing_reason: (
        Literal["not_applicable", "insufficient_data", "withheld", "failed", "not_measured"] | None
    )

    @model_validator(mode="after")
    def missing_is_explicit(self) -> Self:
        if (self.value is None) != (self.missing_reason is not None):
            raise ValueError("null metrics require a reason; measured values must not have one")
        return self


class ReleasedScalar(Contract):
    metric: Literal["extreme_macro_recall", "RankIC_mean"]
    sampling_unit: Literal["mature_matched_decision", "trading_date"]
    period_count: NonNegativeInt
    cost_basis_ref: Text
    baseline_version_id: Text | None
    measurement: MetricValue
    origin_artifact_version_id: Text
    attribution: Literal["current_version", "lineage_best"]


class PilotHurdleFlags(Contract):
    incremental_contribution: Literal["pass", "fail", "insufficient_data", "not_applicable"]
    fold_majority: Literal["pass", "fail", "insufficient_data", "not_applicable"]
    placebo: Literal["pass", "fail", "insufficient_data", "not_applicable"]
    net_result: Literal["pass", "fail", "insufficient_data", "not_applicable"]
    turnover: Literal["pass", "fail", "insufficient_data", "not_applicable"]
    novelty: Literal["pass", "fail", "insufficient_data", "not_applicable"]


class PilotRelease(Contract):
    type: Literal["pilot"]
    scalar: ReleasedScalar
    hurdle_flags: PilotHurdleFlags
    rank_bucket: Literal["top", "middle", "bottom", "withheld"]
    quality_flags: list[Literal["small_sample_warning", "pit_grade_downgrade", "duplicate"]]
    minimum_detectable_effect: MetricValue
    not_for_selection: bool


class StockW1Release(Contract):
    type: Literal["w1"]
    rank_ic_mean: MetricValue
    rank_ic_ir: MetricValue
    nw_t_bucket: Literal["below_1", "1_to_2", "2_to_3", "above_3", "unavailable"]
    positive_rank_ic_date_share: MetricValue
    decay_profile: dict[Literal["1", "5", "10", "20"], MetricValue]
    ls_net_sharpe: MetricValue
    monotonicity: MetricValue
    top_turnover: MetricValue
    rank_autocorrelation: MetricValue
    max_library_correlation: MetricValue
    library_artifact_version_id: Text | None
    yearly_rank_ic: dict[Annotated[str, Field(pattern=r"^[0-9]{4}$")], MetricValue]
    coverage_bucket: Literal["low", "adequate", "high", "unavailable"]
    size_neutral_rank_ic: MetricValue
    complexity: NonNegativeInt


class StockW2Release(Contract):
    type: Literal["w2"]
    decision: Literal["PASS", "FAIL"]
    ladder_status: Literal["improved", "unchanged", "withheld"]
    scalar: ReleasedScalar | None


class StatusRelease(Contract):
    type: Literal["intake", "screening"]
    status: Literal["queued", "running", "failed", "complete", "withheld", "pass"]


class AdvancementRelease(Contract):
    type: Literal["advancement"]
    decision: Literal["ADVANCED", "NOT_ADVANCED"]


class SimulationRelease(Contract):
    type: Literal["sim"]
    status: Literal["completed", "failed"]
    rank_ic_bucket: Literal["negative", "0_to_0.01", "0.01_to_0.03", "above_0.03", "unavailable"]
    sharpe_bucket: Literal["negative", "nonnegative", "unavailable"]
    evidence_mode: Literal["forward", "replay"]


class DecisionRelease(Contract):
    type: Literal["decision"]
    decision: Literal["ACCEPTED", "REJECTED"]
    category: Literal["gates_passed", "gate_failed", "approver_rejected", "incubation_failed"]
    gate: Literal["quality", "validation", "holdout", "incubation", "approval"] | None


class LibraryRelease(Contract):
    type: Literal["library"]
    membership: Literal["baseline", "active", "retired"]


ReleasedContent = Annotated[
    PilotRelease
    | StockW1Release
    | StockW2Release
    | StatusRelease
    | AdvancementRelease
    | SimulationRelease
    | DecisionRelease
    | LibraryRelease,
    Field(discriminator="type"),
]


class Signature(Contract):
    algorithm: Literal["Ed25519"]
    key_id: Text
    signature_hex: Annotated[str, Field(pattern=r"^[0-9a-f]{128}$")]


class ReleasedReport(Contract):
    schema_version: Literal["1"]
    report_id: Text
    identity: EvidenceIdentity
    family_id: Text
    program_id: Text
    release_policy_ref: Text
    protocol_card_ref: Text
    profile: Literal["pilot_industry_v1", "stock_daily_v1"]
    content: ReleasedContent
    reason_codes: list[ReasonCode]
    flags: list[DiagnosticFlag]
    released_at: AwareDatetime
    signature: Signature

    @model_validator(mode="after")
    def policy_and_attribution(self) -> Self:
        if isinstance(self.content, PilotRelease) and self.profile != "pilot_industry_v1":
            raise ValueError("pilot scalar requires pilot policy")
        if (
            isinstance(self.content, (StockW1Release, StockW2Release))
            and self.profile != "stock_daily_v1"
        ):
            raise ValueError("stock release requires stock policy")
        scalar = (
            self.content.scalar
            if isinstance(self.content, (PilotRelease, StockW2Release))
            else None
        )
        if scalar and scalar.attribution == "current_version":
            if scalar.origin_artifact_version_id != self.identity.artifact_version_id:
                raise ValueError("current-version score has a different originating artifact")
        if scalar:
            expected = (
                ("extreme_macro_recall", "mature_matched_decision")
                if isinstance(self.content, PilotRelease)
                else ("RankIC_mean", "trading_date")
            )
            if (scalar.metric, scalar.sampling_unit) != expected:
                raise ValueError("metric identity or sampling unit differs from release profile")
        return self


class PublicProtocolCard(Contract):
    schema_version: Literal["1"]
    protocol_version: Text
    profile: Literal["pilot_industry_v1", "stock_daily_v1"]
    universe: Text
    label_definition: Text
    metric_definitions: dict[Text, Text]
    cost_policy_ref: Text
    public_gate_descriptions: list[Text]
    release_policy_ref: Text
    exposure: Literal["previously_seen", "unknown", "prospective"]
