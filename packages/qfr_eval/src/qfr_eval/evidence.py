"""Owner-grade evidence and the owner's operational reads (PLAN Sections 8.9 and 16.8).

Owner-grade evidence is full precision, labelled owner_only, and goes only to the MCP
front door through eval-admin-api. It is readable as soon as the official record exists;
the owner is not the party being rationed.
"""

from datetime import datetime, timedelta
from typing import Any, Final
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import bindparam, text
from sqlalchemy.engine import Connection

from qfr_eval.configs import EvalError, active_state
from qfr_eval.contracts import (
    EvaluationState,
    GateResult,
    OfficialRecord,
    OwnerEvidence,
    SeriesReference,
)

HYGIENE: Final = "Never copy owner-only evidence into research briefs or steering notes."
TIERS = {
    "Discovered": "pending",
    "Fingerprinting": "pending",
    "Screening": "pending",
    "Held": "held",
    "Deferred": "deferred",
    "IntakeRejected": "rejected",
    "Duplicate": "duplicate",
    "ScreenFailed": "screening_fail",
    "W1GateFailed": "w1_fail",
    "W1Evaluated": "w1_pass",
    "W2Queued": "w1_pass",
    "W2Failed": "w2_fail",
    "W2Expired": "w2_expired",
    "HoldoutCheck": "w2_pass",
    "NotAdvanced": "not_advanced",
    "AwaitingSlot": "advanced",
    "Incubating": "advanced",
    "AcceptanceReview": "advanced",
    "Rejected": "advanced",
    "Accepted": "incubated",
    "Monitoring": "incubated",
    "Retired": "incubated",
}
# The highest pool tier (Section 10.4) a version has reached in each evaluation state:
# the tier a pool entry records when the owner approves it.
POOL_TIERS = {
    "W1Evaluated": "w1_pass",
    "W2Queued": "w1_pass",
    "W2Failed": "w1_pass",
    "W2Expired": "w1_pass",
    "HoldoutCheck": "w2_pass",
    "NotAdvanced": "w2_pass",
    "AwaitingSlot": "advanced",
    "Incubating": "advanced",
    "AcceptanceReview": "advanced",
    "Rejected": "advanced",
    "Accepted": "incubated",
    "Monitoring": "incubated",
    "Retired": "incubated",
}


def _record(row: Any) -> OfficialRecord:
    return OfficialRecord(
        schema_version="official_record/1",
        record_id=row.record_id,
        version_id=row.version_id,
        content_hash=row.content_hash,
        protocol_id=row.protocol_id,
        protocol_version=row.protocol_version,
        data_snapshot_id=row.snapshot_id,
        evaluator_code_version=row.code_version,
        epoch_id=row.epoch_id,
        family_id=row.family_id,
        program_id=row.program_id,
        job_id=row.job_id,
        stage=row.stage,
        window=row.window_name,
        run_ids=list(row.run_ids),
        container_image_digest=row.image_digest,
        seed=row.seed,
        summary=dict(row.summary),
        metrics=dict(row.metrics),
        results_hash=row.results_hash,
        created_at=row.created_at,
        principal=row.principal,
        request_id=row.request_id,
    )


def official_records(conn: Connection, version_id: UUID) -> list[OfficialRecord]:
    rows = conn.execute(
        text(
            "SELECT * FROM eval.official_records WHERE version_id = :v ORDER BY created_at, stage"
        ),
        {"v": version_id},
    ).all()
    return [_record(r) for r in rows]


