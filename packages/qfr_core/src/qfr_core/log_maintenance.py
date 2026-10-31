"""Nightly log compression, retention and the disk guard (PLAN Section 15.4, test LOG-04).

Day files older than compress_after_days are gzip-compressed in place; files older than
delete_after_days are deleted, compressed or not. Both thresholds are logging.yaml
settings and count whole days between a file's UTC date and today's. A compression is
written beside the original under a temporary name, synced and renamed, and only then
is the original removed, so a crash at any point leaves a readable day (the reader skips
an archive whose original still exists). The disk guard compares the volume's total
size with disk_warning_bytes.
"""

import gzip
import os
import shutil
from datetime import date
from pathlib import Path

from pydantic import Field

from qfr_core.config import LoggingConfig
from qfr_core.contracts import Contract
from qfr_core.log_reader import LOG_FILE

PARTIAL = ".partial"


class MaintenanceReport(Contract):
    today: date
    compressed: list[str] = Field(default_factory=list)
    deleted: list[str] = Field(default_factory=list)
    recovered: list[str] = Field(default_factory=list)
    files: int = 0
    volume_bytes: int = 0
    warning_bytes: int
    over_limit: bool = False


def _compress(path: Path) -> None:
    target = path.with_name(path.name + ".gz")
    staging = path.with_name(f".{path.name}.gz{PARTIAL}")
    with open(path, "rb") as source, open(staging, "wb") as raw:
        # mtime=0 keeps the archive a function of the content alone.
        with gzip.GzipFile(filename=path.name, mode="wb", fileobj=raw, mtime=0) as archive:
            shutil.copyfileobj(source, archive)
        raw.flush()
        os.fsync(raw.fileno())
    os.chmod(staging, 0o640)  # the same mode as the day files the services write
    os.replace(staging, target)
    path.unlink()


def _readable(archive: Path) -> bool:
    try:
        with gzip.open(archive, "rb") as stream:
            while stream.read(1 << 20):
                pass
        return True
    except (OSError, EOFError):
        return False


def maintain(root: Path, config: LoggingConfig, today: date) -> MaintenanceReport:
    """Compress, delete and measure every service directory under root."""
    report = MaintenanceReport(today=today, warning_bytes=config.disk_warning_bytes)
    root = root.resolve()
    if not root.is_dir():
        return report
    for service in sorted(root.iterdir()):
        if service.is_symlink() or not service.is_dir():
            continue
        for path in sorted(service.iterdir()):
            if path.is_symlink() or not path.is_file():
                continue
            relative = str(path.relative_to(root))
            if path.name.startswith(".") and path.name.endswith(PARTIAL):
                path.unlink()  # an interrupted compression; its original is still there
                continue
            match = LOG_FILE.match(path.name)
            if match is None:
                continue
            try:
                age = (today - date.fromisoformat(match.group(1))).days
            except ValueError:
                continue
            compressed = match.group(3) is not None
            if age > config.delete_after_days:
                path.unlink()
                report.deleted.append(relative)
                continue
            if compressed or age <= config.compress_after_days:
                continue
            archive = path.with_name(path.name + ".gz")
            if archive.exists() and _readable(archive):
                path.unlink()  # the archive was written before an interruption
                report.recovered.append(relative)
                continue
            _compress(path)
            report.compressed.append(relative)
    report.files, report.volume_bytes = measure(root)
    report.over_limit = report.volume_bytes > config.disk_warning_bytes
    return report


def measure(root: Path) -> tuple[int, int]:
    """Files and bytes in the service directories under root (the logs volume)."""
    files = size = 0
    if not root.is_dir():
        return files, size
    for service in root.iterdir():
        if service.is_symlink() or not service.is_dir():
            continue
        for path in service.iterdir():
            if path.is_file() and not path.is_symlink():
                files += 1
                size += path.stat().st_size
    return files, size
