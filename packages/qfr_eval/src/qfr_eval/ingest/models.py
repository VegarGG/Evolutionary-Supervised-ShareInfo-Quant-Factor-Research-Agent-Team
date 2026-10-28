"""Private operator authorization for one exact local snapshot-build plan."""

from datetime import date
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, PositiveInt, model_validator
from qfr_core.contracts.access import ProgramId
from qfr_core.contracts.base import Contract, Sha256, Text
from qfr_core.contracts.data import AssetReference
from qfr_core.data_layer.pilot import PilotConfig
from qfr_core.data_layer.synthetic import SyntheticConfig

from qfr_eval.scheduler.dedup import digest


class PilotLocalSource(Contract):
    kind: Literal["pilot"]
    package: Text
    inventory_sha256: Sha256
    fixture_manifests_sha256: Sha256
    adapter: PilotConfig


class SnapshotReplaySource(Contract):
    kind: Literal["snapshot_replay"]
    relative_path: Text
    manifest_sha256: Sha256


class SyntheticReplaySource(Contract):
    kind: Literal["synthetic"]
    world: Literal["planted", "null", "decay"]
    configuration: SyntheticConfig


class SnapshotBuildPlan(Contract):
    schema_version: Literal["1"]
    plan_id: UUID
    program_id: ProgramId
    source_ref: ProgramId
    source: Annotated[
        PilotLocalSource | SnapshotReplaySource | SyntheticReplaySource, Field(discriminator="kind")
    ]
    research_cutoff: date
    as_of: date
    build_code_version: ProgramId

    @model_validator(mode="after")
    def explicit_scope(self) -> Self:
        if self.research_cutoff > self.as_of:
            raise ValueError("research cutoff exceeds authorized as-of date")
        path = (
            self.source.package
            if isinstance(self.source, PilotLocalSource)
            else self.source.relative_path
            if isinstance(self.source, SnapshotReplaySource)
            else None
        )
        if path is not None:
            AssetReference(
                transport="mounted_import", reference_id=self.source_ref, relative_path=path
            )
            if path in {"", "."} or any(p in {"", "."} for p in path.split("/")):
                raise ValueError("source requires an explicit confined relative path")
        return self

    @property
    def sha256(self) -> str:
        return digest(self.model_dump(mode="json"))


class SnapshotBuildAuthorization(Contract):
    schema_version: Literal["1"]
    enabled: bool
    plan_sha256: Sha256
    authorization_ref: Text
    authorized_principal: Text
    authorized_at: AwareDatetime
    maximum_source_files: PositiveInt
    maximum_source_bytes: PositiveInt
    maximum_metadata_bytes: PositiveInt = Field(le=1048576)
    maximum_table_cells: PositiveInt
    network: Literal["none"]
    schedule: Literal["on_demand_only"]
