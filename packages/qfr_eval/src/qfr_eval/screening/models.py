from typing import Literal, Self

from pydantic import Field, NonNegativeInt, PositiveInt, model_validator
from qfr_core.contracts.base import Contract, Sha256, Text
from qfr_core.contracts.enums import ReasonCode
from qfr_core.contracts.publication import RegistryClientConfiguration
from qfr_core.dsl.language import DSLConfig

from qfr_eval.backtest.prefix import PrefixCheck
from qfr_eval.records import RuntimeIdentity
from qfr_eval.sandbox.models import SandboxCode, SandboxProfileValue
from qfr_eval.scheduler.models import IntakeCampaign, IntakePolicy, PilotScreeningPolicy


class ScreeningExecutionPolicy(Contract):
    schema_version: Literal["1"]
    policy_id: Text
    revision: PositiveInt
    source_bytes: PositiveInt
    source_ast_nodes: PositiveInt
    allowed_import_roots: list[Text]
    forbidden_calls: list[Text]
    forbidden_attributes: list[Text]
    note_bytes: PositiveInt
    document_rows: PositiveInt
    worker_lease_seconds: PositiveInt
    lease_renewal_seconds: PositiveInt
    perturbation: Literal["scale_future_finite_float_values"]
    future_numeric_scale: float = Field(ge=0.875, le=0.875)
    lookahead_label: Literal["lookahead tested, not certified"]

    @model_validator(mode="after")
    def operational_lease(self) -> Self:
        if self.lease_renewal_seconds * 3 > self.worker_lease_seconds:
            raise ValueError("worker lease needs bounded renewal headroom")
        return self


class KindAdapterProfile(Contract):
    """Explicit supported output conventions, never stock admission thresholds."""

    schema_version: Literal["1"]
    profile_id: Text
    revision: PositiveInt
    scope: Literal["P0_P1_verification_only", "synthetic_contract_fixtures_only"]
    adapter: Literal["pilot_rotation_v1", "price_panel_v1"]
    warmup: Literal["original_pilot_eligibility", "declared_source_observations"]
    strategy_cost_bps: NonNegativeInt
    strategy_execution: Literal["next_close"]
    strategy_cost_policy_ref: Text
    data_product_check: Literal["identity-prices/1"]

    @model_validator(mode="after")
    def separated_profiles(self) -> Self:
        if (self.adapter == "pilot_rotation_v1") != (self.scope == "P0_P1_verification_only"):
            raise ValueError("pilot and synthetic adapter scopes cannot be exchanged")
        if (self.adapter == "pilot_rotation_v1") != (self.warmup == "original_pilot_eligibility"):
            raise ValueError("adapter must preserve its declared eligibility convention")
        return self


class CausalityEvidence(Contract):
    schema_version: Literal["1"]
    status: Literal["passed", "failed", "insufficient_data"]
    code: SandboxCode | Literal["failed:lookahead", "failed:nondeterministic", "insufficient_data"]
    output_sha256: Sha256 | None
    deterministic: bool | None
    prefix_passed: bool | None
    perturbation_passed: bool | None
    prefix: list[PrefixCheck]
    perturbation: list[PrefixCheck]
    label: Literal["lookahead tested, not certified"]

    @model_validator(mode="after")
    def evidence_before_pass(self) -> Self:
        if self.status == "passed" and (
            self.code != "ok"
            or self.deterministic is not True
            or self.output_sha256 is None
            or self.prefix_passed is not True
            or self.perturbation_passed is not True
            or not self.prefix
            or not self.perturbation
            or not sum(p.compared_cells for p in self.prefix)
            or not sum(p.compared_cells for p in self.perturbation)
        ):
            raise ValueError("causality pass requires actual deterministic nonempty comparisons")
        return self


class CoverageEvidence(Contract):
    schema_version: Literal["1"]
    status: Literal["passed", "failed", "insufficient_data"]
    reason_codes: list[ReasonCode]
    required_observations: NonNegativeInt
    complete_observations: NonNegativeInt
    scored_cross_sections: NonNegativeInt
    constant_cross_sections: NonNegativeInt
    fixed_position_exempt: bool
    diagnostics: list[Literal["some_constant_cross_sections"]]

    @model_validator(mode="after")
    def complete_before_pass(self) -> Self:
        if self.complete_observations > self.required_observations:
            raise ValueError("coverage cannot exceed the original eligible grid")
        if self.constant_cross_sections > self.scored_cross_sections:
            raise ValueError("constant cross-sections exceed the scored grid")
        if self.status == "passed" and (
            not self.required_observations
            or self.reason_codes
            or self.complete_observations != self.required_observations
            or (
                self.scored_cross_sections > 0
                and self.scored_cross_sections == self.constant_cross_sections
                and not self.fixed_position_exempt
            )
        ):
            raise ValueError("missing or completely degenerate observations cannot pass")
        return self


class ScreeningSessionConfiguration(Contract):
    """Private owner-supplied configuration, without embedded credentials."""

    schema_version: Literal["1"]
    campaign: IntakeCampaign
    intake_policy: IntakePolicy
    screening_policy: PilotScreeningPolicy
    execution_policy: ScreeningExecutionPolicy
    adapter_profiles: dict[Literal["pilot_industry_v1", "generic"], KindAdapterProfile]
    registry_client: RegistryClientConfiguration
    dsl_configs: dict[Literal["pilot_industry_v1", "stock_daily_v1"], DSLConfig]
    protocol_version: Text
    runtime: RuntimeIdentity
    sandbox_profile: SandboxProfileValue | None
    sandbox_image_digest: Sha256 | None

    @model_validator(mode="after")
    def explicit_backend_pair(self) -> Self:
        if (self.sandbox_profile is None) != (self.sandbox_image_digest is None):
            raise ValueError("sandbox profile and immutable image must be supplied together")
        return self
