"""The generation state machine (P4.8, PLAN Section 11.6).

PENDING → SYNCING → PROPOSING → PLANNING → DEVELOPING → SELECTING → PUBLISHING → CLOSED,
with FAILED and ABORTED terminal. The state is persisted after every step and every
transition is a GENERATION_STATE_CHANGED trace step and a log line, so a crashed
generation resumes from its last persisted state. Tasks run in parallel up to the
charter's concurrency; a failed task never fails the generation. A budget stop, or a
pause, skips straight to SELECTING with whatever is ready. Agents never write the
blackboard or the trace themselves: this module validates their outputs and writes
them through the role's write scope.

Phase 5 adds the evolutionary engine: SYNCING initializes the population once,
PROPOSING refreshes fitness, the archive and the bandit and emits the engine's proposal,
and DEVELOPING runs llm_mutation, crossover and repair tasks (the engineer with the
parents, their released digests, targeted instructions and the assembled context) and
syntactic batches (ready-made deterministic variants, no LLM). Every operator
application is a PARENT_SELECTED step and its operator's APPLIED step with the AST diff.
"""

import asyncio
import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from qfr_core.dsl import ast_diff, canonicalize, parse
from qfr_core.ids import uuid7
from sqlalchemy import text
from sqlalchemy.engine import Connection

from qfr_research.agents import RoleFailed, RoleResult, RoleRunner
from qfr_research.budget import BudgetExceeded
from qfr_research.context import Context, ContextAssembler, parent_hypothesis
from qfr_research.db import dumps
from qfr_research.engine import EvolutionEngine, GenerationRef
from qfr_research.env import ResearchEnv
from qfr_research.feedback import FeedbackSync
from qfr_research.outputs import (
    AnalystOutput,
    CandidateDraft,
    EngineerOutput,
    GenerationPlan,
    HypothesisBatch,
    InterpretationChallenge,
    ReviewVerdict,
    StrategyDraft,
)
from qfr_research.packager import Packager
from qfr_research.planning import (
    Proposal,
    assign_variants,
    fit_to_budget,
    stagnation_choices,
    validate_plan,
)
from qfr_research.prompts import RenderedPrompt
from qfr_research.selection import (
    Screened,
    behavioral_dedup,
    prescreen,
    provisional_fitness,
    select,
)
from qfr_research.store import Ctx
from qfr_research.tools import ToolDeps, invoke, require_write

TERMINAL = frozenset({"CLOSED", "FAILED", "ABORTED"})
NEXT = {
    "PENDING": "SYNCING",
    "SYNCING": "PROPOSING",
    "PROPOSING": "PLANNING",
    "PLANNING": "DEVELOPING",
    "DEVELOPING": "SELECTING",
    "SELECTING": "PUBLISHING",
    "PUBLISHING": "CLOSED",
}
LLM_STATES = frozenset({"SYNCING", "PROPOSING", "PLANNING", "DEVELOPING"})
APPLIED_STEP = {
    "llm_mutation": "MUTATION_APPLIED",
    "crossover": "CROSSOVER_APPLIED",
    "repair": "REPAIR_APPLIED",
    "syntactic_mutation": "SYNTACTIC_MUTATION_APPLIED",
}


@dataclass
class Generation:
    generation_id: UUID
    program_id: UUID
    job_id: UUID
    seq: int
    state: str
    charter: dict[str, Any]
    charter_version: int
    budget_stop: str | None

    @property
    def ctx(self) -> Ctx:
        return Ctx(job_id=self.job_id, program_id=self.program_id, generation_id=self.generation_id)

    @property
    def ref(self) -> GenerationRef:
        return GenerationRef(
            self.generation_id, self.program_id, self.job_id, self.seq, self.charter
        )


@dataclass
class EngineerBrief:
    """What one engineer task works from: the operator and its instructions, the
    hypotheses (explore) or the inherited rationale (parent operators), and the context
    the assembler gathered."""

    operator: str
    hypotheses: list[tuple[UUID, Any]]
    hypothesis_text: str
    parents: list[str]
    context: Context | None = None
    instructions: RenderedPrompt | None = None
    targeted_flags: list[str] | None = None
    inherited_hypothesis: UUID | None = None