def owner_evidence(conn: Connection, version_id: UUID) -> OwnerEvidence:
    intake = conn.execute(
        text(
            "SELECT state, reason_code, duplicate_of, discovered_at, decided_at "
            "FROM eval.intake WHERE version_id = :v"
        ),
        {"v": version_id},
    ).first()
    records = official_records(conn, version_id)
    if intake is None and not records:
        raise EvalError(404, "VERSION_UNKNOWN", "the evaluator has not pulled this version")
    gates: list[GateResult] = []
    library: dict[str, JsonValue] | None = None
    reference: dict[str, float | None] = {}
    series: list[SeriesReference] = []
    for record in records:
        if record.stage != "w1":
            continue
        gates += [GateResult.model_validate(g) for g in record.summary.get("gates", [])]  # type: ignore[union-attr]
        summary_library = record.summary.get("library")
        library = dict(summary_library) if isinstance(summary_library, dict) else None
        if library is not None:
            library["max_abs_correlation"] = record.metrics.get("library_max_abs_correlation")
        reference = {
            k.removeprefix("reference_"): v
            for k, v in record.metrics.items()
            if k.startswith("reference_")
        }
        rows = conn.execute(
            text(
                "SELECT run_id, kind, uri, sha256 FROM eval.series_files WHERE run_id IN :runs "
                "AND kind <> 'factor_values' ORDER BY kind"
            ).bindparams(bindparam("runs", expanding=True)),
            {"runs": record.run_ids},
        ).all()
        series += [
            SeriesReference(
                run_id=r.run_id, window=record.window, kind=r.kind, uri=r.uri, sha256=r.sha256
            )
            for r in rows
        ]
    return OwnerEvidence(
        schema_version="owner_evidence/1",
        visibility="owner_only",
        version_id=version_id,
        evaluation=None
        if intake is None
        else EvaluationState(
            state=intake.state,
            reason_code=intake.reason_code,
            duplicate_of=intake.duplicate_of,
            discovered_at=intake.discovered_at,
            decided_at=intake.decided_at,
        ),
        official_records=records,
        gate_values=gates,
        series=series,
        reference_strategy_stats=reference,
        library_correlation=library,
        simulation_state=None,
        hygiene_warning=HYGIENE,
    )


def version_states(conn: Connection, version_ids: list[UUID]) -> list[dict[str, Any]]:
    if not version_ids:
        return []
    rows = conn.execute(
        text(
            "SELECT i.version_id, i.state, i.reason_code, r.status AS released_state, "
            "r.released_at FROM eval.intake i LEFT JOIN LATERAL (SELECT content ->> 'status' "
            "AS status, report_type, released_at FROM eval.released_reports x "
            "WHERE x.version_id = i.version_id AND x.report_type <> 'library' "
            "ORDER BY release_seq DESC LIMIT 1) r ON TRUE WHERE i.version_id IN :ids"
        ).bindparams(bindparam("ids", expanding=True)),
        {"ids": version_ids},
    ).all()
    return [
        {
            "version_id": r.version_id,
            "evidence_tier": TIERS.get(r.state, "pending"),
            "pool_tier": POOL_TIERS.get(r.state),
            "intake_state": r.state,
            "reason_code": r.reason_code,
            "released_state": r.released_state
            if r.released_state is not None or r.released_at is None
            else "EVALUATED",
            "released_at": r.released_at,
        }
        for r in rows
    ]


def _json_row(row: Any, skip: tuple[str, ...] = ()) -> dict[str, JsonValue]:
    out: dict[str, JsonValue] = {}
    for key, value in row._mapping.items():
        if key in skip:
            continue
        if isinstance(value, UUID):
            out[key] = str(value)
        elif hasattr(value, "isoformat"):
            out[key] = value.isoformat()
        else:
            out[key] = value
    return out


