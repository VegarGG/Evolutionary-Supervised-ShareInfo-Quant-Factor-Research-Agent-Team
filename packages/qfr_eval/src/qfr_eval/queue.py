"""The evaluation job queue in eval_db (PLAN Section 16.3): FOR UPDATE SKIP LOCKED.

Priority is fair round-robin across families and first-in first-out within a family
(Section 8.3): a job's priority is its family's count of jobs still waiting, then the
global enqueue order. Nothing outside the evaluator can set or change a priority.
Fingerprint jobs (which gate behavioral dedup) are claimed first, then W2 and holdout
jobs (each is one rationed query), then W1 evaluation jobs.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from qfr_core.config import canonical_json
from qfr_core.ids import uuid7
from sqlalchemy import text
from sqlalchemy.engine import Connection

QUEUE = "eval"
JobKind = Literal["fingerprint", "evaluate", "w2", "holdout"]
ROUND = 10**12  # Priority = family round x ROUND + enqueue sequence.


@dataclass(frozen=True)
class Job:
    queue_job_id: UUID
    kind: JobKind
    version_id: UUID
    payload: dict[str, Any]
    attempts: int


def enqueue(
    conn: Connection,
    kind: JobKind,
    version_id: UUID,
    family_id: UUID,
    payload: dict[str, Any],
    at: datetime,
) -> UUID | None:
    """Idempotent per (kind, version). Returns the job id, or None if it already existed."""
    waiting: int = conn.execute(
        text(
            "SELECT count(*) FROM eval.queue_jobs WHERE queue = :q AND kind = :k "
            "AND state = 'queued' AND payload ->> 'family_id' = :f"
        ),
        {"q": QUEUE, "k": kind, "f": str(family_id)},
    ).scalar_one()
    job_id = uuid7()
    inserted = conn.execute(
        text(
            "INSERT INTO eval.queue_jobs (queue_job_id, queue, kind, version_id, payload, "
            "priority, state, run_after, created_at) VALUES (:id, :q, :k, :v, "
            "CAST(:p AS jsonb), :round * :size + nextval('eval.queue_priority_seq'), "
            "'queued', :at, :at) ON CONFLICT (kind, version_id) DO NOTHING RETURNING 1"
        ),
        {
            "id": job_id,
            "q": QUEUE,
            "k": kind,
            "v": version_id,
            "p": canonical_json(payload | {"family_id": str(family_id)}),
            "round": int(waiting),
            "size": ROUND,
            "at": at,
        },
    ).first()
    return job_id if inserted is not None else None


def claim(conn: Connection, worker: str, at: datetime) -> Job | None:
    row = conn.execute(
        text(
            "UPDATE eval.queue_jobs SET state = 'running', attempts = attempts + 1, "
            "locked_by = :w, locked_at = :at WHERE queue_job_id = ("
            "  SELECT queue_job_id FROM eval.queue_jobs WHERE queue = :q AND state = 'queued' "
            "  AND run_after <= :at ORDER BY (CASE kind WHEN 'fingerprint' THEN 0 "
            "  WHEN 'evaluate' THEN 2 ELSE 1 END), priority "
            "  FOR UPDATE SKIP LOCKED LIMIT 1) "
            "RETURNING queue_job_id, kind, version_id, payload, attempts"
        ),
        {"w": worker, "at": at, "q": QUEUE},
    ).first()
    if row is None:
        return None
    return Job(row.queue_job_id, row.kind, row.version_id, dict(row.payload), row.attempts)


def finish(conn: Connection, job: Job, at: datetime, state: Literal["done", "failed"]) -> None:
    conn.execute(
        text(
            "UPDATE eval.queue_jobs SET state = :s, finished_at = :at, locked_by = NULL "
            "WHERE queue_job_id = :id"
        ),
        {"s": state, "at": at, "id": job.queue_job_id},
    )


def retry(conn: Connection, job: Job, at: datetime, delay_seconds: int, error: str) -> None:
    conn.execute(
        text(
            "UPDATE eval.queue_jobs SET state = 'queued', run_after = :after, locked_by = NULL, "
            "locked_at = NULL, last_error = :e WHERE queue_job_id = :id"
        ),
        {"after": at + timedelta(seconds=delay_seconds), "e": error[:500], "id": job.queue_job_id},
    )


def requeue_stale(conn: Connection, at: datetime, lease_seconds: int) -> int:
    """Return running jobs whose worker vanished to the queue (attempts already counted)."""
    result = conn.execute(
        text(
            "UPDATE eval.queue_jobs SET state = 'queued', locked_by = NULL, locked_at = NULL, "
            "last_error = 'lease expired' WHERE state = 'running' AND locked_at < :cutoff"
        ),
        {"cutoff": at - timedelta(seconds=lease_seconds)},
    )
    return int(result.rowcount or 0)


def depth(conn: Connection) -> dict[str, int]:
    rows = conn.execute(
        text("SELECT kind || ':' || state AS k, count(*) AS n FROM eval.queue_jobs GROUP BY 1")
    ).all()
    return {str(r.k): int(r.n) for r in rows}
