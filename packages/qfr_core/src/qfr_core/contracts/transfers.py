"""Data-only quarantine transport; readiness does not authorize execution or ingest."""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, NonNegativeInt, PositiveInt, model_validator

from qfr_core.contracts.base import Contract, Sha256, Text
from qfr_core.contracts.data import AssetReference, SourceAsset
from qfr_core.contracts.research import OperationKey


class IntakeTransportPolicy(Contract):
    revision: PositiveInt
    max_metadata_bytes: PositiveInt
    chunk_bytes: PositiveInt
    max_upload_bytes: PositiveInt
    max_uploads_per_program: PositiveInt
    max_reserved_bytes_per_program: PositiveInt
    max_archive_entries: PositiveInt
    max_archive_directory_bytes: PositiveInt
    max_expanded_bytes: PositiveInt
    max_member_bytes: PositiveInt
    request_timeout_seconds: PositiveInt
    sqlite_timeout_seconds: PositiveInt
    media_types: list[Text] = Field(min_length=1)


class UploadDeclaration(Contract):
    operation_key: OperationKey
    asset_id: Text
    sha256: Sha256
    bytes: NonNegativeInt
    media_type: Text
    provenance: Text
    intended_use: Literal[
        "primary_data",
        "auxiliary_data",
        "code",
        "config",
        "documentation",
        "evidence",
        "operations_precedent",
    ]
    licence: Text
    source_is_untrusted_data: Literal[True]


class MountedImportRequest(Contract):
    declaration: UploadDeclaration
    mount_id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")]
    relative_path: Text

    @model_validator(mode="after")
    def confined(self) -> Self:
        AssetReference(
            transport="mounted_import", reference_id=self.mount_id, relative_path=self.relative_path
        )
        if any(part in {"", ".", ".."} for part in self.relative_path.split("/")):
            raise ValueError("import path must name a confined regular file")
        return self


class UploadStatus(Contract):
    upload_id: UUID
    program_id: UUID
    state: Literal["staging", "validated", "rejected"]
    bytes_received: NonNegativeInt
    expected_bytes: NonNegativeInt
    chunk_bytes: PositiveInt
    source: SourceAsset | None
    validation: Literal["transport_only"]
    execution_authorized: Literal[False]
    created_at: AwareDatetime


class FinalizeUpload(Contract):
    sha256: Sha256


class AssetPage(Contract):
    items: list[UploadStatus]
    next_after_id: UUID | None
    has_more: bool