def sim_view(conn: Connection, sim_id: UUID) -> dict[str, Any]:
    """A simulation's state, checkpoints, events, NAV and latest positions (owner only)."""
    sim = conn.execute(
        text("SELECT * FROM eval.sim_accounts WHERE sim_id = :s"), {"s": sim_id}
    ).first()
    if sim is None:
        raise EvalError(404, "SIM_NOT_FOUND", "no simulation with this id")
    events = conn.execute(
        text("SELECT * FROM eval.sim_events WHERE sim_id = :s ORDER BY at, event_id"),
        {"s": sim_id},
    ).all()
    nav = conn.execute(
        text("SELECT * FROM eval.sim_nav WHERE sim_id = :s ORDER BY day"), {"s": sim_id}
    ).all()
    positions = conn.execute(
        text(
            "SELECT instrument, shares, price, value, adjustment FROM eval.sim_positions "
            "WHERE sim_id = :s AND day = :d ORDER BY instrument"
        ),
        {"s": sim_id, "d": sim.last_day},
    ).all()
    rankic = [
        r.value
        for r in conn.execute(
            text("SELECT value FROM eval.sim_rankic WHERE sim_id = :s AND value IS NOT NULL"),
            {"s": sim_id},
        ).all()
    ]
    navs = [r.nav for r in nav]
    peak, drawdown = 0.0, 0.0
    for value in navs:
        peak = max(peak, value)
        drawdown = max(drawdown, 1.0 - value / peak if peak > 0 else 0.0)
    sign = int(dict(sim.settings).get("sign", 1))
    metrics: dict[str, float | None] = {
        "final_nav": navs[-1] if navs else None,
        "cumulative_return": navs[-1] / sim.capital - 1.0 if navs else None,
        "max_drawdown": drawdown if navs else None,
        "rankic_mean": sign * sum(rankic) / len(rankic) if rankic else None,
        "rankic_days": float(len(rankic)),
        "complete_share": sum(1 for r in nav if r.complete) / len(nav) if nav else None,
    }
    return {
        "visibility": "owner_only",
        "sim_id": sim.sim_id,
        "version_id": sim.version_id,
        "kind": sim.kind,
        "purpose": sim.purpose,
        "mode": sim.mode,
        "status": sim.status,
        "not_before": sim.not_before,
        "start_date": sim.start_date,
        "last_day": sim.last_day,
        "days_done": sim.days_done,
        "required_days": sim.required_days,
        "capital": sim.capital,
        "cash": sim.cash,
        "error_code": sim.error_code,
        "settings": dict(sim.settings),
        "metrics": metrics,
        "checkpoints": [
            _json_row(e, ("sim_id", "request_id")) for e in events if e.kind == "CHECKPOINT"
        ],
        "events": [_json_row(e, ("sim_id", "request_id")) for e in events],
        "nav": [_json_row(r, ("sim_id", "snapshot_id")) for r in nav],
        "positions": [_json_row(p) for p in positions],
    }


def private_config(conn: Connection) -> dict[str, JsonValue]:
    """Window dates, holdout and acceptance gates: owner_only (qfr.config.get)."""
    state = active_state(conn)
    if state is None:
        raise EvalError(409, "NOT_READY", "no active protocol, policy, quotas and epoch")
    protocol = state.protocol.config
    return {
        "visibility": "owner_only",
        "epoch": {
            "epoch_id": state.epoch.epoch_id,
            "windows": {
                name: {"start": w.start.isoformat(), "end": w.end.isoformat()}
                for name, w in state.epoch.windows.items()
            },
            "snapshot_id": state.epoch.snapshot_id,
            "embargo_check": state.epoch.embargo_check,
        },
        "private_gates": {
            k: v for k, v in protocol["gates"].items() if k.startswith(("holdout", "acceptance"))
        },
        "simulation": protocol["simulation"],
        "monitoring": protocol["monitoring"],
        "screening": protocol["screening"],
        "dedup": protocol["dedup"],
        "active": {
            "protocol": state.protocol.ref,
            "policy": state.policy.ref,
            "quotas": state.quotas.ref,
        },
        "burn_thresholds": state.quotas.config["burn"],
    }