class Stop(Exception):
    """Stop LLM work for this generation (budget or pause) and select what is ready."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class GenerationRunner:
    def __init__(self, env: ResearchEnv, monitor: Any = None) -> None:
        self.env = env
        self.roles = RoleRunner(env)
        self.packager = Packager(env)
        self.feedback = FeedbackSync(env)
        self.engine = EvolutionEngine(env)
        self.context = ContextAssembler(env)
        self.monitor = monitor

    # Loading and transitions -----------------------------------------------------------

    def load(self, generation_id: UUID) -> Generation:
        with self.env.db.read() as conn:
            row = conn.execute(
                text(
                    "SELECT g.generation_id, g.program_id, p.job_id, g.seq, g.state, p.charter, "
                    "g.charter_version, g.budget_stop FROM generations g JOIN programs p "
                    "ON p.program_id = g.program_id WHERE g.generation_id = :g"
                ),
                {"g": generation_id},
            ).one()
        return Generation(
            row.generation_id,
            row.program_id,
            row.job_id,
            row.seq,
            row.state,
            row.charter,
            row.charter_version,
            row.budget_stop,
        )

    def transition(self, gen: Generation, to: str, payload: dict[str, Any] | None = None) -> None:
        env, now = self.env, self.env.clock.now()
        with env.db.transaction() as conn:
            conn.execute(
                text(
                    "UPDATE generations SET state = :s, updated_at = :now, "
                    "started_at = CASE WHEN :s = 'SYNCING' THEN coalesce(started_at, :now) "
                    "ELSE started_at END, ended_at = CASE WHEN :s IN ('CLOSED', 'FAILED', "
                    "'ABORTED') THEN :now ELSE ended_at END, budget_stop = :b "
                    "WHERE generation_id = :g"
                ),
                {"s": to, "now": now, "g": gen.generation_id, "b": gen.budget_stop},
            )
            if gen.state == "PENDING":
                env.trace.step(
                    conn,
                    "GENERATION_STARTED",
                    gen.ctx,
                    actor="research-worker",
                    inputs={"charter_version": gen.charter_version, "seq": gen.seq},
                )
            env.trace.step(
                conn,
                "GENERATION_STATE_CHANGED",
                gen.ctx,
                actor="research-worker",
                inputs={"from": gen.state},
                payload={"to": to} | (payload or {}),
            )
        env.logger.logger.info(
            "generation_state_changed",
            outcome="ok",
            payload={"from": gen.state, "to": to, "seq": gen.seq} | (payload or {}),
            **gen.ctx.log_ids(),
        )
        gen.state = to

    def stopped(self, gen: Generation) -> str | None:
        """Cancelled jobs abort; paused programs or research stop spending."""
        with self.env.db.read() as conn:
            row = conn.execute(
                text(
                    "SELECT j.state, p.status, coalesce((SELECT paused FROM research_control "
                    "WHERE id = 1), false) AS halted FROM research_jobs j JOIN programs p "
                    "ON p.job_id = j.job_id WHERE j.job_id = :j"
                ),
                {"j": gen.job_id},
            ).one()
        if row.state == "CLOSED":
            return "cancelled"
        if row.status != "active" or row.halted:
            return "paused"
        return None

    # The loop ----------------------------------------------------------------------------

    async def run(self, generation_id: UUID) -> str:
        gen = self.load(generation_id)
        while gen.state not in TERMINAL:
            halt = self.stopped(gen)
            if halt == "cancelled":
                self.transition(gen, "ABORTED", {"reason": "job cancelled"})
                break
            if halt == "paused" and gen.state in LLM_STATES | {"PENDING"}:
                gen.budget_stop = gen.budget_stop or "paused"
                if gen.state == "PENDING":
                    self.transition(gen, "ABORTED", {"reason": "paused before start"})
                    break
                self.transition(gen, "SELECTING", {"budget_stop": gen.budget_stop})
                continue
            handler = getattr(self, f"_{gen.state.lower()}")
            try:
                await handler(gen)
                nxt = NEXT[gen.state]
            except Stop as stop:
                gen.budget_stop = stop.reason
                nxt = "SELECTING" if gen.state in LLM_STATES else NEXT[gen.state]
            self.transition(gen, nxt, {"budget_stop": gen.budget_stop} if gen.budget_stop else None)
        if gen.state == "CLOSED" and self.monitor is not None:
            self.monitor.after_generation(gen.job_id, gen.generation_id)
        return gen.state

    def fail(self, generation_id: UUID, error_code: str) -> None:
        """Mark a generation FAILED after its last attempt; the job schedules the next."""
        gen = self.load(generation_id)
        if gen.state in TERMINAL:
            return
        with self.env.db.transaction() as conn:
            conn.execute(
                text("UPDATE generations SET error_code = :e WHERE generation_id = :g"),
                {"e": error_code[:200], "g": generation_id},
            )
        self.transition(gen, "FAILED", {"error_code": error_code[:200]})
        if self.monitor is not None:
            self.monitor.after_generation(gen.job_id, gen.generation_id)

    async def _pending(self, gen: Generation) -> None:
        return None

    async def _closed(self, gen: Generation) -> None:  # pragma: no cover - terminal
        return None

    # SYNCING ---------------------------------------------------------------------------

    async def _syncing(self, gen: Generation) -> None:
        env = self.env
        # The population starts once per program (Section 12.1); pool and parent-job
        # members are versions published elsewhere, so their reports come by version id.
        self.engine.ensure_initialized(gen.ref)
        external = set(self.engine.external_versions(gen.program_id))
        result = self.feedback.sync(gen.ctx, extra_versions=sorted(external, key=str))
        kinds = set(env.config.service.feedback.report_types_interpreted)
        batches: dict[UUID, list[Any]] = {}
        for report in result.new_reports:
            # The analyst interprets this program's results; reports of members
            # published elsewhere inform fitness but are not this program's evidence.
            if report.content.type in kinds and report.version_id not in external:
                batches.setdefault(report.version_id, []).append(report)
        size = env.config.service.analyst.reports_per_run
        for version_id, reports in batches.items():
            for start in range(0, len(reports), size):
                await self._interpret(gen, version_id, reports[start : start + size])
        if self.monitor is not None:
            self.monitor.evaluate(gen.job_id)
            with env.db.read() as conn:
                state: str = conn.execute(
                    text("SELECT state FROM research_jobs WHERE job_id = :j"), {"j": gen.job_id}
                ).scalar_one()
            if state != "RUNNING":
                # The deliverable criteria are met (or research was stopped): no new LLM
                # work; what is already approved is still selected and published.
                raise Stop("criteria_met" if state == "DELIVERABLE_READY" else "job_stopped")

    async def _interpret(self, gen: Generation, version_id: UUID, reports: list[Any]) -> None:
        env = self.env
        ctx = gen.ctx
        manifest = env.registry.version(version_id).manifest.model_dump(mode="json")
        report_json = [r.model_dump(mode="json") for r in reports]
        prompt = env.prompts.render(
            "analyst",
            {
                "manifest": _compact(manifest),
                "reports": _compact(report_json),
                "parent_reports": "none",
            },
            budget_chars=self._budget_chars(gen),
            trimmable=("reports",),
        )
        result = await self._call(
            gen,
            "analyst",
            prompt,
            AnalystOutput,
            ctx,
            inputs={"report_ids": [str(r.report_id) for r in reports]},
        )
        if result is None:
            return
        out = result.output
        ids = {str(r.report_id) for r in reports}
        interpretation = out.interpretation
        if not {str(i) for i in interpretation.report_ids} <= ids:
            interpretation = interpretation.model_copy(
                update={"report_ids": [r.report_id for r in reports]}
            )
        interpretation_id = uuid7()
        fraction = float(gen.charter["role_limits"]["interpretation_review_fraction"])
        sampled = _sampled(
            env.config.service.analyst.interpretation_review_seed, interpretation_id, fraction
        )
        with env.db.transaction() as conn:
            require_write(env, "analyst", "interpretation", ctx)
            now = env.clock.now()
            conn.execute(
                text(
                    "INSERT INTO interpretations (interpretation_id, program_id, generation_id, "
                    "report_ids, version_id, payload, status, run_id, sampled_for_review, "
                    "created_at, updated_at) VALUES (:i, :p, :g, CAST(:r AS jsonb), :v, "
                    "CAST(:pl AS jsonb), :s, :run, :sampled, :now, :now)"
                ),
                {
                    "i": interpretation_id,
                    "p": gen.program_id,
                    "g": gen.generation_id,
                    "r": dumps(sorted(ids)),
                    "v": version_id,
                    "pl": dumps(interpretation.model_dump(mode="json")),
                    "s": "draft" if sampled else "final",
                    "run": result.run_id,
                    "sampled": sampled,
                    "now": now,
                },
            )
            env.trace.step(
                conn,
                "INTERPRETED",
                ctx,
                actor_kind="llm",
                actor="analyst",
                llm=result.attribution,
                version_id=version_id,
                inputs={"report_ids": sorted(ids)},
                payload={
                    "interpretation_id": str(interpretation_id),
                    "interpretation": interpretation.model_dump(mode="json"),
                    "sampled_for_review": sampled,
                },
            )
            for item in out.knowledge_items:
                require_write(env, "analyst", "knowledge_item", ctx)
                item_id = uuid7()
                conn.execute(
                    text(
                        "INSERT INTO knowledge_items (item_id, program_id, interpretation_id, "
                        "kind, statement, tags, evidence_report_ids, created_at) VALUES (:i, :p, "
                        ":interp, :k, :s, CAST(:t AS jsonb), CAST(:e AS jsonb), :now)"
                    ),
                    {
                        "i": item_id,
                        "p": gen.program_id,
                        "interp": interpretation_id,
                        "k": item.kind,
                        "s": item.statement,
                        "t": dumps(item.tags),
                        "e": dumps([str(e) for e in item.evidence_report_ids]),
                        "now": now,
                    },
                )
                env.trace.step(
                    conn,
                    "KNOWLEDGE_ADDED",
                    ctx,
                    actor_kind="llm",
                    actor="analyst",
                    llm=result.attribution,
                    inputs={"interpretation_id": str(interpretation_id)},
                    payload={"item_id": str(item_id)} | item.model_dump(mode="json"),
                )
        final = interpretation.model_dump(mode="json")
        if sampled:
            final = await self._challenge(gen, interpretation_id, interpretation, report_json)
        self._apply_implications(gen, final)

    async def _challenge(
        self, gen: Generation, interpretation_id: UUID, interpretation: Any, reports: list[Any]
    ) -> dict[str, Any]:
        env, ctx = self.env, gen.ctx
        payload = interpretation.model_dump(mode="json")
        prompt = env.prompts.render(
            "interpretation_review",
            {
                "interpretation": _compact({"interpretation_id": str(interpretation_id)} | payload),
                "reports": _compact(reports),
            },
            budget_chars=self._budget_chars(gen),
            trimmable=("reports",),
        )
        result = await self._call(
            gen,
            "interp_review",
            prompt,
            InterpretationChallenge,
            ctx,
            inputs={"interpretation_id": str(interpretation_id)},
        )
        status, final = "final", dict(payload)
        if result is not None and result.output.verdict == "amend":
            status = "amended"
            final = payload | {"amended_text": result.output.amended_text}
        with env.db.transaction() as conn:
            if result is not None:
                require_write(env, "interp_review", "interpretation_challenge", ctx)
                challenge_id = uuid7()
                conn.execute(
                    text(
                        "INSERT INTO interpretation_challenges (challenge_id, interpretation_id, "
                        "payload, verdict, run_id, created_at) VALUES (:c, :i, CAST(:p AS jsonb), "
                        ":v, :run, :now)"
                    ),
                    {
                        "c": challenge_id,
                        "i": interpretation_id,
                        "p": dumps(result.output.model_dump(mode="json")),
                        "v": result.output.verdict,
                        "run": result.run_id,
                        "now": env.clock.now(),
                    },
                )
                env.trace.step(
                    conn,
                    "INTERPRETATION_CHALLENGED",
                    ctx,
                    actor_kind="llm",
                    actor="interp_review",
                    llm=result.attribution,
                    inputs={"interpretation_id": str(interpretation_id)},
                    payload={"challenge_id": str(challenge_id)}
                    | result.output.model_dump(mode="json"),
                )
            conn.execute(
                text(
                    "UPDATE interpretations SET status = :s, final_payload = CAST(:f AS jsonb), "
                    "updated_at = :now WHERE interpretation_id = :i"
                ),
                {"s": status, "f": dumps(final), "now": env.clock.now(), "i": interpretation_id},
            )
        return final

    def _apply_implications(self, gen: Generation, interpretation: dict[str, Any]) -> None:
        with self.env.db.transaction() as conn:
            for implication in interpretation.get("implications", []):
                conn.execute(
                    text(
                        "UPDATE hypotheses SET status = :s, updated_at = :now WHERE "
                        "hypothesis_id = :h AND program_id = :p AND status <> 'retired'"
                    ),
                    {
                        "s": implication["effect"],
                        "now": self.env.clock.now(),
                        "h": implication["hypothesis_id"],
                        "p": gen.program_id,
                    },
                )

    # PROPOSING and PLANNING ------------------------------------------------------------

    def _islands(self, gen: Generation) -> tuple[list[str], dict[str, str]]:
        with self.env.db.read() as conn:
            rows = conn.execute(
                text(
                    "SELECT island_key, theme, guidance, status FROM islands WHERE program_id = :p "
                    "ORDER BY island_key"
                ),
                {"p": gen.program_id},
            ).all()
        active = [r.island_key for r in rows if r.status == "active"]
        themes = {r.island_key: r.theme + (f" ({r.guidance})" if r.guidance else "") for r in rows}
        return active, themes

    def _strategy_parents(self, gen: Generation) -> list[str]:
        with self.env.db.read() as conn:
            rows = conn.execute(
                text(
                    "SELECT v.version_id FROM candidate_versions v JOIN candidates c ON "
                    "c.candidate_id = v.candidate_id WHERE c.program_id = :p AND c.kind = 'factor' "
                    "ORDER BY v.published_at"
                ),
                {"p": gen.program_id},
            ).all()
            seeds: list[str] = conn.execute(
                text("SELECT seed_version_ids FROM research_jobs WHERE job_id = :j"),
                {"j": gen.job_id},
            ).scalar_one()
        return [str(r.version_id) for r in rows] + [str(s) for s in seeds or []]

    def _stored_proposal(self, gen: Generation) -> Proposal | None:
        with self.env.db.read() as conn:
            stored = conn.execute(
                text("SELECT proposal FROM generations WHERE generation_id = :g"),
                {"g": gen.generation_id},
            ).scalar()
        return None if stored is None else Proposal.from_json(stored)

    def _stored_plan(self, gen: Generation) -> GenerationPlan:
        with self.env.db.read() as conn:
            stored: dict[str, Any] = conn.execute(
                text("SELECT plan FROM generations WHERE generation_id = :g"),
                {"g": gen.generation_id},
            ).scalar_one()
        return GenerationPlan.model_validate(stored)

    async def _proposing(self, gen: Generation) -> None:
        """The engine updates the population, fitness, the archive and the bandit, then
        proposes the generation (Section 11.6); every value it used is in the step."""
        env = self.env
        refresh = self.engine.refresh(gen.ref)
        per_task, remaining = self._task_estimate(gen), self._remaining(gen)
        proposal = self.engine.propose(
            gen.ref, refresh, self._strategy_parents(gen), remaining, per_task
        )
        body = proposal.as_json()
        with env.db.transaction() as conn:
            conn.execute(
                text(
                    "UPDATE generations SET proposal = CAST(:p AS jsonb) WHERE generation_id = :g"
                ),
                {"p": dumps(body), "g": gen.generation_id},
            )
            env.trace.step(
                conn,
                "PROPOSAL_EMITTED",
                gen.ctx,
                actor="evolution-engine",
                inputs={"charter_version": gen.charter_version, "seq": gen.seq},
                payload=body | {"refresh": refresh},
            )
        env.logger.logger.info(
            "proposal_emitted",
            outcome="ok",
            payload={
                "publication_slots": proposal.publication_slots,
                "allocations": proposal.allocations,
                "operator_mix": proposal.operator_mix,
                "guardrail": proposal.engine.get("guardrail"),
                "stagnant_islands": proposal.stagnant_islands,
                "archive_coverage": refresh["archive"]["coverage"],
                "tasks": len(proposal.default_plan.tasks),
            },
            **gen.ctx.log_ids(),
        )

    def _task_estimate(self, gen: Generation) -> Decimal:
        """A planning estimate per task: one call per LLM role a task uses, each priced
        at its primary model's current rate for a full prompt and a full output."""
        env, now = self.env, self.env.clock.now()
        total = Decimal(0)
        context = int(gen.charter.get("context_tokens", 12000))
        for role in ("hypothesis", "engineer", "critic"):
            ref = env.planner.chain(role)[0]
            if env.prices.missing(ref):
                continue
            plan = env.planner.plan(role, ref)
            total += env.prices.quote(ref, now).estimate(context, plan.max_tokens)
        return total

    def _remaining(self, gen: Generation) -> Decimal:
        with self.env.db.read() as conn:
            return self.env.ledger.remaining(conn, gen.ctx, self.env.clock.now()).amount

    async def _planning(self, gen: Generation) -> None:
        env = self.env
        proposal = self._stored_proposal(gen)
        if proposal is None:  # a generation resumed from before its proposal was stored
            await self._proposing(gen)
            proposal = self._stored_proposal(gen)
            assert proposal is not None
        per_task, remaining = self._task_estimate(gen), self._remaining(gen)
        plan: GenerationPlan | None = None
        source = "fallback"
        notes = ""
        for attempt in ("supervisor", "repaired"):
            prompt = env.prompts.render(
                "supervisor",
                self._supervisor_values(gen, proposal, remaining, notes),
                budget_chars=self._budget_chars(gen),
                trimmable=("report_digests", "hypotheses", "knowledge"),
            )
            try:
                result = await self._call(
                    gen,
                    "supervisor",
                    prompt,
                    GenerationPlan,
                    gen.ctx,
                    raise_failures=True,
                    inputs={"proposal": "generations.proposal", "attempt": attempt},
                )
            except RoleFailed:
                break
            assert result is not None
            verdict = validate_plan(result.output, proposal, remaining, per_task)
            with env.db.transaction() as conn:
                env.trace.step(
                    conn,
                    "PLAN_WRITTEN",
                    gen.ctx,
                    actor_kind="llm",
                    actor="supervisor",
                    llm=result.attribution,
                    inputs={"attempt": attempt},
                    payload={
                        "plan": result.output.model_dump(mode="json"),
                        "stagnation_choice": stagnation_choices(result.output, proposal),
                    },
                )
                env.trace.step(
                    conn,
                    "PLAN_VALIDATED",
                    gen.ctx,
                    actor="plan-validator",
                    inputs={"attempt": attempt, "values": verdict.values},
                    payload={"valid": verdict.valid, "violations": verdict.violations},
                    outcome="ok" if verdict.valid else "failed",
                )
            if verdict.valid:
                plan, source = result.output, attempt
                break
            notes = "Your previous plan was rejected for: " + "; ".join(verdict.violations)
        if plan is None:
            plan = fit_to_budget(proposal.default_plan, remaining, per_task)
            with env.db.transaction() as conn:
                env.trace.step(
                    conn,
                    "PLAN_WRITTEN",
                    gen.ctx,
                    actor="plan-fallback",
                    inputs={"source": "proposal.default_plan"},
                    payload={
                        "plan": plan.model_dump(mode="json"),
                        "stagnation_choice": stagnation_choices(plan, proposal),
                    },
                )
        self._store_plan(gen, plan, source, proposal)

    def _store_plan(
        self, gen: Generation, plan: GenerationPlan, source: str, proposal: Proposal
    ) -> None:
        env, now = self.env, self.env.clock.now()
        for island, choice in stagnation_choices(plan, proposal).items():
            env.logger.logger.info(
                "island_stagnation_handled",
                outcome="ok" if choice != "unhandled" else "failed",
                payload={"island": island, "choice": choice, "plan_source": source},
                **gen.ctx.log_ids(),
            )
        with env.db.transaction() as conn:
            require_write(env, "supervisor", "plan", gen.ctx)
            conn.execute(
                text(
                    "UPDATE generations SET plan = CAST(:p AS jsonb), plan_source = :s, "
                    "updated_at = :now WHERE generation_id = :g"
                ),
                {
                    "p": dumps(plan.model_dump(mode="json")),
                    "s": source,
                    "now": now,
                    "g": gen.generation_id,
                },
            )
            for pause in plan.islands_to_pause:
                conn.execute(
                    text(
                        "UPDATE islands SET status = 'paused', paused_reason = :r, "
                        "paused_seq = :seq WHERE program_id = :p AND island_key = :k"
                    ),
                    {"p": gen.program_id, "k": pause.island_id, "r": pause.reason, "seq": gen.seq},
                )
            for ordinal, task in enumerate(plan.tasks):
                require_write(env, "supervisor", "task", gen.ctx)
                conn.execute(
                    text(
                        "INSERT INTO tasks (task_id, generation_id, ordinal, type, island_key, "
                        "brief, parent_version_ids, hypothesis_id, max_candidates, state, "
                        "created_at, updated_at) VALUES (:t, :g, :o, :ty, :i, :b, "
                        "CAST(:pv AS jsonb), :h, :m, 'pending', :now, :now) "
                        "ON CONFLICT (generation_id, ordinal) DO NOTHING"
                    ),
                    {
                        "t": uuid7(),
                        "g": gen.generation_id,
                        "o": ordinal,
                        "ty": task.type,
                        "i": task.island_id,
                        "b": task.brief,
                        "pv": dumps([str(p) for p in task.parent_version_ids]),
                        "h": task.hypothesis_id,
                        "m": task.max_candidates,
                        "now": now,
                    },
                )

    def _supervisor_values(
        self, gen: Generation, proposal: Proposal, remaining: Decimal, notes: str
    ) -> dict[str, str]:
        with self.env.db.read() as conn:
            reports = conn.execute(
                text(
                    "SELECT version_id, report_type, content -> 'content' AS content FROM "
                    "report_cache WHERE program_id = :p ORDER BY released_at LIMIT 200"
                ),
                {"p": gen.program_id},
            ).all()
            hypotheses = conn.execute(
                text(
                    "SELECT hypothesis_id, island_key, status, payload ->> 'title' AS title FROM "
                    "hypotheses WHERE program_id = :p AND status IN ('open', 'supported') "
                    "ORDER BY created_at LIMIT 100"
                ),
                {"p": gen.program_id},
            ).all()
        proposal_json = supervisor_view(proposal)
        return {
            "max_slots": str(proposal.max_slots),
            "min_explore_share": f"{proposal.min_explore_share:.2f}",
            "charter": charter_text(gen.charter),
            "budget": f"{remaining:.2f} {self.env.config.providers.budget['currency']} remaining",
            "proposal": _compact(proposal_json) + (f"\n{notes}" if notes else ""),
            "report_digests": "\n".join(
                f"- {r.version_id} {r.report_type}: {_compact(r.content)}" for r in reports
            )
            or "none yet",
            "hypotheses": "\n".join(
                f"- {h.hypothesis_id} [{h.island_key}, {h.status}] {h.title}" for h in hypotheses
            )
            or "none yet",
            "knowledge": self._knowledge_text(gen),
        }

    def _knowledge_text(self, gen: Generation) -> str:
        with self.env.db.read() as conn:
            rows = conn.execute(
                text(
                    "SELECT kind, statement FROM knowledge_items WHERE program_id = :p "
                    "ORDER BY created_at LIMIT 50"
                ),
                {"p": gen.program_id},
            ).all()
        return "\n".join(f"- [{r.kind}] {r.statement}" for r in rows) or "none yet"

    # DEVELOPING ------------------------------------------------------------------------

    async def _developing(self, gen: Generation) -> None:
        with self.env.db.read() as conn:
            tasks = conn.execute(
                text(
                    "SELECT * FROM tasks WHERE generation_id = :g AND state IN ('pending', "
                    "'running') ORDER BY ordinal"
                ),
                {"g": gen.generation_id},
            ).all()
        semaphore = asyncio.Semaphore(int(gen.charter["throughput"]["concurrency"]))
        stop: list[str] = []

        async def guarded(task: Any) -> None:
            async with semaphore:
                if stop:
                    self._task_state(task.task_id, "skipped", {"reason": stop[0]})
                    return
                try:
                    await self._run_task(gen, task)
                except Stop as halt:
                    stop.append(halt.reason)
                    self._task_state(task.task_id, "failed", {"reason": halt.reason}, halt.reason)

        await asyncio.gather(*(guarded(t) for t in tasks))
        if stop:
            raise Stop(stop[0])

    def _task_state(
        self,
        task_id: UUID,
        state: str,
        result: dict[str, Any] | None = None,
        error: str | None = None,
        attempt: bool = False,
    ) -> None:
        with self.env.db.transaction() as conn:
            conn.execute(
                text(
                    "UPDATE tasks SET state = :s, result = coalesce(CAST(:r AS jsonb), result), "
                    "error_code = :e, attempts = attempts + :a, updated_at = :now "
                    "WHERE task_id = :t"
                ),
                {
                    "s": state,
                    "r": None if result is None else dumps(result),
                    "e": error,
                    "a": 1 if attempt else 0,
                    "now": self.env.clock.now(),
                    "t": task_id,
                },
            )

    async def _run_task(self, gen: Generation, task: Any) -> None:
        ctx = gen.ctx.with_(task_id=task.task_id)
        self._task_state(task.task_id, "running", attempt=True)
        try:
            if task.type == "explore":
                result = await self._explore(gen, task, ctx)
            elif task.type in ("llm_mutation", "crossover", "repair"):
                result = await self._vary(gen, task, ctx)
            elif task.type == "syntactic_batch":
                result = self._syntactic(gen, task, ctx)
            elif task.type == "compose_strategy":
                result = await self._compose(gen, task, ctx)
            else:  # pragma: no cover - the plan validator and the schema forbid it
                self._task_state(task.task_id, "skipped", {"reason": "UNKNOWN_TASK_TYPE"})
                return
        except (Stop, BudgetExceeded):
            raise
        except Exception as error:  # noqa: BLE001 - a failed task never fails the generation
            self.env.logger.logger.error(
                "task_failed",
                outcome="failed",
                error_code=type(error).__name__.upper(),
                payload={"message": str(error)[:500], "type": task.type},
                **ctx.log_ids(),
            )
            self._task_state(
                task.task_id, "failed", {"error": str(error)[:500]}, type(error).__name__.upper()
            )
            return
        self._task_state(task.task_id, "done", result)

    def _settings(self, gen: Generation) -> dict[str, Any]:
        return self.engine.settings(gen.charter)

    def _assemble(self, gen: Generation, island: str, parents: list[str]) -> Context:
        with self.env.db.read() as conn:
            seeds: list[str] | None = conn.execute(
                text("SELECT seed_version_ids FROM research_jobs WHERE job_id = :j"),
                {"j": gen.job_id},
            ).scalar_one()
            return self.context.assemble(
                conn,
                gen.program_id,
                island,
                parents,
                self._settings(gen),
                str(gen.charter.get("mode", "new_factors")),
                [str(s) for s in seeds or []],
            )

    async def _explore(self, gen: Generation, task: Any, ctx: Ctx) -> dict[str, Any]:
        env = self.env
        _, themes = self._islands(gen)
        similar = self._similar_hypotheses(gen, task.island_key)
        prompt = env.prompts.render(
            "hypothesis",
            {
                "charter": charter_text(gen.charter),
                "island": task.island_key,
                "theme": themes.get(task.island_key, ""),
                "task_brief": task.brief,
                "similar": similar["text"],
                "knowledge": self._knowledge_text(gen),
            },
            budget_chars=self._budget_chars(gen),
            trimmable=("similar", "knowledge"),
        )
        result = await self._call(
            gen,
            "hypothesis",
            prompt,
            HypothesisBatch,
            ctx,
            raise_failures=True,
            inputs={"similar_hypothesis_ids": similar["ids"]},
        )
        assert result is not None
        hypotheses: list[tuple[UUID, Any]] = []
        with env.db.transaction() as conn:
            for hypothesis in result.output.hypotheses:
                require_write(env, "hypothesis", "hypothesis", ctx)
                hypothesis_id = uuid7()
                hypothesis = hypothesis.model_copy(update={"island_id": task.island_key})
                conn.execute(
                    text(
                        "INSERT INTO hypotheses (hypothesis_id, program_id, island_key, task_id, "
                        "payload, status, source, created_at, updated_at) VALUES (:h, :p, :i, :t, "
                        "CAST(:pl AS jsonb), 'open', 'agent', :now, :now)"
                    ),
                    {
                        "h": hypothesis_id,
                        "p": gen.program_id,
                        "i": task.island_key,
                        "t": task.task_id,
                        "pl": dumps(hypothesis.model_dump(mode="json")),
                        "now": env.clock.now(),
                    },
                )
                env.trace.step(
                    conn,
                    "HYPOTHESIS_PROPOSED",
                    ctx,
                    actor_kind="llm",
                    actor="hypothesis",
                    llm=result.attribution,
                    inputs={"similar_hypothesis_ids": similar["ids"], "task_brief": task.brief},
                    payload={"hypothesis_id": str(hypothesis_id)}
                    | hypothesis.model_dump(mode="json"),
                )
                hypotheses.append((hypothesis_id, hypothesis))
        brief = EngineerBrief(
            operator="explore",
            hypotheses=hypotheses,
            hypothesis_text="\n".join(
                f"- hypothesis_id {h}: {_compact(p.model_dump(mode='json'))}" for h, p in hypotheses
            ),
            parents=[],
            context=self._assemble(gen, task.island_key, []),
        )
        drafts_result = await self._engineer(gen, task, ctx, brief, None, None)
        candidates: list[UUID] = []
        for draft in drafts_result.output.drafts[: task.max_candidates]:
            known = {h for h, _ in hypotheses}
            corrected = draft.hypothesis_id not in known
            chosen: UUID = (
                hypotheses[0][0]
                if corrected or draft.hypothesis_id is None
                else draft.hypothesis_id
            )
            candidate_id = self._create_candidate(
                gen, task, ctx, draft, chosen, drafts_result, None, 1, corrected, brief
            )
            candidates.append(candidate_id)
        outcomes = []
        for candidate_id in candidates:
            outcomes.append(await self._develop(gen, task, ctx, candidate_id, brief, 1))
        return {
            "hypotheses": [str(h) for h, _ in hypotheses],
            "candidates": [str(c) for c in candidates],
            "outcomes": outcomes,
        }

    async def _vary(self, gen: Generation, task: Any, ctx: Ctx) -> dict[str, Any]:
        """llm_mutation, crossover and repair: the engineer revises, merges or repairs
        the task's parents (Section 12.4), with their released digests, the targeted
        instructions for their flags and the assembled context."""
        env = self.env
        parents = [str(p) for p in task.parent_version_ids]
        context = self._assemble(gen, task.island_key, parents)
        missing = [p for p in parents if p not in context.parents]
        if missing:
            return {"skipped": "PARENTS_UNAVAILABLE", "parent_version_ids": missing}
        proposal = self._stored_proposal(gen)
        settings = self._settings(gen)
        variation = settings["variation"]
        selection = None if proposal is None else proposal.selection_for(task.type, parents)
        digests = {p: context.parents[p]["digest"] for p in parents}
        flags = sorted(
            {f for d in digests.values() for f in (d.get("w1") or {}).get("flags") or []}
        )
        with env.db.transaction() as conn:
            env.trace.step(
                conn,
                "PARENT_SELECTED",
                ctx,
                actor="evolution-engine",
                inputs={"operator": task.type, "parent_version_ids": parents},
                payload={
                    "selection": selection or {"rule": "supervisor_choice"},
                    "parents": [
                        {
                            "version_id": p,
                            "expression": context.parents[p]["expression"],
                            "released": digests[p],
                            "proposal": None if proposal is None else proposal.parent_info.get(p),
                        }
                        for p in parents
                    ],
                    "targeted_flags": flags,
                },
            )
        if task.type == "llm_mutation":
            targeted = [
                str(variation["targeted_instructions"][f])
                for f in flags
                if f in variation["targeted_instructions"]
            ] or [str(variation["generic_instruction"])]
            instructions = env.prompts.render(
                "mutation",
                {"targeted": "\n".join(f"- {t}" for t in targeted)},
                budget_chars=self._budget_chars(gen),
            )
        elif task.type == "crossover":
            instructions = env.prompts.render("crossover", {}, budget_chars=self._budget_chars(gen))
        else:
            reasons = sorted(
                {
                    r
                    for d in digests.values()
                    for key in ("screening", "intake")
                    for r in (d.get(key) or {}).get("reasons") or []
                }
            )
            instructions = env.prompts.render(
                "repair",
                {"reasons": "\n".join(f"- {r}" for r in reasons) or "- not released"},
                budget_chars=self._budget_chars(gen),
            )
        with env.db.read() as conn:
            inherited = task.hypothesis_id or parent_hypothesis(conn, parents[0])
        brief = EngineerBrief(
            operator=task.type,
            hypotheses=[],
            hypothesis_text=context.hypothesis_text,
            parents=parents,
            context=context,
            instructions=instructions,
            targeted_flags=flags,
            inherited_hypothesis=inherited,
        )
        drafts_result = await self._engineer(gen, task, ctx, brief, None, None)
        candidates: list[UUID] = []
        for draft in drafts_result.output.drafts[: task.max_candidates]:
            corrected = draft.hypothesis_id != inherited
            candidate_id = self._create_candidate(
                gen, task, ctx, draft, inherited, drafts_result, None, 1, corrected, brief
            )
            candidates.append(candidate_id)
        outcomes = []
        for candidate_id in candidates:
            outcomes.append(await self._develop(gen, task, ctx, candidate_id, brief, 1))
        return {
            "parents": parents,
            "targeted_flags": flags,
            "candidates": [str(c) for c in candidates],
            "outcomes": outcomes,
        }

    def _syntactic(self, gen: Generation, task: Any, ctx: Ctx) -> dict[str, Any]:
        """A syntactic batch: the engine's ready-made deterministic variants become
        candidates with no LLM call (Section 12.4). They inherit the parent's rationale,
        get an auto-generated change summary and go through the same automated checks;
        the critic does not review them (Section 14.5 lists no LLM steps for them)."""
        proposal = self._stored_proposal(gen)
        if proposal is None:
            return {"skipped": "NO_PROPOSAL"}
        plan = self._stored_plan(gen)
        variants = assign_variants(plan.tasks, proposal).get(task.ordinal, [])
        outcomes = []
        for variant in variants:
            candidate_id = self._create_variant(gen, task, ctx, variant)
            if candidate_id is None:
                outcomes.append({"variant_id": variant["variant_id"], "state": "skipped"})
                continue
            checks = self._checks(gen, ctx, candidate_id)
            state = "invalid" if checks is None else "approved"
            if checks is not None:
                self._candidate(candidate_id, state="approved", review_rounds=0)
            outcomes.append(
                {
                    "variant_id": variant["variant_id"],
                    "candidate_id": str(candidate_id),
                    "state": state,
                }
            )
        return {"variants": [v["variant_id"] for v in variants], "outcomes": outcomes}

    def _create_variant(
        self, gen: Generation, task: Any, ctx: Ctx, variant: dict[str, Any]
    ) -> UUID | None:
        env = self.env
        parents = list(variant["parent_version_ids"])
        first = self.context.parent_manifest(parents[0])
        if first is None:
            return None
        operator = variant["operator"]  # syntactic_mutation, or crossover on a low LLM budget
        with env.db.read() as conn:
            hypothesis_id = parent_hypothesis(conn, parents[0])
        details = variant.get("details") or {}
        summary = (
            f"Deterministic {variant['rule']} (seed {variant['seed']}, attempt "
            f"{variant['attempt']}): {_compact(details)}. Auto-generated change summary; "
            "the rationale is inherited from the parent."
        )
        rationale = first["rationale"]
        payload = {
            "title": first["title"],
            "expression": variant["expression"],
            "description": str(rationale.get("summary") or first["title"])[:2000],
            "expected_sign": int(first["declared"]["expected_sign"]),
            "horizon_days": int(first["declared"]["horizon_days"]),
            "parameter_rationale": "Inherited from the parent; the change is deterministic.",
            "operator": operator,
            "parent_version_ids": parents,
            "change_summary": summary[:600],
            "auto_change_summary": True,
            "deterministic": True,
            "inherited_rationale": {
                k: rationale.get(k)
                for k in ("hypothesis_id", "summary", "mechanism", "falsification")
            }
            | {"from_version_id": parents[0]},
            "variant": {
                k: variant[k] for k in ("variant_id", "rule", "seed", "attempt", "canonical_hash")
            },
        }
        candidate_id = uuid7()
        cctx = ctx.with_(candidate_id=candidate_id)
        with env.db.transaction() as conn:
            require_write(env, "evolution", "population_member", cctx)
            conn.execute(
                text(
                    "INSERT INTO candidates (candidate_id, program_id, generation_id, task_id, "
                    "hypothesis_id, island_key, kind, operator, expression, payload, state, "
                    "review_rounds, created_at, updated_at) VALUES (:c, :p, :g, :t, :h, :i, "
                    "'factor', :o, :e, CAST(:pl AS jsonb), 'drafted', 0, :now, :now)"
                ),
                {
                    "c": candidate_id,
                    "p": gen.program_id,
                    "g": gen.generation_id,
                    "t": task.task_id,
                    "h": hypothesis_id,
                    "i": task.island_key,
                    "o": operator,
                    "e": variant["expression"],
                    "pl": dumps(payload),
                    "now": env.clock.now(),
                },
            )
            env.trace.step(
                conn,
                "PARENT_SELECTED",
                cctx,
                actor="evolution-engine",
                inputs={"operator": operator, "parent_version_ids": parents},
                payload={
                    "selection": variant.get("selection"),
                    "variant_id": variant["variant_id"],
                },
            )
            env.trace.step(
                conn,
                "CROSSOVER_APPLIED" if operator == "crossover" else "SYNTACTIC_MUTATION_APPLIED",
                cctx,
                actor="evolution-engine",
                inputs={
                    "parent_version_ids": parents,
                    "rule": variant["rule"],
                    "seed": variant["seed"],
                },
                payload={
                    "rule": variant["rule"],
                    "seed": variant["seed"],
                    "attempt": variant["attempt"],
                    "expressions_before": variant["expressions_before"],
                    "expression_after": variant["expression"],
                    "ast_diffs": variant["ast_diffs"],
                    "details": details,
                    "change_summary": payload["change_summary"],
                    "deterministic": True,
                    "reason": variant.get("reason"),
                },
            )
        return candidate_id

    def _similar_hypotheses(self, gen: Generation, island: str) -> dict[str, Any]:
        with self.env.db.read() as conn:
            rows = conn.execute(
                text(
                    "SELECT hypothesis_id, status, payload ->> 'title' AS title, "
                    "payload ->> 'mechanism' AS mechanism FROM hypotheses WHERE program_id = :p "
                    "AND island_key = :i ORDER BY created_at LIMIT 20"
                ),
                {"p": gen.program_id, "i": island},
            ).all()
        return {
            "ids": [str(r.hypothesis_id) for r in rows],
            "text": "\n".join(f"- [{r.status}] {r.title}: {r.mechanism}" for r in rows)
            or "none yet",
        }

    async def _engineer(
        self,
        gen: Generation,
        task: Any,
        ctx: Ctx,
        brief: EngineerBrief,
        previous: Any,
        review: ReviewVerdict | None,
    ) -> RoleResult[EngineerOutput]:
        env = self.env
        _, themes = self._islands(gen)
        feedback = "none"
        if review is not None and previous is not None:
            feedback = _compact(
                {
                    "previous_expression": previous.expression,
                    "previous_description": previous.payload.get("description"),
                    "required_changes": review.required_changes,
                    "rationale": review.rationale,
                }
            )
        context = brief.context
        prompt = env.prompts.render(
            "engineer",
            {
                "max_candidates": str(1 if review is not None else task.max_candidates),
                "operator": brief.operator,
                "operator_instructions": "none (a new expression for the hypothesis)"
                if brief.instructions is None
                else brief.instructions.text.strip(),
                "charter": charter_text(gen.charter),
                "island": task.island_key,
                "theme": themes.get(task.island_key, ""),
                "hypothesis": brief.hypothesis_text,
                "task_brief": task.brief,
                "parents": "none" if context is None else context.parents_text,
                "context": "none" if context is None else context.context_text,
                "review_feedback": feedback,
                "dsl_card_version": env.card.version,
                "dsl_card": env.card.text,
            },
            budget_chars=self._budget_chars(gen),
            trimmable=("context", "hypothesis"),
        )
        inputs: dict[str, Any] = {
            "dsl_card_version": env.card.version,
            "hypothesis_ids": [str(h) for h, _ in brief.hypotheses],
            "operator": brief.operator,
            "parent_version_ids": brief.parents,
            "context": {} if context is None else context.included,
        }
        if brief.instructions is not None:
            inputs["operator_template"] = {
                "template_id": brief.instructions.template_id,
                "template_sha256": brief.instructions.template_sha256,
                "targeted_flags": brief.targeted_flags or [],
            }
        result = await self._call(
            gen, "engineer", prompt, EngineerOutput, ctx, raise_failures=True, inputs=inputs
        )
        assert result is not None
        return result

    def _create_candidate(
        self,
        gen: Generation,
        task: Any,
        ctx: Ctx,
        draft: CandidateDraft,
        hypothesis_id: UUID | None,
        engineer: RoleResult[EngineerOutput],
        parent_candidate: UUID | None,
        rounds: int,
        corrected: bool,
        brief: EngineerBrief,
    ) -> UUID:
        env = self.env
        candidate_id = uuid7()
        cctx = ctx.with_(candidate_id=candidate_id)
        operator = brief.operator
        payload = draft.model_dump(mode="json") | {
            "hypothesis_id": None if hypothesis_id is None else str(hypothesis_id),
            "operator": operator,
        }
        parents_corrected = False
        if operator != "explore":
            # The task's parents are the lineage, whatever the draft listed.
            parents_corrected = sorted(str(p) for p in draft.parent_version_ids) != sorted(
                brief.parents
            )
            payload["parent_version_ids"] = list(brief.parents)
            if not payload.get("change_summary"):
                payload["change_summary"] = (
                    "The engineer gave no change summary (recorded by the workflow)."
                )
                payload["auto_change_summary"] = True
            first = (brief.context.parents if brief.context else {}).get(brief.parents[0])
            if first is not None:
                payload.setdefault("title", first["title"])
            if hypothesis_id is None and first is not None:
                payload["inherited_rationale"] = {
                    k: first["rationale"].get(k)
                    for k in ("hypothesis_id", "summary", "mechanism", "falsification")
                } | {"from_version_id": brief.parents[0]}
        with env.db.transaction() as conn:
            require_write(env, "engineer", "candidate", cctx)
            conn.execute(
                text(
                    "INSERT INTO candidates (candidate_id, program_id, generation_id, task_id, "
                    "hypothesis_id, island_key, kind, operator, expression, payload, state, "
                    "review_rounds, engineer_run_id, parent_candidate_id, created_at, updated_at) "
                    "VALUES (:c, :p, :g, :t, :h, :i, 'factor', :o, :e, CAST(:pl AS jsonb), "
                    "'drafted', :r, :run, :parent, :now, :now)"
                ),
                {
                    "c": candidate_id,
                    "p": gen.program_id,
                    "g": gen.generation_id,
                    "t": task.task_id,
                    "h": hypothesis_id,
                    "i": task.island_key,
                    "o": operator,
                    "e": draft.expression,
                    "pl": dumps(payload),
                    "r": rounds - 1,
                    "run": engineer.run_id,
                    "parent": parent_candidate,
                    "now": env.clock.now(),
                },
            )
            env.trace.step(
                conn,
                "DRAFT_CREATED",
                cctx,
                actor_kind="llm",
                actor="engineer",
                llm=engineer.attribution,
                inputs={
                    "dsl_card_version": env.card.version,
                    "hypothesis_id": None if hypothesis_id is None else str(hypothesis_id),
                    "parent_candidate_id": None
                    if parent_candidate is None
                    else str(parent_candidate),
                },
                payload={
                    "draft": payload,
                    "tool_calls": engineer.tool_calls,
                    "hypothesis_id_corrected": corrected,
                    "parents_corrected": parents_corrected,
                },
            )
            if operator in APPLIED_STEP:
                env.trace.step(
                    conn,
                    APPLIED_STEP[operator],
                    cctx,
                    actor="evolution-engine",
                    inputs={
                        "parent_version_ids": brief.parents,
                        "engineer_run_id": str(engineer.run_id),
                    },
                    payload=self._applied(brief, draft.expression, payload),
                )
            if parent_candidate is not None:
                env.trace.step(
                    conn,
                    "REVISED",
                    cctx,
                    actor_kind="llm",
                    actor="engineer",
                    llm=engineer.attribution,
                    inputs={"parent_candidate_id": str(parent_candidate)},
                    payload={"expression": draft.expression, "round": rounds},
                )
        return candidate_id

    def _applied(
        self, brief: EngineerBrief, expression: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """The operator application as research code records it: each parent's canonical
        expression, the child's, and the deterministic AST diff from each parent."""
        parents = brief.context.parents if brief.context else {}
        before = [str(parents[p]["expression"]) for p in brief.parents if p in parents]
        body: dict[str, Any] = {
            "operator": brief.operator,
            "parent_version_ids": brief.parents,
            "targeted_flags": brief.targeted_flags or [],
            "instructions_template": None
            if brief.instructions is None
            else brief.instructions.template_id,
            "change_summary": payload.get("change_summary"),
            "auto_change_summary": bool(payload.get("auto_change_summary")),
        }
        try:
            child = canonicalize(parse(expression))
            trees = [canonicalize(parse(b)) for b in before]
        except Exception as error:  # noqa: BLE001 - DSL_VALIDATED records the failure
            return body | {
                "expressions_before": before,
                "expression_after": expression,
                "ast_diffs": None,
                "parse_error": str(error)[:300],
            }
        from qfr_core.dsl import to_string

        return body | {
            "expressions_before": [to_string(t) for t in trees],
            "expression_after": to_string(child),
            "ast_diffs": [[dict(e) for e in ast_diff(t, child)] for t in trees],
        }

    def _checks(self, gen: Generation, ctx: Ctx, candidate_id: UUID) -> dict[str, Any] | None:
        """Automated checks: dsl.validate, the workbench pre-screen and similarity."""
        env = self.env
        cctx = ctx.with_(candidate_id=candidate_id)
        with env.db.read() as conn:
            row = conn.execute(
                text("SELECT expression, payload FROM candidates WHERE candidate_id = :c"),
                {"c": candidate_id},
            ).one()
        deps = ToolDeps(env, "evolution", cctx)
        validation = invoke(
            deps, "dsl.validate", step_type="DSL_VALIDATED", expression=row.expression
        )
        if not validation.get("ok"):
            self._candidate(candidate_id, state="invalid", reason="DSL_INVALID")
            return None
        analysis = validation["analysis"]
        sign = int(row.payload.get("expected_sign", 1))
        workbench = invoke(
            deps,
            "workbench.evaluate",
            step_type="WORKBENCH_EVALUATED",
            expression=row.expression,
            expected_sign=sign,
        )
        similarity = invoke(
            deps, "similarity.search", step_type="SIMILARITY_CHECKED", expression=row.expression
        )
        self._candidate(
            candidate_id,
            analysis=analysis,
            canonical_hash=analysis["canonical_hash"],
            workbench=workbench,
            similarity={k: v for k, v in similarity.items() if k != "nearest"}
            | {"nearest": similarity.get("nearest", [])[:3]},
        )
        return {"analysis": analysis, "workbench": workbench, "similarity": similarity}

    def _candidate(self, candidate_id: UUID, **fields: Any) -> None:
        sets, params = [], {"c": candidate_id, "now": self.env.clock.now()}
        for key, value in fields.items():
            if key in ("analysis", "workbench", "similarity", "prescreen"):
                sets.append(f"{key} = CAST(:{key} AS jsonb)")
                params[key] = dumps(value)
            else:
                sets.append(f"{key} = :{key}")
                params[key] = value
        with self.env.db.transaction() as conn:
            conn.execute(
                text(
                    f"UPDATE candidates SET {', '.join(sets)}, updated_at = :now "
                    "WHERE candidate_id = :c"
                ),
                params,
            )

    async def _develop(
        self,
        gen: Generation,
        task: Any,
        ctx: Ctx,
        candidate_id: UUID,
        brief: EngineerBrief,
        round_no: int,
    ) -> dict[str, Any]:
        env = self.env
        cctx = ctx.with_(candidate_id=candidate_id)
        checks = self._checks(gen, ctx, candidate_id)
        if checks is None:
            return {"candidate_id": str(candidate_id), "state": "invalid"}
        with env.db.read() as conn:
            row = conn.execute(
                text(
                    "SELECT c.*, h.payload AS hypothesis, a.provider AS engineer_provider "
                    "FROM candidates c LEFT JOIN hypotheses h ON h.hypothesis_id = c.hypothesis_id "
                    "LEFT JOIN agent_runs a ON a.run_id = c.engineer_run_id "
                    "WHERE c.candidate_id = :c"
                ),
                {"c": candidate_id},
            ).one()
        max_rounds = int(gen.charter["throughput"]["review_rounds_max"])
        prompt = env.prompts.render(
            "critic",
            {
                "hypothesis": _compact(
                    row.hypothesis or (row.payload or {}).get("inherited_rationale") or {}
                ),
                "candidate": _compact(
                    {"expression": row.expression}
                    | {
                        k: row.payload.get(k)
                        for k in (
                            "description",
                            "expected_sign",
                            "horizon_days",
                            "parameter_rationale",
                        )
                    }
                ),
                "checks": _compact(
                    {
                        "analysis": checks["analysis"],
                        "workbench": checks["workbench"].get("metrics"),
                        "workbench_label": checks["workbench"].get("label"),
                    }
                ),
                "similar": _compact(checks["similarity"].get("nearest", [])[:5]),
                "round": str(round_no),
                "max_rounds": str(max_rounds),
            },
            budget_chars=self._budget_chars(gen),
            trimmable=("similar",),
        )
        review = await self._call(
            gen,
            "critic",
            prompt,
            ReviewVerdict,
            cctx,
            exclude_provider=row.engineer_provider,
            raise_failures=True,
            inputs={"engineer_provider": row.engineer_provider, "round": round_no},
        )
        assert review is not None
        verdict = review.output
        review_id = uuid7()
        with env.db.transaction() as conn:
            require_write(env, "critic", "review", cctx)
            conn.execute(
                text(
                    "INSERT INTO reviews (review_id, candidate_id, round, verdict, payload, "
                    "run_id, provider, created_at) VALUES (:r, :c, :n, :v, CAST(:p AS jsonb), "
                    ":run, :prov, :now)"
                ),
                {
                    "r": review_id,
                    "c": candidate_id,
                    "n": round_no,
                    "v": verdict.verdict,
                    "p": dumps(verdict.model_dump(mode="json")),
                    "run": review.run_id,
                    "prov": review.ref.provider,
                    "now": env.clock.now(),
                },
            )
            env.trace.step(
                conn,
                "CRITIC_REVIEWED",
                cctx,
                actor_kind="llm",
                actor="critic",
                llm=review.attribution,
                inputs={"round": round_no, "engineer_provider": row.engineer_provider},
                payload={"review_id": str(review_id)} | verdict.model_dump(mode="json"),
            )
        state = {"approve": "approved", "reject": "rejected"}.get(verdict.verdict)
        if state is not None:
            self._candidate(
                candidate_id,
                state=state,
                review_rounds=round_no,
                reason=None if state == "approved" else "CRITIC_REJECTED",
            )
            return {"candidate_id": str(candidate_id), "state": state, "rounds": round_no}
        if round_no >= max_rounds:
            self._candidate(
                candidate_id,
                state="rejected",
                review_rounds=round_no,
                reason="REVIEW_ROUNDS_EXHAUSTED",
            )
            return {"candidate_id": str(candidate_id), "state": "rejected", "rounds": round_no}
        with env.db.transaction() as conn:
            env.trace.step(
                conn,
                "REVISION_REQUESTED",
                cctx,
                actor="workflow",
                inputs={"review_id": str(review_id), "round": round_no},
                payload={"required_changes": verdict.required_changes},
            )
        self._candidate(candidate_id, state="rejected", review_rounds=round_no, reason="REVISED")
        revision = await self._engineer(gen, task, ctx, brief, row, verdict)
        draft = revision.output.drafts[0]
        new_id = self._create_candidate(
            gen,
            task,
            ctx,
            draft,
            row.hypothesis_id,
            revision,
            candidate_id,
            round_no + 1,
            draft.hypothesis_id != row.hypothesis_id,
            brief,
        )
        return await self._develop(gen, task, ctx, new_id, brief, round_no + 1)

    async def _compose(self, gen: Generation, task: Any, ctx: Ctx) -> dict[str, Any]:
        """compose_strategy: the engineer in strategy mode over the job's published
        factors and the seeds, then the same checks, review and states as factors."""
        env = self.env
        parents = self._strategy_parents(gen)
        spec = gen.charter.get("strategy_spec") or {}
        if not parents or not spec:
            return {"skipped": "NO_COMPONENTS"}
        components = []
        rationales: dict[str, dict[str, str]] = {}
        for version_id in parents[:40]:
            manifest = env.registry.version(UUID(version_id)).manifest
            expression = getattr(manifest.implementation, "expression", None)
            if expression:
                components.append(
                    {
                        "version_id": version_id,
                        "expression": expression,
                        "expected_sign": manifest.declared.expected_sign,
                        "title": manifest.title,
                    }
                )
                rationales[version_id] = {
                    "hypothesis_id": str(manifest.rationale.hypothesis_id),
                    "mechanism": manifest.rationale.mechanism,
                    "falsification": manifest.rationale.falsification,
                }
        prompt = env.prompts.render(
            "strategy",
            {
                "max_components": str(min(8, int(spec.get("max_components", 8)))),
                "top_k_min": "20",
                "top_k_max": "100",
                "dropout_min": "1",
                "dropout_max": "20",
                "charter": charter_text(gen.charter),
                "strategy_spec": _compact(spec),
                "components": "\n".join(f"- {_compact(c)}" for c in components),
            },
            budget_chars=self._budget_chars(gen),
            trimmable=("components",),
        )
        result = await self._call(
            gen,
            "engineer",
            prompt,
            StrategyDraft,
            ctx,
            raise_failures=True,
            inputs={"candidate_set": [c["version_id"] for c in components]},
        )
        assert result is not None
        draft = result.output
        known = {c["version_id"]: c for c in components}
        if not {str(c.version_id) for c in draft.components} <= set(known):
            return {"rejected": "UNKNOWN_COMPONENT"}
        candidate_id = uuid7()
        cctx = ctx.with_(candidate_id=candidate_id)
        payload = draft.model_dump(mode="json")
        payload["parent_version_ids"] = sorted(
            {str(c.version_id) for c in draft.components}
            | {str(p) for p in draft.parent_version_ids}
        )
        # Every manifest's rationale names a blackboard hypothesis. A composite tests the
        # hypothesis its task names or, when the task names none, that of its heaviest
        # component, whose mechanism and falsification the manifest inherits.
        lead = max(draft.components, key=lambda c: (c.weight, str(c.version_id)))
        payload["inherited_rationale"] = rationales[str(lead.version_id)] | (
            {"hypothesis_id": str(task.hypothesis_id)} if task.hypothesis_id else {}
        )
        payload["title"] = (
            f"Top-{draft.portfolio.top_k} strategy over {len(draft.components)} factor(s)"
        )
        payload["description"] = draft.composition_rationale
        with env.db.transaction() as conn:
            require_write(env, "engineer", "strategy_draft", cctx)
            env.trace.step(
                conn,
                "STRATEGY_COMPOSED",
                cctx,
                actor="evolution-engine",
                inputs={"candidate_set": [c["version_id"] for c in components]},
                payload={
                    "strategy_spec": spec,
                    "components": payload["components"],
                    "portfolio": payload["portfolio"],
                },
            )
            conn.execute(
                text(
                    "INSERT INTO candidates (candidate_id, program_id, generation_id, task_id, "
                    "island_key, kind, operator, components, payload, state, engineer_run_id, "
                    "created_at, updated_at) VALUES (:c, :p, :g, :t, :i, 'strategy', "
                    "'compose_strategy', CAST(:comp AS jsonb), CAST(:pl AS jsonb), 'drafted', "
                    ":run, :now, :now)"
                ),
                {
                    "c": candidate_id,
                    "p": gen.program_id,
                    "g": gen.generation_id,
                    "t": task.task_id,
                    "i": task.island_key,
                    "comp": dumps(payload["components"]),
                    "pl": dumps(payload),
                    "run": result.run_id,
                    "now": env.clock.now(),
                },
            )
            env.trace.step(
                conn,
                "DRAFT_CREATED",
                cctx,
                actor_kind="llm",
                actor="engineer",
                llm=result.attribution,
                inputs={"mode": "strategy"},
                payload={"draft": payload, "tool_calls": result.tool_calls},
            )
        deps = ToolDeps(env, "evolution", cctx)
        for component in draft.components:
            invoke(
                deps,
                "dsl.validate",
                step_type="DSL_VALIDATED",
                expression=known[str(component.version_id)]["expression"],
            )
        from qfr_core.workbench import ComponentInput

        report = env.workbench.composite(
            [
                ComponentInput(known[str(c.version_id)]["expression"], c.sign, c.weight)
                for c in draft.components
            ],
            draft.portfolio.top_k,
            draft.portfolio.dropout,
        )
        workbench = {
            "visibility": report.visibility,
            "window": "W0",
            "metrics": {
                k: report.metrics.model_dump(mode="json").get(k)
                for k in ("rankic_mean", "rankic_ir", "coverage", "top_turnover")
            },
            "reference_sharpe": report.reference_strategy.sharpe,
        }
        with env.db.transaction() as conn:
            env.trace.step(
                conn,
                "WORKBENCH_EVALUATED",
                cctx,
                actor="tool:workbench.evaluate",
                inputs={"composite": True},
                payload=workbench,
            )
        similarity = self._strategy_similarity(gen, candidate_id, payload)
        with env.db.transaction() as conn:
            env.trace.step(
                conn,
                "SIMILARITY_CHECKED",
                cctx,
                actor="evolution-engine",
                inputs={"canonical_hash": similarity["canonical_hash"]},
                payload=similarity,
            )
        self._candidate(
            candidate_id,
            workbench=workbench,
            canonical_hash=similarity["canonical_hash"],
            similarity={"originality": similarity["originality"]},
        )
        prompt = env.prompts.render(
            "critic",
            {
                "hypothesis": _compact({"composition_rationale": draft.composition_rationale}),
                "candidate": _compact(payload),
                "checks": _compact({"workbench": workbench}),
                "similar": "[]",
                "round": "1",
                "max_rounds": "1",
            },
            budget_chars=self._budget_chars(gen),
        )
        review = await self._call(
            gen,
            "critic",
            prompt,
            ReviewVerdict,
            cctx,
            exclude_provider=result.ref.provider,
            raise_failures=True,
        )
        assert review is not None
        review_id = uuid7()
        with env.db.transaction() as conn:
            conn.execute(
                text(
                    "INSERT INTO reviews (review_id, candidate_id, round, verdict, payload, "
                    "run_id, provider, created_at) VALUES (:r, :c, 1, :v, CAST(:p AS jsonb), "
                    ":run, :prov, :now)"
                ),
                {
                    "r": review_id,
                    "c": candidate_id,
                    "v": review.output.verdict,
                    "p": dumps(review.output.model_dump(mode="json")),
                    "run": review.run_id,
                    "prov": review.ref.provider,
                    "now": env.clock.now(),
                },
            )
            env.trace.step(
                conn,
                "CRITIC_REVIEWED",
                cctx,
                actor_kind="llm",
                actor="critic",
                llm=review.attribution,
                inputs={"round": 1},
                payload={"review_id": str(review_id)} | review.output.model_dump(mode="json"),
            )
        state = "approved" if review.output.verdict == "approve" else "rejected"
        self._candidate(candidate_id, state=state, review_rounds=1)
        return {"candidate_id": str(candidate_id), "state": state}

    def _strategy_similarity(
        self, gen: Generation, candidate_id: UUID, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """A strategy's duplicate check: the canonical hash of its components (sorted, with
        signs and weights) and portfolio, against the program's other strategies. The
        evaluator measures behavioral similarity to the strategy library at W1."""
        canonical = {
            "components": sorted(
                (str(c["version_id"]), int(c["sign"]), float(c["weight"]))
                for c in payload["components"]
            ),
            "portfolio": payload["portfolio"],
        }
        digest = hashlib.sha256(
            json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        with self.env.db.read() as conn:
            twin = conn.execute(
                text(
                    "SELECT candidate_id FROM candidates WHERE program_id = :p AND kind = "
                    "'strategy' AND canonical_hash = :h AND candidate_id <> :c "
                    "ORDER BY created_at LIMIT 1"
                ),
                {"p": gen.program_id, "h": digest, "c": candidate_id},
            ).scalar()
        return {
            "canonical_hash": digest,
            "duplicate_of": None if twin is None else str(twin),
            "originality": 0.0 if twin is not None else 1.0,
        }

    # SELECTING and PUBLISHING ----------------------------------------------------------

    async def _selecting(self, gen: Generation) -> None:
        """Section 11.6 SELECTING (P5.5): pre-screen, canonical dedup against the
        program's publications and the population, behavioral dedup within the batch,
        then provisional fitness with per-island fairness up to the quota."""
        env = self.env
        settings = self._settings(gen)
        thresholds = settings["prescreen"]
        constraints = dict(gen.charter.get("constraints") or {})
        proposal = self._stored_proposal(gen)
        with env.db.read() as conn:
            rows = conn.execute(
                text(
                    "SELECT * FROM candidates WHERE generation_id = :g AND state = 'approved' "
                    "ORDER BY created_at"
                ),
                {"g": gen.generation_id},
            ).all()
            published = {
                r.canonical_hash
                for r in conn.execute(
                    text(
                        "SELECT c.canonical_hash FROM candidates c JOIN candidate_versions v ON "
                        "v.candidate_id = c.candidate_id WHERE c.program_id = :p"
                    ),
                    {"p": gen.program_id},
                ).all()
            }
            members = {
                r.hash
                for r in conn.execute(
                    text(
                        "SELECT DISTINCT analysis ->> 'canonical_hash' AS hash FROM "
                        "population_members WHERE program_id = :p"
                    ),
                    {"p": gen.program_id},
                ).all()
            }
        by_id = {r.candidate_id: r for r in rows}
        screened_all: list[Screened] = []
        reasons: dict[Any, str] = {}
        seen: set[str] = {h for h in published | members if h}
        for row in rows:
            screened = prescreen(row, thresholds, constraints)
            duplicate = row.canonical_hash is not None and row.canonical_hash in seen
            ctx = gen.ctx.with_(task_id=row.task_id, candidate_id=row.candidate_id)
            with env.db.transaction() as conn:
                require_write(env, "evolution", "population_member", ctx)
                env.trace.step(
                    conn,
                    "PRESCREEN_EVALUATED",
                    ctx,
                    actor="evolution-engine",
                    inputs={"thresholds": thresholds, "constraints": constraints},
                    payload={
                        "checks": screened.checks,
                        "passed": screened.passed,
                        "duplicate": duplicate,
                        "score": _finite(screened.score),
                    },
                )
            self._candidate(
                row.candidate_id, prescreen={"checks": screened.checks, "passed": screened.passed}
            )
            if duplicate:
                reasons[row.candidate_id] = "DUPLICATE"
            elif not screened.passed:
                failed = sorted(k for k, v in screened.checks.items() if not v["passed"])
                reasons[row.candidate_id] = "PRESCREEN_FAILED:" + ",".join(failed)
            else:
                screened_all.append(screened)
                if row.canonical_hash:
                    seen.add(row.canonical_hash)
        ranked = sorted(provisional_fitness(screened_all, by_id, settings), key=Screened.key)
        survivors, twins = behavioral_dedup(
            ranked, self.engine.similarity, float(thresholds["similarity_max"])
        )
        for candidate_id in twins:
            reasons[candidate_id] = "DUPLICATE_BEHAVIOR"
        quota = int(settings["throughput"]["publications"])
        slots = proposal.publication_slots if proposal and proposal.publication_slots else None
        chosen, ranks = select(survivors, quota, slots)
        chosen_ids = {c.candidate_id for c in chosen}
        fitness = {s.candidate_id: s for s in ranked}
        for row in rows:
            ctx = gen.ctx.with_(task_id=row.task_id, candidate_id=row.candidate_id)
            selected = row.candidate_id in chosen_ids
            reason = reasons.get(row.candidate_id, None if selected else "QUOTA")
            item = fitness.get(row.candidate_id)
            value = (
                None if item is None else (item.fitness if item.kind == "factor" else item.score)
            )
            with env.db.transaction() as conn:
                env.trace.step(
                    conn,
                    "SELECTED" if selected else "NOT_SELECTED",
                    ctx,
                    actor="evolution-engine",
                    inputs={
                        "quota": quota,
                        "survivors": len(survivors),
                        "island_publication_slots": slots,
                    },
                    payload={
                        "rank": ranks.get(row.candidate_id),
                        "provisional_fitness": _finite(value),
                        "fitness_detail": None if item is None else item.fitness_detail,
                        "originality": None if item is None else item.originality,
                        "rank_score": None if item is None else _finite(item.rank_score),
                        "novelty_weight": float(settings["selection"]["novelty_weight"]),
                        "duplicate_of": twins.get(row.candidate_id),
                        "reason": reason,
                        "rule": "provisional_fitness_plus_novelty_island_slots",
                    },
                )
            self._candidate(
                row.candidate_id,
                state="selected" if selected else "not_selected",
                reason=reason,
                provisional_fitness=_finite(value),
            )

    async def _publishing(self, gen: Generation) -> None:
        with self.env.db.read() as conn:
            rows = conn.execute(
                text(
                    "SELECT candidate_id FROM candidates WHERE generation_id = :g AND "
                    "state = 'selected' ORDER BY created_at"
                ),
                {"g": gen.generation_id},
            ).all()
        published = []
        for row in rows:
            if self.packager.publish(gen.ctx, row.candidate_id) is not None:
                published.append(row.candidate_id)
        # Published factors join their island as provisional members until their W1
        # report arrives (Section 12.1).
        joined = self.engine.add_published(gen.ref, published)
        summary = self.summary(gen) | {"population_joined": joined}
        with self.env.db.transaction() as conn:
            conn.execute(
                text("UPDATE generations SET summary = CAST(:s AS jsonb) WHERE generation_id = :g"),
                {"s": dumps(summary), "g": gen.generation_id},
            )
        self.env.logger.logger.info(
            "generation_summarised", outcome="ok", payload=summary, **gen.ctx.log_ids()
        )

    def summary(self, gen: Generation) -> dict[str, Any]:
        with self.env.db.read() as conn:
            states = {
                r.state: int(r.n)
                for r in conn.execute(
                    text(
                        "SELECT state, count(*) AS n FROM candidates WHERE generation_id = :g "
                        "GROUP BY state"
                    ),
                    {"g": gen.generation_id},
                ).all()
            }
            tasks = {
                r.state: int(r.n)
                for r in conn.execute(
                    text(
                        "SELECT state, count(*) AS n FROM tasks WHERE generation_id = :g "
                        "GROUP BY state"
                    ),
                    {"g": gen.generation_id},
                ).all()
            }
            row = conn.execute(
                text("SELECT cost_cny, plan_source FROM generations WHERE generation_id = :g"),
                {"g": gen.generation_id},
            ).one()
            versions = [
                str(r.version_id)
                for r in conn.execute(
                    text(
                        "SELECT v.version_id FROM candidate_versions v JOIN candidates c ON "
                        "c.candidate_id = v.candidate_id WHERE c.generation_id = :g"
                    ),
                    {"g": gen.generation_id},
                ).all()
            ]
            hypotheses: int = conn.execute(
                text(
                    "SELECT count(*) FROM hypotheses h JOIN tasks t ON t.task_id = h.task_id "
                    "WHERE t.generation_id = :g"
                ),
                {"g": gen.generation_id},
            ).scalar_one()
        return {
            "seq": gen.seq,
            "plan_source": row.plan_source,
            "tasks": tasks,
            "hypotheses": int(hypotheses),
            "candidates": states,
            "published_version_ids": versions,
            "cost_cny": float(row.cost_cny),
            "budget_stop": gen.budget_stop,
        }

    # Calls -----------------------------------------------------------------------------

    def _budget_chars(self, gen: Generation) -> int:
        tokens = int(gen.charter.get("context_tokens", 12000))
        return int(tokens * self.env.config.service.estimate.chars_per_token)

    async def _call(
        self,
        gen: Generation,
        role: str,
        prompt: Any,
        output: type[Any],
        ctx: Ctx,
        *,
        exclude_provider: str | None = None,
        raise_failures: bool = False,
        inputs: dict[str, Any] | None = None,
    ) -> RoleResult[Any] | None:
        if self.stopped(gen):
            raise Stop("paused")
        try:
            return await self.roles.run(
                role,
                prompt,
                output,
                ctx,
                gen.charter,
                exclude_provider=exclude_provider,
                inputs=inputs,
            )
        except BudgetExceeded as error:
            self.env.logger.logger.warning(
                "budget_stop",
                outcome="failed",
                error_code=f"BUDGET_{error.scope.upper()}",
                payload={
                    "spent": float(error.spent),
                    "cap": float(error.cap),
                    "needed": float(error.needed),
                    "role": role,
                },
                **ctx.log_ids(),
            )
            raise Stop(f"budget_{error.scope}") from error
        except RoleFailed as error:
            self.env.logger.logger.error(
                "role_failed",
                outcome="failed",
                error_code="ROLE_FAILED",
                payload={"role": role, "errors": error.errors[:6]},
                **ctx.log_ids(),
            )
            if raise_failures:
                raise
            return None


def charter_text(charter: dict[str, Any]) -> str:
    """The owner's objective, steering notes and constraints, for prompts."""
    lines = [f"Objective: {charter.get('objective', '')}", f"Mode: {charter.get('mode', '')}"]
    for note in charter.get("steering", []):
        lines.append(f"Owner steering ({note.get('at', '')[:10]}): {note.get('note', '')}")
    constraints = charter.get("constraints") or {}
    if constraints:
        lines.append(f"Constraints: {_compact(constraints)}")
    notes = charter.get("seed_notes")
    if notes:
        lines.append(f"Owner notes: {notes}")
    return "\n".join(lines)


def supervisor_view(proposal: Proposal) -> dict[str, Any]:
    """The proposal as the supervisor reads it: the proposed tasks, the parents with
    their fitness and flags, and the ready-made variants without their AST diffs."""
    body = proposal.as_json()
    body["tasks"] = body.pop("default_plan")["tasks"]
    engine = body.pop("engine")
    body["engine"] = {
        k: engine[k]
        for k in ("guardrail", "stagnation_choice", "low_llm_budget", "operator_slots")
        if k in engine
    }
    body["variants"] = [
        {
            k: v.get(k)
            for k in (
                "variant_id",
                "island",
                "operator",
                "rule",
                "parent_version_ids",
                "expression",
            )
        }
        for v in body["variants"]
    ]
    body["selections"] = [
        {
            k: s.get(k)
            for k in ("type", "island", "parent_version_ids", "parent_fitness", "targeted_flags")
        }
        for s in body["selections"]
    ]
    body["parent_info"] = {
        k: {
            x: v.get(x)
            for x in ("island", "fitness", "status", "expression", "flags", "offered_as")
        }
        for k, v in body["parent_info"].items()
    }
    return body


def _compact(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)


def _sampled(seed: int, interpretation_id: UUID, fraction: float) -> bool:
    digest = hashlib.sha256(f"{seed}:{interpretation_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64 < fraction


def _finite(value: float | None) -> float | None:
    if value is None or value != value or value in (float("inf"), float("-inf")):
        return None
    return float(value)


def has_open_generation(conn: Connection, program_id: UUID) -> bool:
    return (
        conn.execute(
            text(
                "SELECT 1 FROM generations WHERE program_id = :p AND state NOT IN ('CLOSED', "
                "'FAILED', 'ABORTED') LIMIT 1"
            ),
            {"p": program_id},
        ).first()
        is not None
    )
