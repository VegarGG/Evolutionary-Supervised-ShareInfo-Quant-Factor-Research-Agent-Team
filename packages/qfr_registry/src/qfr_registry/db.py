"""registry_db access as registry_app (SELECT and INSERT only)."""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine

# All writers take this transaction-level advisory lock first. Sequence values are then
# assigned and committed in the same order, so a since_seq reader can never skip a row
# that commits late (Section 16.5: the evaluator pulls by published_seq and event_seq).
WRITE_LOCK = 0x5146_5252_4547  # "QFRREG"


class Database:
    def __init__(self, url: str | None = None, engine: Engine | None = None) -> None:
        if engine is None:
            if url is None:
                raise ValueError("REGISTRY_DB_URL is required")
            engine = create_engine(url, pool_pre_ping=True)
        self.engine = engine

    @contextmanager
    def transaction(self) -> Iterator[Connection]:
        with self.engine.begin() as conn:
            conn.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": WRITE_LOCK})
            yield conn

    @contextmanager
    def read(self) -> Iterator[Connection]:
        with self.engine.connect() as conn:
            yield conn

    def healthy(self) -> bool:
        try:
            with self.read() as conn:
                return (
                    conn.execute(text("SELECT to_regclass('public.artifact_versions')")).scalar()
                    is not None
                )
        except Exception:
            return False
