"""`qfr setup`: the four setup questions answered through the MCP front door."""

import json
from contextlib import nullcontext

import pytest
from qfr_core.cli import app as qfr
from qfr_core.pool_import import NO_DEFAULTS_NOTICE
from qfr_mcp import setup_cli
from typer.testing import CliRunner

from tests.mcp.setup_rig import setup_rig
from tests.mcp.test_setup import ROWS, csv_file

MCP_URL = "http://127.0.0.1:8765/mcp"


@pytest.fixture
def rig(tmp_path, monkeypatch):
    with setup_rig(tmp_path, monkeypatch) as built:
        monkeypatch.setattr(setup_cli, "http_client", lambda: nullcontext(built.client))
        monkeypatch.setenv("QFR_MCP_TOKEN", "test-token")
        yield built


def summary(output):
    return json.loads(output[output.rindex("\n{") + 1 :])


@pytest.mark.postgres
def test_setup_without_a_pool_records_the_empty_start(rig):
    result = CliRunner().invoke(qfr, ["setup", "--url", MCP_URL], input="\n")
    assert result.exit_code == 0, result.output
    assert NO_DEFAULTS_NOTICE in result.output
    assert "No provider was called" in result.output and "just mcp-config" in result.output
    report = summary(result.output)
    assert report["setup_complete"] is False and report["pool"] == "empty"
    assert report["remaining"] == ["providers", "data"]
    assert report["notice"] == NO_DEFAULTS_NOTICE and report["provider_calls_made"] == 0
    assert rig.store.latest_setup_states()["pool"].status == "empty"
    assert [c.tool for c in rig.audit.calls] == [
        "qfr.status",
        "qfr.pool.import",
        "qfr.setup.status",
    ]


@pytest.mark.postgres
def test_setup_imports_the_named_file_and_reports_each_entry(rig):
    rows = [*ROWS, ("bad_field", "Bad field", "Mean($foo, 5)", 1, 5, "", "")]
    (rig.imports / "owner_pool.csv").write_text(csv_file(rows))
    result = CliRunner().invoke(
        qfr, ["setup", "--url", MCP_URL, "--non-interactive", "--pool-file", "owner_pool.csv"]
    )
    assert result.exit_code == 0, result.output
    assert "invalid   factor   bad_field: FORBIDDEN_CONSTRUCT" in result.output
    assert "5 published, 0 unchanged, 1 invalid, 0 failed" in result.output
    report = summary(result.output)
    assert report["pool"] == "imported" and report["notice"] is None
    assert report["pool_counts"]["factor"]["seed"] == 5
    assert report["import_counts"]["invalid"] == 1


@pytest.mark.postgres
def test_setup_failures_exit_non_zero_with_the_reason(rig):
    result = CliRunner().invoke(
        qfr, ["setup", "--url", MCP_URL, "--non-interactive", "--pool-file", "../escape.csv"]
    )
    assert result.exit_code == 1
    assert "PATH_OUTSIDE_IMPORTS" in result.output


def test_non_interactive_setup_needs_an_explicit_pool_answer(monkeypatch, tmp_path):
    class Door:
        calls = []

        def call(self, tool, **arguments):
            self.calls.append(tool)
            return {"data": {"phase": 2}}

    with pytest.raises(setup_cli.SetupError, match="--pool-file NAME or --no-pool"):
        setup_cli.run_setup(Door(), None, False, lambda _: None, None)
    assert Door.calls == ["qfr.status"]
    result = CliRunner().invoke(qfr, ["setup", "--pool-file", "a.csv", "--no-pool"])
    assert result.exit_code == 2


def test_the_owner_token_comes_from_the_environment_or_the_env_file(monkeypatch, tmp_path):
    monkeypatch.delenv("QFR_MCP_TOKEN", raising=False)
    env = tmp_path / ".env"
    with pytest.raises(setup_cli.SetupError, match="init-secrets"):
        setup_cli.owner_token(env)
    env.write_text("OTHER=1\nQFR_MCP_TOKEN=from-file\n")
    assert setup_cli.owner_token(env) == "from-file"
    monkeypatch.setenv("QFR_MCP_TOKEN", "from-env")
    assert setup_cli.owner_token(env) == "from-env"
