"""The job monitor and the deliverable assembler (P4.10, PLAN Sections 11.6, 13.3, 13.4).

Deterministic code only. The monitor reads each published version's released reports
from report_cache, decides which tier research can read from them, assembles a
deliverable when the brief's criteria are met, applies the stop conditions (generation
cap, cost cap, wall clock) and schedules the next generation on the charter's cadence:
as soon as the previous generation's feedback is complete, or after `max_wait_hours`.

Research reads the tier from released values with the public gates of the active
protocol card. Released values are rounded and bucketed, so this reading can differ from
the evaluator's official decision near a threshold; the front door confirms every item
against the evaluator's official state when it serves the deliverable (Section 13.4).
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from qfr_core.contracts import (
    Deliverable,
    DeliverableItem,
    DiagnosticFlag,
    ReleasedReport,
    Tier,
)
from qfr_core.correlation import bind
from qfr_core.ids import uuid7
from qfr_core.research_api import DeliverableView
from sqlalchemy import text
from sqlalchemy.engine import Connection

from qfr_research.clients import ServiceRefused, ServiceUnavailable
from qfr_research.db import dumps
from qfr_research.env import ResearchEnv
from qfr_research.feedback import FeedbackSync, reports_for
from qfr_research.jobs import JobService
from qfr_research.queue import enqueue
from qfr_research.store import Ctx, job_event
from qfr_research.traces import export, iteration_history, trace_hash
from qfr_research.workflow import has_open_generation

TIERS: tuple[Tier, ...] = ("w1_pass", "w2_pass", "advanced", "incubated")
RANK = {tier: i for i, tier in enumerate(TIERS)}
# Flags whose presence means a public W1 gate failed (policy flags mirror the gates).
BLOCKING_FLAGS = frozenset(
    {
        DiagnosticFlag.WEAK_SIGNAL,
        DiagnosticFlag.HIGH_TURNOVER,
        DiagnosticFlag.CROWDED_WITH_LIBRARY,
        DiagnosticFlag.SIGN_MISMATCH,
        DiagnosticFlag.LOW_COVERAGE,
    }
)
WATCHING = ("WAITING_FOR_EVALUATION", "DELIVERABLE_READY", "DELIVERED")
# The brief's mode fixes the deliverable kind (Section 11.2); review_and_iterate may
# deliver either kind.
DELIVERABLE_KIND = {
    "new_factors": "factor",
    "improve_factors": "factor",
    "new_strategy": "strategy",
    "improve_strategy": "strategy",
}
COUNTED = ("CLOSED", "FAILED")


@dataclass(frozen=True)
class Reading:
    """What research can read from one version's released reports."""

    version_id: UUID
    candidate_id: UUID
    kind: str
    tier: Tier | None
    failed: bool
    score: float
    w0_score: float
    checks: dict[str, Any]

    def pending_for(self, wanted: Tier) -> bool:
        reached = self.tier is not None and RANK[self.tier] >= RANK[wanted]
        return not reached and not self.failed

    def key(self) -> tuple[float, float, float, str]:
        tier = -1.0 if self.tier is None else float(RANK[self.tier])
        return (-tier, -self.score, -self.w0_score, str(self.version_id))


@dataclass
class TickResult:
    started: list[UUID] = field(default_factory=list)
    deliverables: list[UUID] = field(default_factory=list)
    closed: list[UUID] = field(default_factory=list)


def read_w1(kind: str, sign: int, content: Any, gates: dict[str, Any]) -> dict[str, Any]:
    """The public W1 gate applied to one released W1 report; each check with its value."""
    checks: dict[str, Any] = {}

    def check(name: str, value: float | None, threshold: float, above: bool = True) -> None:
        ok = value is not None and (value >= threshold if above else value <= threshold)
        checks[name] = {"value": value, "threshold": threshold, "passed": bool(ok)}

    flags = sorted(f.value for f in content.flags if f in BLOCKING_FLAGS)
    checks["flags"] = {"value": flags, "passed": not flags}
    checks["coverage_bucket"] = {
        "value": content.coverage_bucket,
        "passed": content.coverage_bucket == "PASS",
    }
    if kind == "factor":
        g = gates["w1_factor"]
        check("rankic_mean", sign * content.rankic_mean, float(g["rankic_min"]))
        check("rankic_ir", sign * content.rankic_ir, float(g["ir_min"]))
        check("top_turnover", content.top_turnover, float(g["turnover_max"]), above=False)
        if content.library_empty:
            checks["library_correlation"] = {"value": None, "passed": True, "vacuous": True}
        else:
            check(
                "library_correlation",
                content.max_library_correlation,
                float(g["library_correlation_max"]),
                above=False,
            )
    else:
        g = gates["w1_strategy"]
        check("strategy_net_sharpe", content.strategy_net_sharpe, float(g["net_sharpe_min"]))
        check("strategy_ir", content.strategy_ir, float(g["ir_min"]))
        if content.strategy_drawdown_bucket is not None:
            check(
                "strategy_drawdown",
                content.strategy_drawdown_bucket,
                float(g["drawdown_max"]),
                above=False,
            )
    return checks


