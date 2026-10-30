"""eval-scheduler (P3.2): pull-only intake, schema and kind checks, exact and behavioral
dedup, quotas with deferral and expiry, strategies held, and fair enqueueing."""

from pathlib import Path

import pytest
from qfr_eval import queue
from qfr_eval.configs import activate_version, create_version
from sqlalchemy import text

from tests.eval.stack_rig import eval_apps
from tests.registry_rig import factor_manifest, research_ids, strategy_manifest

pytestmark = pytest.mark.postgres


def publish(rig, name, expression, **kw):
    response = rig.registry.publish(factor_manifest(name, expression, **kw))
    assert response.status_code == 201, response.text
    return response.json()["version"]


def intake(rig, version_id):
    return rig.db.rows(
        "SELECT state, reason_code, duplicate_of, similarity, hold_reason FROM eval.intake "
        "WHERE version_id = :v",
        v=version_id,
    )[0]


def evaluated(rig, version_id):
    """Runs, official records, ledger rows and evaluate jobs for one version."""
    return {
        "runs": rig.db.scalar("SELECT count(*) FROM eval.runs WHERE version_id = :v", v=version_id),
        "trials": rig.db.scalar(
            "SELECT count(*) FROM eval.trial_ledger WHERE version_id = :v", v=version_id
        ),
        "records": rig.db.scalar(
            "SELECT count(*) FROM eval.official_records WHERE version_id = :v", v=version_id
        ),
        "jobs": rig.db.scalar(
            "SELECT count(*) FROM eval.queue_jobs WHERE version_id = :v AND kind = 'evaluate'",
            v=version_id,
        ),
    }


NOTHING = {"runs": 0, "trials": 0, "records": 0, "jobs": 0}


def test_evl_01_discovery_is_since_seq_polling_with_no_inbound_trigger(rig):
    admin, feedback = eval_apps(rig)
    for app in (admin, feedback):
        writes = {
            (method, route.path)
            for route in app.routes
            for method in getattr(route, "methods", set()) - {"GET", "HEAD"}
        }
        # Only the owner's configuration routes write; nothing enqueues or evaluates.
        assert all(
            path.startswith(("/v1/protocols", "/v1/policies", "/v1/quotas")) for _, path in writes
        ), writes
    first = publish(rig, "first", "Mean($close, 5) / Mean($close, 20) - 1")
    rig.scheduler.tick()
    cursor = rig.db.scalar("SELECT last_published_seq FROM eval.intake_cursor")
    assert cursor == first["published_seq"]
    second = publish(rig, "second", "Corr($close, $volume, 20)")
    rig.scheduler.tick()
    assert (
        rig.db.scalar("SELECT last_published_seq FROM eval.intake_cursor")
        == second["published_seq"]
    )
    pulled = rig.db.rows("SELECT version_id FROM eval.intake ORDER BY published_seq")
    assert [str(r.version_id) for r in pulled] == [first["version_id"], second["version_id"]]


def test_evl_05_exact_and_behavioral_duplicates_are_never_evaluated(rig):
    original = publish(rig, "ratio", "Mean($close, 5) / Mean($close, 20) - 1")
    exact = publish(rig, "ratio_again", "Mean($close,5)/Mean($close,20)-1")
    near = publish(rig, "ratio_shifted", "Mean($close, 5) / Mean($close, 20)")
    rig.cycle()
    assert intake(rig, original["version_id"]).state in ("W1Evaluated", "W1GateFailed")
    same = intake(rig, exact["version_id"])
    assert (same.state, same.reason_code) == ("Duplicate", "DUPLICATE_OF")
    assert str(same.duplicate_of) == original["version_id"]
    behavioral = intake(rig, near["version_id"])
    assert (behavioral.state, behavioral.reason_code) == ("Duplicate", "NEAR_DUPLICATE_OF")
    assert behavioral.similarity >= 0.95
    for version in (exact, near):
        assert evaluated(rig, version["version_id"]) == NOTHING
    assert rig.db.scalar("SELECT count(*) FROM eval.trial_ledger") == 1
    rig.clock.advance(hours=6)
    rig.release.tick()
    released = {
        r.version_id: r.report["content"]
        for r in rig.db.rows(
            "SELECT version_id, report FROM eval.released_reports WHERE report_type = 'intake'"
        )
    }
    assert {str(k) for k, v in released.items() if v["status"] == "DUPLICATE"} == {
        exact["version_id"], near["version_id"],
    }  # fmt: skip


def test_schema_and_kind_checks_reject_without_evaluating(rig):
    bad = publish(rig, "bad_schema", "Pct($close, 5)")
    wrong = publish(rig, "wrong_kind", "Pct($close, 10)")
    original = rig.scheduler.registry.versions

    def tampered(since, limit):
        items, next_seq = original(since, limit)
        for item in items:
            if item["version_id"] == bad["version_id"]:
                item["manifest"] = {k: v for k, v in item["manifest"].items() if k != "declared"}
            if item["version_id"] == wrong["version_id"]:
                item["kind"] = "strategy"
        return items, next_seq

    rig.scheduler.registry.versions = tampered
    rig.cycle()
    assert intake(rig, bad["version_id"]).reason_code == "SCHEMA_INVALID"
    assert intake(rig, wrong["version_id"]).reason_code == "KIND_UNSUPPORTED"
    assert evaluated(rig, bad["version_id"]) == NOTHING == evaluated(rig, wrong["version_id"])


def test_strategies_are_held_until_the_strategy_plugin_exists(rig):
    factor = publish(rig, "component", "Pct($close, 20)")
    response = rig.registry.publish(strategy_manifest([(factor["version_id"], 1, 1.0)]))
    assert response.status_code == 201, response.text
    strategy = response.json()["version"]
    rig.cycle()
    held = intake(rig, strategy["version_id"])
    assert held.state == "Held" and "Phase 6" in held.hold_reason
    assert evaluated(rig, strategy["version_id"]) == NOTHING


