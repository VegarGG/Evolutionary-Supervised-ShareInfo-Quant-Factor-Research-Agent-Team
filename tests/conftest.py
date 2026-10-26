"""Real-database migration setup shared by all stage boundary suites."""

import os
from pathlib import Path

import psycopg
import pytest
from psycopg.conninfo import make_conninfo
from qfr_eval.db import migrate

ROOT = Path(__file__).resolve().parents[1]


def database_dsn(role="postgres", database="eval_db"):
    base = os.environ.get("QFR_TEST_POSTGRES_DSN")
    if not base:
        pytest.skip("Live PostgreSQL required: QFR_TEST_POSTGRES_DSN")
    directory = Path(os.environ.get("QFR_TEST_SECRET_DIR", ROOT / ".secrets"))
    return make_conninfo(
        base,
        user=role,
        dbname=database,
        password=(directory / f"{role}_password").read_text().strip(),
    )


@pytest.fixture(scope="session", autouse=True)
def migrated_evaluator():
    if os.environ.get("QFR_TEST_POSTGRES_DSN"):
        try:
            migrate(database_dsn())
        except Exception as error:
            # Never render a driver/SQLAlchemy frame with the credential-bearing DSN.
            pytest.fail(f"Evaluator migration failed ({type(error).__name__})", pytrace=False)


@pytest.fixture
def eval_connect():
    def factory(role="eval_rw"):
        try:
            return psycopg.connect(database_dsn(role), autocommit=True)
        except psycopg.OperationalError as error:
            raise psycopg.OperationalError(str(error)) from None

    return factory
