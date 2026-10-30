"""Scripted MCP transport, database-audit and file-log check; no agent or provider."""

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path


def exercise():
    from qfr_core.contracts import LogLine
    from sqlalchemy import create_engine, text

    headers = {
        "Authorization": "Bearer " + os.environ["QFR_MCP_TOKEN"],
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }

    def rpc(method, params):
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        req = urllib.request.Request(
            "http://127.0.0.1:8765/mcp",
            data=json.dumps(payload).encode(),
            headers=headers,
        )
        with urllib.request.urlopen(req, timeout=45) as response:
            body = json.load(response)
            request_id = response.headers["x-request-id"]
        assert "error" not in body and not body["result"].get("isError", False), body
        return request_id, body["result"]

    rpc(
        "initialize",
        {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "qfr-phase0-scripted-check", "version": "1"},
        },
    )
    _, catalog = rpc("tools/list", {})
    names = {tool["name"] for tool in catalog["tools"]}
    assert names == {
        "qfr.status",
        "qfr.config.get",
        "qfr.logs.search",
        "qfr.logs.tail",
        "qfr.logs.correlate",
    }
    calls = []
    for name, arguments in (
        ("qfr.status", {}),
        ("qfr.config.get", {}),
        ("qfr.logs.tail", {"service": "qfr-mcp", "n": 5}),
        ("qfr.logs.search", {"query": {"services": ["qfr-mcp"], "limit": 5}}),
    ):
        request_id, result = rpc("tools/call", {"name": name, "arguments": arguments})
        content = result["structuredContent"]
        assert content["request_id"] == request_id
        calls.append({"tool": name, "request_id": request_id, "tool_status": content["status"]})
    request_id, result = rpc(
        "tools/call",
        {
            "name": "qfr.logs.correlate",
            "arguments": {
                "id": calls[0]["request_id"],
                "id_kind": "request",
                "query": {},
            },
        },
    )
    assert result["structuredContent"]["data"]["lines"]
    calls.append(
        {
            "tool": "qfr.logs.correlate",
            "request_id": request_id,
            "tool_status": result["structuredContent"]["status"],
        }
    )
    engine = create_engine(os.environ["CONTROL_DB_URL"])
    with engine.connect() as connection:
        for call in calls:
            rows = (
                connection.execute(
                    text(
                        "SELECT tool, outcome, downstream_request_ids FROM mcp_calls "
                        "WHERE request_id=:request_id"
                    ),
                    {"request_id": call["request_id"]},
                )
                .mappings()
                .all()
            )
            assert len(rows) == 1 and rows[0]["tool"] == call["tool"]
            assert rows[0]["outcome"] == "ok"
            call["audit_rows"] = len(rows)
            call["downstream_request_ids"] = rows[0]["downstream_request_ids"]
    lines = []
    for path in Path(os.environ["QFR_LOG_DIR"]).glob("qfr-mcp/*.jsonl"):
        lines.extend(LogLine.model_validate_json(line) for line in path.read_text().splitlines())
    for call in calls:
        matching = [
            line
            for line in lines
            if line.request_id == call["request_id"] and line.event == "mcp_tool_called"
        ]
        assert len(matching) == 1
        call["file_audit_lines"] = len(matching)
    print(
        json.dumps(
            {
                "status": "PASS",
                "transport": "container-loopback-streamable-http",
                "host_loopback_verified": False,
                "tools": calls,
                "limitations": [
                    "This does not verify the Mac host ingress or live downstream APIs."
                ],
            },
            indent=2,
        )
    )


if os.environ.get("QFR_SMOKE_INSIDE") == "1":
    exercise()
else:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            ".env",
            "-f",
            "infra/docker-compose.yml",
            "exec",
            "-T",
            "-e",
            "QFR_SMOKE_INSIDE=1",
            "qfr-mcp",
            "python",
            "-",
        ],
        input=Path(__file__).read_text(),
        text=True,
        cwd=root,
    )
    sys.exit(result.returncode)
