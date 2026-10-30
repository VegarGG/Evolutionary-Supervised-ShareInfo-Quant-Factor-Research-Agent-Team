"""China A-share ingest from chenditc/investment_data releases (PLAN Sections 6.1, 6.2).

Steps: fetch the qlib_bin.tar.gz release archive (or take a local copy), verify its
SHA-256 against the release manifest or an owner-supplied value before extraction,
extract it safely, read the Qlib binary format, build the canonical panel restricted to
names that were ever in a configured universe, and run the sanity checks.
"""

import json
import shutil
import tarfile
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl
from pydantic import JsonValue
from qfr_core.data.panel import DATE, INSTRUMENT, build_panel, equal_weight_benchmark, sanity_checks
from qfr_core.data.qlib import QlibDirectory, QlibError
from qfr_core.data.snapshot import SnapshotData, SnapshotSource, file_sha256
from qfr_core.logging import JsonLogger

from qfr_eval.ingest.config import CnIngestConfig

_CHUNK = 1 << 20
PANEL_BATCH = 200  # Instruments per panel batch; see read_release.
_KEYS = ("sha256", "hash", "checksum", "digest")
_NAMES = ("name", "file", "filename", "path")


class IngestError(ValueError):
    """The release could not be verified, extracted or read."""


def _hash_value(value: object) -> str | None:
    if isinstance(value, str):
        text = value.strip().lower().removeprefix("sha256:")
        if len(text) == 64 and all(c in "0123456789abcdef" for c in text):
            return text
    return None


def manifest_sha256(manifest: Any, archive_name: str) -> str:
    """Find the archive's SHA-256 in a release manifest.

    The investment_data manifest layout could not be confirmed when this was written, so
    the common shapes are accepted: {"sha256": h} (optionally with a matching "name"),
    {name: h}, {name: {"sha256": h}}, {"files"|"assets"|"artifacts": ...} and lists of
    {"name"|"file"|"path": name, "sha256"|"hash"|"checksum": h}. Anything else is an
    error, and the owner verifies the archive and passes --sha256 instead.
    """
    if isinstance(manifest, dict):
        label = next((manifest[n] for n in _NAMES if isinstance(manifest.get(n), str)), None)
        if label is None or Path(label).name == archive_name:
            for key in _KEYS:
                if (found := _hash_value(manifest.get(key))) is not None:
                    return found
        entry = manifest.get(archive_name)
        if (found := _hash_value(entry)) is not None:
            return found
        if isinstance(entry, dict):
            for key in _KEYS:
                if (found := _hash_value(entry.get(key))) is not None:
                    return found
        for container in ("files", "assets", "artifacts"):
            if container in manifest:
                try:
                    return manifest_sha256(manifest[container], archive_name)
                except IngestError:
                    pass
    if isinstance(manifest, list):
        for entry in manifest:
            if isinstance(entry, dict) and _named(entry, archive_name):
                return manifest_sha256(entry, archive_name)
    raise IngestError(
        f"the release manifest has no SHA-256 for {archive_name}; "
        "verify the archive yourself and pass --sha256"
    )


def _named(entry: dict[str, Any], archive_name: str) -> bool:
    return any(
        isinstance(entry.get(n), str) and Path(entry[n]).name == archive_name for n in _NAMES
    )


def download(url: str, target: Path, limit: int, timeout: float) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(f".{target.name}.{uuid.uuid4().hex}")
    size = 0
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response, partial.open("wb") as out:
            while chunk := response.read(_CHUNK):
                size += len(chunk)
                if size > limit:
                    raise IngestError(f"{url} exceeds the configured size limit")
                out.write(chunk)
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)


def safe_extract(archive: Path, destination: Path, limit: int) -> None:
    """Extract regular files and directories only, inside destination, within a size cap."""
    destination.mkdir(parents=True)
    total = 0
    root = destination.resolve()
    with tarfile.open(archive, mode="r:*") as tar:
        for member in tar.getmembers():
            target = (destination / member.name).resolve()
            if not target.is_relative_to(root):
                raise IngestError(f"archive member {member.name!r} escapes the destination")
            if not (member.isfile() or member.isdir()):
                raise IngestError(f"archive member {member.name!r} is not a regular file")
            total += member.size
            if total > limit:
                raise IngestError("the extracted archive exceeds the configured size limit")
        tar.extractall(destination, filter="data")


@dataclass(frozen=True)
class CnRelease:
    archive: Path
    sha256: str
    release_tag: str | None
    expected_from: str


def verify_archive(
    archive: Path,
    config: CnIngestConfig,
    *,
    manifest: Path | None,
    sha256: str | None,
    release_tag: str | None,
) -> CnRelease:
    if not archive.is_file():
        raise IngestError(f"archive {archive} does not exist")
    if sha256 is not None:
        expected = _hash_value(sha256)
        if expected is None:
            raise IngestError("--sha256 must be 64 hexadecimal characters")
        origin = "owner_supplied"
    elif manifest is not None:
        expected = manifest_sha256(json.loads(manifest.read_text(encoding="utf-8")), archive.name)
        origin = "release_manifest"
    else:
        raise IngestError("the archive must be verified: give the release manifest or --sha256")
    actual = file_sha256(archive)
    if actual != expected:
        raise IngestError(f"archive SHA-256 {actual} does not match the expected {expected}")
    return CnRelease(archive, actual, release_tag, origin)


def fetch_release(config: CnIngestConfig, raw_dir: Path, release_tag: str) -> tuple[Path, Path]:
    """Download the archive and its manifest for a release tag into raw_dir/<tag>/."""
    base = config.release_url.format(tag=release_tag)
    folder = raw_dir / "investment_data" / release_tag
    archive, manifest = folder / config.archive_name, folder / config.manifest_name
    limit, timeout = config.max_archive_bytes, config.download_timeout_seconds
    download(f"{base}/{config.manifest_name}", manifest, 16 * _CHUNK, timeout)
    download(f"{base}/{config.archive_name}", archive, limit, timeout)
    return archive, manifest


