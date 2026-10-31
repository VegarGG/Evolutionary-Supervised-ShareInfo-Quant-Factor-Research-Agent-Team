"""The nightly operations job (PLAN Sections 15.4, 17.4 and 17.5), run by ops-nightly.

After deployment.yaml's nightly time (02:30 Asia/Shanghai) it runs once per day:

  1. log compression and retention over the whole logs volume (LOG-04);
  2. the disk guard: a WARNING line and an operations alert when the volume is over
     logging.yaml's disk_warning_bytes;
  3. the backup check: an operations alert when the newest complete backup under
     backups/ is older than deployment.yaml's backup.stale_after_days.

An alert is raised at most once a day and not again while an earlier alert of the same
kind is unacknowledged. Each run is recorded in control_db's ops_runs, which qfr.status
reads. The service holds the control role only: it reads the backups folder, never a
database dump, and it writes nothing but log files and control_db rows.
"""

import os
import re
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml
from pydantic import JsonValue
from qfr_core.config import LoggingConfig, RuntimeSettings, logging_config
from qfr_core.correlation import bind, current
from qfr_core.ids import uuid7
from qfr_core.log_maintenance import maintain
from qfr_core.logging import JsonLogger, env_secrets

from qfr_mcp.control_store import (
    ControlStore,
    OpsAlert,
    OpsAlertKind,
    OpsRun,
    PostgresControlStore,
)

SERVICE = "ops-nightly"
PRINCIPAL = "ops-nightly"
BACKUP_DIR = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# The backup script writes this file last, after every dump and its checksum.
COMPLETE = "COMPLETE"


class Schedule:
    def __init__(self, deployment: dict[str, Any]) -> None:
        self.tz = ZoneInfo(str(deployment["timezone"]))
        hour, minute = (int(x) for x in str(deployment["schedule"]["nightly_local"]).split(":"))
        self.at = (hour, minute)
        self.stale_after_days = int(deployment["backup"]["stale_after_days"])

    def due(self, now: datetime) -> datetime:
        """The latest nightly time at or before now."""
        local = now.astimezone(self.tz)
        hour, minute = self.at
        due = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if local < due:
            due -= timedelta(days=1)
        return due


def backup_status(root: Path | None, today: date, stale_after_days: int) -> dict[str, JsonValue]:
    """The newest complete dated backup folder and whether it is recent enough."""
    if root is None:
        return {"status": "not_configured", "fresh": None}
    if not root.is_dir():
        return {"status": "missing", "fresh": False, "path": str(root)}
    complete = sorted(
        p.name
        for p in root.iterdir()
        if BACKUP_DIR.match(p.name) and p.is_dir() and (p / COMPLETE).is_file()
    )
    if not complete:
        return {"status": "none", "fresh": False, "complete": 0}
    latest = complete[-1]
    age = (today - date.fromisoformat(latest)).days
    fresh = age <= stale_after_days
    return {
        "status": "ok" if fresh else "stale",
        "fresh": fresh,
        "latest": latest,
        "age_days": age,
        "complete": len(complete),
        "stale_after_days": stale_after_days,
    }


def _alert(
    store: ControlStore,
    logger: JsonLogger,
    kind: OpsAlertKind,
    today: date,
    details: dict[str, JsonValue],
    now: datetime,
) -> str | None:
    """Raise the day's alert of this kind unless one is still unacknowledged."""
    earlier = [a for a in store.ops_alerts(200) if a.kind == kind]
    acked = store.acks("operations", [a.alert_id for a in earlier])
    if any(a.alert_id not in acked for a in earlier):
        return None
    alert = OpsAlert(
        alert_id=uuid7(),
        kind=kind,
        dedup_key=f"{kind}:{today.isoformat()}",
        at=now,
        details=details,
        principal=PRINCIPAL,
        request_id=current()["request_id"],
    )
    if not store.raise_ops_alert(alert):
        return None
    logger.logger.warning(
        "alert_raised", outcome="ok", payload={"kind": kind, "alert_id": str(alert.alert_id)}
    )
    return str(alert.alert_id)


