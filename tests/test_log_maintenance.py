"""LOG-04 and the Phase 7 log reader: compression, retention, the disk guard, searches
over compressed days, tail, correlate's default range and export (PLAN Section 15)."""

import gzip
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from qfr_core.config import logging_config, mcp_config
from qfr_core.log_maintenance import maintain
from qfr_core.log_reader import LogQuery, LogReader, log_files

TODAY = date(2026, 6, 30)
NOW = datetime(2026, 6, 30, 12, tzinfo=UTC)


def line(at: datetime, service: str, event: str, **ids: str) -> str:
    row = {
        "ts": at.isoformat(),
        "level": "INFO",
        "service": service,
        "zone": "control",
        "event": event,
        "request_id": ids.pop("request_id", "r-" + event),
        **ids,
    }
    return json.dumps(row, sort_keys=True) + "\n"


def write_day(root: Path, service: str, day: date, lines: list[str], suffix: str = "") -> Path:
    path = root / service / f"{day.isoformat()}{suffix}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(lines))
    return path


def reader(root: Path, **logging_overrides: object) -> LogReader:
    config = logging_config(Path("configs")).model_copy(update=logging_overrides)
    return LogReader(root, config, mcp_config(Path("configs")))


def test_log_04_compression_after_7_days_and_deletion_after_180(tmp_path):
    config = logging_config(Path("configs"))
    assert (config.compress_after_days, config.delete_after_days) == (7, 180)
    ages = [0, 7, 8, 30, 180, 181, 400]
    for age in ages:
        day = TODAY - timedelta(days=age)
        at = datetime.combine(day, datetime.min.time(), UTC) + timedelta(hours=1)
        write_day(tmp_path, "eval-worker", day, [line(at, "eval-worker", f"age_{age}")])
    (tmp_path / "eval-worker" / "notes.txt").write_text("not a log file")
    report = maintain(tmp_path, config, TODAY)
    names = sorted(p.name for p in (tmp_path / "eval-worker").iterdir())
    day = {age: (TODAY - timedelta(days=age)).isoformat() for age in ages}
    assert names == sorted(
        [
            f"{day[0]}.jsonl",
            f"{day[7]}.jsonl",
            f"{day[8]}.jsonl.gz",
            f"{day[30]}.jsonl.gz",
            f"{day[180]}.jsonl.gz",
            "notes.txt",
        ]
    )
    assert sorted(report.compressed) == sorted(f"eval-worker/{day[a]}.jsonl" for a in (8, 30, 180))
    assert sorted(report.deleted) == sorted(f"eval-worker/{day[a]}.jsonl" for a in (181, 400))
    archive = tmp_path / "eval-worker" / f"{day[30]}.jsonl.gz"
    assert json.loads(gzip.decompress(archive.read_bytes()))["event"] == "age_30"
    assert archive.stat().st_mode & 0o777 == 0o640
    # A second run changes nothing; a compressed day ages into deletion like a plain one.
    again = maintain(tmp_path, config, TODAY)
    assert not again.compressed and not again.deleted
    later = maintain(tmp_path, config, TODAY + timedelta(days=1))
    assert later.deleted == [f"eval-worker/{day[180]}.jsonl.gz"]


def test_log_04_rotated_parts_compress_and_interrupted_runs_recover(tmp_path):
    config = logging_config(Path("configs"))
    old = TODAY - timedelta(days=10)
    at = datetime.combine(old, datetime.min.time(), UTC)
    first = write_day(tmp_path, "cli", old, [line(at, "cli", "a")])
    part = write_day(tmp_path, "cli", old, [line(at, "cli", "b")], ".part1")
    # A crash after the archive was written but before the original was removed.
    archive = first.with_name(first.name + ".gz")
    archive.write_bytes(gzip.compress(first.read_bytes()))
    # A crash halfway through writing an archive.
    stray = tmp_path / "cli" / f".{part.name}.gz.partial"
    stray.write_bytes(b"\x1f\x8b broken")
    assert [p.name for _, p in log_files(tmp_path)] == [first.name, part.name]
    report = maintain(tmp_path, config, TODAY)
    assert report.recovered == [f"cli/{first.name}"]
    assert report.compressed == [f"cli/{part.name}"]
    assert sorted(p.name for p in (tmp_path / "cli").iterdir()) == [
        archive.name,
        part.name + ".gz",
    ]


def test_disk_guard_measures_the_whole_volume(tmp_path):
    write_day(tmp_path, "a", TODAY, ["x" * 600 + "\n"])
    write_day(tmp_path, "b", TODAY, ["y" * 600 + "\n"])
    config = logging_config(Path("configs"))
    assert config.disk_warning_bytes == 20 * 1024**3
    report = maintain(tmp_path, config.model_copy(update={"disk_warning_bytes": 1000}), TODAY)
    assert (report.files, report.volume_bytes, report.over_limit) == (2, 1202, True)
    assert not maintain(tmp_path, config, TODAY).over_limit
    assert maintain(tmp_path / "missing", config, TODAY).files == 0


