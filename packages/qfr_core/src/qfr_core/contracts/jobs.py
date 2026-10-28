"""Frozen research intent and independent delivery requirements, with no job runner."""

from typing import Any, Literal, Self

from pydantic import (
    AwareDatetime,
    Field,
    NonNegativeFloat,
    PositiveInt,
    SerializerFunctionWrapHandler,
    model_serializer,
    model_validator,
)

from qfr_core.contracts.artifacts import ArtifactReference
from qfr_core.contracts.base import Contract, Sha256, Text
from qfr_core.contracts.data import ExposureAndQuality
from qfr_core.contracts.enums import Conclusion, JobState


class DeliverableRequirement(Contract):
    name: Text
    schema_ref: Text
    required: bool
    evidence_refs_required: bool


class PilotDeliveryAssessment(Contract):
    """Exact artifact roles frozen before the human-driven pilot job is admitted."""

    schema_version: Literal["1"]
    assessed_artifact_refs: list[ArtifactReference] = Field(min_length=1)
    reference_artifact_refs: list[ArtifactReference]

    @model_validator(mode="after")
    def disjoint_roles(self) -> Self:
        refs = [*self.assessed_artifact_refs, *self.reference_artifact_refs]
        if len({ref.artifact_version_id for ref in refs}) != len(refs):
            raise ValueError("assessment roles must be unique and disjoint")
        return self


class ExitGateSpecification(Contract):
    schema_version: Literal["1", "2"]
    assessment_scope: PilotDeliveryAssessment | None = None
    gate_id: Text
    gate_type: Literal["research_delivery", "investment_promotion"]
    required_deliverables: list[DeliverableRequirement] = Field(min_length=1)
    protocol_refs: list[Text]
    required_checks: list[Text] = Field(min_length=1)
    reproducibility_criteria: list[Text] = Field(min_length=1)
    evidence_release_requirements: list[Text] = Field(min_length=1)
    allowed_conclusions: list[Conclusion] = Field(min_length=1)
    human_signoff_required: bool
    forward_evidence_required: bool
    independent_checker_required: Literal[True]
    frozen_at: AwareDatetime
    spec_hash: Sha256

    @model_validator(mode="after")
    def promotion_is_separate(self) -> Self:
        if (self.schema_version == "2") != (self.assessment_scope is not None):
            raise ValueError("gate version 2 requires explicit artifact assessment roles")
        if self.schema_version == "2" and self.gate_type != "research_delivery":
            raise ValueError("explicit pilot assessment is research delivery only")
        if self.gate_type == "investment_promotion" and (
            not self.human_signoff_required or not self.forward_evidence_required
        ):
            raise ValueError("promotion requires forward evidence and human sign-off")
        return self

    @model_serializer(mode="wrap")
    def preserve_legacy_gate(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        value: dict[str, Any] = handler(self)
        if self.schema_version == "1":
            value.pop("assessment_scope", None)
        return value


class DecisionCycle(Contract):
    name: Text
    signal_date_rule: Text
    publication_rule: Text
    execution_rule: Text
    review_rule: Text | None


class SelectionRule(Contract):
    fraction: float | None = Field(default=None, gt=0, le=1)
    top_n: PositiveInt | None = None
    rounding: Literal["ceil", "floor", "exact_count"]
    tie_break: Text
    weighting: Text

    @model_validator(mode="after")
    def one_selection_basis(self) -> Self:
        if (self.fraction is None) == (self.top_n is None):
            raise ValueError("select either a fraction or a fixed count")
        return self


class BriefBudgets(Contract):
    authorized_spend_ref: Text | None
    authorized_cost_usd: NonNegativeFloat | None
    token_limit: PositiveInt | None
    concurrency_limit: PositiveInt | None
    max_wall_clock_seconds: PositiveInt | None
    max_generations: PositiveInt | None
    evaluator_quota_ref: Text


class ResearchBrief(Contract):
    schema_version: Literal["1"]
    brief_id: Text
    project_id: Text
    input_bundle_id: Text
    objective: Text
    universe_codes: list[Text]
    universe_label_map_ref: Text | None
    benchmarks: list[Text]
    primary_benchmark: Text | None
    decision_cycles: list[DecisionCycle]
    selection_rule: SelectionRule | None
    eligibility_rule_ref: Text | None
    primary_metric: Text | None
    secondary_metrics: list[Text]
    cost_levels_bps: list[NonNegativeFloat]
    protocol_proposal_ref: Text | None
    exposure: ExposureAndQuality
    baseline_artifact_ids: list[Text]
    preservation_rules: list[Text]
    constraints: list[Text]
    success_criteria: list[Text]
    budgets: BriefBudgets
    exit_gate: ExitGateSpecification
    role_profiles: list[Text]
    human_checkpoints: list[Text]
    frozen_config_hash: Sha256

    @model_validator(mode="after")
    def benchmark_declared(self) -> Self:
        if self.primary_benchmark is not None and self.primary_benchmark not in self.benchmarks:
            raise ValueError("primary benchmark is absent from benchmark list")
        return self


class ReceiptReference(Contract):
    receipt_id: Text
    job_id: Text
    gate_spec_hash: Sha256
    result: Literal["pass", "fail"]
    independent_checker: Text
    receipt_sha256: Sha256
    signature_verified: bool


class JobRecord(Contract):
    schema_version: Literal["1"]
    job_id: Text
    project_id: Text
    idempotency_key: Text
    payload_hash: Sha256
    input_bundle_id: Text
    brief_id: Text
    config_hash: Sha256
    provider_profiles_ref: Text
    public_protocol_card_ref: Text | None
    authorized_spend_ref: Text | None
    exit_gate: ExitGateSpecification
    state: JobState
    generation_id: Text | None
    evaluator_status_ref: Text | None
    checkpoint_refs: list[Text]
    reason: (
        Literal[
            "blocked_on_data",
            "required_input_missing",
            "budget_exhausted",
            "outcome_unknown",
            "operator_pause",
            "internal_error",
        ]
        | None
    )
    receipt: ReceiptReference | None
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @model_validator(mode="after")
    def completed_requires_independent_receipt(self) -> Self:
        if self.updated_at < self.created_at:
            raise ValueError("updated_at precedes created_at")
        if self.state == JobState.COMPLETED:
            receipt = self.receipt
            if (
                receipt is None
                or receipt.result != "pass"
                or not receipt.signature_verified
                or receipt.job_id != self.job_id
                or receipt.gate_spec_hash != self.exit_gate.spec_hash
            ):
                raise ValueError("completed job requires its verified independent passing receipt")
            if self.reason is not None:
                raise ValueError("completed job cannot retain an unresolved blocking reason")
        if self.state == JobState.WAITING_FOR_DATA and self.reason != "blocked_on_data":
            raise ValueError("waiting_for_data requires blocked_on_data reason")
        return self
