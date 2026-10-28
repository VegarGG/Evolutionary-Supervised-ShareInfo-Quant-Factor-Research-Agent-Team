"""Durable research tasks, with DB-clock leases and transactional audit.

This queue controls research work only. It cannot schedule evaluation, and
finishing a task never changes a research job's delivery status.
"""

from datetime import datetime
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

from psycopg import Connection
from psycopg.types.json import Jsonb
from pydantic import JsonValue
from qfr_core.contracts.blackboard import ResearchQueueLease
from qfr_core.data_layer.snapshots import canonical_json

from qfr_research.db import attributed


class QueueConflict(ValueError):
    """An enqueue key was already bound to a different immutable request."""


class LeaseLost(ValueError):
    """A worker no longer has a live, current lease for this task."""


def enqueue(
    connection: Connection,
    payload: dict[str, JsonValue],
    *,
    program_id: UUID,
    research_job_id: UUID,
    queue: str,
    enqueue_key: str,
    principal: str,
    request_id: UUID,
    run_after: datetime,
) -> UUID:
    if not queue.strip() or not enqueue_key.strip() or run_after.utcoffset() is None:
        raise ValueError("nonblank queue/key and aware run_after required")
    # Timing belongs to the immutable request too: a retry cannot silently move
    # the task's eligibility time. Canonical JSON also rejects NaN and Infinity.
    digest = sha256(
        canonical_json(
            {"payload": payload, "job": str(research_job_id), "run_after": run_after.isoformat()}
        )
    ).hexdigest()
    identity = uuid4()
    with attributed(connection, principal, request_id):
        inserted = connection.execute(
            "INSERT INTO research.jobs(id,payload,created_by,request_id,program_id,"
            "research_job_id,queue,enqueue_key,payload_hash,run_after) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT(program_id,queue,enqueue_key) DO NOTHING RETURNING id",
            [
                identity,
                Jsonb(payload),
                principal,
                request_id,
                program_id,
                research_job_id,
                queue,
                enqueue_key,
                digest,
                run_after,
            ],
        ).fetchone()
        if inserted:
            return UUID(str(inserted[0]))
        existing = connection.execute(
            "SELECT id,payload_hash FROM research.jobs "
            "WHERE program_id=%s AND queue=%s AND enqueue_key=%s",
            [program_id, queue, enqueue_key],
        ).fetchone()
        if existing is None or existing[1] != digest:
            raise QueueConflict("enqueue key already bound to a different request")
        return UUID(str(existing[0]))


def _lease(row: tuple[Any, ...]) -> ResearchQueueLease:
    return ResearchQueueLease(
        schema_version="1",
        queue_entry_id=str(row[0]),
        program_id=str(row[1]),
        research_job_id=str(row[2]),
        queue=row[3],
        worker=row[4],
        fence=row[5],
        attempt=row[6],
        lease_until=row[7],
        payload=row[8],
    )


def claim(
    connection: Connection, *, worker: str, request_id: UUID, lease_seconds: int, queue: str
) -> ResearchQueueLease | None:
    if not worker.strip() or not queue.strip() or lease_seconds <= 0:
        raise ValueError("nonblank worker/queue and positive lease required")
    with attributed(connection, worker, request_id):
        # Lock the admitted parent with the task so pause/cancel cannot race a
        # claim. Shared program locks allow independent jobs to claim in parallel.
        # SKIP LOCKED means a busy/paused job never blocks the whole queue.
        row = connection.execute(
            "WITH ready AS (SELECT q.id FROM research.jobs q "
            "JOIN research.research_jobs r ON (r.id,r.program_id)=(q.research_job_id,q.program_id) "
            "JOIN research.programs p ON p.id=q.program_id "
            "WHERE q.queue=%s AND p.status='active' AND r.state IN ('ready','running') "
            "AND ((q.state='queued' AND q.run_after<=clock_timestamp()) OR "
            "(q.state='running' AND q.lease_until<=clock_timestamp())) "
            "ORDER BY q.run_after,q.created_at,q.id LIMIT 1 "
            "FOR UPDATE OF q,r SKIP LOCKED FOR SHARE OF p SKIP LOCKED) "
            "UPDATE research.jobs q SET state='running',locked_by=%s,"
            "lease_until=clock_timestamp()+make_interval(secs=>%s),"
            "attempts=attempts+1,fence=fence+1 FROM ready WHERE q.id=ready.id "
            "RETURNING q.id,q.program_id,q.research_job_id,q.queue,q.locked_by,"
            "q.fence,q.attempts,q.lease_until,q.payload",
            [queue, worker, lease_seconds],
        ).fetchone()
        return _lease(row) if row else None


