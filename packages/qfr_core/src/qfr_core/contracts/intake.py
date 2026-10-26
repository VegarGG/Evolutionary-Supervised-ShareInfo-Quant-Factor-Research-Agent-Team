"""Generic intake preserves semantic kinds without fabricating runnable inputs."""

from typing import Annotated, Literal, Self

from pydantic import Field, NonNegativeFloat, NonNegativeInt, PositiveInt, model_validator

from qfr_core.contracts.base import Contract, Sha256, Text
from qfr_core.contracts.data import DataRequirement, ExposureAndQuality, SourceAsset
from qfr_core.contracts.enums import InputKind


class ResourceLimits(Contract):
    cpu_seconds: PositiveInt
    memory_bytes: PositiveInt
    timeout_seconds: PositiveInt
    max_output_bytes: PositiveInt
    network: Literal["none"]
    read_only_root: Literal[True]
    non_root: Literal[True]
    dropped_capabilities: Literal["ALL"]


class ExecutionContract(Contract):
    runner: Text
    image_digest: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    dependency_lock_sha256: Sha256
    interface: Literal["command", "function"]
    command: list[Text] | None
    function: Text | None
    input_schema_ref: Text
    output_schema_ref: Text
    seeds: list[NonNegativeInt] = Field(min_length=1)
    limits: ResourceLimits
    approved_sandbox_profile_ref: Text

    @model_validator(mode="after")
    def declared_interface(self) -> Self:
        if self.interface == "command" and (not self.command or self.function is not None):
            raise ValueError("command interface requires command only")
        if self.interface == "function" and (not self.function or self.command is not None):
            raise ValueError("function interface requires function only")
        return self


class IdeaDefinition(Contract):
    kind: Literal["idea"]
    hypothesis: Text
    unresolved_questions: list[Text]


class FactorDefinition(Contract):
    kind: Literal["factor"]
    formula: Text
    representation: Literal["dsl", "constrained_python", "natural_language"]
    output_schema_ref: Text | None


class ModelDefinition(Contract):
    kind: Literal["model"]
    specification: Text
    weight_asset_ids: list[Text]
    preprocessing: Text
    fallback_logic: Text
    fit_interface: Text | None
    inference_interface: Text | None
    serialization: Text | None


class StrategyDefinition(Contract):
    kind: Literal["strategy"]
    rules: Text
    position_state: Text
    cost_rules: Text | None
    rebalance_timing: Text | None


class BundleDefinition(Contract):
    kind: Literal["bundle"]
    component_asset_ids: list[Text] = Field(min_length=1)
    inventory_ref: Text
    preservation_rules: list[Text] = Field(min_length=1)


Definition = Annotated[
    IdeaDefinition | FactorDefinition | ModelDefinition | StrategyDefinition | BundleDefinition,
    Field(discriminator="kind"),
]


class IntakeJobConfig(Contract):
    role_profile_refs: list[Text]
    permitted_dataset_ids: list[Text]
    permitted_provider_endpoints: list[Text]
    authorized_spend_ref: Text | None
    authorized_cost_usd: NonNegativeFloat | None
    max_wall_clock_seconds: PositiveInt | None
    max_generations: PositiveInt | None
    stop_pause_policy_ref: Text
    proposed_exit_gate_ref: Text | None
    human_checkpoint_policy_ref: Text


class InputBundle(Contract):
    schema_version: Literal["1"]
    bundle_id: Text
    input_kind: InputKind
    objective: Text
    requested_deliverables: list[Text] = Field(min_length=1)
    source_assets: list[SourceAsset]
    definition: Definition
    data_refs: list[Text]
    data_requirements: list[DataRequirement]
    baseline_refs: list[Text]
    execution_contract: ExecutionContract | None
    exposure_and_quality: ExposureAndQuality
    job_config: IntakeJobConfig
    protocol_proposal_ref: Text | None
    readiness: Literal["needs_input", "waiting_for_data", "ready"]
    unresolved_requirements: list[Text]

    @model_validator(mode="after")
    def kind_and_readiness(self) -> Self:
        if self.input_kind.value != self.definition.kind:
            raise ValueError("input_kind differs from definition kind")
        if self.input_kind == InputKind.IDEA and self.execution_contract is not None:
            raise ValueError("an idea must not have a fabricated execution contract")
        if self.readiness == "ready":
            if self.unresolved_requirements or any(r.unresolved for r in self.data_requirements):
                raise ValueError("ready input has unresolved requirements")
            if not self.data_refs:
                raise ValueError("ready input requires authorized data references")
            if self.input_kind != InputKind.IDEA and self.execution_contract is None:
                raise ValueError("ready executable input requires an execution contract")
        ids = [a.asset_id for a in self.source_assets]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate source asset ids")
        if isinstance(self.definition, BundleDefinition):
            if not set(self.definition.component_asset_ids) <= set(ids):
                raise ValueError("bundle component assets are unresolved")
        return self
