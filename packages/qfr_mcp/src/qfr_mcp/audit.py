"""Append-only control_db call audit, written before a response is delivered."""

from typing import Protocol
from uuid import UUID

from pydantic import AwareDatetime, Field
from qfr_core.contracts import Contract, Hash
from qfr_core.ids import uuid7
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

__all__ = ["AuditStore", "MCPCall", "PostgresAudit", "uuid7"]


class MCPCall(Contract):
    call_id: UUID
    at: AwareDatetime
    principal: str
    tool: str
    args_digest: Hash
    args_size: int = Field(ge=0)
    result_size: int = Field(ge=0)
    duration_ms: float = Field(ge=0)
    outcome: str
    error_code: str | None
    downstream_request_ids: list[str]
    request_id: str


class AuditStore(Protocol):
    def append(self, call: MCPCall) -> None: ...
    def healthy(self) -> bool: ...


class PostgresAudit:
    def __init__(self, url: str) -> None:
        self.engine: Engine = create_engine(url, pool_pre_ping=True)

    def append(self, call: MCPCall) -> None:
        values = call.model_dump()
        with self.engine.begin() as conn:
            conn.execute(
                text("""
                INSERT INTO mcp_calls
                  (call_id, at, principal, tool, args_digest, args_size, result_size,
                   duration_ms, outcome, error_code, downstream_request_ids, request_id)
                VALUES (:call_id, :at, :principal, :tool, :args_digest, :args_size,
                        :result_size, :duration_ms, :outcome, :error_code,
                        :downstream_request_ids, :request_id)
            """),
                values,
            )

    def healthy(self) -> bool:
        try:
            with self.engine.connect() as conn:
                return (
                    conn.execute(
                        text("SELECT to_regclass('public.mcp_calls') IS NOT NULL")
                    ).scalar()
                    is True
                )
        except Exception:
            return False
