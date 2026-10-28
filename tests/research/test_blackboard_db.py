"""Real research-zone persistence, audit and queue races; no evaluator control."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb
from qfr_research.db import attributed, migrate
from qfr_research.db.queue import LeaseLost, QueueConflict, claim, defer, enqueue, finish, renew

pytestmark = pytest.mark.database
NOW = datetime(2020, 1, 1, tzinfo=UTC)


def insert(conn, table, *, principal="test-owner", request=None, **columns):
    request = request or uuid4()
    identity = columns.pop("id", uuid4())
    with attributed(conn, principal, request):
        fields = {
            "id": identity,
            "payload": Jsonb({}),
            "created_by": principal,
            "request_id": request,
            **columns,
        }
        conn.execute(
            f"INSERT INTO research.{table} ({','.join(fields)}) "
            f"VALUES ({','.join(['%s'] * len(fields))})",
            list(fields.values()),
        )
    return identity


def program(conn, *, status="active"):
    return insert(
        conn, "programs", name="fixture", status=status, charter=Jsonb({}), charter_revision=1
    )


def job(conn, program_id, *, state="ready"):
    bundle = insert(
        conn, "input_bundles", program_id=program_id, bundle_key=str(uuid4()), sha256="a" * 64
    )
    brief = insert(conn, "briefs", program_id=program_id, input_bundle_id=bundle, sha256="b" * 64)
    return insert(
        conn,
        "research_jobs",
        program_id=program_id,
        input_bundle_id=bundle,
        brief_id=brief,
        idempotency_key=str(uuid4()),
        payload_hash="c" * 64,
        config_hash="d" * 64,
        gate_spec_hash="e" * 64,
        state=state,
    )


def queued(conn, *, program_id=None, state="ready", queue=None, run_after=NOW):
    program_id = program_id or program(conn)
    parent = job(conn, program_id, state=state)
    queue = queue or str(uuid4())
    entry = enqueue(
        conn,
        {"task": "manual"},
        program_id=program_id,
        research_job_id=parent,
        queue=queue,
        enqueue_key=str(uuid4()),
        principal="test-owner",
        request_id=uuid4(),
        run_after=run_after,
    )
    return program_id, parent, queue, entry


def take(conn, queue, worker="test-worker"):
    return claim(conn, worker=worker, request_id=uuid4(), lease_seconds=60, queue=queue)


def test_research_migration_is_idempotent_and_wrong_database_refused(
    research_connect, migration_dsn
):
    migrate(migration_dsn("research_db"))
    with research_connect("postgres") as owner:
        assert owner.execute("SELECT version_num FROM research.alembic_version").fetchone() == (
            "0001_blackboard",
        )
        for table in ("program_revisions", "briefs", "checkpoints", "checkpoint_answers"):
            assert owner.execute("SELECT to_regclass(%s)", [f"research.{table}"]).fetchone()[0]
    with pytest.raises(ValueError, match="research_db"):
        migrate(migration_dsn("eval_db"))


def test_every_write_requires_attribution_and_preserves_original_identity(research_connect):
    with research_connect() as conn:
        with pytest.raises(psycopg.errors.CheckViolation, match="transaction principal"):
            conn.execute(
                "INSERT INTO research.programs(id,payload,created_by,request_id,name,"
                "charter,charter_revision) VALUES(%s,'{}','owner',%s,'fixture','{}',1)",
                [uuid4(), uuid4()],
            )
        identity = program(conn)
        request = uuid4()
        with attributed(conn, "different-editor", request):
            conn.execute("UPDATE research.programs SET status='paused' WHERE id=%s", [identity])
        assert conn.execute(
            "SELECT created_by,status FROM research.programs WHERE id=%s", [identity]
        ).fetchone() == ("test-owner", "paused")
        row = conn.execute(
            "SELECT created_by,payload FROM research.events WHERE request_id=%s", [request]
        ).fetchone()
        assert row == (
            "different-editor",
            {"action": "UPDATE", "entity_type": "programs", "entity_id": str(identity)},
        )
        with (
            pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState),
            attributed(conn, "x", uuid4()),
        ):
            conn.execute("UPDATE research.programs SET created_by='x' WHERE id=%s", [identity])
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("DELETE FROM research.programs WHERE id=%s", [identity])
        assert conn.execute(
            "SELECT count(*) FROM research.events WHERE program_id=%s", [identity]
        ).fetchone() == (2,)


def test_nested_attribution_and_audit_rollback_are_atomic(research_connect):
    with research_connect() as conn:
        outer, inner, failed = uuid4(), uuid4(), uuid4()
        with attributed(conn, "outer", outer):
            first = insert(
                conn,
                "programs",
                principal="inner",
                request=inner,
                name="inner",
                charter=Jsonb({}),
                charter_revision=1,
            )
            assert conn.execute("SELECT current_setting('qfr.principal')").fetchone() == ("outer",)
            with pytest.raises(RuntimeError), attributed(conn, "failed", failed):
                insert(
                    conn,
                    "programs",
                    principal="failed",
                    request=failed,
                    name="failure",
                    charter=Jsonb({}),
                    charter_revision=1,
                )
                raise RuntimeError("roll back work and audit")
            assert conn.execute("SELECT current_setting('qfr.request_id')").fetchone() == (
                str(outer),
            )
        assert conn.execute(
            "SELECT count(*) FROM research.events WHERE request_id=%s", [failed]
        ).fetchone() == (0,)
        assert conn.execute(
            "SELECT count(*) FROM research.events WHERE program_id=%s", [first]
        ).fetchone() == (1,)
        assert not conn.execute("SELECT current_setting('qfr.principal',true)").fetchone()[0]
        failed_outer = uuid4()
        with pytest.raises(RuntimeError), attributed(conn, "outer", failed_outer):
            insert(
                conn,
                "programs",
                principal="outer",
                request=failed_outer,
                name="rollback",
                charter=Jsonb({}),
                charter_revision=1,
            )
            raise RuntimeError("outer rollback")
        assert conn.execute(
            "SELECT count(*) FROM research.events WHERE request_id=%s", [failed_outer]
        ).fetchone() == (0,)


def test_program_scope_cannot_be_changed_or_cross_referenced(research_connect):
    with research_connect() as conn:
        a, b = program(conn), program(conn)
        island = insert(conn, "islands", program_id=a, key="seed", theme="fixture")
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            insert(conn, "hypotheses", program_id=b, island_id=island)
        with (
            pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState),
            attributed(conn, "x", uuid4()),
        ):
            conn.execute("UPDATE research.islands SET program_id=%s WHERE id=%s", [b, island])
        with pytest.raises(psycopg.errors.CheckViolation):
            insert(conn, "islands", key="unscoped", theme="fixture")


def test_immutable_records_and_admitted_job_intent(research_connect):
    with research_connect() as conn:
        p = program(conn)
        j = job(conn, p)
        rev = insert(conn, "program_revisions", program_id=p, revision=1, sha256="1" * 64)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("UPDATE research.program_revisions SET payload='{}' WHERE id=%s", [rev])
        with (
            pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState),
            attributed(conn, "x", uuid4()),
        ):
            conn.execute(
                "UPDATE research.research_jobs SET config_hash=%s WHERE id=%s", ["f" * 64, j]
            )
        with (
            pytest.raises(psycopg.errors.CheckViolation, match="receipt"),
            attributed(conn, "x", uuid4()),
        ):
            conn.execute("UPDATE research.research_jobs SET state='completed' WHERE id=%s", [j])
        second = job(conn, p)
        receipt = insert(
            conn,
            "delivery_refs",
            program_id=p,
            research_job_id=second,
            receipt_id=str(uuid4()),
            gate_spec_hash="e" * 64,
            receipt_sha256="f" * 64,
            result="pass",
            verification_key_id="synthetic-public-key",
        )
        with (
            pytest.raises(psycopg.errors.CheckViolation, match="receipt"),
            attributed(conn, "x", uuid4()),
        ):
            conn.execute(
                "UPDATE research.research_jobs SET state='completed',delivery_ref_id=%s "
                "WHERE id=%s",
                [receipt, j],
            )
        other_bundle = insert(
            conn, "input_bundles", program_id=p, bundle_key=str(uuid4()), sha256="a" * 64
        )
        brief = conn.execute(
            "SELECT brief_id FROM research.research_jobs WHERE id=%s", [j]
        ).fetchone()[0]
        with pytest.raises(psycopg.errors.CheckViolation, match="bundle must agree"):
            insert(
                conn,
                "research_jobs",
                program_id=p,
                input_bundle_id=other_bundle,
                brief_id=brief,
                idempotency_key=str(uuid4()),
                payload_hash="c" * 64,
                config_hash="d" * 64,
                gate_spec_hash="e" * 64,
            )


def test_enqueue_idempotence_and_conflict_including_concurrent_retry(research_connect):
    with research_connect() as conn:
        p = program(conn)
        j = job(conn, p)
    key, queue = str(uuid4()), str(uuid4())

    def submit(payload):
        with research_connect() as conn:
            return enqueue(
                conn,
                payload,
                program_id=p,
                research_job_id=j,
                queue=queue,
                enqueue_key=key,
                principal="submitter",
                request_id=uuid4(),
                run_after=NOW,
            )

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(submit, [{"x": 1}, {"x": 1}]))
    assert results[0] == results[1]
    with pytest.raises(QueueConflict):
        submit({"x": 2})
    with research_connect() as conn:
        assert conn.execute(
            "SELECT count(*) FROM research.events WHERE payload->>'entity_id'=%s", [str(results[0])]
        ).fetchone() == (1,)


def test_concurrent_claims_recovery_and_stale_fence(research_connect):
    queue = str(uuid4())
    with research_connect() as conn:
        p = program(conn)
        entries = [queued(conn, program_id=p, queue=queue)[3] for _ in range(2)]

    def run(worker):
        with research_connect() as conn:
            return take(conn, queue, worker)

    with ThreadPoolExecutor(2) as pool:
        leases = list(pool.map(run, ["worker-1", "worker-2"]))
    assert {UUID(item.queue_entry_id) for item in leases} == set(entries)
    with research_connect() as conn:
        assert take(conn, queue) is None
        old = leases[0]
        with attributed(conn, "expiry-test", uuid4()):
            conn.execute(
                "UPDATE research.jobs SET lease_until=clock_timestamp()-interval '1 second' "
                "WHERE id=%s",
                [UUID(old.queue_entry_id)],
            )
        with pytest.raises(LeaseLost):
            finish(conn, old, request_id=uuid4())
        current = take(conn, queue, "recovery")
        assert current.fence == old.fence + 1 and current.attempt == old.attempt + 1
        with pytest.raises(LeaseLost):
            renew(conn, old, request_id=uuid4(), lease_seconds=60)
        renewed = renew(conn, current, request_id=uuid4(), lease_seconds=120)
        assert renewed.lease_until > current.lease_until and renewed.fence == current.fence
        finish(conn, renewed, request_id=uuid4())
        assert conn.execute(
            "SELECT state FROM research.research_jobs WHERE id=%s", [UUID(current.research_job_id)]
        ).fetchone() == ("ready",)
        with pytest.raises(LeaseLost):
            finish(conn, renewed, request_id=uuid4())


@pytest.mark.parametrize(
    "state",
    [
        "received",
        "validating",
        "needs_input",
        "paused",
        "budget_paused",
        "waiting_for_data",
        "failed",
        "cancelled",
        "awaiting_evaluation",
        "validating_delivery",
    ],
)
def test_non_runnable_parent_never_starts_work(research_connect, state):
    with research_connect() as conn:
        _, _, queue, entry = queued(conn, state=state)
        assert take(conn, queue) is None
        assert conn.execute(
            "SELECT state,attempts FROM research.jobs WHERE id=%s", [entry]
        ).fetchone() == ("queued", 0)


def test_pause_is_one_task_boundary_cancel_refuses_completion_and_defer_is_not_success(
    research_connect,
):
    with research_connect() as conn:
        p, parent, queue, _ = queued(conn)
        lease = take(conn, queue)
        with attributed(conn, "owner", uuid4()):
            conn.execute("UPDATE research.research_jobs SET state='paused' WHERE id=%s", [parent])
        finish(conn, lease, request_id=uuid4())
        assert conn.execute(
            "SELECT state FROM research.research_jobs WHERE id=%s", [parent]
        ).fetchone() == ("paused",)
        _, parent2, _, _ = queued(conn, program_id=p, queue=queue)
        lease = take(conn, queue)
        with attributed(conn, "owner", uuid4()):
            conn.execute(
                "UPDATE research.research_jobs SET state='cancelled' WHERE id=%s", [parent2]
            )
        with pytest.raises(LeaseLost):
            finish(conn, lease, request_id=uuid4())
        queued(conn, program_id=p, queue=queue)
        lease = take(conn, queue)
        defer(conn, lease, request_id=uuid4(), run_after=datetime.now(UTC) + timedelta(days=1))
        assert take(conn, queue) is None
        assert conn.execute(
            "SELECT state FROM research.jobs WHERE id=%s", [UUID(lease.queue_entry_id)]
        ).fetchone() == ("queued",)


def test_inactive_program_and_future_task_remain_idle(research_connect):
    with research_connect() as conn:
        p = program(conn, status="inactive")
        _, _, queue, _ = queued(conn, program_id=p)
        assert take(conn, queue) is None
        with attributed(conn, "owner", uuid4()):
            conn.execute("UPDATE research.programs SET status='active' WHERE id=%s", [p])
        assert take(conn, queue) is not None
        _, _, future, _ = queued(conn, run_after=datetime.now(UTC) + timedelta(days=365))
        assert take(conn, future) is None
        assert take(conn, str(uuid4())) is None


def test_locked_parent_does_not_block_another_job_or_hide_pause(research_connect):
    with research_connect() as first, research_connect() as second:
        p, parent, queue, entry = queued(first)
        other = queued(first, program_id=p, queue=queue)[3]
        with attributed(first, "owner", uuid4()):
            first.execute("UPDATE research.research_jobs SET state='paused' WHERE id=%s", [parent])
            lease = take(second, queue)
            assert UUID(lease.queue_entry_id) == other
        assert take(second, queue) is None
        assert first.execute(
            "SELECT attempts FROM research.jobs WHERE id=%s", [entry]
        ).fetchone() == (0,)


def test_queue_rejects_invalid_request_before_sql():
    with pytest.raises(ValueError, match="positive"):
        claim(None, worker="x", request_id=uuid4(), lease_seconds=0, queue="q")
    with pytest.raises(ValueError, match="aware"):
        enqueue(
            None,
            {},
            program_id=uuid4(),
            research_job_id=uuid4(),
            queue="q",
            enqueue_key="x",
            principal="x",
            request_id=uuid4(),
            run_after=datetime(2020, 1, 1),
        )


@pytest.mark.parametrize("operation", ["finish", "renew", "defer"])
def test_expiry_between_lock_and_mutation_still_refused(research_connect, monkeypatch, operation):
    import qfr_research.db.queue as queue_module

    original = queue_module._locked_current

    def expire_after_lock(conn, lease):
        original(conn, lease)
        conn.execute(
            "UPDATE research.jobs SET lease_until=clock_timestamp()-interval '1 second' "
            "WHERE id=%s",
            [UUID(lease.queue_entry_id)],
        )

    with research_connect() as conn:
        _, _, queue, entry = queued(conn)
        lease = take(conn, queue)
        monkeypatch.setattr(queue_module, "_locked_current", expire_after_lock)
        kwargs = {"request_id": uuid4()}
        if operation == "renew":
            kwargs["lease_seconds"] = 60
        if operation == "defer":
            kwargs["run_after"] = NOW
        with pytest.raises(LeaseLost, match="expired before"):
            getattr(queue_module, operation)(conn, lease, **kwargs)
        assert conn.execute("SELECT state FROM research.jobs WHERE id=%s", [entry]).fetchone() == (
            "running",
        )
        assert conn.execute(
            "SELECT count(*) FROM research.events WHERE request_id=%s", [kwargs["request_id"]]
        ).fetchone() == (0,)
