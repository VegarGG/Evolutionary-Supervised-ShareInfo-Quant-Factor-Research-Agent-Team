"""P3.5 real-database scheduling and quotas with declared synthetic clocks/data.

Unsigned preparations never establish a released/financial acceptance result.
"""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb
from qfr_core.contracts.reports import MetricValue
from qfr_eval.release.models import (
    PilotReleasePolicy,
    QuotaSubject,
    StockReleasePolicy,
    StockReleaseRecord,
)
from qfr_eval.release.quotas import admit
from qfr_eval.release.store import (
    activate_policy,
    active_policy,
    create_policy,
    enqueue_source,
    locked_ready,
)

pytestmark = pytest.mark.database
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def control_time(eval_connect):
    # Separate tests' UTC/global windows without deleting immutable allocations.
    with eval_connect() as conn:
        at = conn.execute(
            "SELECT coalesce(max(admitted_at),'2020-01-01'::timestamptz)+interval '365 days' "
            "FROM eval.quota_usage"
        ).fetchone()[0]
        return at.astimezone(UTC).replace(hour=12, minute=0, second=0, microsecond=0)


def stock_policy(conn, **quota_changes):
    value = json.loads((ROOT / "configs/evaluation/release_stock_v1.json").read_bytes())
    value["policy_id"] = "synthetic-stock-" + str(uuid4())
    value["quotas"].update(quota_changes)
    policy = StockReleasePolicy.model_validate(value)
    create_policy(conn, policy, principal="synthetic-owner", request_id=uuid4())
    activate_policy(conn, policy.sha256, principal="synthetic-owner", request_id=uuid4())
    return policy


def subject(*, program=None, family=None, epoch=None, stage="w1", artifact=None):
    return QuotaSubject(
        schema_version="1",
        profile="stock_daily_v1",
        artifact_version_id=artifact or uuid4(),
        program_id=program or str(uuid4()),
        family_id=family or str(uuid4()),
        epoch_id=epoch or str(uuid4()),
        stage=stage,
    )


def allocate(conn, item, policy, at):
    return admit(
        conn, item, policy, principal="synthetic-dispatcher", request_id=uuid4(), control_time=at
    )


def store_stock_record(conn, item, *, completed_at=None):
    # Explicit fixture clocks are never production elapsed-batch evidence.
    completed_at = completed_at or datetime.now(UTC)
    body = json.loads(
        (
            ROOT / "packages/qfr_eval/src/qfr_eval/private_contracts/StockReleaseRecord.valid.json"
        ).read_bytes()
    )
    identity = uuid4()
    body.update(
        record_id=str(identity),
        program_id=item.program_id,
        family_id=item.family_id,
        economic_lineage_id=item.family_id,
        epoch_id=item.epoch_id,
        window=item.stage.upper(),
        status="complete",
        period_count=20,
        metrics={"rank_ic_mean": MetricValue(value=0.021, missing_reason=None).model_dump()},
        created_at=completed_at.isoformat(),
    )
    body["identity"]["artifact_version_id"] = str(item.artifact_version_id)
    record = StockReleaseRecord.model_validate(body)
    trial = uuid4()
    with conn.transaction():
        conn.execute(
            "INSERT INTO eval.official_records(id,payload,created_by,request_id,"
            "artifact_version_id,"
            "content_hash,protocol_version,dataset_version_id,evaluator_version,"
            "trial_id,created_at) "
            "VALUES(%s,%s,'synthetic-release-fixture',%s,%s,%s,%s,%s,%s,%s,%s)",
            [
                identity,
                Jsonb({"record": record.model_dump(mode="json")}),
                uuid4(),
                item.artifact_version_id,
                record.identity.content_hash,
                record.identity.protocol_version,
                record.identity.dataset_version_id,
                record.identity.evaluator_version,
                trial,
                completed_at,
            ],
        )
        conn.execute(
            "INSERT INTO eval.trial_ledger(id,payload,created_by,request_id,official_record_id) "
            "VALUES(%s,%s,'synthetic-release-fixture',%s,%s)",
            [
                trial,
                Jsonb(
                    {"fixture": "synthetic_stock_release_adapter", "sampling_unit": "trading_date"}
                ),
                uuid4(),
                identity,
            ],
        )
    return record


