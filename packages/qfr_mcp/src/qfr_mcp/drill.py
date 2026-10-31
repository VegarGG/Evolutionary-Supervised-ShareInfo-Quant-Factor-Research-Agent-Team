"""The restore drill (PLAN Section 17.5, task P7.5), run on the Mac by `just restore-drill`.

It restores the newest complete backup into a throwaway Compose project and checks it:

  1. the backup's SHA256SUMS hold;
  2. postgres starts empty in the throwaway project (its own volumes and networks), the
     bootstrap creates the four databases and nine roles, and pg_restore loads each dump;
  3. BND-01: each application role connects to its own database and is refused by the
     others;
  4. REG-01: registry_app is refused UPDATE, DELETE and TRUNCATE on artifact_versions,
     pool_entries and pool_events, and the table owner is stopped by the append-only
     triggers (UPDATE and DELETE are tried where rows exist; the trigger is checked
     otherwise);
  5. EVL-04: the newest official record is re-run by eval-worker against the restored
     database, with the snapshot and evaluation-store mirrors from backups/snapshots/
     copied into the throwaway volumes, and its results hash must match.

The project is removed with its volumes afterwards, whatever happened. The report is
written to exports/restore-drill/ and logged by ops-nightly. Passwords reach psql on
stdin, never on a command line.
"""

import hashlib
import json
import re
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
URL = re.compile(
    r"^postgresql(?:\+psycopg)?://(?P<user>[^:@/]+):(?P<password>[^@/]+)@"
    r"(?P<host>[^:/]+):(?P<port>\d+)/(?P<database>\w+)$"
)
DATABASES = ("registry_db", "research_db", "eval_db", "control_db")
# BND-01: each role, the URL variable holding its credentials, and the databases it must
# not reach.
CROSS_DATABASE = {
    "RESEARCH_DB_URL": ("eval_db", "control_db", "registry_db"),
    "EVAL_DB_URL": ("research_db", "control_db"),
    "CONTROL_DB_URL": ("research_db", "eval_db", "registry_db"),
}
REGISTRY_TABLES = ("artifact_versions", "pool_entries", "pool_events")
UPDATES = {
    "artifact_versions": "UPDATE artifact_versions SET publisher = publisher",
    "pool_entries": "UPDATE pool_entries SET title = title",
    "pool_events": "UPDATE pool_events SET note = note",
}
# The throwaway project's networks, away from the running stack's 10.233.4x.0/24.
DRILL_SUBNETS = {
    "QFR_CONTROL_NET_SUBNET": "10.234.40.0/24",
    "QFR_RESEARCH_NET_SUBNET": "10.234.41.0/24",
    "QFR_REGISTRY_NET_SUBNET": "10.234.42.0/24",
    "QFR_EVAL_NET_SUBNET": "10.234.43.0/24",
    "QFR_RESEARCH_EGRESS_NET_SUBNET": "10.234.44.0/24",
    "QFR_INGEST_EGRESS_NET_SUBNET": "10.234.45.0/24",
    "QFR_MCP_INGRESS_NET_SUBNET": "10.234.47.0/24",
}
# Seed the throwaway volumes from the mirrors: (mirror folder, service, mount point).
SEEDS = (("full", "data-ingest", "/data/full"), ("eval_store", "eval-worker", "/data/eval-store"))
COPY = (
    "import shutil,sys; shutil.copytree('/seed', sys.argv[1], dirs_exist_ok=True); "
    "print('seeded', sys.argv[1])"
)


def latest_backup(backups: Path) -> Path | None:
    """The newest dated folder with its COMPLETE marker."""
    if not backups.is_dir():
        return None
    days = sorted(p for p in backups.iterdir() if DAY.match(p.name) and (p / "COMPLETE").is_file())
    return days[-1] if days else None


def verify_sums(folder: Path) -> list[str]:
    """Errors in the folder's SHA256SUMS: a missing, changed or unlisted dump."""
    sums = folder / "SHA256SUMS"
    if not sums.is_file():
        return ["SHA256SUMS is missing"]
    errors: list[str] = []
    listed: dict[str, str] = {}
    for line in sums.read_text().splitlines():
        digest, _, name = line.partition("  ")
        listed[name] = digest
    for name, digest in sorted(listed.items()):
        path = folder / name
        if not path.is_file():
            errors.append(f"{name}: listed but missing")
            continue
        sha = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1 << 20), b""):
                sha.update(block)
        if sha.hexdigest() != digest:
            errors.append(f"{name}: SHA-256 differs from SHA256SUMS")
    for database in DATABASES:
        if f"{database}.dump" not in listed:
            errors.append(f"{database}.dump is not in the backup")
    return errors


