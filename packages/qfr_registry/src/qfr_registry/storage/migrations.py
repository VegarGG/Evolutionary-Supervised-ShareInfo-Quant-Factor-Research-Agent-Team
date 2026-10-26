"""Registry-only migrations; application connections never perform DDL."""

from pathlib import Path

import psycopg
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool


def migrate(dsn: str) -> None:
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parent / "alembic"))
    engine = create_engine(
        "postgresql+psycopg://", creator=lambda: psycopg.connect(dsn), poolclass=NullPool
    )
    try:
        with engine.begin() as connection:
            if connection.exec_driver_sql("SELECT current_database()").scalar() != "registry_db":
                raise ValueError("Registry migrations require registry_db")
            connection.exec_driver_sql("SELECT pg_advisory_xact_lock(72460301)")
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
    finally:
        engine.dispose()