def test_policy_activation_hash_freeze_and_no_implicit_pilot_configuration(eval_connect):
    with eval_connect() as conn:
        policy = stock_policy(conn)
        assert active_policy(conn, policy.sha256) == policy
        assert (
            activate_policy(conn, policy.sha256, principal="synthetic-owner", request_id=uuid4())
            == policy.sha256
        )
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="immutable"):
            conn.execute(
                "UPDATE eval.release_policies SET payload='{}' WHERE sha256=%s", [policy.sha256]
            )
        with pytest.raises(ValueError, match="different content"):
            create_policy(
                conn,
                policy.model_copy(update={"ladder_eta": 0.01}),
                principal="synthetic-owner",
                request_id=uuid4(),
            )
        pilot = PilotReleasePolicy.model_validate_json(
            (ROOT / "configs/evaluation/release_pilot_v1.json").read_bytes()
        )
        bad = pilot.model_copy(
            update={"protocol_sha256": "f" * 64, "policy_id": "synthetic-invalid-" + str(uuid4())}
        )
        create_policy(conn, bad, principal="synthetic-owner", request_id=uuid4())
        with pytest.raises(ValueError, match="active frozen protocol"):
            activate_policy(conn, bad.sha256, principal="synthetic-owner", request_id=uuid4())


def test_rel_03_family_rolling_window_and_no_reset_by_retry(eval_connect, control_time):
    with eval_connect() as conn:
        policy = stock_policy(conn)
        first = subject()
        items = [first] + [
            subject(program=first.program_id, family=first.family_id, epoch=first.epoch_id)
            for _ in range(3)
        ]
        results = [allocate(conn, item, policy, control_time) for item in items]
        assert [x.state for x in results] == ["admitted"] * 3 + ["deferred"]
        assert (
            allocate(conn, items[0], policy, control_time).admission_id == results[0].admission_id
        )
        assert results[-1].next_eligible_at == control_time + timedelta(days=1)
        assert (
            allocate(
                conn,
                items[-1],
                policy,
                control_time + timedelta(days=1) - timedelta(microseconds=1),
            ).state
            == "deferred"
        )
        assert (
            allocate(conn, items[-1], policy, control_time + timedelta(days=1)).state == "admitted"
        )
        with pytest.raises(ValueError, match="frozen target"):
            allocate(conn, first.model_copy(update={"family_id": "renamed"}), policy, control_time)


@pytest.mark.parametrize("cap", ["program_w1_per_day", "global_w1_per_day"])
def test_rel_03_utc_day_program_and_global_caps(eval_connect, control_time, cap):
    with eval_connect() as conn:
        policy = stock_policy(conn, **{cap: 2})
        same_program = str(uuid4())
        items = [
            subject(program=same_program if cap.startswith("program") else None) for _ in range(3)
        ]
        assert [allocate(conn, item, policy, control_time).state for item in items] == [
            "admitted",
            "admitted",
            "deferred",
        ]
        midnight = control_time.replace(hour=0) + timedelta(days=1)
        assert allocate(conn, items[-1], policy, midnight).state == "admitted"


def test_rel_03_weekly_family_program_epoch_budget_and_seven_day_expiry(eval_connect, control_time):
    with eval_connect() as conn:
        policy = stock_policy(conn, global_w2_per_epoch=2)
        one = subject(stage="w2")
        family = subject(
            stage="w2", program=one.program_id, family=one.family_id, epoch=one.epoch_id
        )
        global_item = subject(stage="w2", epoch=one.epoch_id)
        third = subject(stage="w2", epoch=one.epoch_id)
        assert allocate(conn, one, policy, control_time).state == "admitted"
        blocked = allocate(conn, family, policy, control_time)
        assert blocked.next_eligible_at == control_time + timedelta(days=7)
        assert allocate(conn, global_item, policy, control_time).state == "admitted"
        assert allocate(conn, third, policy, control_time).next_eligible_at is None
        expired = allocate(conn, third, policy, control_time + timedelta(days=7))
        assert expired.state == "expired" and expired.reason == "QUOTA_EXPIRED"
        assert expired.admission_id is None
        # An expired request never becomes admitted even if calendar time moves.
        assert allocate(conn, third, policy, control_time + timedelta(days=8)) == expired


def test_rel_03_weekly_program_cap_uses_monday_utc(eval_connect, control_time):
    with eval_connect() as conn:
        policy = stock_policy(conn, program_w2_per_week=1)
        first = subject(stage="w2")
        second = subject(stage="w2", program=first.program_id)
        assert allocate(conn, first, policy, control_time).state == "admitted"
        blocked = allocate(conn, second, policy, control_time)
        monday = (control_time - timedelta(days=control_time.weekday())).replace(
            hour=0
        ) + timedelta(days=7)
        assert blocked.next_eligible_at == monday
        assert allocate(conn, second, policy, monday).state == "admitted"


