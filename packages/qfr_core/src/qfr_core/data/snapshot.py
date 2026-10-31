"""Content-addressed, verified data snapshots (PLAN Sections 6.3 and 6.4).

Layout: <root>/<zone>/<snapshot_id>/ with panel/year=YYYY/part.parquet,
membership.parquet, calendar.parquet and manifest.json. The manifest lists the SHA-256
of every other file, and the snapshot id is the SHA-256 of the canonical manifest JSON,
so a snapshot cannot change without changing its id. Writes go to a temporary
directory first and are renamed into place, so readers never see a partial snapshot.
"""

import hashlib
import importlib.metadata
import json
import os
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Final, Literal, Self

import polars as pl
from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from qfr_core.config import canonical_json
from qfr_core.data.panel import (
    CALENDAR_SCHEMA,
    DATE,
    INSTRUMENT,
    MEMBERSHIP_SCHEMA,
    PANEL_SCHEMA,
    PanelError,
    check_schema,
)

SNAPSHOT_FORMAT: Final = "qfr-snapshot/1"
MANIFEST: Final = "manifest.json"
CURRENT: Final = "current.json"
Zone = Literal["full", "research"]
Source = Literal["synthetic", "cn"]
_HASH = r"^[0-9a-f]{64}$"
_CHUNK = 1 << 20


class SnapshotError(ValueError):
    """A snapshot that is missing, modified, or not allowed in the requesting zone."""


