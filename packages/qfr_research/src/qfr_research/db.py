"""research_db access as research_rw (PLAN Sections 5.4 and 16.2)."""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, Protocol

from qfr_core.config import canonical_json
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine

# Job state transitions and the scheduler's generation starts take this transaction-level
# advisory lock, so two workers never start the same generation twice.
RESEARCH_LOCK = 0x5146_5252_4553_4541  # "QFRRESEA"


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FixedClock:
    """A settable clock for tests."""

    def __init__(self, at: datetime) -> None:
        self.at = at

    def now(self) -> datetime:
        return self.at

    def advance(self, **delta: float) -> datetime:
        from datetime import timedelta

        self.at = self.at + timedelta(**delta)
        return self.at


class Database:
    def __init__(self, url: str | None = None, engine: Engine | None = None) -> None:
        if engine is None:
            if not url:
                raise ValueError("a database URL is required")
            engine = create_engine(url, pool_pre_ping=True)
        self.engine = engine

    @contextmanager
    def transaction(self, lock: bool = False) -> Iterator[Connection]:
        with self.engine.begin() as conn:
            if lock:
                conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": RESEARCH_LOCK})
            yield conn

    @contextmanager
    def read(self) -> Iterator[Connection]:
        with self.engine.connect() as conn:
            yield conn

    def healthy(self) -> bool:
        try:
            with self.read() as conn:
                return (
                    conn.execute(text("SELECT to_regclass('research_jobs')")).scalar() is not None
                )
        except Exception:
            return False


def dumps(value: Any) -> str:
    """Canonical JSON for JSONB parameters (sorted keys; hashed outputs stay stable)."""
    return canonical_json(json.loads(json.dumps(value, default=str)))
