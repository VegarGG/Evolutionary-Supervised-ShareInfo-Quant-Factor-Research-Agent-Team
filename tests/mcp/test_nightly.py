"""The ops-nightly job: schedule, log maintenance, the disk guard and the backup check
(PLAN Sections 15.4, 17.4 and 17.5), and the control_db tables it writes."""

import gzip
import io
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from qfr_core.config import logging_config
from qfr_core.ids import uuid7
from qfr_core.logging import JsonLogger
from qfr_mcp.control_store import AlertAck, MemoryControlStore, OpsAlert, PostgresControlStore
from qfr_mcp.nightly import COMPLETE, Schedule, backup_status, tick
from sqlalchemy.exc import DBAPIError

from tests.mcp.setup_rig import TransactionalControl
from tests.registry_rig import database_url

DEPLOYMENT = yaml.safe_load(Path("configs/deployment.yaml").read_text())
# 02:30 Asia/Shanghai is 18:30 UTC the previous day.
BEFORE = datetime(2026, 7, 1, 18, 0, tzinfo=UTC)
AFTER = datetime(2026, 7, 1, 18, 45, tzinfo=UTC)


def rig(tmp_path: Path, warning_bytes: int | None = None):
    logs = tmp_path / "logs"
    old = date(2026, 6, 1)
    path = logs / "eval-worker" / f"{old.isoformat()}.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"event": "old"}) + "\n")
    config = logging_config(Path("configs"))
    if warning_bytes is not None:
        config = config.model_copy(update={"disk_warning_bytes": warning_bytes})
    logger = JsonLogger("ops-nightly", "control", logs, config, stdout=io.StringIO())
    return logs, config, logger


def backup(root: Path, day: date, complete: bool = True) -> None:
    folder = root / day.isoformat()
    folder.mkdir(parents=True)
    if complete:
        (folder / COMPLETE).write_text("ok\n")


def test_schedule_runs_once_per_night_after_the_local_time(tmp_path):
    schedule = Schedule(DEPLOYMENT)
    assert schedule.at == (2, 30)
    assert schedule.due(AFTER).isoformat() == "2026-07-02T02:30:00+08:00"
    assert schedule.due(BEFORE).isoformat() == "2026-07-01T02:30:00+08:00"
    store = MemoryControlStore()
    logs, config, logger = rig(tmp_path)
    backups = tmp_path / "backups"
    backup(backups, date(2026, 7, 1))
    first = tick(store, logger, logs, backups, config, schedule, BEFORE)
    assert first is not None and first.due_at == schedule.due(BEFORE)
    assert (
        tick(store, logger, logs, backups, config, schedule, BEFORE + timedelta(minutes=5)) is None
    )
    second = tick(store, logger, logs, backups, config, schedule, AFTER)
    assert second is not None and second.due_at == schedule.due(AFTER)
    assert len(store.runs) == 2
    # The month-old day file was compressed by the first run.
    assert (logs / "eval-worker" / "2026-06-01.jsonl.gz").exists()
    report = first.report
    assert report["logs"]["compressed"] == ["eval-worker/2026-06-01.jsonl"]  # type: ignore[index]
    assert report["backup"]["status"] == "ok" and not report["alerts"]  # type: ignore[index]
    events = [
        json.loads(x)["event"]
        for p in sorted((logs / "ops-nightly").iterdir())
        for x in (gzip.decompress(p.read_bytes()) if p.suffix == ".gz" else p.read_bytes())
        .decode()
        .splitlines()
    ]
    assert events.count("nightly_completed") == 2 and "logs_maintained" in events


def test_disk_guard_alerts_once_until_acknowledged(tmp_path):
    store = MemoryControlStore()
    logs, config, logger = rig(tmp_path, warning_bytes=10)
    schedule = Schedule(DEPLOYMENT)
    run = tick(store, logger, logs, None, config, schedule, BEFORE)
    assert run is not None and run.report["logs"]["over_limit"] is True  # type: ignore[index]
    assert run.report["backup"] == {"status": "not_configured", "fresh": None}
    [alert] = store.alerts
    assert alert.kind == "disk" and alert.dedup_key == "disk:2026-07-01"
    assert alert.details["volume_bytes"] == run.report["logs"]["volume_bytes"]  # type: ignore[index]
    # Still over the limit the next night, but the first alert is open: no second alert.
    tick(store, logger, logs, None, config, schedule, AFTER)
    assert len(store.alerts) == 1
    store.acknowledge(
        AlertAck(
            ack_id=uuid7(), source="operations", alert_id=alert.alert_id, at=AFTER,
            principal="owner", request_id="r",
        )
    )  # fmt: skip
    tick(store, logger, logs, None, config, schedule, AFTER + timedelta(days=1))
    assert [a.dedup_key for a in store.alerts] == ["disk:2026-07-01", "disk:2026-07-03"]


