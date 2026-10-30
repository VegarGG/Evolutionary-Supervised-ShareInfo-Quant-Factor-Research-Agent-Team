"""Intake references and independently labelled data quality."""

from datetime import date
from pathlib import PurePosixPath
from typing import Literal, Self

from pydantic import Field, NonNegativeInt, model_validator

from qfr_core.contracts.access import ProgramId
from qfr_core.contracts.base import Contract, Sha256, Text
from qfr_core.contracts.enums import PITGrade


class AssetReference(Contract):
    transport: Literal["finalized_upload", "mounted_import"]
    reference_id: Text
    relative_path: Text | None = None

    @model_validator(mode="after")
    def relative_only(self) -> Self:
        path = self.relative_path
        if path is not None and (
            PurePosixPath(path).is_absolute()
            or ".." in path.split("/")
            or "\\" in path
            or ":" in path
            or "\x00" in path
        ):
            raise ValueError("asset path must stay inside its declared import/upload reference")
        return self


class SourceAsset(Contract):
    asset_id: Text
    reference: AssetReference
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


class DateRange(Contract):
    start: date
    end: date

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.end < self.start:
            raise ValueError("date range end precedes start")
        return self


class QualityLabels(Contract):
    timing_grade: PITGrade
    timing_basis: Text
    vintage_status: Literal["verified", "unknown", "restated"]
    vintage_notes: Text
    membership_grade: PITGrade | None
    membership_status: Literal["point_in_time", "backfilled", "unknown", "not_applicable"]
    membership_notes: Text

    @model_validator(mode="after")
    def backfill_is_not_clean(self) -> Self:
        if self.membership_status == "backfilled" and self.membership_grade != PITGrade.D:
            raise ValueError("backfilled membership must retain grade D")
        return self


class ExposureAndQuality(Contract):
    history: Literal["previously_seen", "unknown", "prospective"]
    inspected_periods: list[DateRange]
    training_tuning_history: Text
    provider_knowledge_exposure: Literal["known", "unknown"]
    quality: QualityLabels
    licence_constraints: list[Text]
    unknowns: list[Text]


class DataRequirement(Contract):
    table: Text
    fields: list[Text] = Field(min_length=1)
    universe: Text
    frequency: Text
    availability_rule: Text | None
    minimum_timing_grade: PITGrade | None
    lookback: NonNegativeInt | None
    unresolved: list[Text]


class DatasetTable(Contract):
    name: Text
    path: Text
    physical_sha256: Sha256
    logical_sha256: Sha256
    logical_hash_spec: Text
    rows: NonNegativeInt
    columns: list[Text] = Field(min_length=1)
    date_range: DateRange | None
    date_column: Text | None
    grain: list[Text] = Field(min_length=1)
    schema_ref: Text
    quality: QualityLabels
    licence_note: Text
    source_description: Text
    source_asset_ids: list[Text]

    @model_validator(mode="after")
    def column_identity(self) -> Self:
        if len(self.columns) != len(set(self.columns)):
            raise ValueError("duplicate column names")
        if not set(self.grain) <= set(self.columns):
            raise ValueError("grain columns absent from table")
        if self.date_column is not None and self.date_column not in self.columns:
            raise ValueError("date column absent from table")
        if (self.date_range is None) != (self.date_column is None):
            raise ValueError("date range and date column must be declared together")
        return self


class DatasetManifest(Contract):
    schema_version: Literal["1"]
    dataset_version_id: Text
    manifest_sha256: Sha256
    as_of: date
    creator: Text
    parent_dataset_version_id: Text | None
    change_log: list[Text]
    tables: list[DatasetTable] = Field(min_length=1)
    exposure: ExposureAndQuality

    @model_validator(mode="after")
    def table_names_unique(self) -> Self:
        if len({t.name for t in self.tables}) != len(self.tables):
            raise ValueError("dataset table names must be unique")
        return self


class SnapshotFile(Contract):
    path: str = Field(pattern=r"^[A-Za-z0-9_=/.-]+$")
    physical_sha256: Sha256
    bytes: NonNegativeInt

    @model_validator(mode="after")
    def safe_path(self) -> Self:
        if PurePosixPath(self.path).is_absolute() or ".." in self.path.split("/"):
            raise ValueError("snapshot file must be relative and contained")
        return self


class SnapshotTable(Contract):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    files: list[SnapshotFile] = Field(min_length=1)
    columns: dict[str, str] = Field(min_length=1)
    grain: list[Text] = Field(min_length=1)
    date_column: Text | None
    available_date_column: Text | None
    rows: NonNegativeInt
    logical_sha256: Sha256
    logical_hash_spec: Literal["qfr-table/1:sorted-grain,sorted-columns,float-hex,null"]
    quality: QualityLabels
    licence_note: Text
    source_hashes: dict[str, Sha256]
    research_visible: bool = True

    @model_validator(mode="after")
    def valid_columns(self) -> Self:
        keys = self.grain + [x for x in [self.date_column, self.available_date_column] if x]
        if not set(keys) <= self.columns.keys() or len(set(self.grain)) != len(self.grain):
            raise ValueError("invalid snapshot keys or date columns")
        return self


class SnapshotManifest(Contract):
    schema_version: Literal["1"]
    snapshot_id: Sha256
    profile: Text
    zone: Literal["research", "full"]
    research_cutoff: date | None
    as_of: date
    source: Text
    release_tag: Text | None
    archive_sha256: Sha256 | None
    build_code_version: Text
    conventions: dict[str, str]
    tables: list[SnapshotTable] = Field(min_length=1)
    exposure: ExposureAndQuality

    @model_validator(mode="after")
    def valid_zone(self) -> Self:
        if (self.zone == "research") != (self.research_cutoff is not None):
            raise ValueError("only research snapshots require a research cutoff")
        if self.research_cutoff is not None and self.as_of > self.research_cutoff:
            raise ValueError("research as_of exceeds cutoff")
        if self.zone == "research" and any(not table.research_visible for table in self.tables):
            raise ValueError("private table in research snapshot")
        names = [table.name for table in self.tables]
        paths = [file.path for table in self.tables for file in table.files]
        if len(set(names)) != len(names) or len(set(paths)) != len(paths):
            raise ValueError("duplicate snapshot tables or files")
        return self


class ResearchDatasetRegistration(Contract):
    """Trusted ingest catalog: opaque evaluator ID plus authorized research metadata."""

    schema_version: Literal["1"]
    registration_id: Sha256
    program_id: ProgramId
    dataset_version_id: Sha256
    source_ref: Text
    research_manifest: SnapshotManifest
    research_manifest_sha256: Sha256

    @model_validator(mode="after")
    def research_only(self) -> Self:
        if self.research_manifest.zone != "research":
            raise ValueError("research catalog cannot contain a full snapshot manifest")
        return self
