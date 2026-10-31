"""Epoch rollover (P8.4, PLAN Section 10.6).

The proposal and the window contract are checked on a weekday calendar. The synthetic
dry run rolls the small epoch over on the 800-day world through the MCP front door, with
the owner's approval, and checks that every record, run, series file, ledger row,
report, trace step and registry row made before it is still there, unchanged and linked;
that in-flight versions restart and are measured on the new windows; that admitted
versions are fingerprinted again on the new W0 and library members re-measured on the
new W1; and that a job running across the rollover writes nothing into the old epoch.
"""

import hashlib
import json
from datetime import date, timedelta
from typing import Any
from uuid import UUID

import pytest
import yaml
from qfr_core.config import EpochConfig, canonical_json
from qfr_core.ids import uuid7
from qfr_eval import queue, rollover
from qfr_eval.compute import InlineRunner
from qfr_eval.configs import (
    ActiveEpoch,
    EvalError,
    Window,
    active_epoch,
    resolve_windows,
    snapshot_calendar,
)
from qfr_eval.reproduce import reproduce
from qfr_eval.runtime import eval_config
from qfr_eval.store import ArtifactStore
from qfr_eval.worker import Evaluator, MarketCache
from qfr_mcp.approvals import rollover_code
from sqlalchemy import text

from tests.eval.stack_rig import stack
from tests.registry_rig import factor_manifest
from tests.synthetic_fixtures import SMALL_EPOCH

NEW = "epoch_002"
AT = date(2026, 1, 5)


def weekdays(start: date = date(2010, 1, 4), n: int = 800) -> list[date]:
    days, day = [], start
    while len(days) < n:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return days


def small_active(calendar: list[date]) -> ActiveEpoch:
    epoch = EpochConfig.model_validate(SMALL_EPOCH)
    windows, check = resolve_windows(epoch, calendar, AT)
    return ActiveEpoch(epoch.epoch_id, epoch.version, windows, "s" * 64, check, None)


# The proposal and the contract ----------------------------------------------------------


def test_the_proposal_follows_section_10_6():
    calendar = weekdays()
    current = small_active(calendar)
    proposal = rollover.propose(current, 20, calendar, AT, NEW, min_window_days=20)
    old = current.windows
    assert proposal["W0"] == {"start": "2010-01-04", "end": old["W2"].end.isoformat()}
    assert proposal["W1"] == {"start": "2012-07-02", "end": "2012-09-07"}
    assert proposal["W3"]["end"] is None
    epoch = EpochConfig.model_validate(proposal)
    windows, check = resolve_windows(epoch, calendar, AT)
    assert check["passed"], check
    gaps = check["gaps_trading_days"]
    assert gaps["W0-W1"] >= 20 and gaps["W1-W2"] == gaps["W2-W3"] == 20, gaps
    assert rollover.contract_problems(old, windows) == []
    after = [d for d in calendar if d > old["W3"].end]
    assert windows["W2"].start == after[20] and windows["W3"].end == calendar[-1]
    w2_days = sum(1 for d in calendar if windows["W2"].start <= d <= windows["W2"].end)
    w3_days = sum(1 for d in calendar if windows["W3"].start <= d <= windows["W3"].end)
    assert w2_days >= 20 and w3_days >= 20 and w2_days + w3_days == len(after) - 40


def test_the_proposal_waits_for_enough_new_data():
    calendar = weekdays()
    current = small_active(calendar)
    # Two embargoes take 40 of the 60 trading days after W3 by 2012-11-30.
    with pytest.raises(EvalError) as early:
        rollover.propose(current, 20, calendar, date(2012, 12, 15), NEW, min_window_days=20)
    assert early.value.code == "ROLLOVER_TOO_EARLY"
    assert early.value.details == {"days_after_w3": 60, "usable": 20}
    with pytest.raises(EvalError) as same:
        rollover.propose(current, 20, calendar, AT, "small_test")
    assert same.value.code == "EPOCH_ACTIVE"


def test_the_contract_names_each_broken_rule():
    old = small_active(weekdays()).windows

    def shifted(**changes: tuple[str, str]) -> dict[str, Window]:
        new = {
            "W0": Window(old["W0"].start, old["W2"].end),
            "W1": old["W3"],
            "W2": Window(date(2012, 10, 8), date(2012, 11, 16)),
            "W3": Window(date(2012, 12, 17), date(2013, 1, 25)),
        }
        for name, (start, end) in changes.items():
            new[name] = Window(date.fromisoformat(start), date.fromisoformat(end))
        return new

    assert rollover.contract_problems(old, shifted()) == []
    problems = rollover.contract_problems(
        old,
        shifted(
            W0=("2010-06-01", "2012-04-30"),
            W1=("2012-06-01", "2012-09-07"),
            W2=("2012-09-03", "2012-11-16"),
        ),
    )
    assert problems == [
        "W0 must keep its start: research history is never shortened",
        "W0 must end where the old W2 ends (the new research cutoff)",
        "the new W1 must be the old W3, with the same dates",
        "the new W2 must start after the old W3",
    ]


