"""P3.1 migrations, least privilege, transactional auditing and queue fencing."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from qfr_eval.db.queue import claim, enqueue, finish

pytestmark = pytest.mark.database


def test_migration_revision_and_forward_schema_only(eval_connect):
    with eval_connect() as conn:
        for name in ("sim_accounts", "sim_orders", "sim_fills", "sim_positions", "sim_nav"):
            assert conn.execute("SELECT to_regclass(%s)", [f"eval.{name}"]).fetchone()[0]
            assert conn.execute(f"SELECT count(*) FROM eval.{name}").fetchone() == (0,)
        assert conn.execute("SELECT count(*) FROM eval.jobs").fetchone()[0] >= 0
    with eval_connect("postgres") as owner:
        assert owner.execute("SELECT version_num FROM eval.alembic_version").fetchone() == (
            "0001_evaluator_core",
        )


def test_concurrent_claims_fencing_expiry_and_atomic_audit(eval_connect):
    queue = str(uuid4())
    with eval_connect() as conn:
        ids = [
            enqueue(
                conn,
                {"index": i},
                principal="test-owner",
                request_id=uuid4(),
                run_after=datetime.now(UTC),
                queue=queue,
            )
            for i in range(2)
        ]

    def take(worker):
        with eval_connect() as conn, conn.transaction():
            return claim(conn, worker=worker, request_id=uuid4(), lease_seconds=60, queue=queue)

    with ThreadPoolExecutor(2) as pool:
        claims = list(pool.map(take, ["worker-0", "worker-1"]))
    assert {c["id"] for c in claims} == set(ids)
    with eval_connect() as conn:
        assert claim(conn, worker="none", request_id=uuid4(), lease_seconds=60, queue=queue) is None
        old = claims[0]
        conn.execute(
            "UPDATE eval.jobs SET lease_until=clock_timestamp()-interval '1 second',"
            "request_id=%s WHERE id=%s",
            [uuid4(), old["id"]],
        )
        new = claim(conn, worker="recovery", request_id=uuid4(), lease_seconds=60, queue=queue)
        assert new["id"] == old["id"] and new["fence"] == old["fence"] + 1
        with pytest.raises(ValueError, match="stale"):
            finish(conn, old["id"], worker="worker-0", fence=old["fence"], request_id=uuid4())
        finish(conn, new["id"], worker="recovery", fence=new["fence"], request_id=uuid4())
        audit = conn.execute(
            "SELECT payload->>'action',created_by,request_id,created_at "
            "FROM eval.events WHERE payload->>'entity_id'=%s",
            [str(new["id"])],
        )
        rows = audit.fetchall()
        assert len(rows) == 5 and all(all(v is not None for v in row) for row in rows)
        # A transaction failure rolls back the work AND the audit, not just one of them.
        request = uuid4()
        with pytest.raises(RuntimeError), conn.transaction():
            enqueue(
                conn,
                {},
                principal="rollback",
                request_id=request,
                run_after=datetime.now(UTC),
                queue=queue,
            )
            raise RuntimeError("rollback")
        assert conn.execute(
            "SELECT count(*) FROM eval.events WHERE request_id=%s", [request]
        ).fetchone() == (0,)


def test_queue_future_work_not_started_or_completed(eval_connect):
    queue = str(uuid4())
    with eval_connect() as conn:
        identity = enqueue(
            conn,
            {},
            principal="owner",
            request_id=uuid4(),
            run_after=datetime.now(UTC) + timedelta(days=1),
            queue=queue,
        )
        assert (
            claim(conn, worker="worker", request_id=uuid4(), lease_seconds=60, queue=queue) is None
        )
        assert conn.execute("SELECT state FROM eval.jobs WHERE id=%s", [identity]).fetchone() == (
            "queued",
        )


def test_protocol_database_freeze_cannot_be_bypassed(eval_connect):
    identity = uuid4()
    with eval_connect() as conn:
        conn.execute(
            "INSERT INTO eval.protocols(id,payload,created_by,request_id,protocol_id,"
            "version,yaml,sha256,status) VALUES(%s,'{}','owner',%s,%s,'1','x',%s,'draft')",
            [identity, uuid4(), str(identity), "0" * 64],
        )
        conn.execute("UPDATE eval.protocols SET status='active' WHERE id=%s", [identity])
        for query in (
            "UPDATE eval.protocols SET yaml='changed' WHERE id=%s",
            "UPDATE eval.protocols SET status='draft' WHERE id=%s",
            "DELETE FROM eval.protocols WHERE id=%s",
        ):
            with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="immutable"):
                conn.execute(query, [identity])


def test_official_record_without_ledger_cannot_commit(eval_connect):
    with eval_connect() as conn:
        with (
            pytest.raises((psycopg.errors.CheckViolation, psycopg.errors.ForeignKeyViolation)),
            conn.transaction(),
        ):
            conn.execute(
                "INSERT INTO eval.official_records(id,payload,created_by,request_id,"
                "artifact_version_id,content_hash,protocol_version,dataset_version_id,"
                "evaluator_version,trial_id) VALUES(%s,'{}','owner',%s,%s,%s,'v1','d','c',%s)",
                [uuid4(), uuid4(), uuid4(), "a" * 64, uuid4()],
            )
