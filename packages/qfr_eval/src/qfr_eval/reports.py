"""Queueing reports for release (PLAN Section 9.2): the deciding service queues each
report with its decision, and the release engine releases it as soon as it can, which is
on its next tick. Nothing is held back for a later time.
"""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from qfr_core.config import canonical_json
from qfr_core.ids import uuid7
from sqlalchemy import text
from sqlalchemy.engine import Connection

ReportType = Literal["intake", "screening", "w1", "w2", "advancement", "sim", "decision", "library"]


def queue_report(
    conn: Connection,
    report_type: ReportType,
    version_id: UUID,
    payload: dict[str, Any],
    at: datetime,
    request_id: str,
    record_id: UUID | None = None,
) -> UUID:
    """Queue a report in the deciding transaction; it is due at once (due_at = at)."""
    queue_id = uuid7()
    conn.execute(
        text(
            "INSERT INTO eval.release_queue (queue_id, report_type, version_id, record_id, "
            "payload, due_at, state, created_at, request_id) VALUES (:id, :t, :v, :rec, "
            "CAST(:p AS jsonb), :at, 'queued', :at, :r)"
        ),
        {
            "id": queue_id,
            "t": report_type,
            "v": version_id,
            "rec": record_id,
            "p": canonical_json(payload),
            "at": at,
            "r": request_id,
        },
    )
    return queue_id