def read_tier(
    version_id: UUID,
    candidate_id: UUID,
    kind: str,
    sign: int,
    reports: list[ReleasedReport],
    gates: dict[str, Any],
    w0_score: float,
) -> Reading:
    tier: Tier | None = None
    failed = False
    score = float("-inf")
    checks: dict[str, Any] = {}
    latest: dict[str, Any] = {}
    for report in reports:
        latest[report.content.type] = report.content
    intake = latest.get("screening") or latest.get("intake")
    if intake is not None and intake.status in ("FAIL", "DUPLICATE"):
        failed = True
        checks["intake"] = {"value": intake.status, "reasons": [r.value for r in intake.reasons]}
    w1 = latest.get("w1")
    if w1 is not None:
        checks = read_w1(kind, sign, w1, gates)
        passed = all(c["passed"] for c in checks.values())
        tier = "w1_pass" if passed else None
        failed = failed or not passed
        score = sign * w1.rankic_ir if kind == "factor" else (w1.strategy_net_sharpe or score)
    w2 = latest.get("w2")
    if tier == "w1_pass" and w2 is not None:
        failed = w2.status == "FAIL"
        tier = "w2_pass" if w2.status == "PASS" else tier
    advancement = latest.get("advancement")
    if tier == "w2_pass" and advancement is not None:
        failed = advancement.status == "NOT_ADVANCED"
        tier = "advanced" if advancement.status == "ADVANCED" else tier
    decision = latest.get("decision")
    if decision is not None:
        failed = decision.status == "REJECTED"
        tier = "incubated" if decision.status == "ACCEPTED" and tier == "advanced" else tier
    return Reading(version_id, candidate_id, kind, tier, failed, score, w0_score, checks)


def answered(reports: list[ReleasedReport]) -> bool:
    """Whether the evaluator has answered one published version: its intake was refused
    or deferred (a quota deferral counts as an answer), its screening failed, or its W1
    report is out. Research can then learn everything the next generation needs."""
    latest: dict[str, Any] = {report.content.type: report.content for report in reports}
    intake = latest.get("intake")
    if intake is None:
        return False
    if intake.status != "PASS":
        return True
    screening = latest.get("screening")
    if screening is not None and screening.status != "PASS":
        return True
    return "w1" in latest


def generation_versions(conn: Connection, generation_id: UUID) -> list[UUID]:
    """The versions one generation published, in publication order. For the seed
    generation (seq 0) these are the job's seed versions, published or referenced."""
    row = conn.execute(
        text(
            "SELECT g.seq, j.seed_version_ids FROM generations g JOIN programs p ON "
            "p.program_id = g.program_id JOIN research_jobs j ON j.job_id = p.job_id "
            "WHERE g.generation_id = :g"
        ),
        {"g": generation_id},
    ).one()
    if row.seq == 0:
        return [UUID(str(v)) for v in row.seed_version_ids or []]
    return [
        r.version_id
        for r in conn.execute(
            text(
                "SELECT v.version_id FROM candidate_versions v JOIN candidates c ON "
                "c.candidate_id = v.candidate_id WHERE c.generation_id = :g "
                "ORDER BY v.published_at, v.version_id"
            ),
            {"g": generation_id},
        ).all()
    ]


def next_utc_day(at: datetime) -> datetime:
    return datetime(at.year, at.month, at.day, tzinfo=UTC) + timedelta(days=1)


