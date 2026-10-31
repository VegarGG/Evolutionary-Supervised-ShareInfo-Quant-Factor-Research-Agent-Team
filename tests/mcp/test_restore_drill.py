"""The restore drill's steps (qfr_mcp.drill, P7.5) with a recorded command runner.

The drill itself runs on the Mac against Docker (`just restore-drill`); these tests pin
what it checks, which commands it runs and that no password reaches a command line."""

import hashlib
import subprocess
from pathlib import Path

from qfr_mcp.drill import DATABASES, Drill, latest_backup, report, verify_sums

ENV = {
    "RESEARCH_DB_URL": "postgresql+psycopg://research_rw:pw-research@postgres:5432/research_db",
    "EVAL_DB_URL": "postgresql+psycopg://eval_rw:pw-eval@postgres:5432/eval_db",
    "CONTROL_DB_URL": "postgresql+psycopg://control_rw:pw-control@postgres:5432/control_db",
    "REGISTRY_DB_URL": "postgresql+psycopg://registry_app:pw-registry@postgres:5432/registry_db",
    "REGISTRY_MIGRATION_URL": (
        "postgresql+psycopg://registry_migrator:pw-owner@postgres:5432/registry_db"
    ),
}
PASSWORDS = ("pw-research", "pw-eval", "pw-control", "pw-registry", "pw-owner")


def backup(root: Path, day: str, complete: bool = True) -> Path:
    folder = root / day
    folder.mkdir(parents=True)
    lines = []
    for database in DATABASES:
        data = f"dump of {database}".encode()
        (folder / f"{database}.dump").write_bytes(data)
        lines.append(f"{hashlib.sha256(data).hexdigest()}  {database}.dump")
    (folder / "SHA256SUMS").write_text("\n".join(lines) + "\n")
    if complete:
        (folder / "COMPLETE").write_text("x")
    return folder


def test_the_newest_complete_backup_is_chosen_and_its_sums_checked(tmp_path):
    assert latest_backup(tmp_path / "missing") is None
    backup(tmp_path, "2026-10-29")
    newest = backup(tmp_path, "2026-10-30")
    backup(tmp_path, "2026-10-31", complete=False)
    (tmp_path / "snapshots").mkdir()
    assert latest_backup(tmp_path) == newest
    assert verify_sums(newest) == []
    (newest / "eval_db.dump").write_bytes(b"changed")
    (newest / "control_db.dump").unlink()
    assert verify_sums(newest) == [
        "control_db.dump: listed but missing",
        "eval_db.dump: SHA-256 differs from SHA256SUMS",
    ]


class Recorder:
    """Answers each command like the throwaway postgres would."""

    def __init__(self, records: str = "") -> None:
        self.calls: list[tuple[list[str], bytes | None]] = []
        self.records = records

    def __call__(self, args, stdin):
        args = list(args)
        self.calls.append((args, stdin))
        if "psql" in " ".join(args) and "sh" in args:
            # psql_as: user and database are the last three arguments before the SQL.
            user, database, sql = args[-3], args[-2], args[-1]
            own = {"research_rw": "research_db", "eval_rw": "eval_db",
                   "control_rw": "control_db", "registry_app": "registry_db",
                   "registry_migrator": "registry_db"}[user]  # fmt: skip
            if database != own:
                return self.done(2, "", f'FATAL: permission denied for database "{database}"')
            if user == "registry_app" and sql.startswith("BEGIN"):
                return self.done(3, "", "ERROR: permission denied for table x")
            if user == "registry_migrator":
                return self.done(3, "", "ERROR: append-only table")
            return self.done(0, "1\n", "")
        if "psql" in args:
            sql = args[-1]
            if "official_records" in sql:
                return self.done(0, self.records, "")
            if "pg_trigger" in sql:
                return self.done(0, "1\n", "")
            return self.done(0, "0\n", "")
        return self.done(0, "", "")

    @staticmethod
    def done(code, out, err):
        return subprocess.CompletedProcess([], code, out.encode(), err.encode())