# The synthetic dry run ------------------------------------------------------------------

EVAL_TABLES = {
    "official_records": "record_id",
    "runs": "run_id",
    "series_files": "run_id, kind",
    "trial_ledger": "epoch_id, window_name, version_id",
    "release_queue": "queue_id",
    "released_reports": "report_id",
    "fingerprints": "version_id, epoch_id",
    "ladder_events": "event_id",
    "events": "event_id",
}


@pytest.fixture
def full(tmp_path, monkeypatch, replay_zones):
    with stack(tmp_path, monkeypatch, replay_zones) as built:
        yield built


def digest(rows: list[Any]) -> dict[str, str]:
    """Each row's content hash, by its key columns."""
    out = {}
    for row in rows:
        data = dict(row._mapping)
        out[json.dumps(data.pop("_key"), default=str)] = hashlib.sha256(
            canonical_json(json.loads(json.dumps(data, default=str))).encode()
        ).hexdigest()
    return out


def eval_snapshot(rig) -> dict[str, dict[str, str]]:
    return {
        table: digest(rig.db.rows(f"SELECT ROW({key})::text AS _key, t.* FROM eval.{table} t"))
        for table, key in EVAL_TABLES.items()
    }


def other_snapshot(full) -> dict[str, dict[str, str]]:
    def rows(conn: Any, sql: str) -> dict[str, str]:
        return digest(list(conn.execute(text(sql))))

    control, registry = full.mcp.control_db.conn, full.mcp.registry.db.conn
    return {
        "trace_steps": rows(control, "SELECT step_id::text AS _key, t.* FROM trace_steps t"),
        "approvals": rows(control, "SELECT approval_id::text AS _key, t.* FROM approvals t"),
        "artifact_versions": rows(
            registry, "SELECT version_id::text AS _key, t.* FROM artifact_versions t"
        ),
        "artifact_parents": rows(
            registry,
            "SELECT ROW(version_id, parent_version_id)::text AS _key, t.* FROM artifact_parents t",
        ),
    }


def unchanged(before: dict[str, dict[str, str]], after: dict[str, dict[str, str]]) -> None:
    for table, rows in before.items():
        kept = {k: after[table].get(k) for k in rows}
        assert kept == rows, f"{table} rows changed or vanished"


def links_resolve(rig, epoch_id: str) -> None:
    """Every record names its runs; every run its epoch; every ledger row and released
    report its record; every series file is in the store with its hash."""
    assert not rig.db.rows(
        "SELECT r.record_id FROM eval.official_records r WHERE r.epoch_id = :e AND EXISTS ("
        "SELECT 1 FROM unnest(r.run_ids) u(run_id) WHERE NOT EXISTS ("
        "SELECT 1 FROM eval.runs x WHERE x.run_id = u.run_id AND x.epoch_id = r.epoch_id))",
        e=epoch_id,
    )
    assert not rig.db.rows(
        "SELECT 1 FROM eval.trial_ledger l LEFT JOIN eval.official_records r "
        "ON r.record_id = l.record_id WHERE l.epoch_id = :e "
        "AND (r.record_id IS NULL OR r.epoch_id <> l.epoch_id)",
        e=epoch_id,
    )
    assert not rig.db.rows(
        "SELECT 1 FROM eval.released_reports p JOIN eval.release_queue q USING (queue_id) "
        "LEFT JOIN eval.official_records r ON r.record_id = q.record_id "
        "WHERE q.record_id IS NOT NULL AND r.record_id IS NULL"
    )
    files = rig.db.rows(
        "SELECT s.uri, s.sha256 FROM eval.series_files s JOIN eval.runs r USING (run_id) "
        "WHERE r.epoch_id = :e",
        e=epoch_id,
    )
    assert files
    store = ArtifactStore(rig.env.store_dir)
    for f in files:
        path = store._path(f.uri)
        assert path.is_file(), f.uri
        assert hashlib.sha256(path.read_bytes()).hexdigest() == f.sha256


def publish(full, name: str, expression: str) -> UUID:
    response = full.mcp.registry.publish(factor_manifest(name, expression))
    assert response.status_code == 201, response.text
    return UUID(response.json()["version"]["version_id"])


def state(rig, version: UUID) -> str:
    return str(rig.db.scalar("SELECT state FROM eval.intake WHERE version_id = :v", v=version))


