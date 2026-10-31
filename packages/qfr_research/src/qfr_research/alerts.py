"""Provider alerts (PLAN Sections 11.8 and 17.4).

Fallback chains keep research running when a model fails; repeated fallbacks away from
one model, or a probe that finds a role without its primary model, raise an alert the
owner reads in qfr.ops.alerts. An alert is raised once per dedup key (one per model per
UTC day for fallbacks, one per day and set of failed models for probes) and is only
ever acknowledged, never edited or removed.
"""

import hashlib
from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from pydantic import JsonValue
from qfr_core.config import canonical_json
from qfr_core.ids import uuid7
from qfr_core.logging import JsonLogger
from sqlalchemy import text
from sqlalchemy.engine import Connection

ProviderAlertKind = Literal["provider_fallback", "probe_failed"]
COLUMNS = "alert_id, kind, at, details, state, acknowledged_by, acknowledged_at, note"


class AlertNotFound(LookupError):
    pass


def raise_alert(
    conn: Connection,
    kind: ProviderAlertKind,
    dedup_key: str,
    details: dict[str, JsonValue],
    at: datetime,
    request_id: str,
    logger: JsonLogger | None = None,
) -> UUID | None:
    """Insert the alert unless one with the same key exists; returns its id when new."""
    alert_id = uuid7()
    inserted = conn.execute(
        text(
            "INSERT INTO provider_alerts (alert_id, kind, dedup_key, at, details, state, "
            "request_id) VALUES (:id, :k, :key, :at, CAST(:d AS jsonb), 'open', :r) "
            "ON CONFLICT (dedup_key) DO NOTHING RETURNING 1"
        ),
        {"id": alert_id, "k": kind, "key": dedup_key, "at": at,
         "d": canonical_json(details), "r": request_id},
    ).first()  # fmt: skip
    if inserted is None:
        return None
    if logger is not None:
        logger.logger.warning(
            "alert_raised",
            outcome="ok",
            payload={"kind": kind, "alert_id": str(alert_id), "dedup_key": dedup_key},
        )
    return alert_id


def after_fallback(
    conn: Connection,
    model: str,
    at: datetime,
    threshold: int,
    window: timedelta,
    request_id: str,
    logger: JsonLogger | None = None,
) -> UUID | None:
    """Raise the day's alert for a model once its fallbacks in the window reach the
    threshold. Counts the PROVIDER_FALLBACK trace steps away from that model."""
    count: int = conn.execute(
        text(
            "SELECT count(*) FROM trace_steps WHERE step_type = 'PROVIDER_FALLBACK' "
            "AND inputs->>'from' = :m AND at > :since AND at <= :at"
        ),
        {"m": model, "since": at - window, "at": at},
    ).scalar_one()
    if count < threshold:
        return None
    details: dict[str, JsonValue] = {
        "model": model,
        "fallbacks": int(count),
        "window_minutes": int(window.total_seconds() // 60),
        "next": "Check the provider's status; the owner may reorder the chain in roles.yaml "
        "and restart research-worker.",
    }
    key = f"provider_fallback:{model}:{at.date().isoformat()}"
    return raise_alert(conn, "provider_fallback", key, details, at, request_id, logger)


def after_probe(
    conn: Connection,
    probe_id: UUID,
    trigger: str,
    failed_models: list[str],
    failed_roles: list[str],
    at: datetime,
    logger: JsonLogger | None = None,
) -> UUID | None:
    """A probe with a role whose primary model failed raises the day's alert for that set
    of failed models."""
    names: list[JsonValue] = [name for name in sorted(failed_models)]
    digest = hashlib.sha256(canonical_json(names).encode()).hexdigest()[:16]
    details: dict[str, JsonValue] = {
        "probe_id": str(probe_id),
        "trigger": trigger,
        "failed_models": list(failed_models),
        "failed_roles": list(failed_roles),
        "next": "Run qfr llm probe again after checking the model ids and keys; fallback "
        "chains keep research running meanwhile.",
    }
    key = f"probe_failed:{at.date().isoformat()}:{digest}"
    return raise_alert(conn, "probe_failed", key, details, at, str(probe_id), logger)


def list_alerts(
    conn: Connection, state: str | None, kind: str | None, limit: int
) -> dict[str, Any]:
    rows = conn.execute(
        text(
            f"SELECT {COLUMNS} FROM provider_alerts WHERE (CAST(:s AS text) IS NULL OR "
            "state = :s) AND (CAST(:k AS text) IS NULL OR kind = :k) "
            "ORDER BY at DESC, alert_id DESC LIMIT :n"
        ),
        {"s": state, "k": kind, "n": limit},
    ).mappings()
    items = [dict(r) for r in rows]
    open_count: int = conn.execute(
        text("SELECT count(*) FROM provider_alerts WHERE state = 'open'")
    ).scalar_one()
    return {"items": items, "open": int(open_count)}


def acknowledge(
    conn: Connection, alert_id: UUID, by: str, note: str | None, at: datetime
) -> dict[str, Any]:
    """Acknowledge an open alert; acknowledging it again returns it unchanged."""
    conn.execute(
        text(
            "UPDATE provider_alerts SET state = 'acknowledged', acknowledged_by = :by, "
            "acknowledged_at = :at, note = :note WHERE alert_id = :id AND state = 'open'"
        ),
        {"by": by, "at": at, "note": note, "id": alert_id},
    )
    row = (
        conn.execute(
            text(f"SELECT {COLUMNS} FROM provider_alerts WHERE alert_id = :id"), {"id": alert_id}
        )
        .mappings()
        .first()
    )
    if row is None:
        raise AlertNotFound(str(alert_id))
    return dict(row)
