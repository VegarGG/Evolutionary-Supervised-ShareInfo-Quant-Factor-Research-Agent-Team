"""Public human-driven research operations; no evaluation administration."""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, JsonValue, PositiveInt, model_validator

from qfr_core.contracts.artifacts import ArtifactReference
from qfr_core.contracts.base import Contract, Sha256, Text
from qfr_core.contracts.blackboard import BlackboardRecord, ResearchProgram
from qfr_core.contracts.delivery import DeliveryProposal
from qfr_core.contracts.intake import InputBundle
from qfr_core.contracts.jobs import JobRecord, ResearchBrief

OperationKey = Annotated[str, Field(min_length=1, max_length=200)]
NextAction = Literal[
    "start",
    "manual_research",
    "poll_released_feedback",
    "request_delivery_check",
    "export",
    "supply_new_intent",
    "register_data",
    "resume",
    "budget_authorization",
    "inspect_failure",
    "none",
]


class ResearchApiPolicy(Contract):
    revision: PositiveInt
    max_request_bytes: PositiveInt
    request_body_timeout_seconds: PositiveInt
    max_page_size: PositiveInt
    max_page_bytes: PositiveInt
    max_artifacts: PositiveInt
    max_source_assets: PositiveInt
    max_export_bytes: PositiveInt
    max_export_files: PositiveInt
    max_export_metadata_bytes: PositiveInt
    polling_seconds: PositiveInt
    statement_timeout_ms: PositiveInt
    lock_timeout_ms: PositiveInt
    trusted_delivery_checkers: dict[Text, Sha256] = Field(min_length=1)


class ProgramCreate(Contract):
    program_id: UUID
    name: Text
    charter: dict[str, JsonValue]


class ProgramPage(Contract):
    items: list[ResearchProgram]
    next_after_id: UUID | None
    has_more: bool


class DatasetRegistrationRequest(Contract):
    registration_id: Sha256


class BaselineRegistrationRequest(Contract):
    artifact: ArtifactReference


class ProtocolProposal(Contract):
    proposal_id: UUID
    program_id: UUID
    objective: Text
    constraints: list[Text]
    proposed_public_card_ref: Text | None
    authoritative: Literal[False]


class JobAdmission(Contract):
    idempotency_key: OperationKey
    input_bundle: InputBundle
    brief: ResearchBrief


class InputValidation(Contract):
    readiness: Literal["needs_input", "waiting_for_data", "ready"]
    unresolved_requirements: list[Text]
    data_refs_verified: list[Text]
    baseline_refs_verified: list[Text]
    source_assets_verified: list[Text]
    runnable: bool


class JobStatus(Contract):
    job: JobRecord
    revision: PositiveInt
    next_action: NextAction
    polling_seconds: PositiveInt


class JobPage(Contract):
    items: list[JobStatus]
    next_after_id: UUID | None
    has_more: bool


class JobControl(Contract):
    operation_key: OperationKey
    expected_revision: PositiveInt
    action: Literal["start", "await_evaluation", "pause", "resume", "cancel"]


class DeliveryProposalRequest(Contract):
    operation_key: OperationKey
    expected_revision: PositiveInt
    proposal: DeliveryProposal


class DeliveryReceiptRequest(Contract):
    operation_key: OperationKey
    expected_revision: PositiveInt
    receipt_id: UUID
    proposal_id: UUID


class HumanCheckpointRequest(Contract):
    checkpoint_id: UUID
    kind: Literal["clarification", "delivery_approval"]
    question: Text
    proposal_id: UUID | None

    @model_validator(mode="after")
    def approval_binds_proposal(self) -> Self:
        if (self.kind == "delivery_approval") != (self.proposal_id is not None):
            raise ValueError("only delivery approval must bind a proposal")
        return self


class HumanCheckpointAnswer(Contract):
    operation_key: OperationKey
    answer: Text
    decision: Literal["approve", "reject"] | None


class HumanCheckpointRecord(Contract):
    request: HumanCheckpointRequest
    job_id: UUID
    state: Literal["open", "answered"]
    created_by: Text
    created_at: AwareDatetime
    answer: HumanCheckpointAnswer | None
    answered_by: Text | None
    answered_at: AwareDatetime | None


class BlackboardPage(Contract):
    items: list[BlackboardRecord]
    next_after_id: UUID | None
    has_more: bool


class DeliveryExportRequest(Contract):
    operation_key: OperationKey
    shortlist_only: bool


class DeliveryExportReference(Contract):
    export_id: UUID
    job_id: UUID
    manifest_sha256: Sha256
    archive_sha256: Sha256
    archive_bytes: PositiveInt
    download_path: Text
