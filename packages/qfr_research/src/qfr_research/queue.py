"""The research job queue in research_db (P4.1, PLAN Section 16.2): FOR UPDATE SKIP LOCKED.

One kind today: "generation" runs one generation to a terminal state. A worker that
dies leaves its job running; after the lease the job returns to the queue and the
generation resumes from its last persisted state.
"""

from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Literal
from uuid import UUID

from qfr_core.ids import uuid7
from sqlalchemy import text
from sqlalchemy.engine import Connection

from qfr_research.db import Clock, dumps

QUEUE = "research"


@dataclass(frozen=True)
class QueueJob:
    queue_job_id: UUID
    kind: str
    payload: dict[str, Any]
    attempts: int


def enqueue(
    conn: Connection, clock: Clock, kind: str, dedup_key: str, payload: dict[str, Any]
) -> UUID | None:
    """Idempotent by dedup key; returns the new job id or None if it existed."""
    job_id = uuid7()
    inserted = conn.execute(
        text(
            "INSERT INTO queue_jobs (queue_job_id, queue, kind, dedup_key, payload, state, "
            "run_after, created_at) VALUES (:id, :q, :k, :d, CAST(:p AS jsonb), 'queued', :at, "
            ":at) ON CONFLICT (dedup_key) DO NOTHING RETURNING 1"
        ),
        {
            "id": job_id,
            "q": QUEUE,
            "k": kind,
            "d": dedup_key,
            "p": dumps(payload),
            "at": clock.now(),
        },
    ).first()
    return job_id if inserted is not None else None


def claim(conn: Connection, clock: Clock, worker: str) -> QueueJob | None:
    row = conn.execute(
        text(
            "UPDATE queue_jobs SET state = 'running', attempts = attempts + 1, locked_by = :w, "
            "locked_at = :at WHERE queue_job_id = (SELECT queue_job_id FROM queue_jobs WHERE "
            "queue = :q AND state = 'queued' AND run_after <= :at ORDER BY run_after, "
            "created_at FOR UPDATE SKIP LOCKED LIMIT 1) "
            "RETURNING queue_job_id, kind, payload, attempts"
        ),
        {"w": worker, "at": clock.now(), "q": QUEUE},
    ).first()
    if row is None:
        return None
    return QueueJob(row.queue_job_id, row.kind, dict(row.payload), int(row.attempts))


def finish(
    conn: Connection, clock: Clock, job: QueueJob, state: Literal["done", "failed"], error: str = ""
) -> None:
    conn.execute(
        text(
            "UPDATE queue_jobs SET state = :s, finished_at = :at, locked_by = NULL, "
            "last_error = nullif(:e, '') WHERE queue_job_id = :id"
        ),
        {"s": state, "at": clock.now(), "e": error[:500], "id": job.queue_job_id},
    )


def retry(conn: Connection, clock: Clock, job: QueueJob, delay_seconds: int, error: str) -> None:
    conn.execute(
        text(
            "UPDATE queue_jobs SET state = 'queued', run_after = :after, locked_by = NULL, "
            "locked_at = NULL, last_error = :e WHERE queue_job_id = :id"
        ),
        {
            "after": clock.now() + timedelta(seconds=delay_seconds),
            "e": error[:500],
            "id": job.queue_job_id,
        },
    )


def requeue_stale(conn: Connection, clock: Clock, lease_seconds: int) -> int:
    result = conn.execute(
        text(
            "UPDATE queue_jobs SET state = 'queued', locked_by = NULL, locked_at = NULL, "
            "last_error = 'lease expired' WHERE state = 'running' AND locked_at < :cutoff"
        ),
        {"cutoff": clock.now() - timedelta(seconds=lease_seconds)},
    )
    return int(result.rowcount or 0)


def depth(conn: Connection) -> dict[str, int]:
    rows = conn.execute(
        text("SELECT kind || ':' || state AS k, count(*) AS n FROM queue_jobs GROUP BY 1")
    ).all()
    return {str(r.k): int(r.n) for r in rows}
