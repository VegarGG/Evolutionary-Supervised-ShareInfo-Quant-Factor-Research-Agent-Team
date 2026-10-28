"""Versioned private checker configuration, separate from measurement policy."""

from typing import Literal, Self

from pydantic import Field, PositiveInt, model_validator
from qfr_core.contracts.access import ProgramId, PublicServiceClientConfiguration
from qfr_core.contracts.base import Contract, Sha256
from qfr_core.contracts.publication import RegistryClientConfiguration


class PilotDeliveryPolicy(Contract):
    schema_version: Literal["1", "2", "3"]
    checker_id: Literal[
        "pilot-research-delivery-v1", "pilot-research-delivery-v2", "pilot-research-delivery-v3"
    ]
    scope: Literal["P0_P1_verification_only"]
    release_policy_sha256: Sha256
    required_execution: Literal["registry"]
    reproduction: Literal["immutable_evaluator_exact_match_event"]
    negative_meaning: Literal["declared_scope_does_not_meet_frozen_research_hurdle"]
    maximum_artifacts: PositiveInt = Field(le=1000)
    maximum_reports: PositiveInt = Field(le=1000)
    maximum_payload_bytes: PositiveInt

    @model_validator(mode="after")
    def versioned_binding(self) -> Self:
        if self.checker_id != "pilot-research-delivery-v" + self.schema_version:
            raise ValueError("delivery checker version and identity differ")
        return self


class DeliveryWorkerConfiguration(Contract):
    schema_version: Literal["1"]
    program_id: ProgramId
    research_client: PublicServiceClientConfiguration
    registry_client: RegistryClientConfiguration
    policy: PilotDeliveryPolicy