def test_backup_check_reads_complete_dated_folders_only(tmp_path):
    root = tmp_path / "backups"
    today = date(2026, 7, 2)
    assert backup_status(None, today, 2)["status"] == "not_configured"
    assert backup_status(root, today, 2) == {"status": "missing", "fresh": False, "path": str(root)}
    backup(root, date(2026, 6, 28))
    backup(root, date(2026, 7, 2), complete=False)  # tonight's dump still running
    (root / "snapshots").mkdir()
    stale = backup_status(root, today, 2)
    assert stale["status"] == "stale" and stale["latest"] == "2026-06-28"
    assert stale["age_days"] == 4 and stale["complete"] == 1
    backup(root, date(2026, 6, 30))
    assert backup_status(root, today, 2)["fresh"] is True
    store = MemoryControlStore()
    logs, config, logger = rig(tmp_path)
    empty = tmp_path / "no-backups-yet"
    empty.mkdir()
    run = tick(store, logger, logs, empty, config, Schedule(DEPLOYMENT), AFTER)
    assert run is not None and run.report["backup"]["status"] == "none"  # type: ignore[index]
    assert [a.kind for a in store.alerts] == ["backup"]


@pytest.mark.postgres
def test_operations_tables_are_insert_only_and_deduplicated(tmp_path):
    control = TransactionalControl(database_url("CONTROL"))
    try:
        store = PostgresControlStore(begin=control.begin)
        alert = OpsAlert(
            alert_id=uuid7(), kind="backup", dedup_key="backup:2026-07-02", at=AFTER,
            details={"status": "stale"}, principal="ops-nightly", request_id="r",
        )  # fmt: skip
        assert store.raise_ops_alert(alert)
        assert not store.raise_ops_alert(alert.model_copy(update={"alert_id": uuid7()}))
        assert [a.alert_id for a in store.ops_alerts(10)] == [alert.alert_id]
        ack = AlertAck(
            ack_id=uuid7(), source="operations", alert_id=alert.alert_id, at=AFTER,
            note="seen", principal="owner", request_id="r",
        )  # fmt: skip
        assert store.acknowledge(ack) == ack
        again = store.acknowledge(ack.model_copy(update={"ack_id": uuid7(), "note": "twice"}))
        assert again.ack_id == ack.ack_id and again.note == "seen"
        assert store.acks("operations", [alert.alert_id]) == {alert.alert_id: ack}
        assert store.acks("research", [alert.alert_id]) == {}
        logs, config, logger = rig(tmp_path)
        run = tick(store, logger, logs, None, config, Schedule(DEPLOYMENT), AFTER)
        assert run is not None and store.latest_ops_run() == run
        for table in ("ops_alerts", "alert_acks", "ops_runs", "deliveries"):
            with pytest.raises(DBAPIError, match="permission denied|append-only"):
                with control.begin() as conn:
                    conn.exec_driver_sql(f"DELETE FROM {table}")
    finally:
        control.close()


def test_host_side_reports_are_logged_by_ops_nightly(tmp_path, monkeypatch):
    """`just doctor` and `just restore-drill` log their result through ops-nightly."""
    from qfr_mcp.nightly import ops_app
    from typer.testing import CliRunner

    monkeypatch.setenv("QFR_LOG_DIR", str(tmp_path))
    report = {
        "status": "FAIL",
        "at": "2026-10-31T00:00:00+00:00",
        "path": "exports/restore-drill/x.json",
        "backup": "2026-10-30",
        "checks": [{"check": "BND-01:x", "status": "FAIL"}, {"check": "y", "status": "PASS"}],
        "skipped": ["EVL-04"],
    }
    # A one-command Typer app is invoked without the command name (`qfr ops record` in
    # the image, where the qfr CLI mounts it as a group).
    done = CliRunner().invoke(ops_app, ["restore_drill"], input=json.dumps(report))
    assert done.exit_code == 0, done.output
    (log,) = (tmp_path / "ops-nightly").glob("*.jsonl")
    (line,) = [json.loads(x) for x in log.read_text().splitlines()]
    assert (line["event"], line["level"], line["outcome"]) == (
        "restore_drill_completed", "WARNING", "failed",
    )  # fmt: skip
    assert line["payload"]["failed_checks"] == ["BND-01:x"]
    assert line["payload"]["skipped"] == ["EVL-04"]
    refused = CliRunner().invoke(ops_app, ["anything"], input="{}")
    assert refused.exit_code != 0


def test_rotating_the_mcp_token_replaces_only_that_line(tmp_path):
    import os
    import shutil
    import subprocess
    import sys

    (tmp_path / "scripts").mkdir()
    shutil.copy("scripts/ops.py", tmp_path / "scripts/ops.py")
    env_file = tmp_path / ".env"
    env_file.write_text("A=1\nQFR_MCP_TOKEN=old\nZ=2\n")
    done = subprocess.run(
        [sys.executable, str(tmp_path / "scripts/ops.py"), "rotate-mcp-token"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    lines = env_file.read_text().splitlines()
    assert lines[0] == "A=1" and lines[2] == "Z=2"
    assert lines[1].startswith("QFR_MCP_TOKEN=") and lines[1] != "QFR_MCP_TOKEN=old"
    assert lines[1].split("=", 1)[1] not in done.stdout  # the token is never printed
    assert os.stat(env_file).st_mode & 0o777 == 0o600
