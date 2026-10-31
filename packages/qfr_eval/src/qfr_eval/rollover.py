"""Epoch rollover (PLAN Section 10.6, P8.4).

Rollover is manual and owner-approved: qfr.ops.rollover_epoch with a rollover_epoch
approval reaches eval-admin-api, which applies it in one transaction:

  - the new epoch must follow the rules of Section 10.6: its research cutoff (W0's end)
    is the old W2's end, so the old W1 and W2 become research-visible; its W1 is the old
    W3; its W2 and W3 come from data after the old W3, with the embargoes (the usual
    embargo check on the current full snapshot's calendar);
  - the old epoch is retired and the new one activated, naming the old one; every
    official record, run, series file, ledger row and report stays linked to the epoch
    it was made in, unchanged;
  - fingerprint dates are drawn again from the new W0, the trial ledger, the Ladder,
    the trial clusters, the burn meters and the W2 and W3 budgets restart for the new
    windows (they are all kept per epoch);
  - versions on their way through the old epoch (Discovered to HoldoutCheck) restart
    from Discovered in the new one: their old records stay, and they are measured again
    on the new windows. Jobs still queued for the old epoch are cancelled, and the
    worker cancels a running one instead of writing it into the retired epoch;
  - admitted versions are fingerprinted again on the new W0 so behavioral dedup keeps
    comparing with them, and library members are re-measured on the new W1 so the
    library gate keeps its members ('remeasure' records, not trials);
  - pools, the library itself, simulations and acceptance cases are unaffected.

The research snapshot is rebuilt at the new cutoff by the owner afterwards (runbook);
it records the epoch it was cut for, which tags research history by epoch.

`python -m qfr_eval.rollover propose` drafts the next epoch file from the active epoch
and the current full snapshot (`just epoch-propose`); `plan` prints what a rollover to a
given file would do without changing anything.
"""

import json
import os
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

import typer
import yaml
from qfr_core.config import EpochConfig, RuntimeSettings, canonical_json
from qfr_core.correlation import current
from qfr_core.data.snapshot import current_snapshot
from sqlalchemy import bindparam, text
from sqlalchemy.engine import Connection

from qfr_eval import alerts, queue
from qfr_eval.configs import (
    ActiveEpoch,
    EvalError,
    Window,
    _last_full_month_end,
    activate_epoch,
    active_epoch,
    active_version,
    load_epoch_file,
    record_event,
    register_current_full,
    resolve_windows,
    snapshot_calendar,
)
from qfr_eval.runtime import Database

# Versions still on their way through the old epoch: they restart in the new one.
RESTART_STATES = (
    "Discovered", "Fingerprinting", "Deferred", "Screening", "W1Evaluated", "W2Queued",
    "HoldoutCheck",
)  # fmt: skip
# Admitted versions keep a fingerprint in the current epoch for behavioral dedup.
REFINGERPRINT_STATES = (
    "ScreenFailed", "W1GateFailed", "W2Failed", "W2Expired", "NotAdvanced", "AwaitingSlot",
    "Incubating", "AcceptanceReview", "Accepted", "Rejected", "Monitoring", "Retired",
)  # fmt: skip
WINDOW_NAMES = ("W0", "W1", "W2", "W3")


def _states(name: str = "states") -> Any:
    return bindparam(name, expanding=True)


def propose(
    current: ActiveEpoch,
    embargo: int,
    calendar: list[date],
    at: date,
    epoch_id: str,
    *,
    version: str = "1",
    w2_share: float = 0.5,
    min_window_days: int = 60,
) -> dict[str, Any]:
    """The next epoch by Section 10.6. W2 and W3 split the trading days after the old W3
    (up to the last full month before `at`) once both embargoes are taken out: W2 gets
    `w2_share` of them, and W3 keeps the end rule so it is pinned at activation."""
    if epoch_id == current.epoch_id:
        raise EvalError(409, "EPOCH_ACTIVE", f"{epoch_id} is the active epoch")
    old = current.windows
    cutoff = _last_full_month_end(at)
    after = [d for d in calendar if old["W3"].end < d <= cutoff]
    usable = len(after) - 2 * embargo
    if usable < 2 * min_window_days:
        raise EvalError(
            409,
            "ROLLOVER_TOO_EARLY",
            f"{len(after)} trading days after the old W3 leave {max(usable, 0)} for W2 and W3 "
            f"after two {embargo}-day embargoes; at least {2 * min_window_days} are needed",
            {"days_after_w3": len(after), "usable": max(usable, 0)},
        )
    w2_days = min(max(round(usable * w2_share), min_window_days), usable - min_window_days)
    w2 = after[embargo : embargo + w2_days]
    w3_start = after[embargo + w2_days + embargo]
    return {
        "epoch_id": epoch_id,
        "version": version,
        "W0": {"start": old["W0"].start.isoformat(), "end": old["W2"].end.isoformat()},
        "W1": {"start": old["W3"].start.isoformat(), "end": old["W3"].end.isoformat()},
        "W2": {"start": w2[0].isoformat(), "end": w2[-1].isoformat()},
        "W3": {
            "start": w3_start.isoformat(),
            "end": None,
            "end_rule": "last_full_month_before_epoch_activation",
        },
        "embargo_trading_days": embargo,
    }