def quota_summary(conn: Connection, state: Any, now: datetime) -> dict[str, JsonValue] | None:
    """Quota use over the last 24 hours against the active quota limits (Section 9.3):
    totals per scope and window, and the busiest family and program."""
    if state is None:
        return None
    rows = conn.execute(
        text(
            "SELECT scope, window_name, key, count(*) AS n FROM eval.quota_usage "
            "WHERE used_at > :since GROUP BY scope, window_name, key"
        ),
        {"since": now - timedelta(hours=24)},
    ).all()
    counts: dict[str, int] = {}
    peaks: dict[str, int] = {}
    for r in rows:
        name = f"{r.scope}:{r.window_name}"
        counts[name] = counts.get(name, 0) + int(r.n)
        peaks[name] = max(peaks.get(name, 0), int(r.n))
    totals: dict[str, JsonValue] = dict(counts)
    busiest: dict[str, JsonValue] = dict(peaks)
    # Incubation accounts that hold a slot, as the scheduler counts them.
    live_sims: int = conn.execute(
        text(
            "SELECT count(*) FROM eval.sim_accounts WHERE purpose = 'incubation' "
            "AND status IN ('waiting', 'running', 'paused')"
        )
    ).scalar_one()
    limits = state.quotas.config
    return {
        "ref": state.quotas.ref,
        "limits": {k: limits[k] for k in ("family", "program", "global") if k in limits},
        "used_24h": totals,
        "busiest_key_24h": busiest,
        "simulation_slots": {
            "live": int(live_sims),
            "limit": (limits.get("global") or {}).get("simulation_slots"),
        },
    }


def summary(conn: Connection, now: datetime | None = None) -> dict[str, JsonValue]:
    """Counts the front door shows in qfr.status (no per-version detail)."""
    state = active_state(conn)
    intake = {
        r.state: int(r.n)
        for r in conn.execute(
            text("SELECT state, count(*) AS n FROM eval.intake GROUP BY state")
        ).all()
    }
    queue = {
        f"{r.kind}:{r.state}": int(r.n)
        for r in conn.execute(
            text("SELECT kind, state, count(*) AS n FROM eval.queue_jobs GROUP BY kind, state")
        ).all()
    }
    burn = [
        {
            "epoch_id": r.epoch_id,
            "window": r.window_name,
            "trials": r.trials,
            "released_values": r.released_values,
            "queries_used": r.queries_used,
            "budget": r.budget,
            "status": r.status,
        }
        for r in conn.execute(
            text("SELECT * FROM eval.burn_meters ORDER BY epoch_id, window_name")
        ).all()
    ]
    latest = conn.execute(
        text(
            "SELECT snapshot_id, last_date, created_at FROM eval.data_snapshots "
            "WHERE zone = 'full' ORDER BY created_at DESC LIMIT 1"
        )
    ).first()
    pending_release: int = conn.execute(
        text("SELECT count(*) FROM eval.release_queue WHERE state = 'queued'")
    ).scalar_one()
    released: int = conn.execute(text("SELECT count(*) FROM eval.released_reports")).scalar_one()
    open_alerts: int = conn.execute(
        text("SELECT count(*) FROM eval.alerts WHERE state = 'open'")
    ).scalar_one()
    sims = {
        f"{r.purpose}:{r.status}": int(r.n)
        for r in conn.execute(
            text(
                "SELECT purpose, status, count(*) AS n FROM eval.sim_accounts "
                "GROUP BY purpose, status"
            )
        ).all()
    }
    cases = {
        r.state: int(r.n)
        for r in conn.execute(
            text("SELECT state, count(*) AS n FROM eval.acceptance_cases GROUP BY state")
        ).all()
    }
    return {
        "ready": state is not None,
        "active": None
        if state is None
        else {
            "protocol": state.protocol.ref,
            "policy": state.policy.ref,
            "quotas": state.quotas.ref,
            "epoch": state.epoch.epoch_id,
            "epoch_snapshot_id": state.epoch.snapshot_id,
        },
        "intake": intake,  # type: ignore[dict-item]
        "queue": queue,  # type: ignore[dict-item]
        "burn_meters": burn,  # type: ignore[dict-item]
        "release": {"queued": int(pending_release), "released": int(released)},
        "open_alerts": int(open_alerts),
        "quotas": None if now is None else quota_summary(conn, state, now),
        "simulations": sims,  # type: ignore[dict-item]
        "acceptance_cases": cases,  # type: ignore[dict-item]
        "data_freshness": None
        if latest is None
        else {
            "latest_full_snapshot_id": latest.snapshot_id,
            "last_date": latest.last_date.isoformat(),
            "registered_at": latest.created_at.isoformat(),
        },
    }
