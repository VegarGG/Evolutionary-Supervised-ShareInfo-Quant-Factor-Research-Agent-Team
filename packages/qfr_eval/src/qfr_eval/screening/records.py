"""Private quality-screen records; no fabricated financial sampling unit."""

import hashlib
from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, NonNegativeInt, model_validator
from qfr_core.contracts.base import Contract, Sha256, Text
from qfr_core.contracts.enums import ArtifactKind, ReasonCode
from qfr_core.contracts.reports import EvidenceIdentity
from qfr_core.data_layer.snapshots import canonical_json

from qfr_eval.records import RuntimeIdentity, StoredFile
from qfr_eval.screening.models import CausalityEvidence, CoverageEvidence


class ScreeningOutcome(Contract):
    schema_version: Literal["1"]
    kind: ArtifactKind
    execution: Literal["dsl", "sandbox", "document"]
    status: Literal["passed", "failed", "insufficient_data"]
    reason_codes: list[ReasonCode]
    coverage: CoverageEvidence | None
    causality: CausalityEvidence | None
    output_sha256: Sha256 | None
    document_checks: dict[
        Literal["schema", "citations", "released_values", "temporal"],
        Literal["pass", "fail", "insufficient_data", "not_applicable"],
    ]

    @model_validator(mode="after")
    def passing_evidence(self) -> Self:
        if self.status == "passed":
            if self.reason_codes:
                raise ValueError("a passing screen cannot have a failure code")
            if self.execution == "document":
                if (
                    not self.document_checks
                    or self.kind not in (ArtifactKind.RESEARCH_NOTE, ArtifactKind.DATA_PRODUCT)
                    or any(
                        v not in ("pass", "not_applicable") for v in self.document_checks.values()
                    )
                ):
                    raise ValueError("a passing document requires deterministic quality evidence")
            elif (
                self.coverage is None
                or self.coverage.status != "passed"
                or self.causality is None
                or self.causality.status != "passed"
                or self.output_sha256 is None
                or self.output_sha256 != self.causality.output_sha256
            ):
                raise ValueError("a passing executable requires complete actual output evidence")
        return self

    @property
    def sha256(self) -> str:
        return hashlib.sha256(canonical_json(self.model_dump(mode="json"))).hexdigest()


class ScreeningRequest(Contract):
    schema_version: Literal["1"]
    stage: Literal["screening"]
    window: Literal["development"]
    intake_id: UUID
    campaign_id: UUID
    artifact_version_id: UUID
    content_hash: Sha256
    program_id: Text
    family_id: Text
    protocol_id: Text
    protocol_version: Text
    protocol_hash: Sha256
    snapshot_id: Sha256
    screening_policy_hash: Sha256
    execution_policy_hash: Sha256
    adapter_profile_hash: Sha256
    development_input_sha256: Sha256
    probe_input_sha256: Sha256 | None
    runtime: RuntimeIdentity
    runner_image_digest: Sha256 | None
    generation_id: Text

    @property
    def sha256(self) -> str:
        return hashlib.sha256(canonical_json(self.model_dump(mode="json"))).hexdigest()


class ScreeningRecord(Contract):
    schema_version: Literal["1"]
    stage: Literal["screening"]
    record_id: UUID
    trial_id: UUID
    identity: EvidenceIdentity
    request: ScreeningRequest
    request_hash: Sha256
    outcome: ScreeningOutcome
    results_hash: Sha256
    feedback_disposition: Literal["eligible", "withheld:budget"]
    created_by: Text
    request_id: UUID
    created_at: AwareDatetime

    @model_validator(mode="after")
    def pinned(self) -> Self:
        if self.results_hash != self.outcome.sha256 or self.request_hash != self.request.sha256:
            raise ValueError("screening record hash differs from its typed evidence")
        if (
            self.identity.artifact_version_id != str(self.request.artifact_version_id)
            or self.identity.content_hash != self.request.content_hash
            or self.identity.dataset_version_id != self.request.snapshot_id
            or self.identity.evaluator_version != self.request.runtime.evaluator_git_sha
            or self.identity.protocol_version
            != f"{self.request.protocol_id}@{self.request.protocol_version}"
        ):
            raise ValueError("screening record identity differs from its request")
        return self


class ScreeningTrial(Contract):
    schema_version: Literal["1"]
    stage: Literal["screening"]
    trial_id: UUID
    official_record_id: UUID
    identity: EvidenceIdentity
    program_id: Text
    family_id: Text
    generation_id: Text
    window: Literal["development"]
    status: Literal["evaluated", "failed", "withheld"]
    sampling_unit: Literal["eligible_observation", "document"]
    required_observations: NonNegativeInt
    complete_observations: NonNegativeInt
    results_hash: Sha256
    counted_at: AwareDatetime


class ScreeningReceipt(Contract):
    schema_version: Literal["1"]
    kind: Literal["private_screening"]
    authenticity: Literal["internal_unsigned"]
    record_id: UUID
    trial_id: UUID
    identity: EvidenceIdentity
    request_hash: Sha256
    results_hash: Sha256
    files: dict[Text, StoredFile]
    receipt_hash: Sha256
