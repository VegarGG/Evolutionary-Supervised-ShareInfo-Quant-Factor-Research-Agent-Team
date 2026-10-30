"""Bootstrap the disposable CI Postgres service; never used on an existing database."""

import os
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
values = dict(
    line.split("=", 1) for line in (root / ".env").read_text().splitlines() if "=" in line
)
env = (
    os.environ
    | values
    | {
        "POSTGRES_USER": "postgres",
        "PGHOST": "127.0.0.1",
        "PGPASSWORD": os.environ["CI_POSTGRES_PASSWORD"],
        "QFR_INIT_SQL": str(root / "infra/postgres/init/bootstrap.sql.in"),
    }
)
subprocess.run(["sh", "infra/postgres/init/01-bootstrap.sh"], env=env, check=True)
for name in ("REGISTRY", "RESEARCH", "EVAL", "CONTROL"):
    env[name + "_MIGRATION_URL"] = values[name + "_MIGRATION_URL"].replace(
        "@postgres:", "@127.0.0.1:"
    )
subprocess.run(["python", "scripts/migrate.py"], env=env, check=True)
github_env = Path(os.environ["GITHUB_ENV"])
with github_env.open("a") as stream:
    stream.write("QFR_REQUIRE_DB_TESTS=1\n")
    for name in ("REGISTRY", "RESEARCH", "EVAL", "FEEDBACK", "CONTROL"):
        stream.write(
            "QFR_TEST_"
            + name
            + "_DB_URL="
            + values[name + "_DB_URL"].replace("@postgres:", "@127.0.0.1:")
            + "\n"
        )
    stream.write("QFR_TEST_CONTROL_MIGRATION_URL=" + env["CONTROL_MIGRATION_URL"] + "\n")
    stream.write("QFR_TEST_REGISTRY_MIGRATION_URL=" + env["REGISTRY_MIGRATION_URL"] + "\n")
