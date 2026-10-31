"""`qfr data build` and `qfr data verify` end to end on a small synthetic world."""

import json
import shutil

import pytest
import yaml
from qfr_core.cli import app
from typer.testing import CliRunner

from tests.synthetic_fixtures import SMALL_EPOCH


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    base = tmp_path_factory.mktemp("cli")
    configs = base / "configs"
    shutil.copytree("configs", configs)
    synthetic = yaml.safe_load((configs / "data" / "synthetic_v1.yaml").read_text())
    synthetic.update(instruments=80, trading_days=700, epoch="small_test")
    synthetic["universe"]["size"] = 60
    (configs / "data" / "synthetic_v1.yaml").write_text(yaml.safe_dump(synthetic))
    (configs / "epochs" / "small_test.yaml").write_text(yaml.safe_dump(SMALL_EPOCH))
    env = {
        "QFR_CONFIG_DIR": str(configs),
        "QFR_LOG_DIR": str(base / "logs"),
        "QFR_FULL_SNAPSHOT_DIR": str(base / "snapshots" / "full"),
        "QFR_RESEARCH_SNAPSHOT_DIR": str(base / "snapshots" / "research"),
        "QFR_SERVICE": "data-ingest",
    }
    result = CliRunner().invoke(app, ["data", "build", "--source", "synthetic"], env=env)
    return base, env, result


def test_build_writes_both_zones_and_reports_their_ids(built):
    base, _, result = built
    assert result.exit_code == 0, result.output
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report["status"] == "ok"
    for zone in ("full", "research"):
        snapshot_id = report["snapshots"][zone]["snapshot_id"]
        assert (base / "snapshots" / zone / snapshot_id / "manifest.json").is_file()
        pointer = json.loads((base / "snapshots" / zone / "current.json").read_text())
        assert pointer["snapshot_id"] == snapshot_id
    full = json.loads(
        (
            base
            / "snapshots"
            / "full"
            / report["snapshots"]["full"]["snapshot_id"]
            / "manifest.json"
        ).read_text()
    )
    research_id = report["snapshots"]["research"]["snapshot_id"]
    research = json.loads(
        (base / "snapshots" / "research" / research_id / "manifest.json").read_text()
    )
    assert "ground_truth.json" in full["files"]
    assert full["source_details"]["world"] == "planted"
    # Research learns neither the world nor the planted signals.
    assert "ground_truth.json" not in research["files"]
    assert research["source_details"] == {"generator": "qfr-synthetic/1"}
    assert research["research_cutoff"] == "2011-06-30"


def test_build_logs_every_step(built):
    base, _, _ = built
    lines = [
        json.loads(line)
        for path in (base / "logs" / "data-ingest").glob("*.jsonl")
        for line in path.read_text().splitlines()
    ]
    events = [line["event"] for line in lines]
    for event in (
        "data_build_started",
        "data_checks_passed",
        "snapshot_written",
        "research_truncated",
    ):
        assert event in events
    assert all(line["service"] == "data-ingest" and line["zone"] == "eval" for line in lines)
    truncated = next(line for line in lines if line["event"] == "research_truncated")
    assert truncated["payload"]["cutoff"] == "2011-06-30"


def test_verify_runs_bnd_06_on_research_snapshots(built):
    base, env, result = built
    report = json.loads(result.stdout.strip().splitlines()[-1])
    research = report["snapshots"]["research"]["path"]
    verified = CliRunner().invoke(app, ["data", "verify", research, "--zone", "research"], env=env)
    assert verified.exit_code == 0, verified.output
    assert json.loads(verified.stdout)["bnd_06"] == "pass"
    full = report["snapshots"]["full"]["path"]
    refused = CliRunner().invoke(app, ["data", "verify", full, "--zone", "research"], env=env)
    assert refused.exit_code == 1
    assert json.loads(refused.stdout)["status"] == "error"


def test_rebuilding_gives_the_same_snapshot_ids(built):
    _, env, result = built
    again = CliRunner().invoke(app, ["data", "build", "--source", "synthetic"], env=env)
    assert again.exit_code == 0, again.output
    first = json.loads(result.stdout.strip().splitlines()[-1])["snapshots"]
    second = json.loads(again.stdout.strip().splitlines()[-1])["snapshots"]
    assert {z: s["snapshot_id"] for z, s in first.items()} == {
        z: s["snapshot_id"] for z, s in second.items()
    }


def test_failures_are_reported_and_logged(built, tmp_path):
    base, env, _ = built
    failed = CliRunner().invoke(
        app,
        ["data", "build", "--source", "cn", "--archive", str(tmp_path / "missing.tar.gz")],
        env=env,
    )
    assert failed.exit_code == 1
    assert json.loads(failed.stdout.strip().splitlines()[-1])["error"] == "IngestError"
    lines = [
        json.loads(line)
        for path in (base / "logs" / "data-ingest").glob("*.jsonl")
        for line in path.read_text().splitlines()
    ]
    errors = [line for line in lines if line["event"] == "data_build_failed"]
    assert errors and errors[-1]["level"] == "ERROR" and errors[-1]["outcome"] == "failed"
