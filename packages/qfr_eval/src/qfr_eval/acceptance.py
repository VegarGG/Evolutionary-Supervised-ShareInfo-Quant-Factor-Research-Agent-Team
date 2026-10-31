"""Acceptance cases and gates (PLAN Section 10.3, ACC-01 to ACC-03).

When a version's incubation ends, the simulation engine opens one acceptance case with
every automated gate computed from the evaluator's own records: the W1, W2 and holdout
gates, the deflated Sharpe ratio with N_eff from the trial ledger, PBO on the version's
cohort, the Harvey-Liu-Zhu hurdle over W1 to W3, the forward incubation gate, novelty
against the library on W3, and operations. The recommendation is ACCEPT only when
every gate passes. The owner decides through MCP with an approval record; in v1 a case
with a failed gate can never be accepted, which the table also enforces. Gate values
are owner-only; research receives the decision and a reason category.
"""

import math
from datetime import datetime
from typing import Any, Final, cast
from uuid import UUID

import numpy as np
from pydantic import JsonValue
from qfr_core.config import canonical_json
from qfr_core.correlation import current
from qfr_core.eval_api import CaseDecisionRequest
from qfr_core.ids import uuid7
from qfr_core.metrics.factor import sharpe
from sqlalchemy import text
from sqlalchemy.engine import Connection

from qfr_eval.configs import ActiveState, EvalError, record_event
from qfr_eval.reports import queue_report
from qfr_eval.store import ArtifactStore
from qfr_eval.trials import (
    backtest_overfitting,
    cluster_trials,
    deflated_sharpe,
    hlz_hurdle,
)

GATES: Final = (
    "G-W1", "G-W2", "G-HOLDOUT", "G-DSR", "G-PBO", "G-HLZ", "G-FWD", "G-NOVELTY", "G-OPS"
)  # fmt: skip


def _gate(
    name: str,
    passed: bool,
    value: float | None,
    threshold: float | None,
    detail: dict[str, Any],
    skipped: bool = False,
) -> dict[str, Any]:
    finite = None if value is None or not math.isfinite(value) else float(value)
    return {
        "name": name,
        "passed": bool(passed),
        "skipped": skipped,
        "value": finite,
        "threshold": threshold,
        "detail": detail,
    }


def refs(state: ActiveState, code_version: str) -> dict[str, str]:
    return {
        "protocol_id": state.protocol.id,
        "protocol_version": state.protocol.version,
        "data_snapshot_id": state.epoch.snapshot_id,
        "evaluator_code_version": code_version,
    }


def _history_rankic(
    conn: Connection, store: ArtifactStore, epoch_id: str, version_id: UUID
) -> np.ndarray:
    """Daily RankIC over W1 to W3 from the version's official series files."""
    rows = conn.execute(
        text(
            "SELECT s.uri, s.sha256 FROM eval.official_records r JOIN eval.series_files s "
            "ON s.run_id = r.run_ids[1] AND s.kind = 'rankic' WHERE r.version_id = :v "
            "AND r.epoch_id = :e AND r.stage IN ('w1', 'w2', 'holdout') ORDER BY r.window_name"
        ),
        {"v": version_id, "e": epoch_id},
    ).all()
    parts = []
    for row in rows:
        frame = store.read_series(row.uri, row.sha256)
        values = frame.get_column("rank_ic").cast(float).fill_null(np.nan).to_numpy()
        parts.append(values[np.isfinite(values)])
    return np.concatenate(parts) if parts else np.zeros(0)


def forward_statistics(conn: Connection, sim_id: UUID, sign: int) -> dict[str, Any]:
    """The incubation's forward RankIC (sign-adjusted), NAV drawdown, Sharpe and data
    completeness, from the simulation tables."""
    rankic = np.array(
        [
            r.value
            for r in conn.execute(
                text(
                    "SELECT value FROM eval.sim_rankic WHERE sim_id = :s AND value IS NOT NULL "
                    "ORDER BY decision_day"
                ),
                {"s": sim_id},
            ).all()
        ],
        dtype=np.float64,
    )
    nav_rows = conn.execute(
        text("SELECT nav, net_return, complete FROM eval.sim_nav WHERE sim_id = :s ORDER BY day"),
        {"s": sim_id},
    ).all()
    navs = np.array([r.nav for r in nav_rows], dtype=np.float64)
    returns = np.array(
        [np.nan if r.net_return is None else r.net_return for r in nav_rows], dtype=np.float64
    )
    adjusted = sign * rankic
    drawdown = float(np.max(1.0 - navs / np.maximum.accumulate(navs))) if navs.size else None
    complete = sum(1 for r in nav_rows if r.complete)
    return {
        "rankic_mean": float(adjusted.mean()) if adjusted.size else None,
        "rankic_days": int(adjusted.size),
        "max_drawdown": drawdown,
        "sharpe": sharpe(returns),
        "days": len(nav_rows),
        "complete_share": complete / len(nav_rows) if nav_rows else None,
        "final_nav": float(navs[-1]) if navs.size else None,
    }


