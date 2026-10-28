"""Research-only schema migrations and transaction attribution."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

import psycopg
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool


def migrate(dsn: str) -> None:
    """Require a separate owner connection; never migrate another zone."""
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parent / "alembic"))
    engine = create_engine(
        "postgresql+psycopg://", creator=lambda: psycopg.connect(dsn), poolclass=NullPool
    )
    try:
        with engine.begin() as connection:
            if connection.exec_driver_sql("SELECT current_database()").scalar() != "research_db":
                raise ValueError("Research migrations require research_db")
            connection.exec_driver_sql("SELECT pg_advisory_xact_lock(72460401)")
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
    finally:
        engine.dispose()


@contextmanager
def attributed(connection: psycopg.Connection, principal: str, request_id: UUID) -> Iterator[None]:
    """Atomic work and audit, preserving an enclosing transaction's attribution.

    Service authentication supplies the principal. This is not an auth mechanism
    for arbitrary holders of a database credential. Never store tokens here.
    """
    if not principal.strip():
        raise ValueError("nonblank principal required")
    with connection.transaction():
        previous = connection.execute(
            "SELECT current_setting('qfr.principal',true),current_setting('qfr.request_id',true)"
        ).fetchone()
        if previous is None:
            raise RuntimeError("Cannot capture transaction attribution")
        connection.execute(
            "SELECT set_config('qfr.principal',%s,true),set_config('qfr.request_id',%s,true)",
            [principal, str(request_id)],
        )
        yield
        # On error the transaction/savepoint rollback restores the prior values.
        connection.execute(
            "SELECT set_config('qfr.principal',%s,true),set_config('qfr.request_id',%s,true)",
            [previous[0] or "", previous[1] or ""],
        )