def credentials(env: dict[str, str], variable: str) -> dict[str, str]:
    match = URL.match(env.get(variable, ""))
    if match is None:
        raise ValueError(f"{variable} is not a postgresql URL in .env")
    return match.groupdict()


@dataclass
class Check:
    name: str
    status: str  # PASS, FAIL or SKIP
    detail: Any

    def view(self) -> dict[str, Any]:
        return {"check": self.name, "status": self.status, "detail": self.detail}


Run = Callable[[Sequence[str], bytes | None], subprocess.CompletedProcess[bytes]]


def run_process(args: Sequence[str], stdin: bytes | None) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(list(args), input=stdin, capture_output=True, check=False)


@dataclass
class Drill:
    """The drill's steps. `compose` is the `docker compose ... -p <project>` prefix and
    `in_postgres` the prefix that runs a command inside the throwaway postgres."""

    env: dict[str, str]
    compose: list[str]
    run: Run = run_process
    checks: list[Check] = field(default_factory=list)
    in_postgres: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.in_postgres:
            self.in_postgres = [*self.compose, "exec", "-T", "postgres"]

    def check(self, name: str, passed: bool | None, detail: Any) -> bool:
        status = "SKIP" if passed is None else "PASS" if passed else "FAIL"
        self.checks.append(Check(name, status, detail))
        return bool(passed)

    def psql_as(self, variable: str, database: str, sql: str) -> tuple[int, str]:
        """Run SQL as the role in .env's variable, over TCP inside the container so the
        role's CONNECT privilege is what decides. The password arrives on stdin."""
        login = credentials(self.env, variable)
        script = (
            "read -r PGPASSWORD; export PGPASSWORD; exec psql -X -q -At -v ON_ERROR_STOP=1 "
            '-h 127.0.0.1 -U "$1" -d "$2" -c "$3"'
        )
        done = self.run(
            [*self.in_postgres, "sh", "-c", script, "drill", login["user"], database, sql],
            (login["password"] + "\n").encode(),
        )
        return done.returncode, (done.stdout + done.stderr).decode(errors="replace").strip()

    def psql(self, database: str, sql: str) -> tuple[int, str]:
        """Run SQL as the postgres superuser over the container's local socket."""
        done = self.run(
            [*self.in_postgres, "psql", "-X", "-q", "-At", "-v", "ON_ERROR_STOP=1",
             "-U", "postgres", "-d", database, "-c", sql],
            None,
        )  # fmt: skip
        return done.returncode, (done.stdout + done.stderr).decode(errors="replace").strip()

    def restore(self, folder: Path) -> bool:
        ok = True
        for database in DATABASES:
            dump = (folder / f"{database}.dump").read_bytes()
            done = self.run(
                [*self.in_postgres, "pg_restore", "-U", "postgres", "--dbname", database,
                 "--clean", "--if-exists", "--exit-on-error", "--no-password"],
                dump,
            )  # fmt: skip
            ok &= self.check(
                f"restore:{database}",
                done.returncode == 0,
                {"bytes": len(dump), "stderr": done.stderr.decode(errors="replace")[-2000:]},
            )
        return ok

    def bnd_01(self) -> None:
        for variable, refused in CROSS_DATABASE.items():
            own = credentials(self.env, variable)["database"]
            code, output = self.psql_as(variable, own, "SELECT 1")
            self.check(f"BND-01:{variable}:{own}", code == 0 and output == "1", output[-300:])
            for database in refused:
                code, output = self.psql_as(variable, database, "SELECT 1")
                self.check(
                    f"BND-01:{variable}:{database}",
                    code != 0 and "permission denied for database" in output,
                    output[-300:],
                )

    def reg_01(self) -> None:
        for table in REGISTRY_TABLES:
            statements = {
                "UPDATE": UPDATES[table],
                "DELETE": f"DELETE FROM {table}",
                "TRUNCATE": f"TRUNCATE {table} CASCADE",
            }
            for verb, sql in statements.items():
                code, output = self.psql_as(
                    "REGISTRY_DB_URL", "registry_db", f"BEGIN; {sql}; ROLLBACK;"
                )
                self.check(
                    f"REG-01:registry_app:{verb}:{table}",
                    code != 0 and "permission denied" in output,
                    output[-300:],
                )
            code, rows = self.psql("registry_db", f"SELECT count(*) FROM {table}")
            for verb, sql in statements.items():
                if verb != "TRUNCATE" and code == 0 and rows == "0":
                    # A row trigger needs a row; check that it is there and enabled.
                    _, found = self.psql(
                        "registry_db",
                        "SELECT count(*) FROM pg_trigger WHERE tgrelid = "
                        f"'{table}'::regclass AND tgname = '{table}_immutable' "
                        "AND tgenabled = 'O'",
                    )
                    self.check(
                        f"REG-01:owner:{verb}:{table}",
                        found == "1",
                        {"rows": 0, "trigger": f"{table}_immutable", "enabled": found == "1"},
                    )
                    continue
                code_owner, output = self.psql_as(
                    "REGISTRY_MIGRATION_URL", "registry_db", f"BEGIN; {sql}; ROLLBACK;"
                )
                self.check(
                    f"REG-01:owner:{verb}:{table}",
                    code_owner != 0 and "append-only" in output,
                    output[-300:],
                )

    def row_counts(self) -> dict[str, Any]:
        tables = {
            "registry_db": ["artifact_versions", "pool_entries", "pool_events"],
            "research_db": ["research_jobs", "trace_steps"],
            "eval_db": ["eval.official_records", "eval.released_reports"],
            "control_db": ["mcp_calls", "approvals", "deliveries"],
        }
        counts: dict[str, Any] = {}
        for database, names in tables.items():
            for name in names:
                code, output = self.psql(database, f"SELECT count(*) FROM {name}")
                counts[f"{database}.{name}"] = int(output) if code == 0 else output[-200:]
        return counts

    def evl_04(self, backups: Path) -> None:
        code, record = self.psql(
            "eval_db",
            "SELECT record_id FROM eval.official_records ORDER BY created_at DESC, "
            "record_id DESC LIMIT 1",
        )
        if code != 0:
            self.check("EVL-04", False, record[-300:])
            return
        if not record:
            self.check("EVL-04", None, "no official record in the backup to reproduce")
            return
        done = self.run([*self.compose, "run", "--rm", "--no-deps", "-T", "init-volumes"], None)
        if not self.check("EVL-04:init_volumes", done.returncode == 0, done.stderr.decode()[-300:]):
            return
        for mirror, service, target in SEEDS:
            source = backups / "snapshots" / mirror
            if not source.is_dir():
                self.check(f"EVL-04:seed:{mirror}", False, f"{source} is missing")
                return
            done = self.run(
                [*self.compose, "run", "--rm", "--no-deps", "-T",
                 "-v", f"{source.resolve()}:/seed:ro", service, "python", "-c", COPY, target],
                None,
            )  # fmt: skip
            if not self.check(
                f"EVL-04:seed:{mirror}", done.returncode == 0, done.stderr.decode()[-300:]
            ):
                return
        done = self.run(
            [*self.compose, "run", "--rm", "--no-deps", "-T", "eval-worker",
             "qfr", "eval", "reproduce", record],
            None,
        )  # fmt: skip
        output = done.stdout.decode(errors="replace").strip().splitlines()
        try:
            result = json.loads(output[-1]) if output else {}
        except json.JSONDecodeError:
            result = {"stdout": output[-5:]}
        self.check(
            "EVL-04",
            done.returncode == 0 and result.get("match") is True,
            result | {"stderr": done.stderr.decode(errors="replace")[-500:]},
        )


def status(checks: list[Check]) -> str:
    if not checks or any(c.status == "FAIL" for c in checks):
        return "FAIL"
    return "PASS"


def report(
    backup: Path | None, checks: list[Check], observations: dict[str, Any], project: str
) -> dict[str, Any]:
    return {
        "at": datetime.now(UTC).isoformat(),
        "phase": 7,
        "kind": "restore_drill",
        "project": project,
        "backup": None if backup is None else backup.name,
        "status": status(checks),
        "checks": [c.view() for c in checks],
        "skipped": [c.name for c in checks if c.status == "SKIP"],
        "observations": observations,
    }
