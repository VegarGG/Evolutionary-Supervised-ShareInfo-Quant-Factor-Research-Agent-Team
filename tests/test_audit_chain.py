"""Hash-chained audit logs (PLAN Phase 8, P8.5).

registry_events, eval.events, mcp_calls and approvals were insert-only already. Each of
their databases now holds a hash chain over them: audit_seal() links the rows not yet
linked, and audit_verify() recomputes every link and every row digest. A row edited,
deleted or slipped in around the insert-only rules (as a table owner can, by disabling
the triggers) breaks the chain at that row's link. Application roles cannot touch it.

Each test runs as the database's migration role inside a transaction that is rolled back.
"""

import os
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from qfr_core.ids import uuid7

pytestmark = pytest.mark.postgres

ZERO = "0" * 64
# database: (migration URL variable, app URL variable, schema, audit table, id column,
# a row of that table without its id)
AUDITED: dict[str, tuple[str, str, str, str, str, str]] = {
    "registry": (
        "QFR_TEST_REGISTRY_MIGRATION_URL", "QFR_TEST_REGISTRY_DB_URL", "public",
        "registry_events", "event_id",
        "now(), 'test', 'TEST_EVENT', NULL, NULL, 'r', '{\"n\": 1.5}'::jsonb",
    ),
    "eval": (
        "QFR_TEST_EVAL_MIGRATION_URL", "QFR_TEST_EVAL_DB_URL", "eval", "events", "event_id",
        "now(), 'test', 'test_event', 'test', 'x', 'r', '{\"n\": 1.5}'::jsonb",
    ),
    "control": (
        "QFR_TEST_CONTROL_MIGRATION_URL", "QFR_TEST_CONTROL_DB_URL", "public", "mcp_calls",
        "call_id",
        "now(), 'owner', 'qfr.status', repeat('a', 64), 2, 3, 0.125, 'ok', NULL, '{}', 'r'",
    ),
}  # fmt: skip


def url(variable: str) -> str:
    value = os.environ.get(variable)
    if not value:
        if os.environ.get("QFR_REQUIRE_DB_TESTS") == "1":
            pytest.fail(f"{variable} is required")
        pytest.skip(f"{variable} not configured")
    return value.replace("postgresql+psycopg://", "postgresql://")


@pytest.fixture(params=sorted(AUDITED))
def db(request) -> Iterator[tuple[psycopg.Connection, tuple[str, ...]]]:
    spec = AUDITED[request.param]
    with psycopg.connect(url(spec[0])) as conn:
        try:
            yield conn, spec
        finally:
            conn.rollback()


def verify(conn: psycopg.Connection, schema: str) -> dict[str, Any]:
    cursor = conn.execute(f"SELECT * FROM {schema}.audit_verify()")
    names = [c.name for c in cursor.description or []]
    return dict(zip(names, cursor.fetchone() or (), strict=True))


def insert(conn: psycopg.Connection, spec: tuple[str, ...]) -> str:
    _, _, schema, table, _, values = spec
    row_id = str(uuid7())
    conn.execute(f"INSERT INTO {schema}.{table} VALUES ('{row_id}', {values})")
    return row_id


def seq_of(conn: psycopg.Connection, schema: str, table: str, row_id: str) -> int:
    found = conn.execute(
        f"SELECT chain_seq FROM {schema}.audit_chain WHERE table_name = %s AND row_id = %s",
        (table, row_id),
    ).fetchone()
    assert found is not None
    return int(found[0])


def test_sealed_rows_verify_and_their_links_follow_one_another(db):
    conn, spec = db
    schema, table = spec[2], spec[3]
    conn.execute(f"SELECT {schema}.audit_seal()")
    before = verify(conn, schema)
    rows = [insert(conn, spec) for _ in range(3)]
    # Rows other tests commit meanwhile may be sealed too, so counts are lower bounds.
    assert verify(conn, schema)["unsealed"] >= 3
    (added,) = conn.execute(f"SELECT {schema}.audit_seal()").fetchone() or (0,)
    assert added >= 3
    after = verify(conn, schema)
    assert after["status"] == "ok" and after["problem"] is None and after["unsealed"] == 0
    assert after["head_seq"] == before["head_seq"] + added == after["links"]
    links = conn.execute(
        f"SELECT chain_seq, prev_hash, link_hash FROM {schema}.audit_chain "
        "WHERE chain_seq > %s ORDER BY chain_seq",
        (before["head_seq"],),
    ).fetchall()
    assert links[0][1] == (before["head_hash"] if before["head_seq"] else ZERO)
    assert [link[1] for link in links[1:]] == [link[2] for link in links[:-1]]
    seqs = [seq_of(conn, schema, table, r) for r in rows]
    assert seqs == sorted(seqs) and set(seqs) <= {link[0] for link in links}
    # Sealing again adds nothing; the chain does not depend on the session's time zone.
    assert conn.execute(f"SELECT {schema}.audit_seal()").fetchone() == (0,)
    conn.execute("SET timezone TO 'America/New_York'")
    assert verify(conn, schema)["status"] == "ok"


def test_an_edited_or_deleted_audit_row_breaks_the_chain_at_its_link(db):
    conn, spec = db
    schema, table, id_column = spec[2], spec[3], spec[4]
    first, second = insert(conn, spec), insert(conn, spec)
    conn.execute(f"SELECT {schema}.audit_seal()")
    # Only an owner can get around the insert-only triggers, and the chain still shows it.
    conn.execute(f"ALTER TABLE {schema}.{table} DISABLE TRIGGER USER")
    conn.execute(f"UPDATE {schema}.{table} SET request_id = 'edited' WHERE {id_column} = %s",
                 (second,))  # fmt: skip
    result = verify(conn, schema)
    assert (result["status"], result["problem"]) == ("broken", "row_changed")
    assert result["failed_seq"] == seq_of(conn, schema, table, second)
    conn.execute(f"DELETE FROM {schema}.{table} WHERE {id_column} = %s", (first,))
    result = verify(conn, schema)
    assert (result["problem"], result["failed_seq"]) == (
        "row_missing",
        seq_of(conn, schema, table, first),
    )


def test_a_rewritten_link_breaks_the_chain(db):
    conn, spec = db
    schema = spec[2]
    insert(conn, spec)
    conn.execute(f"SELECT {schema}.audit_seal()")
    head = verify(conn, schema)["head_seq"]
    conn.execute(f"ALTER TABLE {schema}.audit_chain DISABLE TRIGGER USER")
    conn.execute(
        f"UPDATE {schema}.audit_chain SET row_digest = repeat('f', 64) WHERE chain_seq = %s",
        (head,),
    )
    result = verify(conn, schema)
    assert (result["status"], result["problem"], result["failed_seq"]) == (
        "broken",
        "link_broken",
        head,
    )


def test_the_chain_refuses_changes_and_application_roles(db):
    conn, spec = db
    schema = spec[2]
    insert(conn, spec)
    conn.execute(f"SELECT {schema}.audit_seal()")
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        conn.execute(f"DELETE FROM {schema}.audit_chain")
    conn.rollback()
    with psycopg.connect(url(spec[1])) as app:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            app.execute(f"SELECT count(*) FROM {schema}.audit_chain")