def make_seed(rig, version: UUID) -> None:
    """A library seed (as a pool import would leave it), effective from its W1 record."""
    rig.db.conn.execute(
        text(
            "INSERT INTO eval.library (version_id, pool, entry_id, status, approved_tier, "
            "effective_from, last_event_seq, updated_at) SELECT :v, 'factor', :entry, 'seed', "
            "NULL, created_at, 0, created_at FROM eval.official_records "
            "WHERE version_id = :v AND stage = 'w1'"
        ),
        {"v": version, "entry": uuid7()},
    )


def write_proposal(full) -> dict[str, Any]:
    rig = full.eval
    with rig.db.read() as conn:
        current = active_epoch(conn)
    assert current is not None
    calendar = snapshot_calendar(rig.env.full_snapshot_dir, current.snapshot_id)
    proposal = rollover.propose(
        current, 20, calendar, rig.clock.now().date(), NEW, min_window_days=20
    )
    folder = rig.tmp_path / "epochs"
    folder.mkdir(exist_ok=True)
    (folder / f"{NEW}.yaml").write_text(yaml.safe_dump(proposal, sort_keys=False))
    return proposal


def test_a_synthetic_rollover_keeps_every_link(full):
    rig, mcp = full.eval, full.mcp
    # A seed that is not in flight (its W1 gate failed under a strict protocol) and a
    # degenerate factor that fails screening; then one version measured through W2 and
    # one still on its way (queued for its fingerprint) when the rollover comes.
    rig.activate_protocol("test-strict", {"w1_factor": {"rankic_min": 1.0}})
    seed = publish(full, "seed_reversal", "-Pct($close, 5)")
    flat = publish(full, "flat", "$close * 0")
    full.settle()
    assert state(rig, seed) == "W1GateFailed" and state(rig, flat) == "ScreenFailed"
    make_seed(rig, seed)
    rig.activate_protocol("test-open", {"w1_factor": {"rankic_min": -1.0, "ir_min": -100.0,
                                                      "nw_t_min": -100.0}})  # fmt: skip
    measured = publish(full, "volume_corr", "Corr($close, $volume, 10)")
    full.settle()
    assert state(rig, measured) in rollover.REFINGERPRINT_STATES
    late = publish(full, "momentum", "Mean($close, 5) / Mean($close, 20) - 1")
    rig.scheduler.tick()
    assert state(rig, late) in rollover.RESTART_STATES
    in_flight = [late]
    queued = rig.db.scalar(
        "SELECT count(*) FROM eval.queue_jobs WHERE state = 'queued' AND epoch_id = :e",
        e="small_test",
    )
    assert queued >= 1
    old_records = rig.db.rows(
        "SELECT record_id, version_id, stage FROM eval.official_records WHERE epoch_id = :e",
        e="small_test",
    )
    old_fingerprints = {
        r.version_id: r.dates_sha256
        for r in rig.db.rows("SELECT version_id, dates_sha256 FROM eval.fingerprints")
    }
    before = eval_snapshot(rig) | other_snapshot(full)
    write_proposal(full)

    # The dry run changes nothing and needs no approval.
    plan = mcp.ok("qfr.ops.rollover_epoch", epoch_id=NEW, dry_run=True)["data"]
    assert plan["problems"] == [] and plan["dry_run"] is True
    assert plan["cancelled_jobs"] == queued
    assert (plan["from_epoch"], plan["to_epoch"]) == ("small_test", NEW)
    assert plan["research_cutoff"] == "2012-05-31"  # the old W2's end
    assert plan["windows"]["W1"] == {"start": "2012-07-02", "end": "2012-09-07"}
    assert sum(plan["restart"].values()) == len(in_flight)
    assert plan["remeasure_jobs"] == 1
    unchanged(before, eval_snapshot(rig) | other_snapshot(full))

    # The rollover needs the owner's approval naming the epoch.
    assert "APPROVAL_REQUIRED" in mcp.error("qfr.ops.rollover_epoch", epoch_id=NEW)
    code = rollover_code(NEW)
    assert code == "R-epoch_002"
    refused = mcp.error(
        "qfr.approval.record", decision="rollover_epoch", epoch_id=NEW,
        owner_confirmation="Yes, roll it over.", rationale="W1 burn meter is red.",
    )  # fmt: skip
    assert "SHORT_CODE_MISSING" in refused and code in refused
    approval = mcp.ok(
        "qfr.approval.record", decision="rollover_epoch", epoch_id=NEW,
        owner_confirmation=f"ROLLOVER {code}", rationale="W1 burn meter is red.",
    )["data"]  # fmt: skip
    approval_id = approval["approval_id"]
    applied = mcp.ok("qfr.ops.rollover_epoch", epoch_id=NEW, approval_id=approval_id)["data"]
    assert applied["dry_run"] is False and applied["approval_id"] == approval_id
    assert applied["restarted_versions"] == len(in_flight)
    assert applied["remeasure_jobs"] == 1
    assert applied["refingerprint_jobs"] == 4 - len(in_flight)
    assert any("data-build --zones research" in step for step in applied["next_steps"])
    # A second rollover to the same epoch is refused.
    again = mcp.error("qfr.ops.rollover_epoch", epoch_id=NEW, approval_id=approval_id)
    assert "EPOCH_ACTIVE" in again

    epochs = {
        r.epoch_id: r
        for r in rig.db.rows(
            "SELECT epoch_id, status, previous_epoch_id, approval_id, rollover FROM eval.epochs"
        )
    }
    assert epochs["small_test"].status == "retired"
    new = epochs[NEW]
    assert (new.status, new.previous_epoch_id) == ("active", "small_test")
    assert str(new.approval_id) == approval_id and new.rollover["to_epoch"] == NEW
    assert not rig.db.rows(
        "SELECT 1 FROM eval.queue_jobs WHERE epoch_id = 'small_test' AND state = 'queued'"
    )
    for version in in_flight:
        assert state(rig, version) == "Discovered"

    # The new epoch runs: restarts measured again, admitted versions fingerprinted on
    # the new W0, the seed re-measured on the new W1.
    full.settle(6)
    for version in in_flight:
        assert rig.db.rows(
            "SELECT 1 FROM eval.official_records WHERE version_id = :v AND epoch_id = :e "
            "AND stage = 'screening'",
            v=version,
            e=NEW,
        )
    new_fingerprints = {
        r.version_id: r.dates_sha256
        for r in rig.db.rows(
            "SELECT version_id, dates_sha256 FROM eval.fingerprints WHERE epoch_id = :e", e=NEW
        )
    }
    # Fingerprint dates are drawn again from the new W0.
    assert set(old_fingerprints) | {late} <= set(new_fingerprints)
    assert all(new_fingerprints[v] != old for v, old in old_fingerprints.items())
    [remeasured] = rig.db.rows(
        "SELECT record_id, version_id, metrics FROM eval.official_records WHERE stage = 'remeasure'"
    )
    assert remeasured.version_id == seed
    assert not rig.db.rows(
        "SELECT 1 FROM eval.trial_ledger WHERE epoch_id = :e AND version_id = :v", e=NEW, v=seed
    )
    members = rig.worker.library_members(rig.db.conn, uuid7(), NEW)
    assert [m.version_id for m in members] == [str(seed)]
    burn = rig.db.rows("SELECT window_name FROM eval.burn_meters WHERE epoch_id = :e", e=NEW)
    assert sorted(r.window_name for r in burn) == ["W1", "W2", "W3"]

    # Nothing made before the rollover changed, and every link still resolves.
    unchanged(before, eval_snapshot(rig) | other_snapshot(full))
    links_resolve(rig, "small_test")
    links_resolve(rig, NEW)
    assert {r.record_id for r in old_records} <= {
        r.record_id
        for r in rig.db.rows(
            "SELECT record_id FROM eval.official_records WHERE epoch_id = 'small_test'"
        )
    }
    # EVL-04 still holds for a record of the retired epoch.
    evaluator = Evaluator(rig.env, InlineRunner(), MarketCache(rig.env.full_snapshot_dir))
    w1 = next(r for r in old_records if r.stage == "w1")
    for record_id in (w1.record_id, remeasured.record_id):
        result = reproduce(rig.db, rig.env, eval_config(rig.env.config_dir), record_id, evaluator)
        assert result["match"] is True, result
    # The research view: the evaluator's own record of the cutoff the owner rebuilds at.
    assert new.rollover["research_cutoff"] == "2012-05-31"


