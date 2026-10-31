"""The nightly backup script (infra/backup/backup.sh, PLAN Section 17.5): retention, the
snapshot mirror and a real pg_dump of the test databases."""

import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from qfr_core.contracts import LogLine
from qfr_mcp.drill import latest_backup, verify_sums

SCRIPT = Path("infra/backup/backup.sh").resolve()


def run(arguments, **env):
    return subprocess.run(
        ["bash", str(SCRIPT), *arguments],
        env={"PATH": os.environ["PATH"], "TZ": "Asia/Shanghai"} | env,
        capture_output=True,
        text=True,
        check=False,
    )


def days(start: date, end: date) -> list[str]:
    return [(start + timedelta(n)).isoformat() for n in range((end - start).days + 1)]


def test_retention_keeps_30_daily_and_the_first_backup_of_12_months(tmp_path):
    every = days(date(2025, 1, 1), date(2026, 10, 31))
    for day in every:
        (tmp_path / day).mkdir()
        (tmp_path / day / "COMPLETE").write_text("x")
    (tmp_path / "2026-11-01").mkdir()  # no COMPLETE marker: never counted or removed
    (tmp_path / "snapshots" / "full").mkdir(parents=True)
    done = run(
        ["prune"],
        QFR_BACKUPS_DIR=str(tmp_path),
        QFR_LOG_DIR=str(tmp_path / "logs"),
        QFR_BACKUP_DAILY_RETENTION="30",
        QFR_BACKUP_MONTHLY_RETENTION="12",
    )
    assert done.returncode == 0, done.stderr
    kept = sorted(p.name for p in tmp_path.iterdir() if re.match(r"\d{4}-", p.name))
    daily = every[-30:]
    monthly = [
        f"{y}-{m:02d}-01" for y, m in [(2025, 11), (2025, 12)] + [(2026, m) for m in range(1, 11)]
    ]
    assert kept == sorted(set(daily) | set(monthly) | {"2026-11-01"})
    assert json.loads(done.stdout) == {"pruned": len(every) - len(set(daily) | set(monthly))}
    assert (tmp_path / "snapshots" / "full").is_dir()


def test_retention_with_fewer_backups_than_the_policy_keeps_them_all(tmp_path):
    for day in ("2026-10-29", "2026-10-30"):
        (tmp_path / day).mkdir()
        (tmp_path / day / "COMPLETE").write_text("x")
    done = run(
        ["prune"],
        QFR_BACKUPS_DIR=str(tmp_path),
        QFR_BACKUP_DAILY_RETENTION="30",
        QFR_BACKUP_MONTHLY_RETENTION="12",
    )
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == {"pruned": 0}
    assert sorted(p.name for p in tmp_path.iterdir()) == ["2026-10-29", "2026-10-30"]


def _server_major(url: str) -> int:
    import psycopg

    with psycopg.connect(url.replace("postgresql+psycopg://", "postgresql://")) as conn:
        return int(str(conn.execute("SHOW server_version_num").fetchone()[0])) // 10000


