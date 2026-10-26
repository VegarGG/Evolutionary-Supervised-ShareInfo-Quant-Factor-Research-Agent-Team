"""Live registry constraints, append-only audit and commit-safe cursor ordering."""

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import Event
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

pytestmark = pytest.mark.database


def family(conn, *, program="registry-test", kind="factor"):
    identity = uuid4()
    conn.execute(
        "INSERT INTO registry.artifact_families"
        "(id,payload,created_by,request_id,program_id,kind,name) "
        "VALUES(%s,'{}','test-publisher',%s,%s,%s,%s)",
        [identity, uuid4(), program, kind, str(identity)],
    )
    return identity


def version(conn, family_id, *, number=1, program="registry-test", kind="factor", request=None):
    identity = uuid4()
    row = conn.execute(
        "INSERT INTO registry.artifact_versions"
        "(id,artifact_version_id,payload,created_by,request_id,content_hash,family_id,"
        "version_no,program_id,kind,implementation_hash,implementation_kind,"
        "payload_ref,payload_digest,published_seq) "
        "VALUES(%s,%s,'{}','test-publisher',%s,%s,%s,%s,%s,%s,%s,'dsl','fixture',%s,999999999) "
        "RETURNING published_seq",
        [
            identity,
            identity,
            request or uuid4(),
            uuid4().hex + uuid4().hex,
            family_id,
            number,
            program,
            kind,
            "a" * 64,
            "b" * 64,
        ],
    ).fetchone()
    return identity, row[0]


def test_registry_migration_and_database_owned_sequence(registry_connect):
    with registry_connect("postgres") as owner:
        assert owner.execute("SELECT version_num FROM registry.alembic_version").fetchone() == (
            "0001_registry",
        )
    with registry_connect() as conn:
        _, seq = version(conn, family(conn))
        assert 0 < seq < 999999999  # Client-supplied sequence is never trusted.
        assert conn.execute(
            "SELECT has_sequence_privilege(current_user,'registry.publication_sequence','UPDATE')"
        ).fetchone() == (False,)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SELECT setval('registry.publication_sequence',999999999)")


def test_family_kind_program_and_revision_uniqueness(registry_connect):
    with registry_connect() as conn:
        identity = family(conn)
        version(conn, identity)
        with pytest.raises(psycopg.errors.UniqueViolation):
            version(conn, identity)
        for kwargs in ({"kind": "model"}, {"program": "other"}):
            with pytest.raises(psycopg.errors.CheckViolation):
                version(conn, identity, number=2, **kwargs)


def test_registry_aud01_principal_request_time_and_rollback(registry_connect):
    request = uuid4()
    with registry_connect() as conn:
        identity, _ = version(conn, family(conn), request=request)
        row = conn.execute(
            "SELECT created_by,request_id,created_at,payload->>'action' "
            "FROM registry.registry_events WHERE payload->>'entity_id'=%s",
            [str(identity)],
        ).fetchone()
        assert row[:2] == ("test-publisher", request)
        assert row[2].tzinfo is not None and row[3] == "INSERT"
        rollback = uuid4()
        with pytest.raises(RuntimeError), conn.transaction():
            version(conn, family(conn), request=rollback)
            raise RuntimeError("intentional transaction abort")
        assert conn.execute(
            "SELECT count(*) FROM registry.registry_events WHERE request_id=%s", [rollback]
        ).fetchone() == (0,)


@pytest.mark.parametrize("table", ["publication_requests", "payload_objects"])
def test_new_registry_tables_preserve_grants_and_owner_triggers(registry_connect, table):
    identity = uuid4()
    with registry_connect() as conn:
        if table == "publication_requests":
            ver, _ = version(conn, family(conn))
            conn.execute(
                "INSERT INTO registry.publication_requests"
                "(id,payload,created_by,request_id,publish_key,request_digest,version_id) "
                "VALUES(%s,'{}','test',%s,%s,%s,%s)",
                [identity, uuid4(), str(uuid4()), "c" * 64, ver],
            )
        else:
            conn.execute(
                "INSERT INTO registry.payload_objects"
                "(id,payload,created_by,request_id,sha256,object_ref,size_bytes) "
                "VALUES(%s,'{}','test',%s,%s,'fixture',1)",
                [identity, uuid4(), uuid4().hex + uuid4().hex],
            )
        for privilege in ("UPDATE", "DELETE", "TRUNCATE", "TRIGGER"):
            assert conn.execute(
                "SELECT has_table_privilege(current_user,%s,%s)",
                [f"registry.{table}", privilege],
            ).fetchone() == (False,)
    with registry_connect("postgres") as owner:
        for query in (
            "UPDATE registry.{} SET payload='{{}}' WHERE id=%s",
            "DELETE FROM registry.{} WHERE id=%s",
        ):
            with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
                owner.execute(sql.SQL(query).format(sql.Identifier(table)), [identity])
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
            owner.execute(sql.SQL("TRUNCATE registry.{} CASCADE").format(sql.Identifier(table)))


def test_lineage_must_point_backwards_in_same_program(registry_connect):
    with registry_connect() as conn:
        f = family(conn)
        first, _ = version(conn, f)
        second, _ = version(conn, f, number=2)
        other, _ = version(conn, family(conn, program="other"), program="other")

        def parent(child, origin):
            conn.execute(
                "INSERT INTO registry.artifact_parents"
                "(id,payload,created_by,request_id,version_id,parent_version_id,relation) "
                "VALUES(%s,'{}','test',%s,%s,%s,'revision')",
                [uuid4(), uuid4(), child, origin],
            )

        parent(second, first)
        for pair in ((first, second), (first, first), (other, first)):
            with pytest.raises(psycopg.errors.CheckViolation):
                parent(*pair)


def test_since_sequence_cannot_skip_an_uncommitted_earlier_publication(registry_connect):
    ready = Event()
    with registry_connect() as first, registry_connect() as observer, ThreadPoolExecutor(1) as pool:
        first_family = family(first)
        second_family = family(first)

        def publish_second():
            with registry_connect() as conn:
                ready.set()
                return version(conn, second_family)

        with first.transaction():
            first_id, first_seq = version(first, first_family)
            future = pool.submit(publish_second)
            assert ready.wait(5)
            with pytest.raises(TimeoutError):
                future.result(timeout=0.1)
            assert observer.execute(
                "SELECT count(*) FROM registry.artifact_versions WHERE family_id IN (%s,%s)",
                [first_family, second_family],
            ).fetchone() == (0,)
        second_id, second_seq = future.result(timeout=5)
        assert second_seq > first_seq
        assert observer.execute(
            "SELECT id FROM registry.artifact_versions WHERE published_seq>=%s "
            "AND family_id IN (%s,%s) ORDER BY published_seq",
            [first_seq, first_family, second_family],
        ).fetchall() == [(first_id,), (second_id,)]


def test_blank_principal_rejected_without_audit_success(registry_connect):
    with registry_connect() as conn, pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            "INSERT INTO registry.registry_events(id,payload,created_by,request_id) "
            "VALUES(%s,'{}','  ',%s)",
            [uuid4(), uuid4()],
        )
