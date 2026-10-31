"""The Phase 3 MCP tools: qfr.ops.activate_*, qfr.config.get cards and owner-only config,
and the audit trail that joins each call to the evaluator's request log (MCP-01)."""

from pathlib import Path

import pytest

from tests.eval.stack_rig import stack

pytestmark = pytest.mark.postgres


@pytest.fixture
def full(tmp_path, monkeypatch, small_zones):
    with stack(tmp_path, monkeypatch, small_zones) as built:
        yield built


def test_activate_tools_create_and_activate_versions_from_imports(full):
    full.eval.scheduler.tick()
    raw = Path("configs/release_policies/default_v1.yaml").read_text()
    (full.mcp.imports / "policy_v2.yaml").write_text(
        raw.replace("version: '1'", "version: '2'").replace("rankic: 0.005", "rankic: 0.01")
    )
    result = full.mcp.ok("qfr.ops.activate_policy", file="policy_v2.yaml")
    data = result["data"]
    assert data["created"] is True and data["version"]["status"] == "active"
    assert data["version"]["activated_by"] == "eval_owner"
    assert data["source"]["file"] == "policy_v2.yaml"
    card = full.mcp.ok("qfr.config.get")["data"]
    assert card["state"] == "active"
    assert card["cards"]["policy"]["ref"].startswith("default/2")
    assert card["cards"]["policy"]["card"]["rounding"]["rankic"] == 0.01
    again = full.mcp.ok("qfr.ops.activate_policy", file="policy_v2.yaml")["data"]
    assert again["created"] is False
    call = full.mcp.audit.calls[-1]
    assert call.tool == "qfr.ops.activate_policy" and call.downstream_request_ids
    admin_lines = full.mcp.events("eval-admin-api", "config_version_activated")
    assert result["request_id"] in {line["request_id"] for line in admin_lines}

    for arguments, code in (
        ({"file": "../outside.yaml"}, "PATH_OUTSIDE_IMPORTS"),
        ({"file": "missing.yaml"}, "FILE_NOT_FOUND"),
    ):
        assert code in full.mcp.error("qfr.ops.activate_protocol", **arguments)
    (full.mcp.imports / "clash.yaml").write_text(raw.replace("rankic: 0.005", "rankic: 0.02"))
    assert "VERSION_IMMUTABLE" in full.mcp.error("qfr.ops.activate_policy", file="clash.yaml")


def test_owner_only_config_comes_from_the_evaluator(full):
    full.eval.scheduler.tick()
    data = full.mcp.ok("qfr.config.get", owner_only=True)["data"]
    assert data["visibility"] == "owner_only"
    windows = data["configuration"]["epoch"]["windows"]
    assert set(windows) == {"W0", "W1", "W2", "W3"}
    public = full.mcp.ok("qfr.config.get")["data"]
    assert "W3" not in str(public["cards"]["protocol"]["card"])


def test_report_list_filters_by_version_and_type(full):
    imported = full.mcp.ok(
        "qfr.pool.import",
        entries=[{"name": "solo", "title": "Solo", "expression": "Pct($close, 20)",
                  "expected_sign": 1, "horizon_days": 5}],
    )["data"]  # fmt: skip
    version = imported["entries"][0]["version_id"]
    full.settle()
    full.eval.release.tick()
    w1 = full.mcp.ok("qfr.report.list", version_id=version, type="w1")["data"]["items"]
    assert len(w1) == 1 and w1[0]["version_id"] == version
    everything = full.mcp.ok("qfr.report.list", version_id=version)["data"]["items"]
    assert [r["content"]["type"] for r in everything] == ["library", "intake", "screening", "w1"]
    assert "LIMIT_INVALID" in full.mcp.error("qfr.report.list", limit=5000)
    unknown = full.mcp.error("qfr.evidence.get", version_id="0190b9b2-7a4e-7cc0-8000-000000000000")
    assert "VERSION_UNKNOWN" in unknown