def contract_problems(old: dict[str, Window], new: dict[str, Window]) -> list[str]:
    """How the new windows break Section 10.6, as stable sentences (empty when none)."""
    problems = []
    if new["W0"].start != old["W0"].start:
        problems.append("W0 must keep its start: research history is never shortened")
    if new["W0"].end != old["W2"].end:
        problems.append("W0 must end where the old W2 ends (the new research cutoff)")
    if (new["W1"].start, new["W1"].end) != (old["W3"].start, old["W3"].end):
        problems.append("the new W1 must be the old W3, with the same dates")
    if new["W2"].start <= old["W3"].end:
        problems.append("the new W2 must start after the old W3")
    return problems


def _windows_json(windows: dict[str, Window]) -> dict[str, dict[str, str]]:
    return {n: {"start": w.start.isoformat(), "end": w.end.isoformat()} for n, w in windows.items()}


def plan(
    conn: Connection, epoch: EpochConfig, calendar: list[date], at: datetime
) -> dict[str, Any]:
    """What a rollover to `epoch` would do now; changes nothing."""
    current = active_epoch(conn)
    if current is None:
        raise EvalError(409, "NOT_READY", "there is no active epoch to roll over")
    if epoch.epoch_id == current.epoch_id:
        raise EvalError(409, "EPOCH_ACTIVE", f"{epoch.epoch_id} is already the active epoch")
    known = conn.execute(
        text("SELECT status FROM eval.epochs WHERE epoch_id = :e"), {"e": epoch.epoch_id}
    ).scalar()
    if known is not None:
        raise EvalError(409, "EPOCH_EXISTS", f"epoch {epoch.epoch_id} was used before ({known})")
    windows, check = resolve_windows(epoch, calendar, at.date())
    problems = contract_problems(current.windows, windows)
    if not check["passed"]:
        problems.append(
            f"each embargo needs {epoch.embargo_trading_days} trading days; the calendar "
            f"gives {check['gaps_trading_days']}"
        )
    if epoch.replay is not None:
        problems.append("a rollover epoch has no replay tail (replay is for synthetic tests)")
    restart = {
        str(r.state): int(r.n)
        for r in conn.execute(
            text(
                "SELECT state, count(*) AS n FROM eval.intake WHERE state IN :states "
                "GROUP BY state ORDER BY state"
            ).bindparams(_states()),
            {"states": RESTART_STATES},
        ).all()
    }
    queued: int = conn.execute(
        text("SELECT count(*) FROM eval.queue_jobs WHERE epoch_id = :e AND state = 'queued'"),
        {"e": current.epoch_id},
    ).scalar_one()
    running: int = conn.execute(
        text("SELECT count(*) FROM eval.queue_jobs WHERE epoch_id = :e AND state = 'running'"),
        {"e": current.epoch_id},
    ).scalar_one()
    refingerprint: int = conn.execute(
        text("SELECT count(*) FROM eval.intake WHERE state IN :states").bindparams(_states()),
        {"states": REFINGERPRINT_STATES},
    ).scalar_one()
    remeasure = len(_library_to_remeasure(conn))
    protocol = active_version(conn, "protocol")
    protocol_ref = "" if protocol is None else str(protocol.config.get("epoch_ref", ""))
    return {
        "from_epoch": current.epoch_id,
        "to_epoch": epoch.epoch_id,
        "windows": _windows_json(windows),
        "old_windows": _windows_json(current.windows),
        "research_cutoff": windows["W0"].end.isoformat(),
        "embargo_check": check,
        "problems": problems,
        "restart": restart,
        "cancelled_jobs": int(queued),
        "running_jobs": int(running),
        "refingerprint_jobs": int(refingerprint),
        "remeasure_jobs": remeasure,
        "protocol_epoch_ref": protocol_ref,
        "protocol_epoch_ref_matches": protocol_ref == epoch.epoch_id,
    }


