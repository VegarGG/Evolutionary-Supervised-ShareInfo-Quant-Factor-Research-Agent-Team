"""Phase 7 acceptance, scripted: the owner's five-step workflow through the MCP front
door on the synthetic world, with the Phase 7 operator tools around it (P7.1 to P7.4,
P7.6, SC8 to SC10).

The real-host-agent rehearsal on the Mac Studio (P7.6) follows docs/HOST_AGENT_GUIDE.md
with the same calls; this test is its offline twin with scripted model answers, so the
calls, audit rows, logs and exports it checks are the ones the rehearsal records.
"""

import gzip
import hashlib
import json
from pathlib import Path

import pytest
from qfr_mcp.exports import MANIFEST, app, verify_bundle
from sqlalchemy import text
from typer.testing import CliRunner

from tests.research.rig import brief, research_stack
from tests.research.scripted import Script
from tests.research.test_owner_workflow import REVERSAL, approve, deliver

pytestmark = pytest.mark.postgres

SERVICES = {
    "qfr-mcp", "research-api", "research-worker", "registry-api", "eval-scheduler",
    "eval-worker", "release-worker",
}  # fmt: skip


@pytest.fixture
def full(tmp_path, monkeypatch, small_zones):
    monkeypatch.setenv("QFR_EXPORTS_DIR", str(tmp_path / "exports"))
    with research_stack(tmp_path, monkeypatch, small_zones, Script([REVERSAL])) as built:
        yield built


def owner_only(data):
    assert data["visibility"] == "owner_only"
    assert data["hygiene_warning"].startswith("Never copy owner-only evidence")


