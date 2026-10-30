"""Inactive synthetic schema examples, never data/spend authorization."""

from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID

from qfr_core.data_layer.pilot import PilotConfig
from qfr_core.data_layer.synthetic import SyntheticConfig
from qfr_eval.ingest.models import (
    PilotLocalSource,
    SnapshotBuildAuthorization,
    SnapshotBuildPlan,
    SnapshotReplaySource,
    SyntheticReplaySource,
)


def examples(root: Path):
    synthetic = SyntheticReplaySource(
        kind="synthetic",
        world="null",
        configuration=SyntheticConfig.model_validate(
            {
                **SyntheticConfig.load(root / "configs/data/synthetic.json").model_dump(),
                "days": 80,
                "instruments": 20,
                "min_names": 10,
            }
        ),
    )
    plan = SnapshotBuildPlan(
        schema_version="1",
        plan_id=UUID(int=20),
        program_id="example-program",
        source_ref="example-synthetic",
        source=synthetic,
        research_cutoff=date(2010, 3, 1),
        as_of=date(2010, 12, 31),
        build_code_version="example-not-deployed",
    )
    authorization = SnapshotBuildAuthorization(
        schema_version="1",
        enabled=False,
        plan_sha256=plan.sha256,
        authorization_ref="example-not-authorized",
        authorized_principal="example-owner",
        authorized_at=datetime(2026, 10, 28, tzinfo=UTC),
        maximum_source_files=10000,
        maximum_source_bytes=1073741824,
        maximum_metadata_bytes=1048576,
        maximum_table_cells=10000000,
        network="none",
        schedule="on_demand_only",
    )
    return [
        plan,
        authorization,
        synthetic,
        PilotLocalSource(
            kind="pilot",
            package="original-package",
            inventory_sha256="0" * 64,
            fixture_manifests_sha256="0" * 64,
            adapter=PilotConfig.model_validate_json(
                (root / "configs/data/pilot_import.json").read_bytes()
            ),
        ),
        SnapshotReplaySource(
            kind="snapshot_replay", relative_path="full/" + "0" * 64, manifest_sha256="0" * 64
        ),
    ]
