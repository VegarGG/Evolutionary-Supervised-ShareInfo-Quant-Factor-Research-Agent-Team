"""Immutable, verified data snapshots. These are datasets, not registry artifacts."""

import hashlib
import json
import math
import os
import shutil
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Final, Literal

import polars as pl

from qfr_core.contracts.blackboard import AuditEvent
from qfr_core.contracts.data import (
    ExposureAndQuality,
    QualityLabels,
    SnapshotFile,
    SnapshotManifest,
    SnapshotTable,
)

HASH_SPEC: Final = "qfr-table/1:sorted-grain,sorted-columns,float-hex,null"


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _scalar(value: object) -> object:
    if isinstance(value, float):
        if math.isnan(value):
            return None
        if not math.isfinite(value):
            raise ValueError("infinite table value")
        return {"float64": (0.0 if value == 0 else value).hex()}
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise ValueError(f"unsupported table scalar: {type(value).__name__}")


def normalize_table(frame: pl.DataFrame, grain: Sequence[str]) -> pl.DataFrame:
    if not grain or not set(grain) <= set(frame.columns):
        raise ValueError("missing table grain")
    if frame.select(pl.any_horizontal(pl.col(list(grain)).is_null()).any()).item():
        raise ValueError("null table key")
    if frame.select(list(grain)).is_duplicated().any():
        raise ValueError("duplicate table key")
    floats = [name for name, dtype in frame.schema.items() if dtype.is_float()]
    if floats:
        if frame.select(pl.any_horizontal(pl.col(floats).is_infinite()).any()).item():
            raise ValueError("infinite table value")
        frame = frame.with_columns(pl.col(floats).fill_nan(None))
    return frame.sort(list(grain)).select(sorted(frame.columns))


def logical_hash(frame: pl.DataFrame, grain: Sequence[str]) -> str:
    frame = normalize_table(frame, grain)
    digest = hashlib.sha256(
        canonical_json(
            {
                "spec": HASH_SPEC,
                "grain": list(grain),
                "columns": {name: str(dtype) for name, dtype in frame.schema.items()},
            }
        )
    )
    for row in frame.iter_rows():
        digest.update(b"\n" + canonical_json([_scalar(value) for value in row]))
    return digest.hexdigest()


def dense_panel(observations: pl.DataFrame, calendar: pl.DataFrame) -> pl.DataFrame:
    """Densify only between each name's first/last observation; never forward fill prices."""
    required = {"date", "instrument", "open", "high", "low", "close", "volume", "amount", "factor"}
    if not required <= set(observations.columns):
        raise ValueError(f"missing stock columns: {sorted(required - set(observations.columns))}")
    if observations.schema["date"] != pl.Date or calendar.schema.get("date") != pl.Date:
        raise ValueError("canonical dates must have Date dtype")
    observations = normalize_table(observations, ["instrument", "date"])
    calendar = normalize_table(calendar.select("date"), ["date"])
    if not observations["date"].is_in(calendar["date"].implode()).all():
        raise ValueError("observation outside trading calendar")
    for name in ["open", "high", "low", "close", "factor"]:
        if (observations[name] <= 0).any():
            raise ValueError(f"non-positive {name}")
    if (observations["volume"] < 0).any() or (observations["amount"] < 0).any():
        raise ValueError("negative volume or amount")
    bounds = observations.group_by("instrument").agg(
        pl.col("date").min().alias("first"), pl.col("date").max().alias("last")
    )
    keys = (
        bounds.join(calendar, how="cross")
        .filter(pl.col("date").is_between(pl.col("first"), pl.col("last")))
        .select("instrument", "date")
    )
    frame = keys.join(observations, on=["instrument", "date"], how="left").sort(
        "instrument", "date"
    )
    numbers = sorted(required - {"date", "instrument"})
    frame = frame.with_columns(pl.col(numbers).cast(pl.Float64)).with_columns(
        (pl.col("close") / pl.col("factor")).alias("close_raw"),
        (pl.col("close") / pl.col("close").shift(1).over("instrument") - 1).alias("ret_1d"),
        (pl.col("volume").is_null() | (pl.col("volume") == 0)).alias("is_suspended"),
        pl.col("date").cum_count().over("instrument").cast(pl.Int32).alias("listed_days"),
        pl.col("amount").rolling_mean(20, min_samples=20).over("instrument").alias("adv20"),
    )
    if "vwap" not in frame.columns:
        frame = frame.with_columns(
            ((pl.col("high") + pl.col("low") + pl.col("close")) / 3).alias("vwap")
        )
    return frame


@dataclass(frozen=True)
class TableInput:
    name: str
    frame: pl.DataFrame
    grain: tuple[str, ...]
    quality: QualityLabels
    licence_note: str
    date_column: str | None = "date"
    available_date_column: str | None = None
    source_hashes: dict[str, str] = field(default_factory=dict)
    research_visible: bool = True


def _identity(manifest: SnapshotManifest) -> str:
    return hashlib.sha256(
        canonical_json(manifest.model_dump(mode="json", exclude={"snapshot_id"}))
    ).hexdigest()


def _contained(root: Path, path: str) -> Path:
    result = root / path
    if not result.resolve().is_relative_to(root.resolve()) or result.is_symlink():
        raise ValueError("snapshot file escapes root")
    return result


def _check_dates(frame: pl.DataFrame, table: SnapshotTable, upto: date) -> None:
    for name in [table.date_column, table.available_date_column]:
        if name is not None:
            if frame.schema[name] != pl.Date:
                raise ValueError(f"{table.name}.{name} must be Date")
            if (frame[name] > upto).any():
                raise ValueError(f"{table.name}.{name} exceeds snapshot cutoff")


