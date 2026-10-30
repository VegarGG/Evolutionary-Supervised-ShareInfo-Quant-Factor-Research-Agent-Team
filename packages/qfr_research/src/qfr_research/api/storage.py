"""Research-only persistence primitives with attribution and bounded transactions."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.types.json import Jsonb
from qfr_core.access import ServicePrincipal
from qfr_core.contracts.research import ResearchApiPolicy
from qfr_core.delivery_rules import content_sha256
from qfr_core.identifiers import uuid7

from qfr_research.api.errors import ResearchConflict, ResearchNotFound
from qfr_research.db import attributed


def scope(principal: ServicePrincipal, program: UUID, role: str | None = None) -> None:
    if principal.audience != "research" or str(program) not in principal.programs:
        raise ResearchNotFound("research program unavailable")
    if role is not None and role not in principal.roles:
        raise PermissionError("research operation not authorized")


class Storage:
    def __init__(self, connect: Callable[[], Connection], policy: ResearchApiPolicy):
        self.connect = connect
        self.policy = ResearchApiPolicy.model_validate(policy.model_dump())

    @contextmanager
    def connection(self) -> Iterator[Connection]:
        with self.connect() as conn:
            if not conn.autocommit or conn.execute(
                "SELECT current_user,current_database()"
            ).fetchone() != ("research_rw", "research_db"):
                raise PermissionError("Research API requires its own research identity")
            conn.execute(
                "SELECT set_config('statement_timeout',%s,false),"
                "set_config('lock_timeout',%s,false)",
                [str(self.policy.statement_timeout_ms), str(self.policy.lock_timeout_ms)],
            )
            yield conn

    @staticmethod
    def now(conn: Connection) -> datetime:
        row = conn.execute("SELECT clock_timestamp()").fetchone()
        if row is None or not isinstance(row[0], datetime):
            raise RuntimeError("database clock unavailable")
        return row[0]

    @staticmethod
    def program(conn: Connection, program: UUID, *, lock: bool = False) -> tuple[Any, ...]:
        row = conn.execute(
            "SELECT id,name,status,charter,charter_revision,created_by,created_at "
            "FROM research.programs WHERE id=%s" + (" FOR SHARE" if lock else ""),
            [program],
        ).fetchone()
        if row is None:
            raise ResearchNotFound("research program unavailable")
        return row

    @staticmethod
    def insert(
        conn: Connection,
        table: str,
        payload: dict[str, Any],
        principal: str,
        request_id: UUID,
        program: UUID,
        *,
        identity: UUID | None = None,
        **extra: Any,
    ) -> UUID:
        # Table/column identifiers are internal constants, never HTTP arguments.
        from psycopg import sql

        identity = identity or uuid7()
        columns = dict(
            id=identity,
            program_id=program,
            payload=Jsonb(payload),
            created_by=principal,
            request_id=request_id,
            **extra,
        )
        with attributed(conn, principal, request_id):
            conn.execute(
                sql.SQL("INSERT INTO research.{} ({}) VALUES ({})").format(
                    sql.Identifier(table),
                    sql.SQL(",").join(map(sql.Identifier, columns)),
                    sql.SQL(",").join(sql.Placeholder() for _ in columns),
                ),
                list(columns.values()),
            )
        return identity

    @staticmethod
    def operation(
        conn: Connection, program: UUID, action_scope: str, key: str, request: dict[str, Any]
    ) -> dict[str, Any] | None:
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            [f"research-operation:{program}:{action_scope}:{key}"],
        )
        row = conn.execute(
            "SELECT payload_hash,payload FROM research.api_operations "
            "WHERE program_id=%s AND scope_key=%s AND operation_key=%s",
            [program, action_scope, key],
        ).fetchone()
        if row is None:
            return None
        if row[0] != content_sha256(request):
            raise ResearchConflict("operation key already binds different intent")
        return dict(row[1])

    def remember(
        self,
        conn: Connection,
        program: UUID,
        action_scope: str,
        key: str,
        request: dict[str, Any],
        result: dict[str, Any],
        principal: str,
        request_id: UUID,
    ) -> None:
        self.insert(
            conn,
            "api_operations",
            result,
            principal,
            request_id,
            program,
            scope_key=action_scope,
            operation_key=key,
            payload_hash=content_sha256(request),
        )