def test_concurrent_quota_claims_do_not_overspend_and_rollback_is_atomic(
    eval_connect, control_time
):
    with eval_connect() as conn:
        policy = stock_policy(conn, family_w1_per_24h=1)
    first = subject()
    second = subject(program=first.program_id, family=first.family_id, epoch=first.epoch_id)

    def run(item):
        with eval_connect() as conn:
            return allocate(conn, item, policy, control_time)

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(run, [first, second]))
    assert sorted(x.state for x in results) == ["admitted", "deferred"]
    with eval_connect() as conn:
        other = subject()
        request = uuid4()
        with pytest.raises(RuntimeError), conn.transaction():
            admit(
                conn,
                other,
                policy,
                principal="synthetic-worker",
                request_id=request,
                control_time=control_time,
            )
            raise RuntimeError("no enqueue, no allocation")
        assert conn.execute(
            "SELECT count(*) FROM eval.quota_usage WHERE subject_sha256=%s", [other.sha256]
        ).fetchone() == (0,)
        assert conn.execute(
            "SELECT count(*) FROM eval.events WHERE request_id=%s", [request]
        ).fetchone() == (0,)


def test_rel_02_source_is_durable_deduplicated_and_never_visible_unsigned(eval_connect):
    with eval_connect() as conn:
        policy = stock_policy(conn)
        item = subject()
        record = store_stock_record(conn, item)
        first = enqueue_source(
            conn,
            "official_record",
            record.record_id,
            policy.sha256,
            principal="release-worker",
            request_id=uuid4(),
        )
        assert (
            enqueue_source(
                conn,
                "official_record",
                record.record_id,
                policy.sha256,
                principal="release-worker",
                request_id=uuid4(),
            )
            == first
        )
        ready = conn.execute(
            "SELECT eligible_at FROM eval.release_queue WHERE id=%s", [first]
        ).fetchone()[0]
    with eval_connect() as restarted:
        with restarted.transaction():
            assert first not in {
                x[0]
                for x in locked_ready(
                    restarted,
                    limit=100,
                    control_time=ready - timedelta(microseconds=1),
                    policy_hash=policy.sha256,
                    program_id=item.program_id,
                )
            }
        with restarted.transaction():
            # Keep immutable evidence from earlier runs. Scope this fixture's
            # cursor so other programs cannot fill its bounded page.
            assert first in {
                x[0]
                for x in locked_ready(
                    restarted,
                    limit=100,
                    control_time=ready,
                    policy_hash=policy.sha256,
                    program_id=item.program_id,
                )
            }
        assert restarted.execute(
            "SELECT count(*) FROM eval.released_reports WHERE artifact_version_id=%s",
            [item.artifact_version_id],
        ).fetchone() == (0,)
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="immutable"):
            restarted.execute(
                "UPDATE eval.release_queue SET eligible_at=clock_timestamp() WHERE id=%s", [first]
            )
        with pytest.raises(psycopg.errors.CheckViolation):
            restarted.execute(
                "UPDATE eval.release_queue SET state='published' WHERE id=%s", [first]
            )
    with eval_connect("feedback_ro") as reader:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            reader.execute("SELECT * FROM eval.release_queue")


def test_quota_usage_and_source_history_are_insert_only(eval_connect, control_time):
    with eval_connect() as conn:
        policy = stock_policy(conn)
        result = allocate(conn, subject(), policy, control_time)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("DELETE FROM eval.quota_usage WHERE id=%s", [result.admission_id])
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="immutable"):
            conn.execute(
                "UPDATE eval.quota_requests SET state='deferred',admission_id=NULL "
                "WHERE admission_id=%s",
                [result.admission_id],
            )


def test_release_request_and_queue_history_survives_owner_delete_and_truncate(
    eval_connect, control_time
):
    with eval_connect() as conn:
        policy = stock_policy(conn)
        item = subject()
        admission = allocate(conn, item, policy, control_time)
        record = store_stock_record(conn, item)
        queue = enqueue_source(
            conn,
            "official_record",
            record.record_id,
            policy.sha256,
            principal="synthetic-worker",
            request_id=uuid4(),
        )
        request = conn.execute(
            "SELECT id FROM eval.quota_requests WHERE admission_id=%s", [admission.admission_id]
        ).fetchone()[0]
    from psycopg import sql

    with eval_connect("postgres") as owner:
        for table, identity in [("quota_requests", request), ("release_queue", queue)]:
            with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="insert-only"):
                owner.execute(
                    sql.SQL("DELETE FROM eval.{} WHERE id=%s").format(sql.Identifier(table)),
                    [identity],
                )
            with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="insert-only"):
                owner.execute(sql.SQL("TRUNCATE eval.{} CASCADE").format(sql.Identifier(table)))