def test_search_reads_compressed_days_in_order_and_stops_early(tmp_path):
    days = [TODAY - timedelta(days=d) for d in (12, 9, 2)]
    for index, day in enumerate(days):
        at = datetime.combine(day, datetime.min.time(), UTC)
        write_day(
            tmp_path, "research-api", day,
            [line(at + timedelta(minutes=m), "research-api", f"d{index}m{m}", job_id="J")
             for m in range(3)],
        )  # fmt: skip
    maintain(tmp_path, logging_config(Path("configs")), TODAY)
    assert sum(1 for p in (tmp_path / "research-api").iterdir() if p.suffix == ".gz") == 2
    logs = reader(tmp_path)
    query = LogQuery.model_validate(
        {"from": (NOW - timedelta(days=13)).isoformat(), "to": NOW.isoformat(), "limit": 2}
    )
    first = logs.search(query, NOW)
    assert [x.event for x in first.lines] == ["d0m0", "d0m1"]
    # Only the first day was read: a later day holds only later lines.
    assert first.scanned == 3
    events = [x.event for x in first.lines]
    cursor = first.next_cursor
    while cursor:
        page = logs.search(query.model_copy(update={"cursor": cursor}), NOW)
        events += [x.event for x in page.lines]
        cursor = page.next_cursor
    assert events == [f"d{d}m{m}" for d in range(3) for m in range(3)]
    # The prefilter skips lines without the id before parsing them.
    none = logs.search(query.model_copy(update={"ids": {"job_id": "other"}}), NOW)
    assert not none.lines and none.malformed == 0


def test_tail_reads_newest_days_first(tmp_path):
    for back in (3, 2, 1):
        day = TODAY - timedelta(days=back)
        at = datetime.combine(day, datetime.min.time(), UTC)
        write_day(tmp_path, "cli", day, [line(at, "cli", f"b{back}")])
    page = reader(tmp_path).tail("cli", 1)
    assert [x.event for x in page.lines] == ["b1"] and page.scanned == 1
    assert [x.event for x in reader(tmp_path).tail(None, 2).lines] == ["b2", "b1"]


def test_correlate_reads_a_month_without_dates(tmp_path):
    days = (25, 3)
    for back in days:
        day = TODAY - timedelta(days=back)
        at = datetime.combine(day, datetime.min.time(), UTC)
        write_day(
            tmp_path, "eval-worker" if back == 3 else "research-api", day,
            [line(at, "x", f"step{back}", job_id="J1"), line(at, "x", "other", job_id="J2")],
        )  # fmt: skip
    logs = reader(tmp_path)
    correlated = logs.correlate("J1", "job", LogQuery(), NOW)
    # The default range is correlate_default_days, not the 24-hour search default.
    assert [x["event"] for x in correlated["lines"]] == ["step25", "step3"]  # type: ignore[index]
    assert correlated["timeline"] == "x:step25 → x:step3"
    # Explicit long ranges still need both dates.
    with pytest.raises(ValueError, match="explicit dates"):
        logs.search(LogQuery.model_validate({"from": "2000-01-01T00:00:00Z"}))
    with pytest.raises(ValueError, match="unsupported id kind"):
        logs.correlate("J1", "secret", LogQuery())


def test_export_writes_a_gzip_slice_atomically_and_reports_truncation(tmp_path):
    root = tmp_path / "logs"
    at = NOW - timedelta(hours=1)
    write_day(
        root, "qfr-mcp", TODAY,
        [line(at + timedelta(seconds=s), "qfr-mcp", f"e{s}", job_id="J") for s in range(5)],
    )  # fmt: skip
    target = tmp_path / "exports" / "logs" / "slice.jsonl.gz"
    full = reader(root).export(LogQuery(ids={"job_id": "J"}), target, NOW)
    assert full["lines"] == 5 and not full["truncated"] and full["next_cursor"] is None
    rows = [json.loads(x) for x in gzip.decompress(target.read_bytes()).splitlines()]
    assert [r["event"] for r in rows] == [f"e{s}" for s in range(5)]
    assert not list(target.parent.glob(".*"))
    capped = reader(root, export_max_lines=3)
    first = capped.export(LogQuery(ids={"job_id": "J"}), target, NOW)
    assert first["lines"] == 3 and first["truncated"]
    rest = capped.export(
        LogQuery(ids={"job_id": "J"}, cursor=str(first["next_cursor"])), target, NOW
    )
    assert rest["lines"] == 2 and not rest["truncated"]
    rows = [json.loads(x) for x in gzip.decompress(target.read_bytes()).splitlines()]
    assert [r["event"] for r in rows] == ["e3", "e4"]
