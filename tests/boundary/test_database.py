import os
from datetime import UTC, datetime
from uuid import uuid4

import psycopg
import pytest
from qfr_mcp.audit import MCPCall, PostgresAudit, uuid7
from sqlalchemy import create_engine, text

pytestmark = pytest.mark.postgres


@pytest.fixture
def credentials():
    url = os.environ.get("QFR_TEST_CONTROL_DB_URL")
    if not url:
        if os.environ.get("QFR_REQUIRE_DB_TESTS") == "1":
            pytest.fail("real PostgreSQL boundary tests required but credentials are absent")
        pytest.skip("PostgreSQL integration credentials not configured")
    return {
        name: os.environ[f"QFR_TEST_{name}_DB_URL"]
        for name in ("CONTROL", "RESEARCH", "EVAL", "REGISTRY", "FEEDBACK")
    }


def test_bnd_01_cross_database_connections_denied(credentials):
    pairs = {
        "RESEARCH": ["eval_db", "control_db", "registry_db"],
        "EVAL": ["research_db", "control_db"],
        "CONTROL": ["research_db", "eval_db", "registry_db"],
    }
    for role, databases in pairs.items():
        source = credentials[role].replace("postgresql+psycopg://", "postgresql://")
        with psycopg.connect(source):
            pass
        for database in databases:
            url = source.rsplit("/", 1)[0] + "/" + database
            with pytest.raises(psycopg.OperationalError, match="permission denied for database"):
                psycopg.connect(url)


def test_control_audit_is_insert_only_even_for_migration_owner(credentials):
    audit = PostgresAudit(credentials["CONTROL"])
    call = MCPCall(
        call_id=uuid7(),
        at=datetime.now(UTC),
        principal="boundary-test",
        tool="test",
        args_digest="a" * 64,
        args_size=0,
        result_size=0,
        duration_ms=0,
        outcome="ok",
        error_code=None,
        downstream_request_ids=[],
        request_id=str(uuid4()),
    )
    audit.append(call)
    assert audit.healthy()
    for url in (credentials["CONTROL"], os.environ["QFR_TEST_CONTROL_MIGRATION_URL"]):
        engine = create_engine(url)
        for sql in (
            "UPDATE mcp_calls SET outcome='altered'",
            "DELETE FROM mcp_calls",
            "TRUNCATE mcp_calls",
        ):
            with pytest.raises(Exception, match="permission denied|append-only"):
                with engine.begin() as conn:
                    conn.execute(text(sql))


def test_feedback_role_has_no_private_table_or_create_access(credentials):
    engine = create_engine(credentials["FEEDBACK"])
    with engine.connect() as conn:
        assert (
            conn.execute(
                text("SELECT has_schema_privilege(current_user, 'eval', 'USAGE')")
            ).scalar()
            is False
        )
        assert (
            conn.execute(
                text("SELECT has_schema_privilege(current_user, 'feedback', 'CREATE')")
            ).scalar()
            is False
        )