def _locked_current(connection: Connection, lease: ResearchQueueLease) -> None:
    row = connection.execute(
        "SELECT q.id FROM research.jobs q JOIN research.research_jobs r "
        "ON (r.id,r.program_id)=(q.research_job_id,q.program_id) "
        "WHERE q.id=%s AND q.program_id=%s AND q.research_job_id=%s "
        "AND q.queue=%s AND q.state='running' AND q.locked_by=%s AND q.fence=%s "
        "AND q.lease_until>clock_timestamp() AND r.state NOT IN ('cancelled','failed','completed') "
        "FOR UPDATE OF q,r SKIP LOCKED",
        [
            UUID(lease.queue_entry_id),
            UUID(lease.program_id),
            UUID(lease.research_job_id),
            lease.queue,
            lease.worker,
            lease.fence,
        ],
    ).fetchone()
    if row is None:
        raise LeaseLost("queue lease is stale, expired, cancelled or concurrently controlled")


def renew(
    connection: Connection, lease: ResearchQueueLease, *, request_id: UUID, lease_seconds: int
) -> ResearchQueueLease:
    if lease_seconds <= 0:
        raise ValueError("positive lease required")
    with attributed(connection, lease.worker, request_id):
        _locked_current(connection, lease)
        row = connection.execute(
            "UPDATE research.jobs SET lease_until=clock_timestamp()+make_interval(secs=>%s) "
            "WHERE id=%s AND lease_until>clock_timestamp() "
            "RETURNING id,program_id,research_job_id,queue,locked_by,"
            "fence,attempts,lease_until,payload",
            [lease_seconds, UUID(lease.queue_entry_id)],
        ).fetchone()
        if row is None:
            raise LeaseLost("queue lease expired before renewal")
        return _lease(row)


def finish(
    connection: Connection, lease: ResearchQueueLease, *, request_id: UUID, failed: bool = False
) -> None:
    with attributed(connection, lease.worker, request_id):
        _locked_current(connection, lease)
        row = connection.execute(
            "UPDATE research.jobs SET state=%s,locked_by=NULL,lease_until=NULL "
            "WHERE id=%s AND lease_until>clock_timestamp() RETURNING id",
            ["failed" if failed else "complete", UUID(lease.queue_entry_id)],
        ).fetchone()
        if row is None:
            raise LeaseLost("queue lease expired before completion")


def defer(
    connection: Connection, lease: ResearchQueueLease, *, request_id: UUID, run_after: datetime
) -> None:
    """Release one task for a declared data/input wait; never report success."""
    if run_after.utcoffset() is None:
        raise ValueError("aware run_after required")
    with attributed(connection, lease.worker, request_id):
        _locked_current(connection, lease)
        row = connection.execute(
            "UPDATE research.jobs SET state='queued',locked_by=NULL,lease_until=NULL,"
            "run_after=%s WHERE id=%s AND lease_until>clock_timestamp() RETURNING id",
            [run_after, UUID(lease.queue_entry_id)],
        ).fetchone()
        if row is None:
            raise LeaseLost("queue lease expired before deferral")
