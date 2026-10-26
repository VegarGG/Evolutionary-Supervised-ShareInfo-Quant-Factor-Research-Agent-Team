"""Live PostgreSQL boundaries; no test silently substitutes a different backend."""

import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.database


@pytest.fixture
def connect():
    dsn = os.environ.get("QFR_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("Live PostgreSQL required: set QFR_TEST_POSTGRES_DSN after just up")

    def factory(role, database):
        secret_dir = Path(os.environ.get("QFR_TEST_SECRET_DIR", ROOT / ".secrets"))
        password = (secret_dir / f"{role}_password").read_text().strip()
        try:
            return psycopg.connect(
                make_conninfo(dsn, user=role, password=password, dbname=database), autocommit=True
            )
        except psycopg.OperationalError as exc:
            # Do not allow pytest to render driver frames containing credentials.
            raise psycopg.OperationalError(str(exc)) from None

    return factory


def test_postgres16_databases_and_roles(connect):
    with connect("postgres", "postgres") as conn:
        assert 160000 <= conn.info.server_version < 170000
        assert set(
            conn.execute(
                "SELECT datname FROM pg_database WHERE datname IN "
                "('research_db', 'registry_db', 'eval_db')"
            ).fetchall()
        ) == {("research_db",), ("registry_db",), ("eval_db",)}
        roles = conn.execute(
            "SELECT rolname, rolsuper, rolcreatedb, rolcreaterole, rolbypassrls "
            "FROM pg_roles WHERE rolname IN "
            "('research_rw','registry_app','eval_rw','feedback_ro')"
        ).fetchall()
        assert len(roles) == 4
        assert all(row[1:] == (False, False, False, False) for row in roles)


def test_all_application_passwords_are_scram_credentials(connect):
    with connect("postgres", "postgres") as conn:
        # Select only booleans: neither plaintext credentials nor hashes enter evidence.
        rows = conn.execute(
            "SELECT rolpassword IS NOT NULL AND rolpassword LIKE 'SCRAM-SHA-256$%' "
            "FROM pg_authid WHERE rolname IN "
            "('research_rw','registry_app','eval_rw','feedback_ro')"
        ).fetchall()
        assert rows == [(True,)] * 4


@pytest.mark.parametrize(
    "role,allowed,forbidden",
    [
        ("research_rw", "research_db", "eval_db"),
        ("eval_rw", "eval_db", "research_db"),
        ("research_rw", "research_db", "registry_db"),
        ("registry_app", "registry_db", "eval_db"),
        ("feedback_ro", "eval_db", "research_db"),
    ],
)
def test_bnd_01_connect_isolation(connect, role, allowed, forbidden):
    with connect(role, allowed) as conn:
        assert conn.execute("SELECT current_user").fetchone() == (role,)
    with pytest.raises(psycopg.OperationalError, match="permission denied for database"):
        connect(role, forbidden)


def test_feedback_can_only_select_released_views(connect):
    with connect("feedback_ro", "eval_db") as conn:
        for view in [
            "released_reports_v",
            "artifact_status_v",
            "library_v",
            "policy_card_v",
            "protocol_card_v",
        ]:
            conn.execute(sql.SQL("SELECT * FROM feedback.{} LIMIT 1").format(sql.Identifier(view)))
        for query in [
            "SELECT * FROM eval.official_records",
            "SELECT * FROM eval.released_reports",
            "CREATE TABLE feedback.attack (id int)",
            "DELETE FROM feedback.released_reports_v",
        ]:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(query)


@pytest.mark.parametrize(
    "database,role,schema,table",
    [
        ("registry_db", "registry_app", "registry", "artifact_versions"),
        ("research_db", "research_rw", "research", "events"),
        ("eval_db", "eval_rw", "eval", "official_records"),
        ("eval_db", "eval_rw", "eval", "released_reports"),
        ("eval_db", "eval_rw", "eval", "events"),
        ("eval_db", "eval_rw", "eval", "delivery_receipts"),
    ],
)
def test_reg_01_insert_only_grants_and_owner_triggers(connect, database, role, schema, table):
    table_id = sql.Identifier(schema, table)
    row_id = uuid4()
    columns = ["id", "payload", "created_by", "request_id"]
    values = [row_id, "{}", "stage0-test", uuid4()]
    if table in ["artifact_versions", "official_records", "released_reports"]:
        columns += ["artifact_version_id", "content_hash"]
        values += [uuid4(), uuid4().hex + uuid4().hex]
    if table in ["official_records", "released_reports"]:
        columns += ["protocol_version", "dataset_version_id", "evaluator_version"]
        values += ["fixture-protocol/1", "fixture-data", "stage0"]
    with connect(role, database) as conn:
        conn.execute(
            sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                table_id,
                sql.SQL(",").join(map(sql.Identifier, columns)),
                sql.SQL(",").join(sql.Placeholder() for _ in columns),
            ),
            values,
        )
        assert conn.execute(
            sql.SQL("SELECT id FROM {} WHERE id=%s").format(table_id), [row_id]
        ).fetchone() == (row_id,)
        for verb in ["UPDATE", "DELETE", "TRUNCATE"]:
            assert conn.execute(
                "SELECT has_table_privilege(current_user,%s,%s)", [f"{schema}.{table}", verb]
            ).fetchone() == (False,)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(sql.SQL("ALTER TABLE {} DISABLE TRIGGER ALL").format(table_id))
    # Grants alone are insufficient: even the bootstrap owner hits the triggers.
    with connect("postgres", database) as conn:
        for statement in [
            sql.SQL("UPDATE {} SET payload='{{}}' WHERE id=%s"),
            sql.SQL("DELETE FROM {} WHERE id=%s"),
        ]:
            with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="insert-only"):
                conn.execute(statement.format(table_id), [row_id])
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="insert-only"):
            conn.execute(sql.SQL("TRUNCATE {} CASCADE").format(table_id))


def test_all_insert_only_tables_have_mutation_and_truncate_triggers(connect):
    for database, schema in [
        ("registry_db", "registry"),
        ("research_db", "research"),
        ("eval_db", "eval"),
    ]:
        with connect("postgres", database) as conn:
            rows = conn.execute(
                "SELECT c.relname, count(t.oid) FROM pg_class c "
                "JOIN pg_namespace n ON n.oid=c.relnamespace "
                "JOIN pg_trigger t ON t.tgrelid=c.oid AND NOT t.tgisinternal "
                "WHERE n.nspname=%s GROUP BY c.relname",
                [schema],
            ).fetchall()
            assert rows
            assert all(count == 2 for _, count in rows)
            if schema == "eval":
                assert {"trial_ledger", "official_records", "released_reports", "events"} <= {
                    name for name, _ in rows
                }