def test_a_job_running_across_the_rollover_writes_nothing(full):
    rig = full.eval
    version = publish(full, "momentum", "Mean($close, 5) / Mean($close, 20) - 1")
    rig.scheduler.tick()
    with rig.db.transaction(lock=False) as conn:
        job = queue.claim(conn, "test-worker", rig.clock.now())
    assert job is not None and job.kind == "fingerprint" and job.epoch_id == "small_test"
    write_proposal(full)
    with rig.db.transaction() as conn:
        rollover.rollover_from_file(
            conn, rig.tmp_path / "epochs", rig.env.full_snapshot_dir, NEW, "owner",
            uuid7(), "r", rig.clock.now(), dry_run=False,
        )  # fmt: skip
    rig.worker._fingerprint(job)  # the worker finishes its computation after the rollover
    assert (
        rig.db.scalar(
            "SELECT state FROM eval.queue_jobs WHERE queue_job_id = :j", j=job.queue_job_id
        )
        == "cancelled"
    )
    assert not rig.db.rows("SELECT 1 FROM eval.fingerprints WHERE epoch_id = 'small_test'")
    # The version restarted in the new epoch and is fingerprinted there.
    full.settle()
    assert rig.db.rows(
        "SELECT 1 FROM eval.fingerprints WHERE version_id = :v AND epoch_id = :e",
        v=version,
        e=NEW,
    )
