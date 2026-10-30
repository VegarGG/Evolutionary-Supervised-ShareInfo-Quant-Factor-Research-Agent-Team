"""Data-only local sources; no URL fetch, original-package import or code execution."""

import json
import stat
from dataclasses import dataclass, replace
from pathlib import Path

import polars as pl
from qfr_core.contracts.data import ExposureAndQuality, SnapshotManifest
from qfr_core.data_layer.pilot import import_pilot
from qfr_core.data_layer.snapshots import (
    Snapshot,
    TableInput,
    canonical_json,
    file_hash,
    slice_frame,
)
from qfr_core.data_layer.synthetic import generate

from qfr_eval.ingest.cli import _quality
from qfr_eval.ingest.models import (
    PilotLocalSource,
    SnapshotBuildAuthorization,
    SnapshotBuildPlan,
    SnapshotReplaySource,
)
from qfr_eval.scheduler.dedup import digest


@dataclass(frozen=True)
class ImportedTables:
    tables: list[TableInput]
    exposure: ExposureAndQuality
    profile: str
    source_hashes: dict[str, str]
    conventions: dict[str, str]


def contained(root: Path, relative: str) -> Path:
    path = root / relative
    if not root.is_dir() or root.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("source path escapes authorized root")
    item = path
    while item != root:
        if item.is_symlink():
            raise ValueError("source path contains a symlink")
        item = item.parent
    return path


def bounded_tree(root: Path, limits: SnapshotBuildAuthorization) -> dict[str, str]:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("source directory unavailable")
    values: dict[str, str] = {}
    total = 0
    for number, path in enumerate(root.rglob("*"), start=1):
        if number > limits.maximum_source_files:
            raise ValueError("source inventory exceeds authorized entry bound")
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode):
            raise ValueError("source contains a link or special file")
        total += path.stat().st_size
        if len(values) >= limits.maximum_source_files or total > limits.maximum_source_bytes:
            raise ValueError("source inventory exceeds authorized bounds")
        values[path.relative_to(root).as_posix()] = file_hash(path)
    return values


def load_source(
    plan: SnapshotBuildPlan,
    limits: SnapshotBuildAuthorization,
    source_root: Path,
    fixtures_root: Path,
) -> ImportedTables:
    source = plan.source
    hashes: dict[str, str]
    if isinstance(source, PilotLocalSource):
        package = contained(source_root, source.package)
        hashes = bounded_tree(package, limits)
        if hashes.get("SHA256SUMS.json") != source.inventory_sha256:
            raise ValueError("pilot inventory differs from authorized original")
        inventory_file = package / "SHA256SUMS.json"
        if inventory_file.stat().st_size > limits.maximum_metadata_bytes:
            raise ValueError("source inventory metadata exceeds authorized bounds")
        inventory = json.loads(inventory_file.read_bytes())["files"]
        if not inventory or any(
            hashes.get(name) != value["sha256"] for name, value in inventory.items()
        ):
            raise ValueError("original pilot package inventory mismatch")
        manifests = contained(fixtures_root, "manifests")
        fixture_hashes = bounded_tree(manifests, limits)
        if digest(fixture_hashes) != source.fixture_manifests_sha256:
            raise ValueError("pilot adapter manifests differ from authorized identity")
        if any(p.stat().st_size > limits.maximum_metadata_bytes for p in manifests.glob("*.json")):
            raise ValueError("pilot adapter metadata exceeds authorized bounds")
        cells = sum(
            int(value["rows"]) * len(value["columns"])
            for path in sorted(manifests.glob("*.json"))
            for value in [json.loads(path.read_bytes())]
        )
        if cells > limits.maximum_table_cells:
            raise ValueError("pilot table size exceeds authorized bounds")
        result = import_pilot(package, fixtures_root, source.adapter)
        tables, exposure, profile = result.tables, result.exposure, "pilot_industry_v1"
        conventions = dict(
            financial_availability=json.dumps(
                source.adapter.fundamental_availability, sort_keys=True
            ),
            vintage=source.adapter.vintage_note,
            membership=source.adapter.membership_note,
            exposure="previously_seen",
            new_supplier_requests="0",
        )
    elif isinstance(source, SnapshotReplaySource):
        path = contained(source_root, source.relative_path)
        hashes = bounded_tree(path, limits)
        if hashes.get("manifest.json") != source.manifest_sha256:
            raise ValueError("snapshot source manifest differs from authorized identity")
        if (path / "manifest.json").stat().st_size > limits.maximum_metadata_bytes:
            raise ValueError("snapshot metadata exceeds authorized bounds")
        manifest = SnapshotManifest.model_validate_json((path / "manifest.json").read_bytes())
        if sum(t.rows * len(t.columns) for t in manifest.tables) > limits.maximum_table_cells:
            raise ValueError("snapshot table size exceeds authorized bounds")
        snapshot = Snapshot.load(path)
        tables = [
            TableInput(
                t.name,
                snapshot.read(t.name),
                tuple(t.grain),
                t.quality,
                t.licence_note,
                t.date_column,
                t.available_date_column,
                t.source_hashes,
                t.research_visible,
            )
            for t in manifest.tables
        ]
        exposure, profile = manifest.exposure, manifest.profile
        # A full snapshot's free-form conventions can contain private analysis.
        # Preserve typed quality/exposure, not arbitrary full-zone metadata.
        conventions = {"replay_source_snapshot": manifest.snapshot_id}
    else:
        cfg = source.configuration
        # Bound the declared synthetic panel before allocation/calibration.
        if cfg.days * cfg.instruments * 32 > limits.maximum_table_cells:
            raise ValueError("synthetic dimensions exceed authorized bounds")
        world = generate(cfg, source.world)
        quality = _quality(True)
        exposure = ExposureAndQuality(
            history="previously_seen",
            inspected_periods=[],
            training_tuning_history="Synthetic replay",
            provider_knowledge_exposure="unknown",
            quality=quality,
            licence_constraints=["Synthetic"],
            unknowns=[],
        )
        tables = [
            TableInput("panel", world.panel, ("instrument", "date"), quality, "Synthetic"),
            TableInput("calendar", world.calendar, ("date",), quality, "Synthetic"),
            TableInput(
                "membership", world.membership, ("instrument", "date"), quality, "Synthetic"
            ),
            TableInput(
                "ground_truth",
                pl.DataFrame(
                    {"id": ["truth"], "payload": [canonical_json(world.ground_truth).decode()]}
                ),
                ("id",),
                quality,
                "Synthetic",
                None,
                None,
                research_visible=False,
            ),
        ]
        hashes = {"synthetic_recipe": digest(source.model_dump(mode="json"))}
        profile = "stock_daily_v1"
        conventions = dict(source="synthetic", timing=str(world.ground_truth["timing"]))
    if sum(t.frame.height * t.frame.width for t in tables) > limits.maximum_table_cells:
        raise ValueError("imported table size exceeds authorized bounds")
    selected = [
        replace(t, frame=slice_frame(t.frame, plan.as_of, t.date_column, t.available_date_column))
        for t in tables
    ]
    conventions.update(on_demand_replay="true", new_supplier_requests="0")
    return ImportedTables(selected, exposure, profile, hashes, conventions)
