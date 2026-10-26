"""Private evaluator-owned intake contracts; never a research control surface."""

import hashlib
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, NonNegativeFloat, PositiveInt, model_validator
from qfr_core.contracts.base import Contract, Sha256, Text
from qfr_core.contracts.enums import ArtifactKind
from qfr_core.contracts.execution import RunnerTable
from qfr_core.data_layer.snapshots import canonical_json


class PilotScreeningPolicy(Contract):
    schema_version: Literal["1"]
    policy_id: Text
    revision: PositiveInt
    status: Literal["active"]
    scope: Literal["P0_P1_verification_only"]
    protocol_sha256: Sha256
    approval_ref: Text
    approved_proposal_sha256: Sha256
    duplicates: Literal["equivalent_development_outputs_all_declared_cycles"]
    required_eligible_coverage: Literal[1]
    reject_constant_scorer_fraction: Literal[1]
    fixed_position_strategy_exempt: Literal[True]
    score_atol: NonNegativeFloat
    score_rtol: NonNegativeFloat
    preserve_original_eligibility_and_warmup: Literal[True]
    feedback_versions_per_lineage_generation: Literal[3]

    @property
    def sha256(self) -> str:
        return hashlib.sha256(canonical_json(self.model_dump(mode="json"))).hexdigest()


class IntakePolicy(Contract):
    schema_version: Literal["1"]
    revision: PositiveInt
    page_size: PositiveInt = Field(le=100)
    max_ready_jobs_per_campaign: PositiveInt
    poll_interval_seconds: PositiveInt
    deferral_expiry_seconds: PositiveInt | None
    fairness: Literal["round_robin_family_fifo"]
    idle_behavior: Literal["no_poll_or_jobs"]


class IntakeCampaign(Contract):
    schema_version: Literal["1"]
    campaign_id: UUID
    active: bool
    owner_authorization_ref: Text
    program_ids: list[Text] = Field(min_length=1)
    protocol_ref: Text
    protocol_hash: Sha256
    snapshot_id: Sha256
    runtime_hash: Sha256
    screening_policy_hash: Sha256
    server_generation_id: Text
    allowed_kinds: list[ArtifactKind] = Field(min_length=1)
    # Owner binds first roots; descendants inherit. Missing roots wait for input.
    # Research-supplied generation/lineage/name fields never grant a fresh budget.
    root_lineages: dict[UUID, Text]

    @model_validator(mode="after")
    def unambiguous(self) -> Self:
        if len(self.program_ids) != len(set(self.program_ids)) or "*" in self.program_ids:
            raise ValueError("campaign requires distinct explicit programs")
        if len(self.allowed_kinds) != len(set(self.allowed_kinds)):
            raise ValueError("campaign kinds must be distinct")
        return self

    @property
    def sha256(self) -> str:
        return hashlib.sha256(canonical_json(self.model_dump(mode="json"))).hexdigest()


class DevelopmentBehavior(Contract):
    schema_version: Literal["1"]
    semantic_scope_sha256: Sha256
    complete_original_eligible_outputs: Literal[True]
    tables: dict[Text, RunnerTable] = Field(min_length=1)
    score_columns: dict[Text, list[Text]]

    @model_validator(mode="after")
    def declared_score_columns(self) -> Self:
        if self.score_columns.keys() != self.tables.keys():
            raise ValueError("behavior must declare score columns for every table")
        for name, columns in self.score_columns.items():
            if len(columns) != len(set(columns)) or not set(columns) <= set(
                self.tables[name].columns
            ):
                raise ValueError("behavior score columns are unresolved or repeated")
        return self
