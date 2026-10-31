"""`just restore-drill`: restore the newest backup into a throwaway Compose project and run
BND-01, REG-01 and EVL-04 on it (PLAN Section 17.5). See qfr_mcp.drill for the steps.

The running stack is never touched: the drill uses its own project name, volumes and
network subnets, starts only postgres (plus one-off init-volumes, data-ingest and
eval-worker containers), and removes everything it created at the end.
"""

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from qfr_mcp.drill import DRILL_SUBNETS, Drill, latest_backup, report, verify_sums

root = Path(__file__).resolve().parents[1]
backups = Path(os.environ.get("QFR_BACKUPS_HOST_DIR") or root / "backups")
stamp = datetime.now(UTC).strftime("%Y%m%dt%H%M%Sz")
project = f"qfr-drill-{stamp}"
env = dict(
    line.split("=", 1)
    for line in (root / ".env").read_text().splitlines()
    if "=" in line and not line.startswith("#")
)
compose = [
    "docker", "compose", "--env-file", str(root / ".env"),
    "-f", str(root / "infra/docker-compose.yml"), "-p", project,
]  # fmt: skip
process_env = os.environ | DRILL_SUBNETS


def run(args, stdin=None):
    return subprocess.run(
        list(args), input=stdin, capture_output=True, env=process_env, check=False
    )


drill = Drill(env=env, compose=compose, run=run)
observations: dict[str, object] = {}
backup = latest_backup(backups)
try:
    if drill.check("backup_found", backup is not None, str(backups)) and backup is not None:
        errors = verify_sums(backup)
        if drill.check("backup_checksums", not errors, errors or backup.name):
            started = run([*compose, "up", "-d", "--wait", "postgres"])
            if drill.check(
                "throwaway_postgres", started.returncode == 0, started.stderr.decode()[-500:]
            ) and drill.restore(backup):
                drill.bnd_01()
                drill.reg_01()
                observations["row_counts"] = drill.row_counts()
                drill.evl_04(backups)
finally:
    removed = run([*compose, "down", "--volumes", "--remove-orphans"])
    drill.check("throwaway_removed", removed.returncode == 0, removed.stderr.decode()[-300:])

result = report(backup, drill.checks, observations, project)
directory = root / "exports/restore-drill"
directory.mkdir(parents=True, exist_ok=True)
destination = directory / f"{stamp}.json"
result["path"] = f"exports/restore-drill/{destination.name}"
destination.write_text(json.dumps(result, indent=2) + "\n")
# Logged by ops-nightly in the running stack, when it is up.
logged = subprocess.run(
    [*compose[:-2], "exec", "-T", "ops-nightly", "qfr", "ops", "record", "restore_drill"],
    input=json.dumps(result).encode(),
    capture_output=True,
    check=False,
)
result["logged"] = logged.returncode == 0
print(json.dumps(result, indent=2))
sys.exit(0 if result["status"] == "PASS" else 1)