def _library_to_remeasure(conn: Connection) -> list[Any]:
    """Effective library members that do not restart: they keep their place in the
    library gate by a re-measurement on the new W1."""
    return list(
        conn.execute(
            text(
                "SELECT l.version_id, i.family_id FROM eval.library l "
                "JOIN eval.intake i ON i.version_id = l.version_id "
                "WHERE l.status IN ('seed', 'active') AND l.effective_from IS NOT NULL "
                "AND i.state NOT IN :states ORDER BY i.published_seq"
            ).bindparams(_states()),
            {"states": RESTART_STATES},
        ).all()
    )


def apply(
    conn: Connection,
    epoch: EpochConfig,
    source_sha256: str,
    snapshot_id: str,
    calendar: list[date],
    principal: str,
    approval_id: UUID,
    request_id: str,
    at: datetime,
) -> dict[str, Any]:
    """The rollover, in the caller's transaction (under the evaluator's write lock)."""
    report = plan(conn, epoch, calendar, at)
    if report["problems"]:
        raise EvalError(409, "ROLLOVER_REFUSED", "; ".join(report["problems"]), {"plan": report})
    old = report["from_epoch"]
    conn.execute(
        text(
            "UPDATE eval.epochs SET status = 'retired', retired_at = :at "
            "WHERE epoch_id = :e AND status = 'active'"
        ),
        {"e": old, "at": at},
    )
    report |= {"approval_id": str(approval_id), "applied_at": at.isoformat()}
    pinned = activate_epoch(
        conn, epoch, source_sha256, snapshot_id, calendar, report["protocol_epoch_ref"],
        principal, approval_id, request_id, at, previous_epoch_id=old, rollover=report,
    )  # fmt: skip
    cancelled = queue.cancel_retired(conn, old, at)
    restarted = conn.execute(
        text(
            "UPDATE eval.intake SET state = 'Discovered', reason_code = NULL, "
            "duplicate_of = NULL, similarity = NULL, fingerprint_error = NULL, "
            "w1_passed = NULL, deferred_at = NULL, enqueued_at = NULL, decided_at = NULL, "
            "w2_queued_at = NULL, w2_admitted_at = NULL, w2_passed = NULL, "
            "holdout_admitted_at = NULL, holdout_passed = NULL, updated_at = :at "
            "WHERE state IN :states RETURNING version_id"
        ).bindparams(_states()),
        {"states": RESTART_STATES, "at": at},
    ).all()
    payload = {"epoch_id": pinned.epoch_id, "snapshot_id": pinned.snapshot_id}
    refingerprint = conn.execute(
        text(
            "SELECT version_id, family_id FROM eval.intake WHERE state IN :states "
            "ORDER BY published_seq"
        ).bindparams(_states()),
        {"states": REFINGERPRINT_STATES},
    ).all()
    for row in refingerprint:
        queue.enqueue(
            conn, "fingerprint", row.version_id, row.family_id,
            payload | {"version_id": str(row.version_id), "correlation": current()}, at,
            pinned.epoch_id,
        )  # fmt: skip
    remeasure = _library_to_remeasure(conn)
    for row in remeasure:
        queue.enqueue(
            conn, "remeasure", row.version_id, row.family_id,
            payload | {"version_id": str(row.version_id), "correlation": current()}, at,
            pinned.epoch_id,
        )  # fmt: skip
    # The red burn meters that prompted the rollover belong to the retired epoch.
    burn_alerts: list[UUID] = list(
        conn.execute(
            text(
                "SELECT alert_id FROM eval.alerts WHERE state = 'open' AND kind = 'burn' "
                "AND dedup_key LIKE :k"
            ),
            {"k": f"burn:{old}:%"},
        ).scalars()
    )
    for alert_id in burn_alerts:
        alerts.acknowledge(
            conn, alert_id, principal, f"epoch {old} rolled over to {pinned.epoch_id}", at,
            principal, request_id,
        )  # fmt: skip
    applied = report | {
        "cancelled_jobs": cancelled,
        "restarted_versions": len(restarted),
        "refingerprint_jobs": len(refingerprint),
        "remeasure_jobs": len(remeasure),
    }
    record_event(
        conn, at, principal, "epoch_rolled_over", "epoch", pinned.epoch_id, request_id,
        json.loads(canonical_json(applied)),
    )  # fmt: skip
    return applied


