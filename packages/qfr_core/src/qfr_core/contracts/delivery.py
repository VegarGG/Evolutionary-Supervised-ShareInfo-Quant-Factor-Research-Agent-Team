"""Independent acceptance receipts and research-safe export manifests."""

from pathlib import PurePosixPath
from typing import Literal, Self

from pydantic import AwareDatetime, Field, NonNegativeInt, model_validator

from qfr_core.contracts.artifacts import ArtifactReference
from qfr_core.contracts.base import Contract, Sha256, Text
from qfr_core.contracts.enums import Conclusion
from qfr_core.contracts.reports import Signature


class VersionReference(Contract):
    reference_id: Text
    sha256: Sha256


class DeliveryCheck(Contract):
    check_id: Text
    schema_ref: Text
    result: Literal["pass", "fail"]
    evidence_refs: list[VersionReference] = Field(min_length=1)


class DeliveryReceipt(Contract):
    schema_version: Literal["1"]
    receipt_id: Text
    job_id: Text
    gate_spec_hash: Sha256
    artifact_refs: list[ArtifactReference]
    dataset_refs: list[VersionReference]
    protocol_refs: list[VersionReference]
    config_refs: list[VersionReference] = Field(min_length=1)
    released_report_refs: list[VersionReference]
    checks: list[DeliveryCheck] = Field(min_length=1)
    allowed_conclusions: list[Conclusion] = Field(min_length=1)
    conclusion: Conclusion
    result: Literal["pass", "fail"]
    independent_checker: Text
    human_signoff_ref: Text | None
    created_at: AwareDatetime
    signature: Signature

    @model_validator(mode="after")
    def supported_conclusion_and_checks(self) -> Self:
        if self.conclusion not in self.allowed_conclusions:
            raise ValueError("conclusion not permitted by the frozen gate")
        if self.result == "pass" and any(check.result != "pass" for check in self.checks):
            raise ValueError("passing delivery has a failed required check")
        return self


class ExportEntry(Contract):
    path: Text
    kind: Literal[
        "artifact_manifest",
        "artifact_payload",
        "source_manifest",
        "dataset_manifest",
        "public_protocol_card",
        "released_report",
        "configuration_reference",
        "provenance",
        "delivery_receipt",
    ]
    reference_id: Text
    sha256: Sha256
    bytes: NonNegativeInt

    @model_validator(mode="after")
    def safe_path(self) -> Self:
        if (
            PurePosixPath(self.path).is_absolute()
            or ".." in self.path.split("/")
            or "\\" in self.path
        ):
            raise ValueError("export path must be relative and confined")
        return self


class ExportManifest(Contract):
    schema_version: Literal["1"]
    export_id: Text
    job_id: Text
    receipt: VersionReference
    artifact_refs: list[ArtifactReference]
    files: list[ExportEntry] = Field(min_length=1)
    created_at: AwareDatetime
    source_config_hash: Sha256

    @model_validator(mode="after")
    def unique_paths_and_receipt(self) -> Self:
        if len({entry.path for entry in self.files}) != len(self.files):
            raise ValueError("duplicate export paths")
        if not any(
            entry.kind == "delivery_receipt"
            and entry.reference_id == self.receipt.reference_id
            and entry.sha256 == self.receipt.sha256
            for entry in self.files
        ):
            raise ValueError("export must include its exact delivery receipt")
        return self