def compute_gates(
    conn: Connection,
    store: ArtifactStore,
    state: ActiveState,
    intake: Any,
    sim: Any,
    novelty: dict[str, Any],
    at: datetime,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Every Section 10.3 gate for one version whose incubation ended."""
    protocol = state.protocol.config
    g = protocol["gates"]["acceptance"]
    epoch_id = state.epoch.epoch_id
    sign = int(sim.settings["sign"])
    kind = intake.kind
    gates = [
        _gate("G-W1", intake.w1_passed is True, None, None, {"w1_passed": intake.w1_passed}),
        _gate("G-W2", intake.w2_passed is True, None, None, {"w2_passed": intake.w2_passed}),
        _gate(
            "G-HOLDOUT",
            intake.holdout_passed is True,
            None,
            None,
            {"holdout_passed": intake.holdout_passed},
        ),
    ]

    # G-DSR with N_eff (ACC-01): cluster again when the latest run predates a trial.
    latest_trial = conn.execute(
        text(
            "SELECT max(counted_at) FROM eval.trial_ledger WHERE epoch_id = :e "
            "AND window_name = 'W1'"
        ),
        {"e": epoch_id},
    ).scalar()
    latest_run = conn.execute(
        text(
            "SELECT max(computed_at) FROM eval.trial_cluster_runs WHERE epoch_id = :e "
            "AND window_name = 'W1'"
        ),
        {"e": epoch_id},
    ).scalar()
    if latest_run is None or (latest_trial is not None and latest_run < latest_trial):
        cluster_trials(
            conn, store, epoch_id, "W1", float(g["cluster_similarity"]),
            int(g["neff_family_fallback_trials"]), at, current()["request_id"],
        )  # fmt: skip
    deflated = deflated_sharpe(conn, epoch_id, intake.version_id, kind)
    gates.append(
        _gate(
            "G-DSR",
            deflated.value is not None and deflated.value >= float(g["dsr_min"]),
            deflated.value,
            float(g["dsr_min"]),
            {
                "dsr_raw_n": deflated.value_raw_n,
                "sharpe_daily": deflated.sharpe,
                "n_obs": deflated.n_obs,
                "n_eff": deflated.n_eff,
                "n_raw": deflated.n_raw,
                "sharpe_variance": deflated.variance,
                "sr0": deflated.sr0,
                "cluster_run_id": deflated.cluster_run_id,
                "note": deflated.note,
            },
        )
    )

    overfit = backtest_overfitting(
        conn, store, epoch_id, intake.version_id, kind, int(g["pbo_blocks"]),
        int(g["pbo_cohort_min"]),
    )  # fmt: skip
    pbo_detail: dict[str, Any] = {
        "cohort": overfit.cohort,
        "members": overfit.members,
        "rows": overfit.rows,
        "blocks": int(g["pbo_blocks"]),
        "note": overfit.note,
    }
    if overfit.value is None:
        gates.append(_gate("G-PBO", True, None, float(g["pbo_max"]), pbo_detail, skipped=True))
    else:
        gates.append(
            _gate(
                "G-PBO",
                overfit.value <= float(g["pbo_max"]),
                overfit.value,
                float(g["pbo_max"]),
                pbo_detail,
            )
        )

    horizon = int(protocol["label"]["primary"])
    hurdle = hlz_hurdle(conn, store, epoch_id, intake.version_id, kind, horizon)
    gates.append(
        _gate(
            "G-HLZ",
            hurdle.t_value is not None and hurdle.t_value >= float(g["hlz_t_min"]),
            hurdle.t_value,
            float(g["hlz_t_min"]),
            {"observations": hurdle.observations, "lag": hurdle.lag, "windows": hurdle.windows},
        )
    )

    forward = forward_statistics(conn, sim.sim_id, sign)
    history = sign * _history_rankic(conn, store, epoch_id, intake.version_id)
    z = None
    if forward["rankic_mean"] is not None and history.size >= 2 and forward["rankic_days"] > 0:
        sd = float(history.std(ddof=1))
        if sd > 0:
            z = (forward["rankic_mean"] - float(history.mean())) / (
                sd / math.sqrt(forward["rankic_days"])
            )
    checks = {
        "incubation_days": sim.days_done >= int(g["incubation_days_min"]),
        "rankic_positive": forward["rankic_mean"] is not None and forward["rankic_mean"] > 0,
        "consistency": z is not None and z >= float(g["consistency_z_min"]),
        "drawdown": forward["max_drawdown"] is not None
        and forward["max_drawdown"] <= float(g["forward_drawdown_max"]),
    }
    gates.append(
        _gate(
            "G-FWD",
            all(checks.values()),
            forward["rankic_mean"],
            0.0,
            {
                "checks": checks,
                "days": sim.days_done,
                "days_min": int(g["incubation_days_min"]),
                "consistency_z": z,
                "consistency_z_min": float(g["consistency_z_min"]),
                "historical_rankic_mean": float(history.mean()) if history.size else None,
                "max_drawdown": forward["max_drawdown"],
                "drawdown_max": float(g["forward_drawdown_max"]),
                "sharpe": forward["sharpe"],
                "mode": sim.mode,
            },
        )
    )

    threshold = float(g["library_correlation_max"])
    if novelty.get("vacuous"):
        gates.append(
            _gate(
                "G-NOVELTY",
                True,
                None,
                threshold,
                {"note": "the library is empty; the gate is vacuous", "members": []},
                skipped=True,
            )  # fmt: skip
        )
    else:
        value = novelty.get("max_abs")
        gates.append(
            _gate(
                "G-NOVELTY",
                value is not None and value <= threshold,
                value,
                threshold,
                {"argmax_version_id": novelty.get("argmax"), "members": novelty.get("members")},
            )
        )

    share = forward["complete_share"]
    ok = sim.status == "completed" and sim.error_code is None
    gates.append(
        _gate(
            "G-OPS",
            ok and share is not None and share >= float(g["complete_data_min"]),
            share,
            float(g["complete_data_min"]),
            {"status": sim.status, "error_code": sim.error_code, "days": forward["days"]},
        )
    )
    return gates, forward


def open_case(
    conn: Connection,
    state: ActiveState,
    intake: Any,
    sim: Any,
    gates: list[dict[str, Any]],
    at: datetime,
    principal: str,
    request_id: str,
) -> tuple[UUID, str]:
    """Insert the case (the table refuses one before incubation ends, ACC-02)."""
    failing = [g["name"] for g in gates if not g["passed"]]
    case_id = uuid7()
    number = int(conn.execute(text("SELECT nextval('eval.acceptance_case_seq')")).scalar_one())
    short_code = f"C-{number:04d}"
    conn.execute(
        text(
            "INSERT INTO eval.acceptance_cases (case_id, short_code, version_id, epoch_id, "
            "sim_id, kind, mode, gate_results, recommendation, failing_gates, state, "
            "opened_at, request_id) VALUES (:id, :code, :v, :e, :s, :k, :m, "
            "CAST(:g AS jsonb), :rec, :failing, 'open', :at, :r)"
        ),
        {
            "id": case_id,
            "code": short_code,
            "v": intake.version_id,
            "e": state.epoch.epoch_id,
            "s": sim.sim_id,
            "k": intake.kind,
            "m": sim.mode,
            "g": canonical_json(cast(JsonValue, gates)),
            "rec": "REJECT" if failing else "ACCEPT",
            "failing": failing,
            "at": at,
            "r": request_id,
        },
    )
    conn.execute(
        text(
            "UPDATE eval.intake SET state = 'AcceptanceReview', updated_at = :at "
            "WHERE version_id = :v"
        ),
        {"at": at, "v": intake.version_id},
    )
    record_event(
        conn, at, principal, "case_opened", "acceptance_case", str(case_id), request_id,
        {"short_code": short_code, "version_id": str(intake.version_id),
         "recommendation": "REJECT" if failing else "ACCEPT", "failing_gates": failing},
    )  # fmt: skip
    return case_id, short_code


def case_view(row: Any) -> dict[str, Any]:
    return {
        "visibility": "owner_only",
        "case_id": row.case_id,
        "short_code": row.short_code,
        "version_id": row.version_id,
        "kind": row.kind,
        "sim_id": row.sim_id,
        "mode": row.mode,
        "opened_at": row.opened_at,
        "recommendation": row.recommendation,
        "failing_gates": list(row.failing_gates),
        "gates": list(row.gate_results),
        "state": row.state,
        "decision": row.decision,
        "reason": row.reason,
        "reason_gate": row.reason_gate,
        "rationale": row.rationale,
        "approval_id": row.approval_id,
        "decided_at": row.decided_at,
    }


def list_cases(
    conn: Connection,
    state: str | None = None,
    version_id: UUID | None = None,
    case_id: UUID | None = None,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            "SELECT * FROM eval.acceptance_cases WHERE (CAST(:s AS text) IS NULL OR state = :s) "
            "AND (CAST(:v AS uuid) IS NULL OR version_id = :v) "
            "AND (CAST(:c AS uuid) IS NULL OR case_id = :c) ORDER BY opened_at DESC, case_id"
        ),
        {"s": state, "v": version_id, "c": case_id},
    ).all()
    return [case_view(r) for r in rows]


def decide_case(
    conn: Connection,
    state: ActiveState,
    case_id: UUID,
    request: CaseDecisionRequest,
    principal: str,
    at: datetime,
    request_id: str,
    code_version: str,
) -> dict[str, Any]:
    """The owner's decision with its approval (ACC-03). Accepting a case with a failed
    gate is refused in v1; the approval's scope must name the case."""
    row = conn.execute(
        text("SELECT * FROM eval.acceptance_cases WHERE case_id = :c FOR UPDATE"),
        {"c": case_id},
    ).first()
    if row is None:
        raise EvalError(404, "CASE_NOT_FOUND", "no acceptance case with this id")
    if row.state != "open":
        raise EvalError(409, "CASE_DECIDED", "the case is already decided")
    approval = request.approval
    expected = "accept_case" if request.decision == "accept" else "reject_case"
    scope = approval.scope
    if (
        approval.decision != expected
        or scope.case_id != case_id
        or (scope.version_ids and row.version_id not in scope.version_ids)
    ):
        raise EvalError(
            403, "APPROVAL_SCOPE_MISMATCH", "the approval's decision and scope must name the case"
        )
    if request.decision == "accept" and row.recommendation != "ACCEPT":
        raise EvalError(
            409,
            "GATE_FAILED",
            "in v1 a case with a failed gate cannot be accepted",
            {"failing_gates": list(row.failing_gates)},
        )
    sim = conn.execute(
        text("SELECT status FROM eval.sim_accounts WHERE sim_id = :s"), {"s": row.sim_id}
    ).scalar()
    reason_gate = None
    if request.decision == "accept":
        decision, reason = "accepted", "gates_passed"
    elif sim == "failed":
        decision, reason = "rejected", "incubation_failed"
    elif row.recommendation == "REJECT":
        decision, reason = "rejected", "gate_failed"
        reason_gate = next(name for name in GATES if name in row.failing_gates)
    else:
        decision, reason = "rejected", "owner_rejected"
    updated = conn.execute(
        text(
            "UPDATE eval.acceptance_cases SET state = 'decided', decision = :d, reason = :reason, "
            "reason_gate = :gate, rationale = :rat, approval_id = :a, decided_by = :p, "
            "decided_at = :at WHERE case_id = :c RETURNING *"
        ),
        {
            "d": decision,
            "reason": reason,
            "gate": reason_gate,
            "rat": request.rationale,
            "a": approval.approval_id,
            "p": principal,
            "at": at,
            "c": case_id,
        },
    ).first()
    conn.execute(
        text("UPDATE eval.intake SET state = :s, updated_at = :at WHERE version_id = :v"),
        {"s": "Accepted" if decision == "accepted" else "Rejected", "at": at, "v": row.version_id},
    )
    content: dict[str, JsonValue] = {
        "type": "decision",
        "status": "ACCEPTED" if decision == "accepted" else "REJECTED",
        "reason": reason,
        "gate": reason_gate,
    }
    queue_report(
        conn, "decision", row.version_id,
        {"content": content, "refs": refs(state, code_version)}, at, request_id,
    )  # fmt: skip
    record_event(
        conn, at, principal, "case_decided", "acceptance_case", str(case_id), request_id,
        {"decision": decision, "reason": reason, "approval_id": str(approval.approval_id)},
    )  # fmt: skip
    return case_view(updated)