def _benchmark(
    directory: QlibDirectory, config: CnIngestConfig, calendar: list[date]
) -> pl.DataFrame | None:
    try:
        index = directory.frame(config.benchmark_symbol, ["close"], calendar, ["close"])
    except QlibError:
        return None
    return index.sort(DATE).select(
        DATE, (pl.col("close") / pl.col("close").shift(1) - 1.0).alias("benchmark_ret")
    )


def read_release(
    directory: QlibDirectory, config: CnIngestConfig, release: CnRelease
) -> tuple[SnapshotData, SnapshotSource]:
    calendar = directory.calendar()
    membership = pl.concat([directory.membership(u) for u in config.universes])
    members = sorted(set(membership.get_column(INSTRUMENT).to_list()))
    available = set(directory.symbols())
    absent = [m for m in members if m not in available]
    fields = [*config.required_fields, *[f for f in config.optional_fields if f != "change"]]
    symbols = [m for m in members if m in available]
    if not symbols:
        raise IngestError("no universe member has feature data")
    found: list[JsonValue] = [*sorted(directory.fields(symbols[0]))]
    # Every panel column is computed per instrument, so building in batches of names
    # gives the same rows as one pass while bounding peak memory on the full history.
    parts: list[pl.DataFrame] = []
    for offset in range(0, len(symbols), PANEL_BATCH):
        batch = symbols[offset : offset + PANEL_BATCH]
        frames = [directory.frame(s, fields, calendar, config.required_fields) for s in batch]
        observations = pl.concat(frames, how="vertical_relaxed")
        if not observations.is_empty():
            members_batch = membership.filter(pl.col(INSTRUMENT).is_in(batch))
            parts.append(build_panel(observations, calendar, members_batch))
    if not parts:
        raise IngestError("no universe member has a traded close")
    panel = pl.concat(parts)
    del parts
    last_day = panel.get_column(DATE).max()
    assert isinstance(last_day, date)
    days = [d for d in calendar if d <= last_day]
    checks = sanity_checks(panel)
    checks["universe_members_without_data"] = len(absent)
    index = _benchmark(directory, config, days)
    if index is not None:
        benchmark_source = config.benchmark_symbol
        returns = index
    else:
        benchmark_source = f"equal_weight_{config.universes[0]}"
        returns = equal_weight_benchmark(panel, config.universes[0])
    calendar_frame = (
        pl.DataFrame({DATE: pl.Series(days, dtype=pl.Date)})
        .join(returns, on=DATE, how="left")
        .with_columns(pl.col("benchmark_ret").cast(pl.Float64))
        .sort(DATE)
    )
    first = panel.get_column(DATE).min()
    calendar_frame = calendar_frame.filter(pl.col(DATE) >= first)
    data = SnapshotData(panel=panel, membership=membership, calendar=calendar_frame)
    raw_share = checks["raw_close_share_in_range"]
    source = SnapshotSource(
        source="cn",
        release_tag=release.release_tag,
        archive_sha256=release.sha256,
        source_details={
            "provider": "chenditc/investment_data",
            "archive": release.archive.name,
            "checksum_from": release.expected_from,
            "universes": list[JsonValue](config.universes),
            "panel_instruments": "names in any configured universe at any date",
            "fields_found": found,
        },
        conventions={
            "prices": "adjusted; close_raw = close / factor",
            "raw_price_check": {"share_in_0.5_5000_cny": raw_share, "minimum": 0.99},
            "volume": "adjusted consistently with prices, as in the source",
            "vwap": "source vwap when present and positive, else (high + low + close) / 3",
            "suspended": "no row, no close, or zero volume; market fields null",
            "ret_1d": "adjusted close over the last traded adjusted close, minus 1",
            "limits": "main board 10%, STAR 20%, ChiNext 20% from 2020-08-24; "
            "reference is the last traded adjusted close divided by today's factor; "
            "ST (5%) is not detectable",
            "benchmark": benchmark_source,
            "calendar": "Qlib calendars/day.txt up to the last date with data",
        },
        checks=checks,
    )
    return data, source


def ingest_cn(
    config: CnIngestConfig,
    raw_dir: Path,
    *,
    archive: Path | None,
    manifest: Path | None,
    sha256: str | None,
    release_tag: str | None,
    logger: JsonLogger | None = None,
) -> tuple[SnapshotData, SnapshotSource]:
    log = logger.logger if logger is not None else None
    if archive is None:
        if release_tag is None:
            raise IngestError("give --archive or a --release-tag to download")
        archive, fetched = fetch_release(config, raw_dir, release_tag)
        manifest = manifest or fetched
        if log is not None:
            log.info("data_downloaded", outcome="ok", payload={"release_tag": release_tag})
    release = verify_archive(
        archive, config, manifest=manifest, sha256=sha256, release_tag=release_tag
    )
    if log is not None:
        log.info(
            "archive_verified",
            outcome="ok",
            payload={"sha256": release.sha256, "checksum_from": release.expected_from},
        )
    extracted = raw_dir / "extracted" / release.sha256
    if not extracted.is_dir():
        staging = extracted.with_name(f".{release.sha256}.{uuid.uuid4().hex}")
        try:
            safe_extract(release.archive, staging, config.max_extracted_bytes)
            staging.replace(extracted)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
    data, source = read_release(QlibDirectory.locate(extracted), config, release)
    if log is not None:
        log.info("data_checks_passed", outcome="ok", payload={"checks": source.checks})
    return data, source