def test_the_operator_rehearsal_runs_through_the_front_door(full, tmp_path):
    mcp = full.mcp

    # Before work starts: the status view answers every question of Section 13.7.
    status = mcp.ok("qfr.status")["data"]
    assert status["phase"] == 7
    for key in ("queues", "quotas", "burn_meters", "data_freshness", "disk", "alerts",
                "costs_today", "budgets"):  # fmt: skip
        assert key in status, key
    assert {k: status["alerts"][k] for k in ("evaluation", "research", "operations")} == {
        "evaluation": 0, "research": 0, "operations": 0,
    }  # fmt: skip

    # 1-2. A brief and its deliverable.
    job, fetched = deliver(full, brief())
    document = fetched["deliverable"]
    (factor,) = document["items"]
    version_id = factor["version_id"]
    owner_only(fetched)

    # P7.2: the evidence view of the delivered version, every window labelled.
    evidence = mcp.ok("qfr.evidence.get", version_id=version_id)["data"]
    owner_only(evidence)
    assert ("w1", "W1") in {(w["stage"], w["window"]) for w in evidence["windows"]}
    assert evidence["gate_values"] and all(g["stage"] for g in evidence["gate_values"])

    # P7.1: the deliverable bundle, written under exports/ and recorded in control_db.
    exported = mcp.ok("qfr.deliverable.export", deliverable_id=document["deliverable_id"])
    assert exported["status"] == "ok"
    bundle = exported["data"]
    owner_only(bundle)
    assert bundle["path"] == f"exports/{job['job_id']}/{document['deliverable_id']}"
    assert bundle["verify"] == f"just export-verify {bundle['path']}"
    folder = tmp_path / bundle["path"]
    names = {p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()}
    item = f"items/{version_id}"
    assert {
        "deliverable.json", "iteration_history.md", "bundle.json", MANIFEST,
        f"{item}/manifest.json", f"{item}/trace.json", f"{item}/owner_records.json",
    } <= names  # fmt: skip
    series = sorted(n for n in names if n.startswith(f"{item}/series/"))
    assert any(n.endswith(".parquet") for n in series), names
    assert {n.rsplit(".", 1)[0] for n in series if n.endswith(".csv")} == {
        n.rsplit(".", 1)[0] for n in series if n.endswith(".parquet")
    }
    assert bundle["files"] == len(names)
    (indexed,) = bundle["items"]
    assert indexed["trace_hash_matches_deliverable"] is True
    row = mcp.control_db.conn.execute(
        text(
            "SELECT exported_path, export_sha256, files FROM deliveries WHERE deliverable_id = :d"
        ),
        {"d": document["deliverable_id"]},
    ).one()
    assert tuple(row) == (bundle["path"], bundle["manifest_sha256"], len(names))

    # SC8: every file validates against its published schema and every hash holds.
    report = verify_bundle(folder, Path("schemas"))
    assert report["ok"] is True, report["errors"]
    assert report["checked"]["series"] >= 1 and report["checked"]["traces"] == 1
    cli = CliRunner().invoke(app, [str(folder), "--schemas", "schemas"])
    assert cli.exit_code == 0, cli.output

    # SC9: the exported trace reconstructs every hop of the delivered version.
    trace = json.loads((folder / item / "trace.json").read_text())
    hops = factor["iteration_history"]["hops"]
    assert hops and trace["version_id"] == version_id
    history = (folder / "iteration_history.md").read_text()
    assert version_id in history and "Owner-grade evidence (owner_only)" in history

    # A tampered bundle is caught: a changed byte, an extra file, and a series whose
    # manifest line was rewritten to match it.
    parquet = folder / next(n for n in series if n.endswith(".parquet"))
    original = parquet.read_bytes()
    parquet.write_bytes(original + b"\0")
    assert any("SHA-256 differs" in e for e in verify_bundle(folder, Path("schemas"))["errors"])
    lines = (folder / MANIFEST).read_text()
    relative = parquet.relative_to(folder).as_posix()
    rewritten = "".join(
        (f"{hashlib.sha256(parquet.read_bytes()).hexdigest()}  {relative}\n"
         if line.endswith(f"  {relative}") else line + "\n")
        for line in lines.splitlines()
    )  # fmt: skip
    (folder / MANIFEST).write_text(rewritten)
    errors = verify_bundle(folder, Path("schemas"))["errors"]
    assert any("evaluator's recorded SHA-256" in e for e in errors), errors
    (folder / "notes.txt").write_text("added by hand")
    assert any("not in MANIFEST" in e for e in verify_bundle(folder, Path("schemas"))["errors"])
    assert CliRunner().invoke(app, [str(folder), "--schemas", "schemas"]).exit_code == 1

    # Exporting again replaces the folder with a clean bundle and records a second delivery.
    again = mcp.ok("qfr.deliverable.export", deliverable_id=document["deliverable_id"])["data"]
    assert verify_bundle(folder, Path("schemas"))["ok"] is True
    assert not (folder / "notes.txt").exists()
    assert again["manifest_sha256"] != bundle["manifest_sha256"]  # exported_at differs
    count = "SELECT count(*) FROM deliveries WHERE deliverable_id = :d"
    assert mcp.control_db.count(count, d=document["deliverable_id"]) == 2

    # 3-4. The owner's approval with its short codes, and the pool entry.
    recorded = approve(full, job, fetched, f"APPROVE {job['short_code']} F-1")
    approval = recorded["structuredContent"]["data"]["approval"]
    entry = mcp.ok(
        "qfr.pool.add", approval_id=approval["approval_id"], version_id=version_id,
        title="Short-horizon reversal",
    )["data"]["entry"]  # fmt: skip
    assert entry["status"] == "approved"

    # 5. The evaluator syncs the approved entry into its library.
    full.eval.scheduler.tick()
    (synced,) = full.eval.db.rows(
        "SELECT status FROM eval.library WHERE version_id = :v", v=version_id
    )
    assert synced.status == "active"

    # P7.3: an incident pause and resume of all research, and the merged alert view.
    paused = mcp.ok("qfr.ops.pause_research", reason="Rehearsal incident drill.")["data"]
    assert paused["research_paused"] is True
    resumed = mcp.ok("qfr.ops.resume_research", reason="Drill over.")["data"]
    assert resumed["research_paused"] is False
    alerts = mcp.ok("qfr.ops.alerts")
    assert alerts["status"] == "ok"
    owner_only(alerts["data"])
    costs = mcp.ok("qfr.ops.costs", group_by=["job", "provider"], job_id=job["job_id"])["data"]
    assert costs["group_by"] == ["job", "provider"]

    # SC10: the job id tells the whole story across services, the export included.
    found = mcp.ok("qfr.logs.correlate", id=job["job_id"], id_kind="job", query={"limit": 2000})[
        "data"
    ]
    assert set(found["grouped_by_service"]) >= SERVICES, found["grouped_by_service"]
    events = {line["event"] for line in found["lines"]}
    assert "deliverable_exported" in events

    # P7.4: the same story as a compressed log slice under exports/logs/.
    sliced = mcp.ok("qfr.logs.export", query={"ids": {"job_id": job["job_id"]}})["data"]
    assert sliced["path"].startswith("exports/logs/") and sliced["lines"] > 0
    with gzip.open(tmp_path / sliced["path"], "rt") as stream:
        written = [json.loads(line) for line in stream]
    assert len(written) == sliced["lines"]
    assert all(line.get("job_id") == job["job_id"] for line in written)

    # SC8 / MCP-01: every call was audited, and each wrote a front-door log line.
    calls = list(mcp.audit.calls)
    assert {c.tool for c in calls} >= {
        "qfr.status", "qfr.job.submit", "qfr.deliverable.get", "qfr.deliverable.export",
        "qfr.approval.record", "qfr.pool.add", "qfr.ops.pause_research",
        "qfr.ops.resume_research", "qfr.ops.alerts", "qfr.logs.correlate", "qfr.logs.export",
    }  # fmt: skip
    logged = {line.get("request_id") for line in mcp.logs("qfr-mcp")}
    assert {c.request_id for c in calls} <= logged
