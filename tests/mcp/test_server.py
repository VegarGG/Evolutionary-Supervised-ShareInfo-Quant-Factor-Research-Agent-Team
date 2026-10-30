import io
import json
from pathlib import Path

import httpx
import pytest
from qfr_core.config import RuntimeSettings, logging_config
from qfr_core.correlation import bind
from qfr_core.logging import JsonLogger
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
    app = create_app(settings, audit)
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


def test_mcp_catalog_exactly_phase_zero_reads(rig):
    client, _, headers, _ = rig
    response = call(client, headers, "tools/list")
    tools = {tool["name"] for tool in response.json()["result"]["tools"]}
    assert tools == {
        "qfr.status",
        "qfr.config.get",
        "qfr.logs.search",
        "qfr.logs.tail",
        "qfr.logs.correlate",
    }


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