class JobMonitor:
    def __init__(self, env: ResearchEnv, jobs: JobService | None = None) -> None:
        self.env = env
        self.jobs = jobs or JobService(env)
        self.feedback = FeedbackSync(env)

    # Cards -----------------------------------------------------------------------------

    def cards(self) -> tuple[dict[str, Any], dict[str, Any], str]:
        """The active protocol and policy cards from feedback-api; the bundled preview
        only when feedback-api is not configured or does not answer."""
        if self.env.feedback is not None:
            try:
                protocol = self.env.feedback.card("protocol")
                policy = self.env.feedback.card("policy")
                return dict(protocol.card), dict(policy.card), f"{protocol.ref}|{policy.ref}"
            except (ServiceUnavailable, ServiceRefused):
                pass
        cards = self.env.public_cards
        return dict(cards["protocol"]), dict(cards["policy"]), "bundled"

    # Readings --------------------------------------------------------------------------

    def readings(self, conn: Connection, job: Any, gates: dict[str, Any]) -> list[Reading]:
        """The job's published versions of the kind its mode delivers."""
        kind = DELIVERABLE_KIND.get(str(job.brief["mode"]))
        rows = conn.execute(
            text(
                "SELECT v.version_id, c.candidate_id, c.kind, c.payload, c.workbench "
                "FROM candidate_versions v JOIN candidates c ON c.candidate_id = v.candidate_id "
                "WHERE c.program_id = :p AND c.operator <> 'human_seed' "
                "AND (CAST(:k AS text) IS NULL OR c.kind = :k) ORDER BY v.published_at"
            ),
            {"p": job.program_id, "k": kind},
        ).all()
        found = []
        for row in rows:
            sign = int((row.payload or {}).get("expected_sign", 1))
            metrics = (row.workbench or {}).get("metrics") or {}
            w0 = (
                (row.workbench or {}).get("reference_sharpe")
                if row.kind != "factor"
                else (None if metrics.get("rankic_ir") is None else sign * metrics["rankic_ir"])
            )
            found.append(
                read_tier(
                    row.version_id,
                    row.candidate_id,
                    row.kind,
                    sign,
                    reports_for(conn, row.version_id),
                    gates,
                    float(w0) if w0 is not None else float("-inf"),
                )
            )
        return found

    def _job(self, conn: Connection, job_id: UUID, lock: bool = False) -> Any:
        return conn.execute(
            text(
                "SELECT j.*, p.status AS program_status, p.charter, p.charter_version "
                "FROM research_jobs j LEFT JOIN programs p ON p.program_id = j.program_id "
                "WHERE j.job_id = :j" + (" FOR UPDATE OF j" if lock else "")
            ),
            {"j": job_id},
        ).one()

    @staticmethod
    def delivered(conn: Connection, job_id: UUID) -> list[UUID]:
        return [
            r.version_id
            for r in conn.execute(
                text(
                    "SELECT i.version_id FROM deliverable_items i JOIN deliverables d ON "
                    "d.deliverable_id = i.deliverable_id WHERE d.job_id = :j ORDER BY d.seq, "
                    "i.ordinal"
                ),
                {"j": job_id},
            ).all()
        ]

    # Criteria --------------------------------------------------------------------------

    def evaluate(self, job_id: UUID) -> UUID | None:
        """Check the brief's deliverable criteria; assemble a deliverable when met."""
        env = self.env
        protocol, _, source = self.cards()
        with env.db.transaction(lock=True) as conn:
            job = self._job(conn, job_id, lock=True)
            if job.state == "CLOSED" or job.program_id is None:
                return None
            criteria = job.deliverable_criteria
            wanted: Tier = criteria["tier"]
            readings = self.readings(conn, job, protocol["gates"])
            delivered = set(self.delivered(conn, job_id))
            qualifying = sorted(
                (
                    r
                    for r in readings
                    if r.tier is not None
                    and RANK[r.tier] >= RANK[wanted]
                    and r.version_id not in delivered
                ),
                key=Reading.key,
            )
            room = int(criteria["max_candidates"]) - len(delivered)
            need = int(criteria["min_count"]) if not delivered else 1
            met = room > 0 and len(qualifying) >= need
            ctx = Ctx(job_id=job_id, program_id=job.program_id)
            env.trace.step(
                conn,
                "DELIVERABLE_CRITERIA_EVALUATED",
                ctx,
                actor="job-monitor",
                inputs={
                    "criteria": criteria,
                    "kind": DELIVERABLE_KIND.get(str(job.brief["mode"])),
                    "gates_source": source,
                    "gates": protocol["gates"],
                    "delivered": len(delivered),
                },
                payload={
                    "met": met,
                    "qualifying": [str(r.version_id) for r in qualifying],
                    "readings": [
                        {
                            "version_id": str(r.version_id),
                            "tier": r.tier,
                            "failed": r.failed,
                            "pending": r.pending_for(wanted),
                            "checks": r.checks,
                        }
                        for r in readings
                    ],
                },
            )
            if not met:
                return None
            picks = qualifying[:room]
            deliverable_id = self.assemble(conn, job, picks, "complete", "criteria met")
            self.jobs.set_state(
                conn, job_id, "DELIVERABLE_READY", reason="deliverable criteria met"
            )
            return deliverable_id

    # Generations -----------------------------------------------------------------------

    def after_generation(self, job_id: UUID, generation_id: UUID) -> None:
        """Re-evaluate the stop conditions and schedule the next generation."""
        env = self.env
        now = env.clock.now()
        with env.db.transaction(lock=True) as conn:
            job = self._job(conn, job_id, lock=True)
            if job.state == "CLOSED" or job.program_id is None:
                return
            ctx = Ctx(job_id=job_id, program_id=job.program_id)
            run = int(
                conn.execute(
                    text(
                        "SELECT count(*) FROM generations WHERE program_id = :p AND seq > 0 "
                        "AND state IN ('CLOSED', 'FAILED')"
                    ),
                    {"p": job.program_id},
                ).scalar_one()
            )
            budget_stop = conn.execute(
                text("SELECT budget_stop FROM generations WHERE generation_id = :g"),
                {"g": generation_id},
            ).scalar()
            left = env.ledger.remaining(conn, ctx, now)
            job_spent = left.scope == "job" and left.amount <= 0
            stop = None
            if budget_stop == "budget_job" or job_spent or job.cost_cny >= job.budget["max_cost"]:
                stop = "job cost cap reached"
            elif run >= int(job.budget["max_generations"]):
                stop = "generation cap reached"
            if stop is not None:
                conn.execute(
                    text(
                        "UPDATE research_jobs SET next_generation_at = NULL, updated_at = :now "
                        "WHERE job_id = :j"
                    ),
                    {"now": now, "j": job_id},
                )
                job_event(
                    conn,
                    env.clock,
                    job_id,
                    "research_stopped",
                    {"reason": stop, "generations_run": run, "cost_cny": float(job.cost_cny)},
                )
                env.logger.logger.info(
                    "research_stopped", outcome="ok", payload={"reason": stop}, **ctx.log_ids()
                )
                if job.state == "RUNNING":
                    self.jobs.set_state(conn, job_id, "WAITING_FOR_EVALUATION", reason=stop)
                return
            if job.state != "RUNNING":
                # The criteria are met: research stops spending; evaluation continues.
                conn.execute(
                    text("UPDATE research_jobs SET next_generation_at = NULL WHERE job_id = :j"),
                    {"j": job_id},
                )
                return
            failed: bool = (
                conn.execute(
                    text("SELECT state FROM generations WHERE generation_id = :g"),
                    {"g": generation_id},
                ).scalar_one()
                == "FAILED"
            )
            waiting = len(generation_versions(conn, generation_id))
            at = self.next_start(job.charter or {}, now, waiting=waiting, failed=failed)
            conn.execute(
                text(
                    "UPDATE research_jobs SET next_generation_at = :at, updated_at = :now "
                    "WHERE job_id = :j"
                ),
                {"at": at, "now": now, "j": job_id},
            )
            job_event(
                conn,
                env.clock,
                job_id,
                "generation_scheduled",
                {"at": at.isoformat(), "generations_run": run, "awaiting_versions": waiting},
            )

    def next_start(
        self, charter: dict[str, Any], now: datetime, *, waiting: int, failed: bool
    ) -> datetime:
        """When the next generation is due at the latest. With nothing to wait for it is
        due now; otherwise after `max_wait_hours`, and earlier once the feedback is
        complete (see `_feedback_complete`). A failed generation always waits the full
        time, so a provider outage cannot spend the generation cap in minutes."""
        cadence = charter.get("cadence") or self.env.charter_defaults["cadence"]
        if waiting == 0 and not failed:
            return now
        return now + timedelta(hours=float(cadence["max_wait_hours"]))

    def start_generation(self, conn: Connection, job: Any) -> UUID:
        env, now = self.env, self.env.clock.now()
        seq = int(
            conn.execute(
                text("SELECT coalesce(max(seq), 0) + 1 FROM generations WHERE program_id = :p"),
                {"p": job.program_id},
            ).scalar_one()
        )
        generation_id = uuid7()
        conn.execute(
            text(
                "INSERT INTO generations (generation_id, program_id, seq, state, charter_version, "
                "created_at, updated_at) VALUES (:g, :p, :s, 'PENDING', :cv, :now, :now)"
            ),
            {
                "g": generation_id,
                "p": job.program_id,
                "s": seq,
                "cv": job.charter_version,
                "now": now,
            },
        )
        conn.execute(
            text(
                "UPDATE research_jobs SET next_generation_at = NULL, daily_wait_until = NULL, "
                "updated_at = :now WHERE job_id = :j"
            ),
            {"now": now, "j": job.job_id},
        )
        enqueue(
            conn,
            env.clock,
            "generation",
            f"gen:{generation_id}",
            {"generation_id": str(generation_id), "job_id": str(job.job_id)},
        )
        job_event(
            conn,
            env.clock,
            job.job_id,
            "generation_queued",
            {"generation_id": str(generation_id), "seq": seq},
        )
        env.logger.logger.info(
            "generation_queued",
            outcome="ok",
            job_id=str(job.job_id),
            program_id=str(job.program_id),
            generation_id=str(generation_id),
            payload={"seq": seq},
        )
        return generation_id

    # The tick --------------------------------------------------------------------------

    def tick(self) -> TickResult:
        """Deadlines, watched jobs and due generations, once per worker tick."""
        env = self.env
        result = TickResult()
        with env.db.read() as conn:
            jobs = conn.execute(
                text(
                    "SELECT job_id, state FROM research_jobs WHERE state <> 'CLOSED' "
                    "AND program_id IS NOT NULL ORDER BY submitted_at"
                )
            ).all()
            halted = bool(
                conn.execute(text("SELECT paused FROM research_control WHERE id = 1")).scalar()
            )
        for row in jobs:
            with self._bound(row.job_id):
                self._tick_job(row.job_id, halted, result)
        return result

    def _bound(self, job_id: UUID) -> Any:
        return bind(job_id=str(job_id))

    def _tick_job(self, job_id: UUID, halted: bool, result: TickResult) -> None:
        env = self.env
        now = env.clock.now()
        with env.db.read() as conn:
            job = self._job(conn, job_id)
        if now >= job.deadline_at:
            if self.close(job_id, "expired", "wall-clock limit reached"):
                result.closed.append(job_id)
            return
        if job.state in WATCHING:
            if env.feedback is not None:
                self.feedback.sync(Ctx(job_id=job_id, program_id=job.program_id))
            delivered = self.evaluate(job_id)
            if delivered is not None:
                result.deliverables.append(delivered)
            if job.state == "WAITING_FOR_EVALUATION" and delivered is None:
                self._maybe_finish(job_id, result)
            return
        if job.state != "RUNNING" or halted or job.program_status != "active":
            return
        if job.next_generation_at is None:
            return
        if job.daily_wait_until is not None and now < job.daily_wait_until:
            return
        due = job.next_generation_at <= now or self._feedback_complete(job)
        if not due:
            return
        with env.db.transaction(lock=True) as conn:
            job = self._job(conn, job_id, lock=True)
            if job.state != "RUNNING" or job.next_generation_at is None:
                return
            if has_open_generation(conn, job.program_id):
                return
            ctx = Ctx(job_id=job_id, program_id=job.program_id)
            left = env.ledger.remaining(conn, ctx, now)
            if left.scope == "daily" and left.amount <= 0:
                until = next_utc_day(now)
                conn.execute(
                    text("UPDATE research_jobs SET daily_wait_until = :u WHERE job_id = :j"),
                    {"u": until, "j": job_id},
                )
                job_event(
                    conn,
                    env.clock,
                    job_id,
                    "daily_cap_wait",
                    {
                        "until": until.isoformat(),
                        "spent": float(left.spent),
                        "cap": float(left.cap),
                    },
                )
                env.logger.logger.info(
                    "daily_cap_wait",
                    outcome="deferred",
                    payload={"until": until.isoformat()},
                    **ctx.log_ids(),
                )
                return
            result.started.append(self.start_generation(conn, job))

    def _feedback_complete(self, job: Any) -> bool:
        """Whether every version the previous generation published (the seeds, for the
        first generation) has been answered. The released reports are read from
        feedback-api by version without moving the program's sync cursor, so the next
        generation's sync still sees and interprets them as new."""
        env = self.env
        cadence = (job.charter or {}).get("cadence") or env.charter_defaults["cadence"]
        if env.feedback is None or not cadence.get("after_feedback_complete"):
            return False
        with env.db.read() as conn:
            last = conn.execute(
                text(
                    "SELECT generation_id, state FROM generations WHERE program_id = :p "
                    "AND state IN ('CLOSED', 'FAILED') ORDER BY seq DESC LIMIT 1"
                ),
                {"p": job.program_id},
            ).first()
            if last is None or last.state == "FAILED":
                return False
            versions = generation_versions(conn, last.generation_id)
        limit = env.config.service.feedback.page_limit
        for version_id in versions:
            # Stop at the first version still waiting: one request per tick while waiting.
            try:
                page = env.feedback.reports(version_id=version_id, limit=limit)
            except (ServiceUnavailable, ServiceRefused):
                return False
            if not answered(page.items):
                return False
        return True

    def _maybe_finish(self, job_id: UUID, result: TickResult) -> None:
        """A stopped job with nothing pending and nothing at the tier closes best effort."""
        env = self.env
        protocol, _, _ = self.cards()
        with env.db.read() as conn:
            job = self._job(conn, job_id)
            readings = self.readings(conn, job, protocol["gates"])
            delivered = self.delivered(conn, job_id)
        wanted: Tier = job.deliverable_criteria["tier"]
        if delivered or any(r.pending_for(wanted) for r in readings):
            return
        if self.close(job_id, "budget_exhausted", "research stopped and no version met the tier"):
            result.closed.append(job_id)

    # Closing ---------------------------------------------------------------------------

    def close(self, job_id: UUID, decision: str, reason: str) -> bool:
        """Close a job on a stop condition, with a best_effort deliverable when nothing
        was delivered and something was published."""
        env = self.env
        protocol, _, _ = self.cards()
        with env.db.transaction(lock=True) as conn:
            job = self._job(conn, job_id, lock=True)
            if job.state == "CLOSED":
                return False
            if not self.delivered(conn, job_id) and job.program_id is not None:
                readings = sorted(self.readings(conn, job, protocol["gates"]), key=Reading.key)
                picks = readings[: int(job.deliverable_criteria["max_candidates"])]
                if picks:
                    self.assemble(conn, job, picks, "best_effort", reason)
            self.jobs.set_state(conn, job_id, "CLOSED", reason=reason, close_decision=decision)
        return True

    # Assembly --------------------------------------------------------------------------

    def assemble(
        self, conn: Connection, job: Any, picks: list[Reading], status: str, reason: str
    ) -> UUID:
        env, now = self.env, self.env.clock.now()
        deliverable_id = uuid7()
        seq = int(
            conn.execute(
                text("SELECT coalesce(max(seq), 0) + 1 FROM deliverables WHERE job_id = :j"),
                {"j": job.job_id},
            ).scalar_one()
        )
        # Item codes number factors (F-k) and strategies (S-k) separately across the
        # job's deliverables; the owner repeats them in approvals (Section 13.5).
        numbered = {
            r.kind: int(r.n)
            for r in conn.execute(
                text(
                    "SELECT i.kind, count(*) AS n FROM deliverable_items i JOIN deliverables d "
                    "ON d.deliverable_id = i.deliverable_id WHERE d.job_id = :j GROUP BY i.kind"
                ),
                {"j": job.job_id},
            ).all()
        }
        wanted: Tier = job.deliverable_criteria["tier"]
        items: list[DeliverableItem] = []
        codes: list[str] = []
        stats = self._stats(conn, job)
        for pick in picks:
            trace = export(conn, version_id=pick.version_id)
            history = iteration_history(conn, pick.version_id, now, trace)
            manifest: dict[str, Any] = conn.execute(
                text(
                    "SELECT payload -> 'manifest' FROM trace_steps WHERE step_type = 'PUBLISHED' "
                    "AND outcome = 'ok' AND version_id = :v ORDER BY at LIMIT 1"
                ),
                {"v": pick.version_id},
            ).scalar_one()
            numbered[pick.kind] = numbered.get(pick.kind, 0) + 1
            code = f"{'F' if pick.kind == 'factor' else 'S'}-{numbered[pick.kind]}"
            codes.append(f"{job.short_code} {code}")
            item = DeliverableItem.model_validate(
                {
                    "version_id": pick.version_id,
                    "kind": pick.kind,
                    "manifest": manifest,
                    "tier_reached": pick.tier,
                    "iteration_history": history,
                    "trace_ref": pick.candidate_id,
                    "trace_hash": trace_hash(trace),
                    "released_reports": trace.released_reports,
                    "owner_evidence": None,
                    "caveats": caveats(pick, wanted, history.totals, stats, env.public_cards),
                }
            )
            items.append(item)
        costs = self._costs(conn, job, stats)
        document = Deliverable(
            schema_version="deliverable/1",
            deliverable_id=deliverable_id,
            job_id=job.job_id,
            created_at=now,
            status=status,  # type: ignore[arg-type]
            items=items,
            summary=summary(job, items, status, reason, costs, codes),
            costs=costs,
            short_codes=codes,
        )
        conn.execute(
            text(
                "INSERT INTO deliverables (deliverable_id, job_id, seq, status, summary, costs, "
                "document, created_at) VALUES (:d, :j, :s, :st, :sum, CAST(:c AS jsonb), "
                "CAST(:doc AS jsonb), :now)"
            ),
            {
                "d": deliverable_id,
                "j": job.job_id,
                "s": seq,
                "st": status,
                "sum": document.summary,
                "c": dumps(costs),
                "doc": dumps(document.model_dump(mode="json")),
                "now": now,
            },
        )
        for ordinal, (item, code) in enumerate(zip(items, codes, strict=True), 1):
            conn.execute(
                text(
                    "INSERT INTO deliverable_items (item_id, deliverable_id, ordinal, version_id, "
                    "kind, tier_reached, iteration_history, trace_hash, short_code) VALUES (:i, "
                    ":d, :o, :v, :k, :t, CAST(:h AS jsonb), :th, :sc)"
                ),
                {
                    "i": uuid7(),
                    "d": deliverable_id,
                    "o": ordinal,
                    "v": item.version_id,
                    "k": item.kind,
                    "t": item.tier_reached,
                    "h": dumps(item.iteration_history.model_dump(mode="json")),
                    "th": item.trace_hash,
                    "sc": code.split(" ", 1)[1],
                },
            )
        ctx = Ctx(job_id=job.job_id, program_id=job.program_id)
        env.trace.step(
            conn,
            "DELIVERABLE_ASSEMBLED",
            ctx,
            actor="deliverable-assembler",
            inputs={"reason": reason, "status": status},
            payload={
                "deliverable_id": str(deliverable_id),
                "seq": seq,
                "short_codes": codes,
                "items": [
                    {
                        "version_id": str(i.version_id),
                        "tier_reached": i.tier_reached,
                        "trace_hash": i.trace_hash,
                    }
                    for i in items
                ],
            },
        )
        job_event(
            conn,
            env.clock,
            job.job_id,
            "deliverable_ready",
            {"deliverable_id": str(deliverable_id), "status": status, "short_codes": codes},
        )
        env.logger.logger.info(
            "deliverable_assembled",
            outcome="ok",
            job_id=str(job.job_id),
            payload={
                "deliverable_id": str(deliverable_id),
                "status": status,
                "items": len(items),
                "version_ids": [str(i.version_id) for i in items],
            },
        )
        return deliverable_id

    def _stats(self, conn: Connection, job: Any) -> dict[str, Any]:
        row = conn.execute(
            text(
                "SELECT (SELECT count(*) FROM generations WHERE program_id = :p AND seq > 0 AND "
                "state IN ('CLOSED', 'FAILED')) AS generations, (SELECT count(*) FROM "
                "candidate_versions v JOIN candidates c ON c.candidate_id = v.candidate_id WHERE "
                "c.program_id = :p AND c.operator <> 'human_seed') AS publications, (SELECT "
                "count(DISTINCT version_id) FROM report_cache WHERE program_id = :p AND "
                "report_type = 'w1') AS w1_evaluated"
            ),
            {"p": job.program_id},
        ).one()
        return {
            "generations_run": int(row.generations),
            "publications": int(row.publications),
            "w1_evaluated_in_program": int(row.w1_evaluated),
        }

    def _costs(self, conn: Connection, job: Any, stats: dict[str, Any]) -> dict[str, Any]:
        rows = conn.execute(
            text(
                "SELECT provider, role, count(*) AS calls, sum(tokens_in) AS tin, "
                "sum(tokens_out) AS tout, sum(tokens_cached) AS tcache, sum(cost_cny) AS cost "
                "FROM budget_ledger WHERE job_id = :j GROUP BY provider, role "
                "ORDER BY provider, role"
            ),
            {"j": job.job_id},
        ).all()
        by_provider: dict[str, Any] = {}
        by_role: dict[str, Any] = {}
        for r in rows:
            for key, bucket in ((r.provider, by_provider), (r.role, by_role)):
                entry = bucket.setdefault(
                    key,
                    {
                        "calls": 0,
                        "tokens_in": 0,
                        "tokens_out": 0,
                        "tokens_cached": 0,
                        "cost_cny": 0.0,
                    },
                )
                entry["calls"] += int(r.calls)
                entry["tokens_in"] += int(r.tin)
                entry["tokens_out"] += int(r.tout)
                entry["tokens_cached"] += int(r.tcache)
                entry["cost_cny"] = round(entry["cost_cny"] + float(r.cost), 6)
        total: Any = conn.execute(
            text("SELECT cost_cny FROM research_jobs WHERE job_id = :j"), {"j": job.job_id}
        ).scalar_one()
        return {
            "currency": "CNY",
            "total_cny": round(float(total), 6),
            "by_provider": by_provider,
            "by_role": by_role,
            "generations_run": stats["generations_run"],
            "publications": stats["publications"],
            "trials_counted": stats["w1_evaluated_in_program"],
        }

    # Reads -----------------------------------------------------------------------------

    def deliverables(self, conn: Connection, job_id: UUID) -> list[DeliverableView]:
        rows = conn.execute(
            text("SELECT document, fetched_at FROM deliverables WHERE job_id = :j ORDER BY seq"),
            {"j": job_id},
        ).all()
        return [DeliverableView(deliverable=r.document, fetched_at=r.fetched_at) for r in rows]

    def deliverable(self, conn: Connection, deliverable_id: UUID) -> DeliverableView | None:
        row = conn.execute(
            text("SELECT document, fetched_at FROM deliverables WHERE deliverable_id = :d"),
            {"d": deliverable_id},
        ).first()
        return (
            None
            if row is None
            else DeliverableView(deliverable=row.document, fetched_at=row.fetched_at)
        )

    def mark_fetched(self, deliverable_id: UUID, principal: str) -> DeliverableView | None:
        """The first fetch through the front door records DELIVERED (Section 13.3)."""
        env = self.env
        with env.db.transaction(lock=True) as conn:
            row = conn.execute(
                text(
                    "SELECT job_id, fetched_at FROM deliverables WHERE deliverable_id = :d "
                    "FOR UPDATE"
                ),
                {"d": deliverable_id},
            ).first()
            if row is None:
                return None
            if row.fetched_at is None:
                conn.execute(
                    text("UPDATE deliverables SET fetched_at = :now WHERE deliverable_id = :d"),
                    {"now": env.clock.now(), "d": deliverable_id},
                )
                job = self._job(conn, row.job_id, lock=True)
                env.trace.step(
                    conn,
                    "DELIVERED",
                    Ctx(job_id=row.job_id, program_id=job.program_id),
                    actor_kind="host_agent",
                    actor=principal,
                    inputs={"deliverable_id": str(deliverable_id)},
                    payload={"fetched_at": env.clock.now().isoformat()},
                )
                job_event(
                    conn,
                    env.clock,
                    row.job_id,
                    "deliverable_fetched",
                    {"deliverable_id": str(deliverable_id)},
                )
                if job.state == "DELIVERABLE_READY" and not self._unfetched(conn, row.job_id):
                    self.jobs.set_state(
                        conn,
                        row.job_id,
                        "DELIVERED",
                        reason="the host agent fetched the deliverable",
                        principal=principal,
                    )
            return self.deliverable(conn, deliverable_id)

    @staticmethod
    def _unfetched(conn: Connection, job_id: UUID) -> bool:
        return (
            conn.execute(
                text("SELECT 1 FROM deliverables WHERE job_id = :j AND fetched_at IS NULL"),
                {"j": job_id},
            ).first()
            is not None
        )