FAMILY = [
    ("family_momentum", "Mean($close, 5) / Mean($close, 20) - 1"),
    ("family_momentum", "Corr($close, $volume, 20)"),
    ("family_momentum", "Std(Pct($close, 1), 20)"),
    ("family_momentum", "TsRank($volume, 10)"),
]


def publish_family(rig):
    ids = research_ids()  # one program, so the family may hold all four versions
    first = publish(rig, *FAMILY[0], ids=ids)
    versions = [first]
    for name, expression in FAMILY[1:]:
        versions.append(publish(rig, name, expression, family_id=first["family_id"], ids=ids))
    return versions


def test_rel_03_quota_defers_excess_and_admits_when_room_opens(rig):
    versions = publish_family(rig)
    rig.cycle()
    states = [intake(rig, v["version_id"]).state for v in versions]
    assert states[:3] != ["Deferred"] * 3 and "Deferred" not in states[:3]
    deferred = intake(rig, versions[3]["version_id"])
    assert (deferred.state, deferred.reason_code) == ("Deferred", "QUOTA_DEFERRED")
    assert evaluated(rig, versions[3]["version_id"]) == NOTHING
    family_usage = rig.db.scalar(
        "SELECT count(*) FROM eval.quota_usage WHERE scope = 'family' AND key = :f",
        f=versions[0]["family_id"],
    )
    assert family_usage == 3  # consumed at admission
    rig.clock.advance(hours=24, minutes=1)  # the rolling 24-hour window has room again
    rig.cycle()
    assert intake(rig, versions[3]["version_id"]).state in ("W1Evaluated", "W1GateFailed")


def test_rel_03_deferrals_expire_after_seven_days(rig):
    rig.scheduler.tick()
    raw = (
        Path("configs/quotas/default_v1.yaml")
        .read_text()
        .replace("version: '1'", "version: '2'")
        .replace("w1_hours: 24", "w1_hours: 240")
    )
    with rig.db.transaction() as conn:
        created, _ = create_version(conn, "quotas", raw, "test", "r", rig.clock.now())
        activate_version(conn, "quotas", created.id, created.version, "test", None, "r",
                         rig.clock.now())  # fmt: skip
    versions = publish_family(rig)
    rig.cycle()
    last = versions[3]["version_id"]
    assert intake(rig, last).state == "Deferred"
    rig.clock.advance(days=6, hours=23)
    rig.scheduler.tick()
    assert intake(rig, last).state == "Deferred"
    rig.clock.advance(hours=1)
    rig.scheduler.tick()
    expired = intake(rig, last)
    assert (expired.state, expired.reason_code) == ("IntakeRejected", "QUOTA_EXPIRED")
    assert evaluated(rig, last) == NOTHING
    rig.clock.advance(hours=6)
    rig.release.tick()
    statuses = [
        r.report["content"]["status"]
        for r in rig.db.rows(
            "SELECT report FROM eval.released_reports WHERE version_id = :v ORDER BY release_seq",
            v=last,
        )
    ]
    assert statuses == ["DEFERRED", "FAIL"]


def test_queue_is_fair_round_robin_across_families_and_fingerprints_first(rig):
    from qfr_core.ids import uuid7

    family_a, family_b = uuid7(), uuid7()
    at = rig.clock.now()
    with rig.db.transaction() as conn:
        a = [queue.enqueue(conn, "evaluate", uuid7(), family_a, {}, at) for _ in range(3)]
        b = queue.enqueue(conn, "evaluate", uuid7(), family_b, {}, at)
        f = queue.enqueue(conn, "fingerprint", uuid7(), family_b, {}, at)
        claimed = [queue.claim(conn, "w", at).queue_job_id for _ in range(5)]
        assert queue.claim(conn, "w", at) is None
        assert claimed == [f, a[0], b, a[1], a[2]]
        again = queue.enqueue(conn, "evaluate", rig.db.scalar(
            "SELECT version_id FROM eval.queue_jobs WHERE queue_job_id = :j", j=b), family_b, {},
            at)  # fmt: skip
        assert again is None  # one job per (kind, version)
        conn.execute(text("UPDATE eval.queue_jobs SET locked_at = :t"), {"t": at})
    rig.clock.advance(hours=2)
    with rig.db.transaction() as conn:
        assert queue.requeue_stale(conn, rig.clock.now(), 3600) == 5


def test_library_follows_pool_events(rig):
    from qfr_core.ids import uuid7

    from tests.registry_rig import seed_manifest

    response = rig.registry.publish(seed_manifest("seed_one", "Pct($close, 20)"), role="control")
    assert response.status_code == 201, response.text
    version = response.json()["version"]
    entry = rig.registry.client.post(
        "/v1/pools/factor/entries",
        json={"version_id": version["version_id"], "title": "Seed one", "status": "seed",
              "setup_ref": str(uuid7())},
        headers={"Authorization": "Bearer test-control-token"},
    )  # fmt: skip
    assert entry.status_code == 201, entry.text
    rig.cycle()
    row = rig.db.rows("SELECT status, effective_from FROM eval.library")[0]
    assert row.status == "seed" and row.effective_from is not None
    library_reports = rig.db.rows(
        "SELECT report FROM eval.released_reports WHERE report_type = 'library'"
    )
    assert library_reports == []  # released immediately, but only by the release engine
    rig.release.tick()
    assert (
        rig.db.scalar("SELECT count(*) FROM eval.released_reports WHERE report_type = 'library'")
        == 1
    )
