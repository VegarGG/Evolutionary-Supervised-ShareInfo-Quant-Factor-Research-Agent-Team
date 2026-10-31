import io
import json
from pathlib import Path

import httpx
import pytest
from qfr_core.config import RuntimeSettings, logging_config
from qfr_core.correlation import bind
from qfr_core.logging import JsonLogger
from qfr_mcp.control_store import MemoryControlStore
from qfr_mcp.server import create_app
from starlette.testclient import TestClient


class MemoryAudit:
    def __init__(self):
        self.calls = []
        self.fail = False

    def append(self, call):
        if self.fail:
            raise RuntimeError("database unavailable")
        self.calls.append(call)

    def healthy(self):
        return True


@pytest.fixture
def rig(tmp_path, monkeypatch):
    audit = MemoryAudit()
    for key in ("DEEPSEEK_API_KEY", "MOONSHOT_API_KEY", "ZHIPU_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("RESEARCH_API_URL", "http://research-api:8000")
    monkeypatch.setenv("RESEARCH_CONTROL_TOKEN", "research-control-token")
    downstream = JsonLogger(
        "research-api", "research", tmp_path, logging_config(Path("configs")), stdout=io.StringIO()
    )

    def handler(request):
        request_id = request.headers["X-Request-Id"]
        with bind(request_id=request_id):
            downstream.logger.info(
                "api_request_completed", outcome="ok", payload={"path": request.url.path}
            )
        return httpx.Response(200, json={"status": "scripted_placeholder"})

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: original(**kw, transport=httpx.MockTransport(handler))
    )
    settings = RuntimeSettings(mcp_token="test-token", config_dir=Path("configs"), log_dir=tmp_path)
    app = create_app(settings, audit, MemoryControlStore())
    headers = {
        "Authorization": "Bearer test-token",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        yield client, audit, headers, tmp_path


def call(client, headers, method, params=None):
    return client.post(
        "/mcp",
        headers=headers,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
    )


def test_mcp_01_status_tail_are_audited_and_request_id_reaches_downstream(rig):
    client, audit, headers, directory = rig
    result = call(client, headers, "tools/call", {"name": "qfr.status", "arguments": {}})
    assert result.status_code == 200, result.text
    body = result.json()
    assert not body["result"].get("isError", False), body
    returned_id = body["result"]["structuredContent"]["request_id"]
    assert audit.calls[-1].request_id == returned_id
    assert returned_id in next((directory / "research-api").glob("*.jsonl")).read_text()
    assert returned_id in next((directory / "qfr-mcp").glob("*.jsonl")).read_text()
    tail = call(
        client,
        headers,
        "tools/call",
        {"name": "qfr.logs.tail", "arguments": {"service": "research-api", "n": 10}},
    )
    assert tail.status_code == 200 and not tail.json()["result"].get("isError", False)
    assert audit.calls[-1].tool == "qfr.logs.tail"
    assert audit.calls[-1].result_size > 0
    assert audit.calls[-1].downstream_request_ids == []


def test_mcp_02_catalog_is_the_phase_four_catalog(rig):
    client, _, headers, _ = rig
    response = call(client, headers, "tools/list")
    tools = {tool["name"] for tool in response.json()["result"]["tools"]}
    assert tools == {
        "qfr.status",
        "qfr.config.get",
        "qfr.logs.search",
        "qfr.logs.tail",
        "qfr.logs.correlate",
        "qfr.setup.status",
        "qfr.pool.import",
        "qfr.pool.list",
        "qfr.pool.get",
        "qfr.dsl.validate",
        "qfr.artifact.get",
        "qfr.evidence.get",
        "qfr.report.list",
        "qfr.ops.activate_protocol",
        "qfr.ops.activate_policy",
        "qfr.ops.activate_quotas",
        "qfr.job.submit",
        "qfr.job.list",
        "qfr.job.get",
        "qfr.job.events",
        "qfr.job.wait",
        "qfr.job.steer",
        "qfr.job.pause",
        "qfr.job.resume",
        "qfr.job.cancel",
        "qfr.deliverable.list",
        "qfr.deliverable.get",
        "qfr.trace.get",
        "qfr.lineage.get",
        "qfr.ops.costs",
    }
    annotations = {
        t["name"]: t.get("annotations") or {} for t in response.json()["result"]["tools"]
    }
    writes = {name for name, a in annotations.items() if not a.get("readOnlyHint")}
    assert writes == {
        "qfr.pool.import",
        "qfr.ops.activate_protocol",
        "qfr.ops.activate_policy",
        "qfr.ops.activate_quotas",
        "qfr.job.submit",
        "qfr.job.steer",
        "qfr.job.pause",
        "qfr.job.resume",
        "qfr.job.cancel",
    }
    # No tool publishes, runs research tools, writes official records or alters the
    # evaluator's runs and queues (MCP-02, INV-14).
    forbidden = ("publish", "evaluate", "record", "queue", "run", "tool", "official", "agent")
    assert not {name for name in tools for word in forbidden if word in name.split(".")[-1]}
    resources = call(client, headers, "resources/list").json()["result"]["resources"]
    assert {r["uri"] for r in resources} == {
        "qfr://cards/protocol",
        "qfr://cards/policy",
        "qfr://pools/factors",
        "qfr://pools/strategies",
    }
    templates = call(client, headers, "resources/templates/list").json()["result"]
    assert {t["uriTemplate"] for t in templates["resourceTemplates"]} == {
        "qfr://jobs/{job_id}",
        "qfr://deliverables/{deliverable_id}",
        "qfr://trace/{version_id}",
        "qfr://schemas/{name}",
    }
    prompts = call(client, headers, "prompts/list").json()["result"]["prompts"]
    assert {p["name"] for p in prompts} == {"qfr.brief", "qfr.report_deliverable"}


def test_schema_resources_and_prompts_hold_no_defaults(rig):
    client, audit, headers, _ = rig
    read = call(client, headers, "resources/read", {"uri": "qfr://schemas/brief"}).json()
    schema = json.loads(read["result"]["contents"][0]["text"])
    assert schema["properties"]["schema_version"]["const"] == "brief/1"
    assert audit.calls[-1].tool == "resources/read" and audit.calls[-1].outcome == "ok"
    unknown = call(client, headers, "resources/read", {"uri": "qfr://schemas/nothing"}).json()
    assert "error" in unknown
    for name in ("qfr.brief", "qfr.report_deliverable"):
        prompt = call(client, headers, "prompts/get", {"name": name}).json()["result"]
        text = prompt["messages"][0]["content"]["text"]
        assert "owner-only" in text.lower() or "owner_evidence" in text
        # A prompt teaches the workflow; it never carries an expression to submit.
        assert "$close" not in text and "$open" not in text
    brief = call(client, headers, "prompts/get", {"name": "qfr.brief"}).json()["result"]
    assert "no default factors" in brief["messages"][0]["content"]["text"]


def test_auth_limits_errors_and_audit_fail_closed(rig):
    client, audit, headers, _ = rig
    assert (
        call(client, headers | {"Authorization": "Bearer wrong"}, "tools/list").status_code == 401
    )
    assert audit.calls[-1].principal == "unauthenticated"
    assert (
        call(client, headers | {"Origin": "https://attacker.invalid"}, "tools/list").status_code
        == 403
    )
    response = client.post("/mcp", headers=headers, content=b"x" * (1048576 + 1))
    assert response.status_code == 413
    audit.fail = True
    assert call(client, headers, "tools/list").status_code == 503


def test_private_config_is_not_in_public_preview(rig):
    client, _, headers, _ = rig
    response = call(client, headers, "tools/call", {"name": "qfr.config.get", "arguments": {}})
    assert "W3" not in json.dumps(response.json())
    assert "2010-01-04" not in response.text
    assert "holdout_factor" not in response.text


def test_protocol_and_tool_errors_are_audited_as_failures(rig):
    client, audit, headers, _ = rig
    call(client, headers, "tools/call", {"name": "qfr.publish", "arguments": {}})
    assert audit.calls[-1].outcome == "failed"
    assert audit.calls[-1].error_code == "MCP_ERROR"
    call(client, headers, "nonexistent_method")
    assert audit.calls[-1].outcome == "failed"


def structured(client, headers, tool, **arguments):
    response = call(client, headers, "tools/call", {"name": tool, "arguments": arguments})
    assert response.status_code == 200, response.text
    return response.json()["result"]


def test_dsl_validate_returns_canonical_form_complexity_and_explanation(rig):
    client, audit, headers, _ = rig
    result = structured(
        client, headers, "qfr.dsl.validate", expression="Mean($close,20)/Mean($close,60)-1"
    )
    data = result["structuredContent"]["data"]
    assert data["ok"] is True and data["errors"] == []
    assert data["analysis"]["canonical"] == "((Mean($close,20)/Mean($close,60))-1)"
    assert data["analysis"]["complexity"] > 0 and data["analysis"]["max_lookback_days"] == 59
    assert "Mean over 20/60 days" in data["explanation"]["summary"]
    assert audit.calls[-1].tool == "qfr.dsl.validate" and audit.calls[-1].outcome == "ok"
    bad = structured(client, headers, "qfr.dsl.validate", expression="Mean($foo, 5)")
    data = bad["structuredContent"]["data"]
    assert data["ok"] is False and data["errors"][0]["code"] == "FORBIDDEN_CONSTRUCT"
    assert data["explanation"] is None
    capped = structured(client, headers, "qfr.dsl.validate", expression="Mean($close, 5000)")
    assert capped["structuredContent"]["data"]["errors"][0]["code"] == "FORBIDDEN_CONSTRUCT"


def test_registry_tools_fail_explicitly_when_the_registry_is_not_configured(rig):
    client, audit, headers, _ = rig
    status = structured(client, headers, "qfr.status")["structuredContent"]["data"]
    assert status["phase"] == 4
    assert status["services"]["registry-api"] == {"status": "not_configured"}
    assert status["pool_counts"] is None and status["notice"] is None
    setup = structured(client, headers, "qfr.setup.status")["structuredContent"]["data"]
    assert setup["registry"] == "unavailable" and setup["steps"]["pool"]["status"] == "not_started"
    for tool, arguments in (
        ("qfr.pool.import", {"no_pool": True}),
        ("qfr.pool.list", {"pool": "factor"}),
        ("qfr.artifact.get", {"version_id": "019a35e0-0000-7000-8000-000000000001"}),
    ):
        result = structured(client, headers, tool, **arguments)
        assert result["isError"] is True
        assert "REGISTRY_UNCONFIGURED" in result["content"][0]["text"]
        assert audit.calls[-1].outcome == "failed"