# Templates -------------------------------------------------------------------------------


def caveats(
    pick: Reading,
    wanted: Tier,
    totals: dict[str, Any],
    stats: dict[str, Any],
    cards: dict[str, Any],
) -> list[str]:
    """Mandatory, generated caveats (Section 13.4); no LLM writes any of them."""
    rounding = cards["policy"]["rounding"]
    costs = cards["protocol"]["costs"]
    if pick.tier is None:
        tier = (
            f"Best effort: this version did not reach any tier; the brief asked for {wanted}. "
            "It is included as one of the best candidates so far."
        )
    else:
        tier = (
            f"Tier reached: {pick.tier}, read by research from released values with the public "
            "gates; the front door confirms it against the evaluator's official state."
        )
        if RANK[pick.tier] < RANK[wanted]:
            tier += f" The brief asked for {wanted}, which this version has not reached."
    return [
        tier,
        (
            "Released values are coarsened: RankIC rounded to "
            f"{rounding['rankic']}, IR to {rounding['ir']}, Sharpe to {rounding['sharpe']}, and "
            "the Newey-West t-statistic is bucketed. Exact values are in the owner-grade "
            "evidence only."
        ),
        (
            f"Trials: {totals.get('trials_in_family', 0)} published version(s) in this family and "
            f"{stats['w1_evaluated_in_program']} W1-evaluated version(s) in this program. "
            "Multiple testing inflates apparent significance; the effective number of "
            "independent trials (N_eff) is not estimated at this tier."
        ),
        (
            "The evaluator's W1 window is out of sample for research. The W0 statistics in "
            "the iteration history are research-side and in sample only."
        ),
        (
            "The expression was drafted with language models that may have seen published "
            "factor research; a familiar-looking factor may be memorized rather than "
            "discovered."
        ),
        (
            f"The cost model is fixed (buy {costs['buy_bps']} bps, sell {costs['sell_bps']} bps, "
            f"long-short {costs['long_short_bps_per_side']} bps per side); real costs, capacity "
            "and market impact may differ."
        ),
    ]


def summary(
    job: Any,
    items: list[DeliverableItem],
    status: str,
    reason: str,
    costs: dict[str, Any],
    codes: list[str],
) -> str:
    criteria = job.deliverable_criteria
    asked = (
        f"{job.short_code} asked for at least {criteria['min_count']} version(s) at tier "
        f"{criteria['tier']} (mode {job.brief['mode']}): {job.brief['title']}."
    )
    tiers = ", ".join(
        f"{c.split(' ')[-1]} {i.tier_reached or 'no tier'}"
        for c, i in zip(codes, items, strict=True)
    )
    if status == "complete":
        delivered = f"Delivered {len(items)} version(s): {tiers}."
    else:
        delivered = (
            f"Best effort ({reason}): no version met the tier; the {len(items)} best "
            f"version(s) so far are {tiers}."
        )
    spent = (
        f"Research cost {costs['total_cny']:.2f} CNY over {costs['generations_run']} "
        f"generation(s) and {costs['publications']} publication(s)."
    )
    return " ".join([asked, delivered, spent])
