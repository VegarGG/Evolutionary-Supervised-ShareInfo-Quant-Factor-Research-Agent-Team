"""Evaluator-only stock intake allocations, with explicit deferral and expiry.

Pilot feedback reservations stay in the existing all-version ledger; stock
capacity quotas must never be silently applied to the pilot.
"""

from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from psycopg import Connection
from psycopg.types.json import Jsonb

from qfr_eval.release.models import QuotaDecision, QuotaSubject, StockReleasePolicy
from qfr_eval.scheduler.dedup import digest


def _next_capacity(
    conn: Connection, subject: QuotaSubject, policy: StockReleasePolicy, at: datetime
) -> tuple[bool, datetime | None]:
    day = at.replace(hour=0, minute=0, second=0, microsecond=0)
    week = day - timedelta(days=day.weekday())
    quota = policy.quotas
    rules: list[tuple[str, list[object], int, timedelta | None, datetime | None]]
    # Each tuple is a fixed SQL predicate, its parameters, cap and reset rule.
    # Rolling scopes exclude their left boundary; UTC calendar scopes include it.
    if subject.stage == "w1":
        rules = [
            (
                "program_id=%s AND family_id=%s AND stage='w1' AND admitted_at>%s",
                [subject.program_id, subject.family_id, at - timedelta(days=1)],
                quota.family_w1_per_24h,
                timedelta(days=1),
                None,
            ),
            (
                "program_id=%s AND stage='w1' AND admitted_at>=%s",
                [subject.program_id, day],
                quota.program_w1_per_day,
                None,
                day + timedelta(days=1),
            ),
            (
                "stage='w1' AND admitted_at>=%s",
                [day],
                quota.global_w1_per_day,
                None,
                day + timedelta(days=1),
            ),
        ]
    else:
        rules = [
            (
                "program_id=%s AND family_id=%s AND stage='w2' AND admitted_at>%s",
                [subject.program_id, subject.family_id, at - timedelta(days=7)],
                quota.family_w2_per_7d,
                timedelta(days=7),
                None,
            ),
            (
                "program_id=%s AND stage='w2' AND admitted_at>=%s",
                [subject.program_id, week],
                quota.program_w2_per_week,
                None,
                week + timedelta(days=7),
            ),
            (
                "epoch_id=%s AND stage='w2'",
                [subject.epoch_id],
                quota.global_w2_per_epoch,
                None,
                None,
            ),
        ]
    blocked: list[datetime | None] = []
    for predicate, params, cap, rolling, reset in rules:
        where = predicate + " AND admitted_at<=%s"
        params = [*params, at]
        count = conn.execute(
            "SELECT count(*) FROM eval.quota_usage WHERE " + where, params
        ).fetchone()
        assert count is not None
        if count[0] < cap:
            continue
        if rolling:
            oldest = conn.execute(
                "SELECT admitted_at FROM eval.quota_usage WHERE "
                + where
                + " ORDER BY admitted_at,id OFFSET %s LIMIT 1",
                [*params, count[0] - cap],
            ).fetchone()
            assert oldest is not None
            blocked.append(oldest[0] + rolling)
        else:
            blocked.append(reset)
    if not blocked:
        return True, None
    return False, max(x for x in blocked if x is not None) if None not in blocked else None


def admit(
    conn: Connection,
    subject: QuotaSubject,
    policy: StockReleasePolicy,
    *,
    principal: str,
    request_id: UUID,
    control_time: datetime | None = None,
) -> QuotaDecision:
    """Call inside the evaluator dispatch transaction, before enqueueing work.

    Production uses PostgreSQL time. Explicit control_time is for declared
    deterministic scheduling tests, never exposed to research or an MCP client.
    """
    if not isinstance(policy, StockReleasePolicy):
        raise ValueError("stock intake quota cannot be applied to the pilot")
    if not principal.strip() or (control_time is not None and control_time.utcoffset() is None):
        raise ValueError("principal and aware control time required")
    key = digest(
        {
            "program": subject.program_id,
            "epoch": subject.epoch_id,
            "stage": subject.stage,
            "artifact": str(subject.artifact_version_id),
        }
    )
    identity = uuid5(NAMESPACE_URL, "qfr-stock-quota:" + key)
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(72460405)")
        active = conn.execute(
            "SELECT payload FROM eval.release_policies WHERE sha256=%s AND status='active'",
            [policy.sha256],
        ).fetchone()
        if active is None or StockReleasePolicy.model_validate(active[0]) != policy:
            raise ValueError("quota requires its active frozen policy")
        now = control_time
        if now is None:
            clock = conn.execute("SELECT clock_timestamp()").fetchone()
            assert clock is not None
            now = clock[0]
        now = now.astimezone(UTC)
        existing = conn.execute(
            "SELECT subject_sha256,policy_sha256,first_seen_at,state,admission_id,"
            "next_eligible_at FROM eval.quota_requests WHERE id=%s FOR UPDATE",
            [identity],
        ).fetchone()
        first = now
        if existing:
            if existing[0] != subject.sha256 or existing[1] != policy.sha256:
                raise ValueError("quota request conflicts with its frozen target")
            first = existing[2]
            if now < first:
                raise ValueError("quota control time precedes first observation")
            if existing[3] != "deferred":
                return QuotaDecision(
                    schema_version="1",
                    subject_sha256=subject.sha256,
                    state=existing[3],
                    reason=None if existing[3] == "admitted" else "QUOTA_EXPIRED",
                    admission_id=existing[4],
                    next_eligible_at=None,
                )
        expired = existing is not None and now >= first + timedelta(
            days=policy.quotas.deferral_expiry_days
        )
        allowed, next_at = (False, None) if expired else _next_capacity(conn, subject, policy, now)
        allocated = None
        if allowed:
            allocated = uuid4()
            conn.execute(
                "INSERT INTO eval.quota_usage(id,payload,created_by,request_id,subject_sha256,"
                "policy_sha256,artifact_version_id,program_id,family_id,epoch_id,"
                "stage,admitted_at) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                [
                    allocated,
                    Jsonb(subject.model_dump(mode="json")),
                    principal,
                    request_id,
                    subject.sha256,
                    policy.sha256,
                    subject.artifact_version_id,
                    subject.program_id,
                    subject.family_id,
                    subject.epoch_id,
                    subject.stage,
                    now,
                ],
            )
        state = "expired" if expired else "admitted" if allowed else "deferred"
        if existing:
            conn.execute(
                "UPDATE eval.quota_requests SET state=%s,admission_id=%s,next_eligible_at=%s,"
                "created_by=%s,request_id=%s WHERE id=%s",
                [state, allocated, next_at, principal, request_id, identity],
            )
        else:
            conn.execute(
                "INSERT INTO eval.quota_requests(id,payload,created_by,request_id,subject_sha256,"
                "policy_sha256,first_seen_at,state,admission_id,next_eligible_at) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                [
                    identity,
                    Jsonb(subject.model_dump(mode="json")),
                    principal,
                    request_id,
                    subject.sha256,
                    policy.sha256,
                    first,
                    state,
                    allocated,
                    next_at,
                ],
            )
        return QuotaDecision.model_validate(
            dict(
                schema_version="1",
                subject_sha256=subject.sha256,
                state=state,
                reason="QUOTA_EXPIRED" if expired else None if allowed else "QUOTA_DEFERRED",
                admission_id=allocated,
                next_eligible_at=next_at,
            )
        )