def test_restore_and_boundary_probes_pass_without_passwords_on_a_command_line(tmp_path):
    folder = backup(tmp_path, "2026-10-30")
    recorder = Recorder()
    drill = Drill(env=ENV, compose=["docker", "compose", "-p", "qfr-drill-x"], run=recorder)
    assert drill.restore(folder)
    drill.bnd_01()
    drill.reg_01()
    drill.evl_04(tmp_path)
    statuses = {c.name: c.status for c in drill.checks}
    assert statuses["EVL-04"] == "SKIP"  # no official record in this backup
    assert {s for n, s in statuses.items() if n != "EVL-04"} == {"PASS"}
    assert {n.split(":")[0] for n in statuses} == {"restore", "BND-01", "REG-01", "EVL-04"}
    assert len([n for n in statuses if n.startswith("BND-01")]) == 3 + 3 + 2 + 3
    # Owner-side UPDATE and DELETE on empty tables check the trigger instead.
    assert len([n for n in statuses if n.startswith("REG-01:owner")]) == 9
    restores = [c for c in recorder.calls if "pg_restore" in c[0]]
    assert [c[0][c[0].index("--dbname") + 1] for c in restores] == list(DATABASES)
    assert all(c[0][:6] == ["docker", "compose", "-p", "qfr-drill-x", "exec", "-T"]
               for c in recorder.calls)  # fmt: skip
    for args, stdin in recorder.calls:
        assert not any(p in " ".join(args) for p in PASSWORDS), args
        if "sh" in args:
            assert stdin is not None and stdin.decode().strip() in PASSWORDS
    result = report(folder, drill.checks, {}, "qfr-drill-x")
    assert result["status"] == "PASS" and result["skipped"] == ["EVL-04"]


def test_evl_04_seeds_the_throwaway_volumes_from_the_mirrors(tmp_path):
    record = "019a35e0-0000-7000-8000-000000000001"
    recorder = Recorder(records=record + "\n")
    drill = Drill(env=ENV, compose=["docker", "compose", "-p", "qfr-drill-x"], run=recorder)
    drill.evl_04(tmp_path)
    assert [c.view()["status"] for c in drill.checks] == ["PASS", "FAIL"]
    assert "snapshots/full is missing" in drill.checks[-1].detail
    for name in ("full", "eval_store"):
        (tmp_path / "snapshots" / name).mkdir(parents=True, exist_ok=True)

    class Reproduces(Recorder):
        def __call__(self, args, stdin):
            if "reproduce" in args:
                self.calls.append((list(args), stdin))
                return self.done(0, '{"match": true, "status": "ok"}\n', "")
            return super().__call__(args, stdin)

    recorder = Reproduces(records=record + "\n")
    drill = Drill(env=ENV, compose=["docker", "compose", "-p", "qfr-drill-x"], run=recorder)
    drill.evl_04(tmp_path)
    assert all(c.status == "PASS" for c in drill.checks), [c.view() for c in drill.checks]
    runs = [c[0] for c in recorder.calls if "run" in c[0]]
    services = ("init-volumes", "data-ingest", "eval-worker")
    assert [next(a for a in r if a in services) for r in runs] == [
        "init-volumes", "data-ingest", "eval-worker", "eval-worker",
    ]  # fmt: skip
    assert f"{(tmp_path / 'snapshots' / 'full').resolve()}:/seed:ro" in runs[1]
    assert runs[-1][-4:] == ["qfr", "eval", "reproduce", record]


def test_a_failed_check_fails_the_drill_and_no_checks_is_a_failure():
    drill = Drill(env=ENV, compose=["docker"], run=Recorder())
    assert report(None, [], {}, "p")["status"] == "FAIL"
    drill.check("a", True, None)
    drill.check("b", None, "skipped")
    assert report(None, drill.checks, {}, "p")["status"] == "PASS"
    drill.check("c", False, "broken")
    assert report(None, drill.checks, {}, "p")["status"] == "FAIL"
