"""Queueing reports for release (PLAN Section 9.2): the decision is recorded at once and
released by the release engine at the report type's batch time.
"""

import math
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from qfr_core.config import canonical_json
from qfr_core.ids import uuid7
from sqlalchemy import text
from sqlalchemy.engine import Connection

ReportType = Literal["intake", "screening", "w1", "library"]


def next_w1_batch(at: datetime, hours: float) -> datetime:
    """The next batch boundary strictly after `at`; boundaries are every `hours` from
    00:00 UTC (00:00, 06:00, 12:00 and 18:00 for the default policy)."""
    period = hours * 3600.0
    day = datetime(at.year, at.month, at.day, tzinfo=UTC)
    elapsed = (at.astimezone(UTC) - day).total_seconds()
    return day + timedelta(seconds=(math.floor(elapsed / period) + 1) * period)


def queue_report(
    conn: Connection,
    report_type: ReportType,
    version_id: UUID,
    payload: dict[str, Any],
    due_at: datetime,
    at: datetime,
    request_id: str,
    record_id: UUID | None = None,
) -> UUID:
    queue_id = uuid7()
    conn.execute(
        text(
            "INSERT INTO eval.release_queue (queue_id, report_type, version_id, record_id, "
            "payload, due_at, state, created_at, request_id) VALUES (:id, :t, :v, :rec, "
            "CAST(:p AS jsonb), :due, 'queued', :at, :r)"
        ),
        {
            "id": queue_id,
            "t": report_type,
            "v": version_id,
            "rec": record_id,
            "p": canonical_json(payload),
            "due": due_at,
            "at": at,
            "r": request_id,
        },
    )
    return queue_id
