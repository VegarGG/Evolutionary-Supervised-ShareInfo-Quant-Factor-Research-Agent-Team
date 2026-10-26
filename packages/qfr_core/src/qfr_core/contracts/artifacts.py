"""Common immutable publication shape and semantic payload specializations."""

from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, JsonValue, NonNegativeInt, PositiveInt, model_validator

from qfr_core.contracts.base import Contract, Sha256, Text
from qfr_core.contracts.data import DataRequirement, ExposureAndQuality
from qfr_core.contracts.enums import ArtifactKind
from qfr_core.contracts.intake import ExecutionContract
from qfr_core.contracts.providers import EffectiveTaskConfiguration


class ArtifactReference(Contract):
    artifact_version_id: Text
    content_hash: Sha256


class PayloadFile(Contract):
    asset_id: Text
    sha256: Sha256
    media_type: Text


class DSLImplementation(Contract):
    type: Literal["dsl"]
    language: Literal["qfr-dsl/1"]
    expression: Annotated[str, Field(min_length=1, max_length=1000)]


class PythonImplementation(Contract):
    type: Literal["constrained_python"]
    source_asset_id: Text
    entrypoint: Text
    execution_contract: ExecutionContract


class CompositeComponent(Contract):
    artifact: ArtifactReference
    weight: float


class CompositeImplementation(Contract):
    type: Literal["fixed_composite"]
    components: list[CompositeComponent] = Field(min_length=1)
    fitting: Literal[False]


class PackageImplementation(Contract):
    type: Literal["declared_package_runner"]
    package_asset_id: Text
    execution_contract: ExecutionContract


class DocumentImplementation(Contract):
    type: Literal["document"]
    asset_id: Text
    format: Literal["markdown", "json", "parquet", "csv"]


Implementation = Annotated[
    DSLImplementation
    | PythonImplementation
    | CompositeImplementation
    | PackageImplementation
    | DocumentImplementation,
    Field(discriminator="type"),
]


class MechanismCard(Contract):
    event: Text
    context: Text
    qualities: Text
    direction: Text
    output: Text


class Rationale(Contract):
    hypothesis_id: Text | None
    summary: Annotated[str, Field(min_length=1, max_length=1500)]
    mechanism: Annotated[str, Field(min_length=1, max_length=1500)]
    falsification: Annotated[str, Field(min_length=1, max_length=600)]
    change_summary: Annotated[str, Field(min_length=1, max_length=600)] | None


class FactorPayload(Contract):
    kind: Literal["factor"]
    expected_sign: Literal[-1, 1]
    horizon_days: PositiveInt
    fields_used: list[Text] = Field(min_length=1)
    max_lookback_days: NonNegativeInt
    formulation: Text
    mechanism_card: MechanismCard


class ModelPayload(Contract):
    kind: Literal["model"]
    specification: Text
    weight_asset_ids: list[Text]
    preprocessing: Text
    fallback_logic: Text
    fit_interface: Text | None
    inference_interface: Text
    serialization: Text
    training_dataset_refs: list[Text]


class StrategyPayload(Contract):
    kind: Literal["strategy"]
    signal_artifacts: list[ArtifactReference]
    position_state_rules: Text
    rebalance_timing: Text
    cost_policy_ref: Text
    execution_prices_ref: Text


class ResearchNotePayload(Contract):
    kind: Literal["research_note"]
    document_asset_id: Text
    citation_refs: list[Text]
    released_report_refs: list[Text]


class DataProductPayload(Contract):
    kind: Literal["data_product"]
    dataset_manifest_ref: Text
    output_schema_ref: Text
    deterministic_check_refs: list[Text] = Field(min_length=1)


ArtifactPayload = Annotated[
    FactorPayload | ModelPayload | StrategyPayload | ResearchNotePayload | DataProductPayload,
    Field(discriminator="kind"),
]


class Provenance(Contract):
    program_id: Text
    generation_id: Text | None
    island_id: Text | None
    task_id: Text | None
    operator: Literal[
        "explore",
        "llm_mutation",
        "syntactic_mutation",
        "crossover",
        "repair",
        "human_seed",
        "import",
    ]
    source_asset_ids: list[Text]
    source_hashes: list[Sha256]
    blackboard_refs: list[Text]
    agent_runs: list[EffectiveTaskConfiguration]
    research_snapshot_id: Text | None
    qfr_core_version: Text
    exposure: ExposureAndQuality
    dependency_lock_sha256: Sha256 | None


class ResearchChecks(Contract):
    official: Literal[False]
    dsl_validation: Literal["pass", "fail", "not_run", "not_applicable"]
    static_analysis: Literal["pass", "fail", "not_run", "not_applicable"]
    development_prefix_check: Literal["pass", "fail", "not_run", "not_applicable"]
    evidence_refs: list[Text]
    critic_verdict_id: Text | None
    review_rounds: NonNegativeInt


class ArtifactDefinition(Contract):
    """Publication input without invented server identities or audit timestamps."""

    schema_version: Literal["1"]
    family_id: Text | None
    parent_version_ids: list[Text]
    name: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")]
    title: Annotated[str, Field(min_length=1, max_length=120)]
    kind: ArtifactKind
    implementation: Implementation
    payload: ArtifactPayload
    payload_files: list[PayloadFile]
    parameters: dict[Text, JsonValue]
    data_requirements: list[DataRequirement]
    eligible_protocols: list[Text] = Field(min_length=1)
    cycles: list[Text]
    output_schema_ref: Text
    rationale: Rationale
    complexity: NonNegativeInt
    provenance: Provenance
    research_side_checks: ResearchChecks

    @model_validator(mode="after")
    def semantic_kind_and_lineage(self) -> Self:
        if self.kind.value != self.payload.kind:
            raise ValueError("manifest kind differs from semantic payload")
        if self.parent_version_ids and self.rationale.change_summary is None:
            raise ValueError("a revised artifact requires a change summary")
        if self.kind == ArtifactKind.RESEARCH_NOTE:
            if not isinstance(self.implementation, DocumentImplementation):
                raise ValueError("research notes use document representation")
        elif (
            isinstance(self.implementation, DocumentImplementation)
            and self.kind != ArtifactKind.DATA_PRODUCT
        ):
            raise ValueError("executable artifact requires a declared implementation")
        if isinstance(self.implementation, DSLImplementation) and self.kind != ArtifactKind.FACTOR:
            raise ValueError("DSL representation is a factor specialization")
        if (
            self.provenance.operator in ("human_seed", "import")
            and not self.provenance.source_hashes
        ):
            raise ValueError("human/import artifacts require source provenance")
        return self


class ArtifactManifest(ArtifactDefinition):
    artifact_version_id: Text
    artifact_id: Text
    content_hash: Sha256
    implementation_fingerprint: Sha256
    canonical_fingerprint: Sha256 | None
    created_at: AwareDatetime
    created_by: Text

    @model_validator(mode="after")
    def no_self_parent(self) -> Self:
        if self.artifact_version_id in self.parent_version_ids:
            raise ValueError("artifact cannot be its own parent")
        return self
