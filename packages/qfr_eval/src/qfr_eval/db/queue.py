"""Private durable queue. Leases use DB time; deterministic measurement does not."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from psycopg import Connection
from psycopg.types.json import Jsonb


def enqueue(
    connection: Connection,
    payload: dict[str, Any],
    *,
    principal: str,
    request_id: UUID,
    run_after: datetime,
    queue: str = "evaluation",
    job_id: UUID | None = None,
) -> UUID:
    identity = job_id or uuid4()
    connection.execute(
        "INSERT INTO eval.jobs(id,payload,created_by,request_id,queue,run_after) "
        "VALUES(%s,%s,%s,%s,%s,%s)",
        (identity, Jsonb(payload), principal, request_id, queue, run_after),
    )
    return identity


def claim(
    connection: Connection,
    *,
    worker: str,
    request_id: UUID,
    lease_seconds: int,
    queue: str = "evaluation",
) -> dict[str, Any] | None:
    if lease_seconds <= 0:
        raise ValueError("positive lease required")
    row = connection.execute(
        "WITH ready AS (SELECT id FROM eval.jobs WHERE queue=%s AND "
        "((state='queued' AND run_after<=clock_timestamp()) OR "
        "(state='running' AND lease_until<=clock_timestamp())) "
        "ORDER BY run_after,created_at,id FOR UPDATE SKIP LOCKED LIMIT 1) "
        "UPDATE eval.jobs j SET state='running',locked_by=%s,"
        "lease_until=clock_timestamp()+make_interval(secs=>%s),"
        "attempts=attempts+1,fence=fence+1,created_by=%s,request_id=%s "
        "FROM ready WHERE j.id=ready.id RETURNING j.id,j.payload,j.fence,j.attempts",
        (queue, worker, lease_seconds, worker, request_id),
    ).fetchone()
    return dict(zip(("id", "payload", "fence", "attempts"), row, strict=True)) if row else None


def finish(
    connection: Connection,
    job_id: UUID,
    *,
    worker: str,
    fence: int,
    request_id: UUID,
    failed: bool = False,
) -> None:
    row = connection.execute(
        "UPDATE eval.jobs SET state=%s,locked_by=NULL,lease_until=NULL,"
        "created_by=%s,request_id=%s WHERE id=%s AND state='running' "
        "AND locked_by=%s AND fence=%s AND lease_until>clock_timestamp() RETURNING id",
        ("failed" if failed else "complete", worker, request_id, job_id, worker, fence),
    ).fetchone()
    if row is None:
        raise ValueError("stale or expired queue lease")
