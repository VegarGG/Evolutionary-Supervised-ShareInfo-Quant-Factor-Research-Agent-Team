"""Alerts (PLAN Sections 9.4, 10.2 and 10.4): decay, staleness, burn and operations.

An alert is raised once per condition (its dedup key) and stays in eval_db; the owner
reads it through qfr.ops.alerts and qfr.status. Nothing deletes or edits an alert; the
table's trigger allows only acknowledgement, which arrives with Phase 7's operations
tools.
"""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import JsonValue
from qfr_core.config import canonical_json
from qfr_core.ids import uuid7
from qfr_core.logging import JsonLogger
from sqlalchemy import text
from sqlalchemy.engine import Connection

from qfr_eval.configs import record_event

AlertKind = Literal["decay", "staleness", "burn", "ops"]


def raise_alert(
    conn: Connection,
    kind: AlertKind,
    dedup_key: str,
    details: dict[str, JsonValue],
    at: datetime,
    principal: str,
    request_id: str,
    *,
    version_id: UUID | None = None,
    sim_id: UUID | None = None,
    logger: JsonLogger | None = None,
) -> UUID | None:
    """Insert the alert unless one with the same key exists; returns its id when new."""
    alert_id = uuid7()
    inserted = conn.execute(
        text(
            "INSERT INTO eval.alerts (alert_id, kind, dedup_key, version_id, sim_id, at, "
            "details, state, request_id) VALUES (:id, :k, :key, :v, :s, :at, "
            "CAST(:d AS jsonb), 'open', :r) ON CONFLICT (dedup_key) DO NOTHING RETURNING 1"
        ),
        {
            "id": alert_id,
            "k": kind,
            "key": dedup_key,
            "v": version_id,
            "s": sim_id,
            "at": at,
            "d": canonical_json(details),
            "r": request_id,
        },
    ).first()
    if inserted is None:
        return None
    record_event(
        conn, at, principal, "alert_raised", "alert", str(alert_id), request_id,
        {"kind": kind, "dedup_key": dedup_key,
         "version_id": None if version_id is None else str(version_id)},
    )  # fmt: skip
    if logger is not None:
        logger.logger.warning(
            "alert_raised",
            outcome="ok",
            payload={"kind": kind, "alert_id": str(alert_id), "details": details},
        )
    return alert_id


def alert_view(row: Any) -> dict[str, Any]:
    return {
        "alert_id": row.alert_id,
        "kind": row.kind,
        "version_id": row.version_id,
        "sim_id": row.sim_id,
        "at": row.at,
        "details": dict(row.details),
        "state": row.state,
        "acknowledged_by": row.acknowledged_by,
        "acknowledged_at": row.acknowledged_at,
    }


def list_alerts(
    conn: Connection, state: str | None = None, kind: str | None = None, limit: int = 200
) -> dict[str, Any]:
    rows = conn.execute(
        text(
            "SELECT * FROM eval.alerts WHERE (CAST(:s AS text) IS NULL OR state = :s) "
            "AND (CAST(:k AS text) IS NULL OR kind = :k) ORDER BY at DESC, alert_id DESC "
            "LIMIT :n"
        ),
        {"s": state, "k": kind, "n": limit},
    ).all()
    open_count: int = conn.execute(
        text("SELECT count(*) FROM eval.alerts WHERE state = 'open'")
    ).scalar_one()
    return {"items": [alert_view(r) for r in rows], "open": int(open_count)}
