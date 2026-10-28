"""Versioned private checker configuration, separate from measurement policy."""

from typing import Literal

from pydantic import Field, PositiveInt
from qfr_core.contracts.access import ProgramId, PublicServiceClientConfiguration
from qfr_core.contracts.base import Contract, Sha256
from qfr_core.contracts.publication import RegistryClientConfiguration


class PilotDeliveryPolicy(Contract):
    schema_version: Literal["1"]
    checker_id: Literal["pilot-research-delivery-v1"]
    scope: Literal["P0_P1_verification_only"]
    release_policy_sha256: Sha256
    required_execution: Literal["registry"]
    reproduction: Literal["immutable_evaluator_exact_match_event"]
    negative_meaning: Literal["declared_scope_does_not_meet_frozen_research_hurdle"]
    maximum_artifacts: PositiveInt = Field(le=1000)
    maximum_reports: PositiveInt = Field(le=1000)
    maximum_payload_bytes: PositiveInt


class DeliveryWorkerConfiguration(Contract):
    schema_version: Literal["1"]
    program_id: ProgramId
    research_client: PublicServiceClientConfiguration
    registry_client: RegistryClientConfiguration
    policy: PilotDeliveryPolicy
