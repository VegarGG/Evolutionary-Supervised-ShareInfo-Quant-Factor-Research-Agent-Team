"""Run the suite against this project's isolated, disposable PostgreSQL instance."""

import os
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
values = dict(
    line.split("=", 1) for line in (root / ".env").read_text().splitlines() if "=" in line
)
subprocess.run(
    [
        "docker",
        "compose",
        "--env-file",
        ".env",
        "-f",
        "infra/docker-compose.ci.yml",
        "up",
        "-d",
        "--wait",
        "postgres",
    ],
    cwd=root,
    check=True,
)
env = os.environ | {
    "QFR_REQUIRE_DB_TESTS": "1",
    "QFR_LOG_DIR": str(root / "exports/test-db-logs"),
}
for name in ("REGISTRY", "RESEARCH", "EVAL", "CONTROL"):
    env[name + "_MIGRATION_URL"] = values[name + "_MIGRATION_URL"].replace(
        "@postgres:5432/", "@127.0.0.1:55433/"
    )
subprocess.run([sys.executable, "scripts/migrate.py"], env=env, cwd=root, check=True)
for name in ("REGISTRY", "RESEARCH", "EVAL", "FEEDBACK", "CONTROL"):
    env["QFR_TEST_" + name + "_DB_URL"] = values[name + "_DB_URL"].replace(
        "@postgres:5432/", "@127.0.0.1:55433/"
    )
env["QFR_TEST_CONTROL_MIGRATION_URL"] = env["CONTROL_MIGRATION_URL"]
env["QFR_TEST_REGISTRY_MIGRATION_URL"] = env["REGISTRY_MIGRATION_URL"]
result = subprocess.run(
    [sys.executable, "-m", "pytest", "--junitxml=exports/pytest-postgres.xml"],
    env=env,
    cwd=root,
)
raise SystemExit(result.returncode)