# Owner commands (run in the eval-scheduler container: database and full snapshot) ------

app = typer.Typer(no_args_is_help=True, help="Epoch rollover (Section 10.6).")


def _context() -> tuple[Database, Path, Path]:
    settings = RuntimeSettings(service="eval-rollover", zone="eval")
    database = Database(os.environ.get("EVAL_DB_URL", ""))
    full = Path(os.environ.get("QFR_FULL_SNAPSHOT_DIR") or "data/full")
    return database, settings.config_dir, full


@app.command("propose")
def propose_command(
    epoch_id: Annotated[str, typer.Option(help="The new epoch's id, e.g. epoch_002")],
    w2_share: Annotated[float, typer.Option(help="Share of the new days for W2")] = 0.5,
    min_window_days: Annotated[int, typer.Option(help="Least trading days in W2 and W3")] = 60,
) -> None:
    """Print the next epoch file (YAML) for the owner to review and save."""
    database, _, full = _context()
    now = datetime.now(UTC)
    with database.read() as conn:
        current_epoch = active_epoch(conn)
        if current_epoch is None:
            raise typer.BadParameter("there is no active epoch")
        embargo = int(
            conn.execute(
                text("SELECT config FROM eval.epochs WHERE epoch_id = :e"),
                {"e": current_epoch.epoch_id},
            ).scalar_one()["embargo_trading_days"]
        )
    calendar = snapshot_calendar(full, current_snapshot(full).name)
    try:
        proposal = propose(
            current_epoch, embargo, calendar, now.date(), epoch_id, w2_share=w2_share,
            min_window_days=min_window_days,
        )  # fmt: skip
    except EvalError as error:
        typer.echo(json.dumps({"status": "error", "code": error.code, "message": error.message}))
        raise typer.Exit(1) from None
    typer.echo(
        f"# Proposed by `just epoch-propose` on {now.date()} from {current_epoch.epoch_id} "
        "(PLAN Section 10.6).\n# W0 ends where the old W2 ends; W1 is the old W3; W2 and W3 "
        "follow with the embargoes.\n# Review it, then roll over with qfr.ops.rollover_epoch."
    )
    typer.echo(yaml.safe_dump(proposal, sort_keys=False).rstrip())


@app.command("plan")
def plan_command(
    epoch_id: Annotated[str, typer.Option(help="The epoch file under configs/epochs/")],
) -> None:
    """Print what a rollover to the epoch file would do; changes nothing."""
    database, config_dir, full = _context()
    epoch, _ = load_epoch_file(config_dir / "epochs" / f"{epoch_id}.yaml")
    with database.read() as conn:
        snapshot_id = current_snapshot(full).name
        report = plan(conn, epoch, snapshot_calendar(full, snapshot_id), datetime.now(UTC))
    typer.echo(json.dumps(report, sort_keys=True, indent=2))


def rollover_from_file(
    conn: Connection,
    epochs_dir: Path,
    full_dir: Path,
    epoch_id: str,
    principal: str,
    approval_id: UUID | None,
    request_id: str,
    at: datetime,
    dry_run: bool,
) -> dict[str, Any]:
    """eval-admin-api's entry: the epoch file, the current full snapshot, then plan or
    apply."""
    path = epochs_dir / f"{epoch_id}.yaml"
    if not path.is_file():
        raise EvalError(
            404, "EPOCH_FILE_NOT_FOUND", f"no epoch file configs/epochs/{epoch_id}.yaml"
        )
    epoch, sha = load_epoch_file(path)
    if epoch.epoch_id != epoch_id:
        raise EvalError(409, "EPOCH_FILE_MISMATCH", f"the file names epoch {epoch.epoch_id}")
    snapshot_id = register_current_full(conn, full_dir, principal, request_id, at)
    if snapshot_id is None:
        raise EvalError(409, "NOT_READY", "there is no current full snapshot")
    calendar = snapshot_calendar(full_dir, snapshot_id)
    if dry_run:
        return plan(conn, epoch, calendar, at) | {"dry_run": True, "snapshot_id": snapshot_id}
    if approval_id is None:
        raise EvalError(400, "APPROVAL_REQUIRED", "a rollover needs a rollover_epoch approval")
    applied = apply(conn, epoch, sha, snapshot_id, calendar, principal, approval_id, request_id, at)
    return applied | {"dry_run": False, "snapshot_id": snapshot_id}


if __name__ == "__main__":
    app()
