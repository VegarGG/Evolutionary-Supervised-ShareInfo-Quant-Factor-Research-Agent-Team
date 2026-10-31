"""The MCP front door wired to a real registry-api and real control_db tables.

The registry runs in process (ASGI transport) over registry_db, and the control store
writes control_db; both run inside transactions that are rolled back after the test,
so every test starts from a fresh, empty stack.
"""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from qfr_core.config import RuntimeSettings
from qfr_mcp.control_store import PostgresControlStore
from qfr_mcp.server import create_app
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection
from starlette.testclient import TestClient

from tests.registry_rig import TOKENS, RegistryRig, database_url, registry_rig

MCP_HEADERS = {
    "Authorization": "Bearer test-token",
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


class MemoryAudit:
    def __init__(self) -> None:
        self.calls: list[Any] = []

    def append(self, call: Any) -> None:
        self.calls.append(call)

    def healthy(self) -> bool:
        return True


class TransactionalControl:
    """One control_db connection; each store call is a savepoint in a rolled-back outer."""

    def __init__(self, url: str) -> None:
        self.engine = create_engine(url)
        self.conn = self.engine.connect()
        self.outer = self.conn.begin()

    @contextmanager
    def begin(self) -> Iterator[Connection]:
        with self.conn.begin_nested():
            yield self.conn

    def count(self, sql: str, **params: Any) -> int:
        return int(self.conn.execute(text(sql), params).scalar_one())

    def close(self) -> None:
        self.outer.rollback()
        self.conn.close()
        self.engine.dispose()


@dataclass
class SetupRig:
    client: TestClient
    registry: RegistryRig
    control_db: TransactionalControl
    store: PostgresControlStore
    audit: MemoryAudit
    imports: Path
    log_dir: Path

    def call(self, tool: str, **arguments: Any) -> dict[str, Any]:
        response = self.client.post(
            "/mcp",
            headers=MCP_HEADERS,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": tool, "arguments": arguments},
            },
        )
        assert response.status_code == 200, response.text
        return response.json()["result"]

    def ok(self, tool: str, **arguments: Any) -> dict[str, Any]:
        result = self.call(tool, **arguments)
        assert not result.get("isError", False), result
        return result["structuredContent"]

    def error(self, tool: str, **arguments: Any) -> str:
        result = self.call(tool, **arguments)
        assert result.get("isError") is True, result
        return " ".join(c.get("text", "") for c in result["content"])

    def logs(self, service: str) -> list[dict[str, Any]]:
        lines = []
        for path in sorted((self.log_dir / service).glob("*.jsonl")):
            lines += [json.loads(line) for line in path.read_text().splitlines() if line]
        return lines

    def events(self, service: str, event: str) -> list[dict[str, Any]]:
        return [line for line in self.logs(service) if line.get("event") == event]

    def trace_counts(self) -> dict[str, int]:
        rows = self.control_db.conn.execute(
            text("SELECT step_type, count(*) FROM trace_steps GROUP BY step_type")
        ).all()
        return {str(step): int(n) for step, n in rows}


EVAL_TOKENS = {"eval-admin-api": "test-eval-owner-token", "feedback-api": "test-feedback-token"}


@contextmanager
def setup_rig(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    eval_transports: dict[str, httpx.AsyncBaseTransport] | None = None,
) -> Iterator[SetupRig]:
    """With eval_transports, the front door also reaches eval-admin-api and feedback-api,
    and research-api when the transports include one."""
    with registry_rig(tmp_path) as registry:
        control_db = TransactionalControl(database_url("CONTROL"))
        store = PostgresControlStore(begin=control_db.begin)
        imports = tmp_path / "imports"
        imports.mkdir()
        monkeypatch.setenv("REGISTRY_API_URL", "http://registry-api:8000")
        monkeypatch.setenv("REGISTRY_CONTROL_TOKEN", TOKENS["control"])
        monkeypatch.setenv("QFR_IMPORTS_DIR", str(imports))
        for name in ("RESEARCH_API_URL", "EVAL_ADMIN_API_URL", "FEEDBACK_API_URL"):
            monkeypatch.delenv(name, raising=False)
        if eval_transports is not None and "research-api" in eval_transports:
            # The caller sets RESEARCH_CONTROL_TOKEN; the research rig serves the app.
            monkeypatch.setenv("RESEARCH_API_URL", "http://research-api:8000")
        if eval_transports is not None:
            monkeypatch.setenv("EVAL_ADMIN_API_URL", "http://eval-admin-api:8000")
            monkeypatch.setenv("EVAL_OWNER_TOKEN", EVAL_TOKENS["eval-admin-api"])
            monkeypatch.setenv("FEEDBACK_API_URL", "http://feedback-api:8000")
            monkeypatch.setenv("FEEDBACK_READER_TOKEN", EVAL_TOKENS["feedback-api"])
        audit = MemoryAudit()
        settings = RuntimeSettings(
            mcp_token="test-token", config_dir=Path("configs"), log_dir=tmp_path
        )
        transport = httpx.ASGITransport(app=registry.client.app)
        app = create_app(settings, audit, store, transport, eval_transports)
        try:
            with TestClient(app, base_url="http://127.0.0.1:8765") as client:
                yield SetupRig(client, registry, control_db, store, audit, imports, tmp_path)
        finally:
            control_db.close()
