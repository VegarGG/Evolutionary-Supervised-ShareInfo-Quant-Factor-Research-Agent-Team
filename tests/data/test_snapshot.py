"""Content-addressed snapshots and the BND-06 research guard (PLAN 6.3, 6.4, 18.2)."""

import hashlib
import json
import shutil

import polars as pl
import pytest
from pydantic import ValidationError
from qfr_core.data.panel import PANEL_SCHEMA
from qfr_core.data.snapshot import (
    DateRange,
    SnapshotData,
    SnapshotError,
    SnapshotManifest,
    SnapshotSource,
    current_snapshot,
    open_research_snapshot,
    read_snapshot,
    write_snapshot,
)


def test_layout_manifest_and_content_address(small_zones):
    full = small_zones.full
    names = sorted(full.manifest.files)
    assert "membership.parquet" in names and "calendar.parquet" in names
    assert "ground_truth.json" in names
    assert all(
        n.startswith("panel/year=") and n.endswith("/part.parquet")
        for n in names
        if n.startswith("panel")
    )
    text = (full.path / "manifest.json").read_text()
    assert hashlib.sha256(text.encode()).hexdigest() == full.snapshot_id
    manifest = full.manifest
    assert manifest.zone == "full" and manifest.research_cutoff is None
    assert manifest.fields == list(PANEL_SCHEMA)
    assert manifest.row_counts["panel"] == small_zones.world.panel.height
    assert manifest.build_code_version == "0.1.0"


def test_reading_returns_the_written_frames(small_zones):
    snapshot = read_snapshot(small_zones.full.path)
    assert snapshot.panel().equals(small_zones.world.panel)
    assert snapshot.calendar().equals(small_zones.world.calendar.sort("date"))
    assert dict(snapshot.panel(["close"]).schema) == {
        "instrument": pl.String,
        "date": pl.Date,
        "close": pl.Float64,
    }


def test_rewriting_identical_content_is_idempotent(small_zones, tmp_path):
    world = small_zones.world
    data = SnapshotData(world.panel, world.membership, world.calendar)
    source = SnapshotSource("synthetic", None, None, {}, {}, {})
    first = write_snapshot(tmp_path / "full", "full", data, source)
    second = write_snapshot(tmp_path / "full", "full", data, source)
    assert first.snapshot_id == second.snapshot_id
    assert sorted(p.name for p in (tmp_path / "full").iterdir()) == [first.snapshot_id]