@pytest.mark.postgres
def test_a_backup_dumps_checksums_mirrors_and_logs(tmp_path):
    registry = os.environ.get("QFR_TEST_REGISTRY_MIGRATION_URL")
    control = os.environ.get("QFR_TEST_CONTROL_MIGRATION_URL")
    if not registry or not control:
        if os.environ.get("QFR_REQUIRE_DB_TESTS") == "1":
            pytest.fail("the registry and control migration URLs are required")
        pytest.skip("migration credentials not configured")
    pg_dump = shutil.which("pg_dump")
    if pg_dump is None:
        pytest.skip("pg_dump is not installed; the backup image carries its own")
    version = subprocess.run([pg_dump, "--version"], capture_output=True, text=True).stdout
    found = re.match(r"pg_dump \(PostgreSQL\) (\d+)", version)
    if found is None or int(found.group(1)) < _server_major(registry):
        pytest.skip(f"{version.strip()} is older than the test server")

    backups, logs, full, store = (tmp_path / n for n in ("backups", "logs", "full", "store"))
    (logs / "qfr-mcp").mkdir(parents=True)
    (logs / "qfr-mcp" / "2026-10-30.jsonl").write_text("{}\n")
    (full / "snap-a").mkdir(parents=True)
    (full / "snap-a" / "prices.parquet").write_bytes(b"prices")
    (full / "snap-a" / ".prices.parquet.tmp").write_bytes(b"staging")
    (store / "series").mkdir(parents=True)
    (store / "series" / "nav.parquet").write_bytes(b"nav")
    (store / "scratch").mkdir()
    (store / "scratch" / "work").write_bytes(b"scratch")
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    earlier = today.replace(day=1)
    if earlier != today:
        # An earlier complete backup this month: today's is not the month's first.
        (backups / earlier.isoformat()).mkdir(parents=True)
        (backups / earlier.isoformat() / "COMPLETE").write_text("x")
    env = {
        "QFR_BACKUPS_DIR": str(backups),
        "QFR_LOG_DIR": str(logs / "backup"),
        "QFR_LOG_VOLUME": str(logs),
        "QFR_MIRROR_SOURCES": f"full={full} eval_store={store} research={tmp_path / 'none'}",
        "QFR_BACKUP_DATABASES": "registry_db=QFR_TEST_REGISTRY_MIGRATION_URL "
        "control_db=QFR_TEST_CONTROL_MIGRATION_URL",
        "QFR_TEST_REGISTRY_MIGRATION_URL": registry,
        "QFR_TEST_CONTROL_MIGRATION_URL": control,
        "QFR_BACKUP_DAILY_RETENTION": "30",
        "QFR_BACKUP_MONTHLY_RETENTION": "12",
    }
    done = run(["now"], **env)
    assert done.returncode == 0, done.stderr

    folder = backups / today.isoformat()
    assert latest_backup(backups) == folder
    names = {p.name for p in folder.iterdir()}
    assert {"registry_db.dump", "control_db.dump", "SHA256SUMS", "COMPLETE"} <= names
    assert ("logs.tar.gz" in names) == (earlier == today)
    assert not list(backups.glob(".*.partial"))
    # The drill's checker reads the same sums; it also wants the two other dumps.
    errors = verify_sums(folder)
    assert errors == ["research_db.dump is not in the backup", "eval_db.dump is not in the backup"]
    for line in (folder / "SHA256SUMS").read_text().splitlines():
        digest, _, name = line.partition("  ")
        assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == digest
    if pg_restore := shutil.which("pg_restore"):
        listed = subprocess.run([pg_restore, "--list", str(folder / "registry_db.dump")],
                                capture_output=True, text=True)  # fmt: skip
        assert listed.returncode == 0 and "artifact_versions" in listed.stdout

    # The mirror copies new files, never hidden staging files or the store's scratch.
    mirror = backups / "snapshots"
    assert (mirror / "full" / "snap-a" / "prices.parquet").read_bytes() == b"prices"
    assert not (mirror / "full" / "snap-a" / ".prices.parquet.tmp").exists()
    assert (mirror / "eval_store" / "series" / "nav.parquet").exists()
    assert not (mirror / "eval_store" / "scratch").exists()

    # Each line is a LogLine; the completion line says what was done.
    lines = [
        json.loads(line)
        for path in (logs / "backup").glob("*.jsonl")
        for line in path.read_text().splitlines()
    ]
    for line in lines:
        LogLine.model_validate(line)
    completed = next(line for line in lines if line["event"] == "backup_completed")
    assert completed["payload"]["mirrored"] == {"full": 1, "eval_store": 1, "research": 0}
    assert completed["payload"]["day"] == today.isoformat()

    # A second run copies only what changed and replaces today's folder.
    (full / "snap-b").mkdir()
    (full / "snap-b" / "prices.parquet").write_bytes(b"newer")
    again = run(["now"], **env)
    assert again.returncode == 0, again.stderr
    lines = [
        json.loads(line)
        for path in (logs / "backup").glob("*.jsonl")
        for line in path.read_text().splitlines()
    ]
    last = [line for line in lines if line["event"] == "backup_completed"][-1]
    assert last["payload"]["mirrored"] == {"full": 1, "eval_store": 0, "research": 0}


def test_a_failed_dump_leaves_no_dated_folder_and_logs_the_failure(tmp_path):
    done = run(
        ["now"],
        QFR_BACKUPS_DIR=str(tmp_path / "backups"),
        QFR_LOG_DIR=str(tmp_path / "logs"),
        QFR_LOG_VOLUME=str(tmp_path / "none"),
        QFR_MIRROR_SOURCES="",
        QFR_BACKUP_DATABASES="registry_db=QFR_MISSING_URL",
        QFR_BACKUP_DAILY_RETENTION="30",
        QFR_BACKUP_MONTHLY_RETENTION="12",
    )
    assert done.returncode != 0
    assert "QFR_MISSING_URL is not set" in done.stderr
    assert latest_backup(tmp_path / "backups") is None
    (log,) = (tmp_path / "logs").glob("*.jsonl")
    events = [json.loads(line)["event"] for line in log.read_text().splitlines()]
    assert events == ["backup_started", "backup_failed"]