def run_nightly(
    store: ControlStore,
    logger: JsonLogger,
    log_root: Path,
    backups: Path | None,
    config: LoggingConfig,
    schedule: Schedule,
    now: datetime,
) -> OpsRun:
    """One nightly pass. Log day files are named by UTC date, so retention ages count UTC
    days; backup folders are named by local date."""
    with bind():
        return _run(store, logger, log_root, backups, config, schedule, now)


def _run(
    store: ControlStore,
    logger: JsonLogger,
    log_root: Path,
    backups: Path | None,
    config: LoggingConfig,
    schedule: Schedule,
    now: datetime,
) -> OpsRun:
    log = logger.logger
    due = schedule.due(now)
    maintenance = maintain(log_root, config, now.astimezone(UTC).date())
    log.info(
        "logs_maintained",
        outcome="ok",
        payload={
            "compressed": len(maintenance.compressed),
            "deleted": len(maintenance.deleted),
            "recovered": len(maintenance.recovered),
            "files": maintenance.files,
            "volume_bytes": maintenance.volume_bytes,
        },
    )
    alerts: dict[str, JsonValue] = {}
    if maintenance.over_limit:
        log.warning(
            "disk_guard_exceeded",
            outcome="failed",
            payload={
                "volume_bytes": maintenance.volume_bytes,
                "warning_bytes": maintenance.warning_bytes,
            },
        )
        alerts["disk"] = _alert(
            store, logger, "disk", due.date(),
            {"volume": "qfr_logs", "volume_bytes": maintenance.volume_bytes,
             "warning_bytes": maintenance.warning_bytes},
            now,
        )  # fmt: skip
    backup = backup_status(backups, due.date(), schedule.stale_after_days)
    if backup["fresh"] is False:
        log.warning("backup_stale", outcome="failed", payload=backup)
        alerts["backup"] = _alert(store, logger, "backup", due.date(), backup, now)
    report: dict[str, JsonValue] = {
        "logs": maintenance.model_dump(mode="json"),
        "backup": backup,
        "alerts": alerts,
    }
    run = OpsRun(
        run_id=uuid7(),
        at=now,
        kind="nightly",
        due_at=due,
        report=report,
        request_id=current()["request_id"],
    )
    store.append_ops_run(run)
    log.info("nightly_completed", outcome="ok", payload={"due_at": due.isoformat()})
    return run


def tick(
    store: ControlStore,
    logger: JsonLogger,
    log_root: Path,
    backups: Path | None,
    config: LoggingConfig,
    schedule: Schedule,
    now: datetime,
) -> OpsRun | None:
    """Run the nightly pass when this night's has not run yet."""
    last = store.latest_ops_run()
    if last is not None and last.due_at >= schedule.due(now):
        return None
    return run_nightly(store, logger, log_root, backups, config, schedule, now)


def main() -> None:
    settings = RuntimeSettings(service=SERVICE, zone="control")
    if settings.control_db_url is None:
        raise ValueError("CONTROL_DB_URL is required")
    config = logging_config(settings.config_dir)
    if settings.log_level:
        config = config.model_copy(update={"level": settings.log_level})
    logger = JsonLogger(
        SERVICE, "control", settings.log_dir, config,
        secrets=env_secrets(os.environ),
    )  # fmt: skip
    deployment = yaml.safe_load((settings.config_dir / "deployment.yaml").read_text())
    schedule = Schedule(deployment)
    store = PostgresControlStore(settings.control_db_url.get_secret_value())
    log_root = Path(os.environ.get("QFR_LOG_VOLUME") or "/var/log/qfr")
    backups = Path(b) if (b := os.environ.get("QFR_BACKUPS_DIR")) else None
    beat = Path(os.environ.get("QFR_HEARTBEAT_FILE") or "/tmp/heartbeat")
    poll = float(os.environ.get("QFR_NIGHTLY_POLL_SECONDS") or 60)
    logger.logger.info("service_started", payload={"phase": 7, "nightly": schedule.at})
    while True:
        try:
            tick(store, logger, log_root, backups, config, schedule, datetime.now(UTC))
        except Exception as error:  # noqa: BLE001 - logged, retried next poll
            logger.logger.error("nightly_failed", outcome="failed", error_code=type(error).__name__)
        beat.parent.mkdir(parents=True, exist_ok=True)
        beat.touch()
        time.sleep(poll)


if __name__ == "__main__":
    main()