def test_any_changed_byte_or_file_is_detected(small_zones, tmp_path):
    copy = tmp_path / small_zones.full.snapshot_id
    shutil.copytree(small_zones.full.path, copy)
    part = sorted(copy.glob("panel/*/part.parquet"))[0]
    part.write_bytes(part.read_bytes() + b"\0")
    with pytest.raises(SnapshotError, match="differ from the manifest"):
        read_snapshot(copy)
    shutil.rmtree(copy)
    shutil.copytree(small_zones.full.path, copy)
    (copy / "extra.txt").write_text("x")
    with pytest.raises(SnapshotError, match="extra.txt"):
        read_snapshot(copy)
    shutil.rmtree(copy)
    shutil.copytree(small_zones.full.path, copy)
    manifest = json.loads((copy / "manifest.json").read_text())
    manifest["release_tag"] = "edited"
    (copy / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(SnapshotError, match="id mismatch"):
        read_snapshot(copy)


def test_bnd_06_research_snapshot_ends_at_the_cutoff(small_zones):
    research = open_research_snapshot(small_zones.research.path)
    cutoff = research.manifest.research_cutoff
    assert cutoff is not None and str(cutoff) == "2011-06-30"
    assert research.manifest.research_window == DateRange.model_validate(
        {"start": "2010-01-04", "end": "2011-06-30"}
    )
    assert research.panel()["date"].max() <= cutoff
    assert research.calendar()["date"].max() <= cutoff
    assert research.membership()["end"].max() <= cutoff
    assert "ground_truth.json" not in research.manifest.files
    assert research.manifest.parent_snapshot_id == small_zones.full.snapshot_id
    assert current_snapshot(small_zones.root / "research") == small_zones.research.path
    assert current_snapshot(small_zones.root / "full") == small_zones.full.path


def test_bnd_06_research_rows_equal_the_full_rows(small_zones):
    cutoff = small_zones.research.manifest.research_cutoff
    full = small_zones.full.panel().filter(pl.col("date") <= cutoff)
    assert small_zones.research.panel().equals(full)


def test_bnd_06_the_guard_refuses_full_snapshots(small_zones):
    with pytest.raises(SnapshotError, match="BND-06"):
        open_research_snapshot(small_zones.full.path)


def test_bnd_06_the_guard_checks_data_not_only_the_manifest(small_zones, tmp_path):
    """A research snapshot whose files were swapped for later data, with the manifest
    re-hashed to match, still fails: the guard reads the dates themselves."""
    forged = tmp_path / "forged"
    shutil.copytree(small_zones.research.path, forged)
    late = small_zones.full.panel().filter(pl.col("date").dt.year() == 2012)
    target = forged / "panel" / "year=2011" / "part.parquet"
    pl.concat([pl.read_parquet(target), late]).write_parquet(target)
    manifest = json.loads((forged / "manifest.json").read_text())
    manifest["files"]["panel/year=2011/part.parquet"] = hashlib.sha256(
        target.read_bytes()
    ).hexdigest()
    text = SnapshotManifest.model_validate(manifest).canonical_json()
    (forged / "manifest.json").write_text(text)
    renamed = tmp_path / hashlib.sha256(text.encode()).hexdigest()
    forged.rename(renamed)
    with pytest.raises(SnapshotError, match="BND-06: panel data dated 2012"):
        open_research_snapshot(renamed)


def test_research_manifests_must_respect_their_cutoff():
    base = {
        "format": "qfr-snapshot/1",
        "zone": "research",
        "source": "synthetic",
        "release_tag": None,
        "archive_sha256": None,
        "source_details": {},
        "build_code_version": "0.1.0",
        "fields": [],
        "conventions": {},
        "date_range": {"start": "2010-01-04", "end": "2012-01-02"},
        "row_counts": {},
        "research_cutoff": "2011-06-30",
        "research_window": {"start": "2010-01-04", "end": "2011-06-30"},
        "parent_snapshot_id": None,
        "checks": {},
        "files": {},
    }
    with pytest.raises(ValidationError, match="BND-06"):
        SnapshotManifest.model_validate(base)
    with pytest.raises(ValidationError, match="only research snapshots"):
        SnapshotManifest.model_validate(
            base | {"zone": "full", "date_range": {"start": "2010-01-04", "end": "2011-01-04"}}
        )


def test_research_snapshots_reject_extra_files(small_zones, tmp_path):
    world = small_zones.world
    data = SnapshotData(
        world.panel.filter(pl.col("date") <= pl.date(2011, 6, 30)),
        world.membership,
        world.calendar.filter(pl.col("date") <= pl.date(2011, 6, 30)),
        {"ground_truth.json": b"{}"},
    )
    window = DateRange.model_validate({"start": "2010-01-04", "end": "2011-06-30"})
    with pytest.raises(SnapshotError, match="no extra files"):
        write_snapshot(
            tmp_path / "research",
            "research",
            data,
            SnapshotSource("synthetic", None, None, {}, {}, {}),
            research_window=window,
        )


def test_failed_writes_leave_no_partial_snapshot(small_zones, tmp_path):
    world = small_zones.world
    bad = SnapshotData(world.panel, world.membership, world.calendar, {"../escape": b"x"})
    with pytest.raises(SnapshotError, match="invalid extra file name"):
        write_snapshot(
            tmp_path / "full", "full", bad, SnapshotSource("synthetic", None, None, {}, {}, {})
        )
    assert list((tmp_path / "full").iterdir()) == []