class DateRange(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    start: date
    end: date

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.end < self.start:
            raise ValueError("date range end precedes start")
        return self


class SnapshotManifest(BaseModel):
    """PLAN 6.3: source, release tag, archive hash, build code version, field list,
    conventions, date range, row counts, zone and research cutoff (research zone only)."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    format: Literal["qfr-snapshot/1"]
    zone: Zone
    source: Source
    release_tag: str | None
    archive_sha256: str | None = Field(pattern=_HASH)
    source_details: dict[str, JsonValue]
    build_code_version: str
    fields: list[str]
    conventions: dict[str, JsonValue]
    date_range: DateRange
    row_counts: dict[str, int]
    research_cutoff: date | None
    research_window: DateRange | None
    parent_snapshot_id: str | None = Field(pattern=_HASH)
    checks: dict[str, JsonValue]
    files: dict[str, str]

    @model_validator(mode="after")
    def zone_rules(self) -> Self:
        if self.zone == "research":
            if self.research_cutoff is None or self.research_window is None:
                raise ValueError("a research snapshot records its cutoff and window")
            if self.date_range.end > self.research_cutoff:
                raise ValueError("BND-06: research data extends past the cutoff")
            if self.research_window.end != self.research_cutoff:
                raise ValueError("the research window ends at the cutoff")
        elif self.research_cutoff is not None or self.research_window is not None:
            raise ValueError("only research snapshots carry a cutoff")
        if any(not _is_hash(v) for v in self.files.values()):
            raise ValueError("file hashes must be lowercase SHA-256")
        return self

    def canonical_json(self) -> str:
        return canonical_json(self.model_dump(mode="json"))

    @property
    def snapshot_id(self) -> str:
        return hashlib.sha256(self.canonical_json().encode()).hexdigest()


def _is_hash(value: str) -> bool:
    return len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def code_version() -> str:
    return importlib.metadata.version("qfr-core")


@dataclass(frozen=True)
class SnapshotData:
    """Frames in canonical schema plus extra files (full zone only, e.g. ground truth)."""

    panel: pl.DataFrame
    membership: pl.DataFrame
    calendar: pl.DataFrame
    extras: dict[str, bytes] = field(default_factory=dict)


@dataclass(frozen=True)
class SnapshotSource:
    """Manifest fields describing where the data came from and how it was built."""

    source: Source
    release_tag: str | None
    archive_sha256: str | None
    source_details: dict[str, JsonValue]
    conventions: dict[str, JsonValue]
    checks: dict[str, JsonValue]


@dataclass(frozen=True)
class Snapshot:
    path: Path
    manifest: SnapshotManifest

    @property
    def snapshot_id(self) -> str:
        return self.path.name

    def panel_files(self) -> list[Path]:
        return [
            self.path / name for name in sorted(self.manifest.files) if name.startswith("panel/")
        ]

    def scan_panel(self) -> pl.LazyFrame:
        return pl.scan_parquet(self.panel_files(), hive_partitioning=False).select(
            list(PANEL_SCHEMA)
        )

    def panel(self, columns: list[str] | None = None) -> pl.DataFrame:
        """The panel sorted by instrument and date, as the operator library requires."""
        frame = self.scan_panel()
        if columns is not None:
            keep = [INSTRUMENT, DATE, *[c for c in columns if c not in (INSTRUMENT, DATE)]]
            frame = frame.select(keep)
        return frame.sort(INSTRUMENT, DATE).collect()

    def membership(self) -> pl.DataFrame:
        return pl.read_parquet(self.path / "membership.parquet")

    def calendar(self) -> pl.DataFrame:
        return pl.read_parquet(self.path / "calendar.parquet")

    def extra(self, name: str) -> bytes:
        if name not in self.manifest.files or name.startswith("panel/"):
            raise SnapshotError(f"{name} is not part of snapshot {self.snapshot_id}")
        return (self.path / name).read_bytes()


def _date_bounds(frame: pl.DataFrame, column: str) -> tuple[date | None, date | None]:
    if frame.is_empty():
        return None, None
    low, high = frame.select(
        pl.col(column).min().alias("low"), pl.col(column).max().alias("high")
    ).row(0)
    return low, high


def _write_frames(directory: Path, data: SnapshotData) -> None:
    years = data.panel.get_column(DATE).dt.year().unique().sort().to_list()
    for year in years:
        part = directory / "panel" / f"year={year:04d}" / "part.parquet"
        part.parent.mkdir(parents=True)
        data.panel.filter(pl.col(DATE).dt.year() == year).sort(INSTRUMENT, DATE).write_parquet(
            part, compression="zstd", statistics=True
        )
    data.membership.sort("universe", INSTRUMENT, "start").write_parquet(
        directory / "membership.parquet", compression="zstd"
    )
    data.calendar.sort(DATE).write_parquet(directory / "calendar.parquet", compression="zstd")
    for name, content in sorted(data.extras.items()):
        if "/" in name or name in {MANIFEST, CURRENT} or not name:
            raise SnapshotError(f"invalid extra file name {name!r}")
        (directory / name).write_bytes(content)


def _hash_tree(directory: Path) -> dict[str, str]:
    return {
        path.relative_to(directory).as_posix(): file_sha256(path)
        for path in sorted(directory.rglob("*"))
        if path.is_file() and path.name != MANIFEST
    }


@dataclass(frozen=True)
class ZoneDirs:
    """Where each zone keeps its snapshots: in Compose, the mount points named by
    QFR_FULL_SNAPSHOT_DIR and QFR_RESEARCH_SNAPSHOT_DIR; locally, <root>/full and
    <root>/research under data/snapshots."""

    full: Path
    research: Path

    @classmethod
    def under(cls, root: Path) -> Self:
        return cls(root / "full", root / "research")

    def of(self, zone: Zone) -> Path:
        return self.full if zone == "full" else self.research


def write_snapshot(
    zone_dir: Path,
    zone: Zone,
    data: SnapshotData,
    source: SnapshotSource,
    *,
    research_window: DateRange | None = None,
    parent_snapshot_id: str | None = None,
) -> Snapshot:
    """Write a snapshot atomically to <zone_dir>/<snapshot id> and return it.

    Rewriting identical content is a no-op.
    """
    check_schema(data.panel, PANEL_SCHEMA, "the panel")
    check_schema(data.membership, MEMBERSHIP_SCHEMA, "the membership table")
    check_schema(data.calendar, CALENDAR_SCHEMA, "the calendar")
    if zone == "research" and data.extras:
        raise SnapshotError("research snapshots carry no extra files")
    first, last = _date_bounds(data.calendar, DATE)
    if first is None or last is None or data.panel.is_empty():
        raise PanelError("a snapshot needs at least one trading date and one panel row")
    zone_dir.mkdir(parents=True, exist_ok=True)
    staging = zone_dir / f".building-{uuid.uuid4().hex}"
    staging.mkdir()
    try:
        _write_frames(staging, data)
        manifest = SnapshotManifest(
            format=SNAPSHOT_FORMAT,
            zone=zone,
            source=source.source,
            release_tag=source.release_tag,
            archive_sha256=source.archive_sha256,
            source_details=source.source_details,
            build_code_version=code_version(),
            fields=list(PANEL_SCHEMA),
            conventions=source.conventions,
            date_range=DateRange(start=first, end=last),
            row_counts={
                "panel": data.panel.height,
                "instruments": data.panel.get_column(INSTRUMENT).n_unique(),
                "dates": data.calendar.height,
                "membership": data.membership.height,
            },
            research_cutoff=research_window.end if research_window else None,
            research_window=research_window,
            parent_snapshot_id=parent_snapshot_id,
            checks=source.checks,
            files=_hash_tree(staging),
        )
        (staging / MANIFEST).write_text(manifest.canonical_json(), encoding="utf-8")
        final = zone_dir / manifest.snapshot_id
        if final.exists():
            existing = read_snapshot(final)
            shutil.rmtree(staging)
            return existing
        os.replace(staging, final)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return Snapshot(final, manifest)


def read_snapshot(path: Path, *, verify: bool = True) -> Snapshot:
    """Open a snapshot. With verify, every file hash and the id itself are checked."""
    manifest_path = path / MANIFEST
    if not manifest_path.is_file():
        raise SnapshotError(f"no snapshot manifest at {path}")
    manifest = SnapshotManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    if manifest.snapshot_id != path.name:
        raise SnapshotError(f"snapshot id mismatch: {path.name} holds {manifest.snapshot_id}")
    if verify:
        actual = _hash_tree(path)
        if actual != manifest.files:
            changed = sorted(set(actual.items()) ^ set(manifest.files.items()))
            names = sorted({name for name, _ in changed})
            raise SnapshotError(f"snapshot files differ from the manifest: {', '.join(names)}")
    return Snapshot(path, manifest)


def check_research_snapshot(snapshot: Snapshot) -> date:
    """BND-06: the research snapshot's maximum date is on or before the cutoff.

    Checked on the data itself, not only on the manifest. Returns the cutoff.
    """
    manifest = snapshot.manifest
    if manifest.zone != "research" or manifest.research_cutoff is None:
        raise SnapshotError("BND-06: research processes may open research snapshots only")
    cutoff = manifest.research_cutoff
    extras = [n for n in manifest.files if not n.startswith("panel/")]
    if sorted(extras) != ["calendar.parquet", "membership.parquet"]:
        raise SnapshotError("BND-06: research snapshots hold only panel, membership and calendar")
    _, panel_max = _date_bounds(snapshot.scan_panel().select(DATE).collect(), DATE)
    _, calendar_max = _date_bounds(snapshot.calendar(), DATE)
    _, member_max = _date_bounds(snapshot.membership(), "end")
    for label, value in (
        ("panel", panel_max),
        ("calendar", calendar_max),
        ("membership", member_max),
    ):
        if value is not None and value > cutoff:
            raise SnapshotError(f"BND-06: {label} data dated {value} is after the cutoff {cutoff}")
    return cutoff


def open_research_snapshot(path: Path) -> Snapshot:
    """The only way research code opens market data: verified and cutoff-checked."""
    snapshot = read_snapshot(path)
    check_research_snapshot(snapshot)
    return snapshot


def set_current(zone_dir: Path, snapshot: Snapshot) -> None:
    """Point <zone_dir>/current.json at a snapshot in that directory, atomically."""
    if snapshot.path.parent.resolve() != zone_dir.resolve():
        raise SnapshotError(f"snapshot {snapshot.snapshot_id} is not in {zone_dir}")
    pointer = zone_dir / f".{CURRENT}.{uuid.uuid4().hex}"
    pointer.write_text(json.dumps({"snapshot_id": snapshot.snapshot_id}) + "\n", encoding="utf-8")
    os.replace(pointer, zone_dir / CURRENT)


def current_snapshot(zone_dir: Path) -> Path:
    """The path of the snapshot that <zone_dir>/current.json points at."""
    pointer = zone_dir / CURRENT
    if not pointer.is_file():
        raise SnapshotError(f"no current snapshot in {zone_dir}")
    snapshot_id = json.loads(pointer.read_text(encoding="utf-8"))["snapshot_id"]
    if not isinstance(snapshot_id, str) or not _is_hash(snapshot_id):
        raise SnapshotError("the current-snapshot pointer is malformed")
    return zone_dir / snapshot_id