@dataclass(frozen=True)
class Snapshot:
    path: Path
    manifest: SnapshotManifest

    @classmethod
    def load(cls, path: Path) -> "Snapshot":
        manifest = SnapshotManifest.model_validate_json((path / "manifest.json").read_bytes())
        if _identity(manifest) != manifest.snapshot_id or path.name != manifest.snapshot_id:
            raise ValueError("snapshot identity mismatch")
        instance = cls(path, manifest)
        for table in manifest.tables:
            frame = instance.read(table.name)
            _check_dates(frame, table, manifest.as_of)
        return instance

    def read(self, name: str) -> pl.DataFrame:
        table = next((x for x in self.manifest.tables if x.name == name), None)
        if table is None:
            raise KeyError(name)
        frames = []
        for item in table.files:
            path = _contained(self.path, item.path)
            if path.stat().st_size != item.bytes or file_hash(path) != item.physical_sha256:
                raise ValueError(f"physical hash mismatch: {item.path}")
            frames.append(pl.read_parquet(path))
        frame = normalize_table(pl.concat(frames), table.grain)
        if (
            frame.height != table.rows
            or {n: str(t) for n, t in frame.schema.items()} != table.columns
        ):
            raise ValueError(f"table shape/schema mismatch: {name}")
        if logical_hash(frame, table.grain) != table.logical_sha256:
            raise ValueError(f"logical hash mismatch: {name}")
        return frame

    def slice(self, upto: date) -> dict[str, pl.DataFrame]:
        """Date and information availability must both be observable at the cutoff."""
        boundary = min(upto, self.manifest.research_cutoff or self.manifest.as_of)
        return {
            table.name: slice_frame(
                self.read(table.name), boundary, table.date_column, table.available_date_column
            )
            for table in self.manifest.tables
        }


def slice_frame(
    frame: pl.DataFrame, upto: date, date_column: str | None, available_date_column: str | None
) -> pl.DataFrame:
    for column in dict.fromkeys([date_column, available_date_column]):
        if column is not None:
            if frame.schema.get(column) != pl.Date:
                raise ValueError(f"as-of column must be Date: {column}")
            # Unknown availability is not permission to reveal a value.
            frame = frame.filter(pl.col(column).is_not_null() & (pl.col(column) <= upto))
    return frame


def write_snapshot(
    root: Path,
    tables: Sequence[TableInput],
    *,
    profile: str,
    zone: Literal["research", "full"],
    cutoff: date | None,
    as_of: date,
    source: str,
    build_code_version: str,
    exposure: ExposureAndQuality,
    conventions: dict[str, str],
    principal: str,
    request_id: str,
    release_tag: str | None = None,
    archive_sha256: str | None = None,
) -> Snapshot:
    """Stage then atomically finalize; a repeat verifies and reuses the immutable snapshot."""
    if not principal or not request_id:
        raise ValueError("snapshot writes require principal and request_id")
    zone_root = root / zone
    zone_root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=zone_root))
    try:
        metadata = []
        for table in sorted(tables, key=lambda t: t.name):
            # Validate names before using them as paths.
            if not table.name.isidentifier() or not table.name.isascii():
                raise ValueError("invalid table name")
            frame = normalize_table(table.frame, table.grain)
            pieces = [(f"{table.name}.parquet", frame)]
            if table.name == "panel" and frame.height:
                pieces = [
                    (
                        f"panel/year={year}/part.parquet",
                        frame.filter(pl.col("date").dt.year() == year),
                    )
                    for year in sorted(frame["date"].dt.year().unique().to_list())
                ]
            files = []
            for filename, piece in pieces:
                path = staging / filename
                path.parent.mkdir(parents=True, exist_ok=True)
                piece.write_parquet(path)
                files.append(
                    SnapshotFile(
                        path=filename, physical_sha256=file_hash(path), bytes=path.stat().st_size
                    )
                )
            item = SnapshotTable(
                name=table.name,
                files=files,
                columns={n: str(t) for n, t in frame.schema.items()},
                grain=list(table.grain),
                date_column=table.date_column,
                available_date_column=table.available_date_column,
                rows=frame.height,
                logical_sha256=logical_hash(frame, table.grain),
                logical_hash_spec=HASH_SPEC,
                quality=table.quality,
                licence_note=table.licence_note,
                source_hashes=table.source_hashes,
                research_visible=table.research_visible,
            )
            _check_dates(frame, item, min(as_of, cutoff) if cutoff else as_of)
            metadata.append(item)
        manifest = SnapshotManifest(
            schema_version="1",
            snapshot_id="0" * 64,
            profile=profile,
            zone=zone,
            research_cutoff=cutoff,
            as_of=as_of,
            source=source,
            release_tag=release_tag,
            archive_sha256=archive_sha256,
            build_code_version=build_code_version,
            conventions=conventions,
            tables=metadata,
            exposure=exposure,
        )
        manifest = manifest.model_copy(update={"snapshot_id": _identity(manifest)})
        (staging / "manifest.json").write_bytes(canonical_json(manifest.model_dump(mode="json")))
        target = zone_root / manifest.snapshot_id
        if target.exists():
            Snapshot.load(target)
        else:
            try:
                staging.rename(target)
            except FileExistsError:
                Snapshot.load(target)
        event = AuditEvent(
            schema_version="1",
            event_id=f"snapshot:{request_id}:{manifest.snapshot_id}",
            principal=principal,
            request_id=request_id,
            action="snapshot_verified",
            entity_ref=manifest.snapshot_id,
            evidence_refs=[manifest.snapshot_id],
            at=datetime.now(UTC),
        )
        with os.fdopen(
            os.open(root / "events.jsonl", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600), "ab"
        ) as stream:
            stream.write(canonical_json(event.model_dump(mode="json")) + b"\n")
        return Snapshot(target, manifest)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
