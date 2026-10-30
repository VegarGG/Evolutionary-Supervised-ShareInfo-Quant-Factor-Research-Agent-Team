"""Private burn accounting derived from immutable attempts and publications.

No clock, reset, public field or confirmation query is created by this reader.
A red stock meter is advisory; it never silently discards an official attempt.
"""

from typing import Literal

from psycopg import Connection

from qfr_eval.release.models import BurnSummary, PilotReleasePolicy, StockReleasePolicy
from qfr_eval.release.store import active_policy


def summarize(
    conn: Connection,
    policy_hash: str,
    epoch: str,
    window: Literal["development", "validation", "W1", "W2"],
) -> BurnSummary:
    policy = active_policy(conn, policy_hash)
    if (isinstance(policy, PilotReleasePolicy) and window not in ("development", "validation")) or (
        isinstance(policy, StockReleasePolicy) and window not in ("W1", "W2")
    ):
        raise ValueError("burn window differs from release profile")
    trials = conn.execute(
        "SELECT count(*) FROM eval.trial_ledger t JOIN eval.official_records o "
        "ON o.id=t.official_record_id WHERE "
        "coalesce(o.payload->'record'->>'epoch_id',o.protocol_version)=%s "
        "AND coalesce(o.payload->'record'->>'window',"
        "o.payload->'record'->'request'->>'window')=%s",
        [epoch, window],
    ).fetchone()
    stage = {"development": "screening", "validation": "pilot", "W1": "w1", "W2": "w2"}[window]
    values = conn.execute(
        "SELECT coalesce(sum(p.numeric_values),0) FROM eval.release_publications p "
        "JOIN eval.release_queue q ON q.id=p.queue_id WHERE q.epoch_id=%s "
        "AND q.policy_sha256=%s AND q.payload->>'stage'=%s",
        [epoch, policy_hash, stage],
    ).fetchone()
    assert trials is not None and values is not None
    count, used, budget = int(trials[0]), 0, None
    status: Literal["green", "amber", "red", "unthresholded"] = "unthresholded"
    if isinstance(policy, StockReleasePolicy):
        queries = conn.execute(
            "SELECT count(*) FROM eval.quota_usage WHERE epoch_id=%s AND stage=%s",
            [epoch, stage],
        ).fetchone()
        assert queries is not None
        used = int(queries[0])
        quota = policy.quotas
        if window == "W1":
            status = (
                "red"
                if count >= quota.burn_w1_red
                else "amber"
                if count >= quota.burn_w1_amber
                else "green"
            )
        else:
            budget = quota.global_w2_per_epoch
            status = "red" if used >= budget else "green"
    else:
        # The pilot budget is per lineage/generation, never a fabricated global
        # allowance. Count unique reserved versions represented in this epoch.
        queries = conn.execute(
            "SELECT count(*) FROM (SELECT DISTINCT r.program_id,r.generation_id,"
            "r.artifact_version_id FROM eval.feedback_reservations r "
            "JOIN eval.official_records o ON o.artifact_version_id=r.artifact_version_id "
            "WHERE coalesce(o.payload->'record'->>'epoch_id',o.protocol_version)=%s "
            "AND coalesce(o.payload->'request'->>'program_id',"
            "o.payload->'record'->'request'->>'program_id')=r.program_id "
            "AND coalesce(o.payload->'request'->>'generation_id',"
            "o.payload->'record'->'request'->>'generation_id')=r.generation_id) versions",
            [epoch],
        ).fetchone()
        assert queries is not None
        used = int(queries[0])
    return BurnSummary(
        schema_version="1",
        epoch_id=epoch,
        window=window,
        trials=count,
        released_values=int(values[0]),
        queries_used=used,
        query_budget=budget,
        status=status,
    )
