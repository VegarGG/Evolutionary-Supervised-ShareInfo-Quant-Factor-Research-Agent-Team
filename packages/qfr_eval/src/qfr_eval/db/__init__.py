"""Evaluator-only persistence; the measurement path does not open connections."""

from pathlib import Path

import psycopg
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool


def migrate(dsn: str) -> None:
    """Apply the reviewed eval_db migration with a separately supplied owner DSN."""
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parent / "alembic"))
    engine = create_engine(
        "postgresql+psycopg://", creator=lambda: psycopg.connect(dsn), poolclass=NullPool
    )
    try:
        with engine.begin() as connection:
            if connection.exec_driver_sql("SELECT current_database()").scalar() != "eval_db":
                raise ValueError("Evaluator migrations require eval_db")
            # Serialize first installation, including creation of Alembic's version table.
            connection.exec_driver_sql("SELECT pg_advisory_xact_lock(72460201)")
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
    finally:
        engine.dispose()
