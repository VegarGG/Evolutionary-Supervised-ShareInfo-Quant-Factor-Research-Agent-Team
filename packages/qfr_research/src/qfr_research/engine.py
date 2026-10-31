"""The evolutionary engine (P5.1 to P5.6, PLAN Section 12).

Deterministic research code. Each generation it

1. initializes the population once per program (pool entries named in the brief, all
   pool entries in the improve modes, the brief's human_seed versions, and a parent
   job's population), which is empty on a fresh deployment (Section 12.1);
2. refreshes the population from released reports: a published version with a
   released W1 report is official; one waiting for evaluation (a quota deferral
   included) is provisional and does not expire; one rejected at intake or whose
   screening failed leaves the population (archived); recomputes official fitness
   (Section 12.2), rebuilds the MAP-Elites archive, counts each published child once in
   its island's Thompson-sampling arm, tracks each island's best fitness and migrates
   island bests around the ring every 5 generations (Section 12.6);
3. proposes the generation: Thompson-sampled publication slots per island with a floor
   and a cap, the operator mix with the mode bias and the diversity guardrail, parents
   chosen by tournament or archive elite with a recorded seed, partner choice for
   crossovers, ready-made deterministic variants, and a default plan.

Every value a decision used goes into the PROPOSAL_EMITTED trace step. The engine
writes only population members, archive cells and bandit state (its blackboard write
scope); outcomes it counts are insert-only rows.
"""

import copy
import math
import re
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from qfr_core.dsl import ast_similarity, canonicalize, parse, validate
from qfr_core.ids import uuid7
from qfr_core.metrics.fingerprint import behavioral_similarity
from sqlalchemy import text
from sqlalchemy.engine import Connection

from qfr_research.clients import ServiceRefused, ServiceUnavailable
from qfr_research.db import dumps
from qfr_research.env import ResearchEnv
from qfr_research.fitness import (
    FitnessInput,
    cell_count,
    descriptors,
    quantile,
    rank_key,
    score,
    w0_input,
    w1_input,
)
from qfr_research.outputs import GenerationPlan, IslandPause, PlanTask
from qfr_research.planning import STRATEGY_MODES, Proposal
from qfr_research.store import Ctx
from qfr_research.tools import require_write
from qfr_research.variation import (
    Choice,
    Variant,
    derive_seed,
    generator,
    select_parent,
    subtree_crossover,
    syntactic_mutation,
    tournament,
)

EVOLUTION_KEYS = (
    "throughput",
    "population",
    "selection",
    "prescreen",
    "bandit",
    "fitness",
    "archive",
    "variation",
    "context",
)
IMPROVE_POOL_MODES = frozenset({"improve_factors", "improve_strategy"})
PARENT_OPERATORS = ("llm_mutation", "crossover", "syntactic_mutation", "repair")
LLM_TASK_TYPES = frozenset({"explore", "llm_mutation", "crossover", "repair", "compose_strategy"})
FAILED_REASONS = frozenset({"SCREENING_FAILED", "INTAKE_FAILED", "DUPLICATE"})
ARCHIVE_KEEP = frozenset({"CAPACITY", "ARCHIVE_ELITE"})


def evolution_settings(defaults: dict[str, Any], charter: dict[str, Any]) -> dict[str, Any]:
    """The charter's evolution sections over the shipped defaults. A program created
    before a section existed keeps working with the defaults; the program's own values
    win wherever it has them."""
    out: dict[str, Any] = {}
    for key in EVOLUTION_KEYS:
        merged = copy.deepcopy(defaults.get(key) or {})
        if isinstance(charter.get(key), dict):
            merged.update(copy.deepcopy(charter[key]))
        out[key] = merged
    out["operator_mix"] = dict(charter.get("operator_mix") or defaults["operator_mix"])
    out["constraints"] = dict(charter.get("constraints") or {})
    out["mode"] = str(charter.get("mode", "new_factors"))
    return out


@dataclass
class Member:
    member_id: UUID
    island: str
    version_id: UUID
    candidate_id: UUID | None
    status: str
    source: str
    expression: str
    sign: int
    analysis: dict[str, Any]
    joined_seq: int
    fitness: float | None
    metrics: dict[str, Any] | None
    detail: dict[str, Any] | None
    originality: float | None
    descriptors: dict[str, Any] | None
    archived_reason: str | None

    @property
    def nodes(self) -> int:
        return int(self.analysis.get("nodes", 0))

    @property
    def fields(self) -> list[str]:
        return list(self.analysis.get("fields", []))

    @property
    def w1(self) -> dict[str, Any] | None:
        if self.metrics and self.metrics.get("source") == "W1":
            w1: dict[str, Any] = self.metrics["w1"]
            return w1
        return None

    def key(self) -> tuple[Any, ...]:
        return rank_key(self.fitness, self.originality, self.nodes, str(self.version_id))

    def choice(self) -> Choice:
        return Choice(
            str(self.version_id),
            self.island,
            float(self.fitness or 0.0),
            self.status,
            self.expression,
            self.sign,
            (self.descriptors or {}).get("cell_key"),
        )


def _member(row: Any) -> Member:
    return Member(
        row.member_id,
        row.island_key,
        row.version_id,
        row.candidate_id,
        row.status,
        row.source,
        row.expression or "",
        int(row.expected_sign or 1),
        dict(row.analysis or {}),
        int(row.joined_seq),
        row.fitness,
        row.metrics,
        row.fitness_detail,
        row.originality,
        row.descriptors,
        row.archived_reason,
    )


def load_members(conn: Connection, program_id: UUID) -> list[Member]:
    rows = conn.execute(
        text(
            "SELECT * FROM population_members WHERE program_id = :p ORDER BY island_key, "
            "joined_seq, version_id"
        ),
        {"p": program_id},
    ).all()
    return [_member(r) for r in rows]


@dataclass(frozen=True)
class GenerationRef:
    """What the engine needs to know about the generation it serves."""

    generation_id: UUID
    program_id: UUID
    job_id: UUID
    seq: int
    charter: dict[str, Any]

    @property
    def ctx(self) -> Ctx:
        return Ctx(job_id=self.job_id, program_id=self.program_id, generation_id=self.generation_id)


class EvolutionEngine:
    def __init__(self, env: ResearchEnv) -> None:
        self.env = env

    def settings(self, charter: dict[str, Any]) -> dict[str, Any]:
        return evolution_settings(self.env.charter_defaults, charter)

    # Shared helpers --------------------------------------------------------------------

    def islands(self, program_id: UUID) -> dict[str, Any]:
        with self.env.db.read() as conn:
            rows = conn.execute(
                text("SELECT * FROM islands WHERE program_id = :p ORDER BY island_key"),
                {"p": program_id},
            ).all()
        return {r.island_key: r for r in rows}

    def fingerprint(self, expression: str) -> Any:
        from qfr_research.tools import _fingerprint

        analysis = validate(expression, self.env.limits).analysis
        if analysis is None:
            return None
        return _fingerprint(self.env, analysis.canonical)

    def similarity(self, a: str, b: str) -> float | None:
        fa, fb = self.fingerprint(a), self.fingerprint(b)
        if fa is None or fb is None:
            return None
        return behavioral_similarity(fa, fb)

    def _island_for(self, tags: Iterable[str], islands: list[str]) -> str:
        """The island whose theme matches the tags, else I6, else the first island."""
        keywords = self.env.config.service.island_keywords
        for tag in sorted(t.lower() for t in tags):
            for keyword, targets in keywords.items():
                if re.search(rf"\b{re.escape(keyword)}", tag):
                    for target in targets:
                        if target in islands:
                            return target
        return "I6" if "I6" in islands else islands[0]

    def _pool_entries(self) -> list[Any]:
        entries: list[Any] = []
        cursor: str | None = None
        while True:
            page = self.env.registry.pool("factor", cursor=cursor)
            entries += [e for e in page.items if e.status != "retired"]
            if page.next_cursor is None:
                return entries
            cursor = page.next_cursor

    # P5.1: initialization --------------------------------------------------------------

    def ensure_initialized(self, gen: GenerationRef) -> dict[str, Any] | None:
        """Insert the program's starting members once. An empty pool and a brief without
        seeds give an empty population: the normal fresh start (SET-01)."""
        env = self.env
        with env.db.read() as conn:
            program = conn.execute(
                text(
                    "SELECT p.population_initialized_at, j.brief, j.seed_version_ids, "
                    "j.parent_job_id FROM programs p JOIN research_jobs j ON j.job_id = p.job_id "
                    "WHERE p.program_id = :p"
                ),
                {"p": gen.program_id},
            ).one()
            if program.population_initialized_at is not None:
                return None
            own_seeds = conn.execute(
                text(
                    "SELECT c.candidate_id, c.island_key, c.expression, c.payload, c.analysis, "
                    "v.version_id FROM candidates c JOIN candidate_versions v ON "
                    "v.candidate_id = c.candidate_id WHERE c.program_id = :p AND "
                    "c.operator = 'human_seed' AND c.kind = 'factor' ORDER BY v.published_at"
                ),
                {"p": gen.program_id},
            ).all()
            parent_program = None
            if program.parent_job_id is not None:
                parent_program = conn.execute(
                    text("SELECT program_id FROM programs WHERE job_id = :j"),
                    {"j": program.parent_job_id},
                ).scalar()
            parent_rows = (
                conn.execute(
                    text(
                        "SELECT m.* FROM population_members m WHERE m.program_id = :p AND "
                        "(m.status <> 'archived' OR m.version_id IN (SELECT elite_version_id "
                        "FROM archive_cells WHERE program_id = :p)) ORDER BY m.island_key, "
                        "m.joined_seq, m.version_id"
                    ),
                    {"p": parent_program},
                ).all()
                if parent_program is not None
                else []
            )
        islands = sorted(self.islands(gen.program_id))
        rows: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()

        def add(**row: Any) -> None:
            key = (row["island"], str(row["version_id"]))
            if key in seen:
                return
            seen.add(key)
            rows.append(row)

        own_versions = set()
        for seed in own_seeds:
            own_versions.add(str(seed.version_id))
            add(
                island=seed.island_key if seed.island_key in islands else islands[0],
                version_id=seed.version_id,
                candidate_id=seed.candidate_id,
                source="seed",
                expression=seed.expression,
                sign=int(seed.payload.get("expected_sign", 1)),
                analysis=seed.analysis or {},
                status="provisional",
            )
        mode = str(program.brief.get("mode", "new_factors"))
        named = [str(v) for v in program.seed_version_ids or [] if str(v) not in own_versions]
        pool_entries: list[Any] = []
        if named or mode in IMPROVE_POOL_MODES:
            pool_entries = self._pool_entries()
        by_version = {str(e.version_id): e for e in pool_entries}
        if mode in IMPROVE_POOL_MODES:
            named += [str(e.version_id) for e in pool_entries]
        for version_id in dict.fromkeys(named):
            try:
                record = env.registry.version(UUID(version_id))
            except (ServiceRefused, ServiceUnavailable):
                continue
            expression = getattr(record.manifest.implementation, "expression", None)
            if record.kind != "factor" or not expression:
                continue  # strategies compose factors; the population holds factors
            entry = by_version.get(version_id)
            analysis = validate(expression, env.limits).analysis
            add(
                island=self._island_for(entry.tags if entry else [], islands),
                version_id=UUID(version_id),
                candidate_id=None,
                source="pool",
                expression=expression,
                sign=int(record.manifest.declared.expected_sign),
                analysis=analysis.model_dump(mode="json") if analysis else {},
                status="provisional",
            )
        for parent in parent_rows:
            island = parent.island_key if parent.island_key in islands else None
            add(
                island=island or ("I6" if "I6" in islands else islands[0]),
                version_id=parent.version_id,
                candidate_id=None,
                source="parent_program",
                expression=parent.expression,
                sign=int(parent.expected_sign or 1),
                analysis=dict(parent.analysis or {}),
                status="archived" if parent.status == "archived" else "provisional",
                archived_reason="ARCHIVE_ELITE" if parent.status == "archived" else None,
                metrics=parent.metrics,
                originality=parent.originality,
            )
        now = env.clock.now()
        with env.db.transaction() as conn:
            require_write(env, "evolution", "population_member", gen.ctx)
            for row in rows:
                conn.execute(
                    text(
                        "INSERT INTO population_members (member_id, program_id, island_key, "
                        "version_id, candidate_id, status, source, kind, expression, analysis, "
                        "expected_sign, joined_seq, metrics, originality, archived_reason, "
                        "updated_at, created_at) VALUES (:m, :p, :i, :v, :c, :s, :src, "
                        "'factor', :e, CAST(:a AS jsonb), :sign, :seq, CAST(:met AS jsonb), "
                        ":orig, :ar, :now, :now) ON CONFLICT DO NOTHING"
                    ),
                    {
                        "m": uuid7(),
                        "p": gen.program_id,
                        "i": row["island"],
                        "v": row["version_id"],
                        "c": row["candidate_id"],
                        "s": row["status"],
                        "src": row["source"],
                        "e": row["expression"],
                        "a": dumps(row["analysis"]),
                        "sign": row["sign"],
                        "seq": gen.seq,
                        "met": None if row.get("metrics") is None else dumps(row["metrics"]),
                        "orig": row.get("originality"),
                        "ar": row.get("archived_reason"),
                        "now": now,
                    },
                )
            conn.execute(
                text("UPDATE programs SET population_initialized_at = :now WHERE program_id = :p"),
                {"now": now, "p": gen.program_id},
            )
        summary = {
            "seeds": sum(1 for r in rows if r["source"] == "seed"),
            "pool": sum(1 for r in rows if r["source"] == "pool"),
            "parent_program": sum(1 for r in rows if r["source"] == "parent_program"),
            "empty_start": not rows,
            "mode": mode,
        }
        env.logger.logger.info(
            "population_initialized", outcome="ok", payload=summary, **gen.ctx.log_ids()
        )
        return summary

    def external_versions(self, program_id: UUID) -> list[UUID]:
        """Member versions published outside this program, whose reports feedback sync
        fetches by version id."""
        with self.env.db.read() as conn:
            rows = conn.execute(
                text(
                    "SELECT DISTINCT m.version_id FROM population_members m WHERE "
                    "m.program_id = :p AND m.source IN ('pool', 'parent_program') "
                    "ORDER BY m.version_id"
                ),
                {"p": program_id},
            ).all()
        return [r.version_id for r in rows]

    # P5.1, P5.2 and P5.6: the refresh --------------------------------------------------

    def add_published(self, gen: GenerationRef, candidate_ids: list[UUID]) -> int:
        """Published program candidates join their island as provisional members, with
        their W0 metrics and provisional fitness, until their W1 report arrives."""
        env = self.env
        added = 0
        with env.db.transaction() as conn:
            require_write(env, "evolution", "population_member", gen.ctx)
            for candidate_id in candidate_ids:
                row = conn.execute(
                    text(
                        "SELECT c.*, v.version_id FROM candidates c JOIN candidate_versions v ON "
                        "v.candidate_id = c.candidate_id WHERE c.candidate_id = :c AND "
                        "c.kind = 'factor'"
                    ),
                    {"c": candidate_id},
                ).first()
                if row is None:
                    continue
                similarity = row.similarity or {}
                added += self._insert_program_member(conn, gen, row, similarity)
        return added

    def _insert_program_member(
        self, conn: Connection, gen: GenerationRef, row: Any, similarity: Any
    ) -> int:
        metrics = {
            "source": "W0",
            "metrics": dict((row.workbench or {}).get("metrics") or {}),
            "pool_similarity": similarity.get("max_pool_behavioral_similarity"),
        }
        result = conn.execute(
            text(
                "INSERT INTO population_members (member_id, program_id, island_key, version_id, "
                "candidate_id, status, source, kind, expression, analysis, expected_sign, "
                "joined_seq, fitness, metrics, originality, updated_at, created_at) VALUES (:m, "
                ":p, :i, :v, :c, 'provisional', 'program', 'factor', :e, CAST(:a AS jsonb), "
                ":sign, :seq, :f, CAST(:met AS jsonb), :orig, :now, :now) ON CONFLICT DO NOTHING "
                "RETURNING 1"
            ),
            {
                "m": uuid7(),
                "p": gen.program_id,
                "i": row.island_key,
                "v": row.version_id,
                "c": row.candidate_id,
                "e": row.expression,
                "a": dumps(row.analysis or {}),
                "sign": int((row.payload or {}).get("expected_sign", 1)),
                "seq": gen.seq,
                "f": row.provisional_fitness,
                "met": dumps(metrics),
                "orig": similarity.get("originality"),
                "now": self.env.clock.now(),
            },
        ).first()
        return 0 if result is None else 1

    def refresh(self, gen: GenerationRef) -> dict[str, Any]:
        env = self.env
        settings = self.settings(gen.charter)
        islands = self.islands(gen.program_id)
        active = sorted(k for k, r in islands.items() if r.status == "active")
        with env.db.transaction() as conn:
            require_write(env, "evolution", "population_member", gen.ctx)
            self._adopt_missing(conn, gen, settings)
            members = load_members(conn, gen.program_id)
            changes = self._sync_statuses(conn, gen, members, settings)
            migrated = self._migrate(conn, gen, members, active, settings)
            if migrated:
                # Add the migrants without reloading: the status changes above are not
                # written yet.
                known = {m.member_id for m in members}
                members += [
                    m for m in load_members(conn, gen.program_id) if m.member_id not in known
                ]
            evicted = self._capacity(members, settings)
            self._fitness(members, settings)
            self._write_members(conn, members)
            require_write(env, "evolution", "archive_cell", gen.ctx)
            archive = self._rebuild_archive(conn, gen, members, settings)
            require_write(env, "evolution", "bandit_state", gen.ctx)
            bandit = self._update_bandit(conn, gen, members, islands, settings)
            best = self._track_best(conn, gen, members, islands, settings)
        counts: dict[str, dict[str, int]] = {}
        for m in members:
            counts.setdefault(m.island, {}).setdefault(m.status, 0)
            counts[m.island][m.status] += 1
        return {
            "members": counts,
            "status_changes": changes,
            "migrated": migrated,
            "evicted": evicted,
            "archive": archive,
            "bandit": bandit,
            "islands": best,
        }

    def _adopt_missing(
        self, conn: Connection, gen: GenerationRef, settings: dict[str, Any]
    ) -> None:
        """Program publications not yet in the population (a program started before the
        engine existed, or a crash between publishing and joining) join now."""
        rows = conn.execute(
            text(
                "SELECT c.*, v.version_id FROM candidates c JOIN candidate_versions v ON "
                "v.candidate_id = c.candidate_id WHERE c.program_id = :p AND c.kind = 'factor' "
                "AND c.operator <> 'human_seed' AND NOT EXISTS (SELECT 1 FROM population_members "
                "m WHERE m.program_id = c.program_id AND m.version_id = v.version_id) "
                "ORDER BY v.published_at"
            ),
            {"p": gen.program_id},
        ).all()
        for row in rows:
            self._insert_program_member(conn, gen, row, row.similarity or {})

    def _sync_statuses(
        self, conn: Connection, gen: GenerationRef, members: list[Member], settings: dict[str, Any]
    ) -> list[dict[str, Any]]:
        versions = sorted({m.version_id for m in members}, key=str)
        reports: dict[UUID, list[Any]] = {}
        for row in conn.execute(
            text(
                "SELECT report_id, version_id, report_type, content FROM report_cache WHERE "
                "version_id = ANY(:v) ORDER BY released_at, report_id"
            ),
            {"v": versions},
        ).all():
            reports.setdefault(row.version_id, []).append(row)
        changes = []
        for m in members:
            latest: dict[str, Any] = {}
            for r in reports.get(m.version_id, []):
                latest[r.report_type] = r
            before, before_reason = m.status, m.archived_reason
            w1, w2 = latest.get("w1"), latest.get("w2")
            screening, intake = latest.get("screening"), latest.get("intake")
            if w1 is not None:
                if m.status != "archived":
                    m.status, m.archived_reason = "official", None
                m.metrics = {
                    "source": "W1",
                    "w1": w1.content["content"],
                    "report_id": str(w1.report_id),
                    "w2_status": None if w2 is None else w2.content["content"]["status"],
                }
            elif screening is not None and screening.content["content"]["status"] == "FAIL":
                m.status, m.archived_reason = "archived", "SCREENING_FAILED"
                m.metrics = {
                    "source": "screening",
                    "status": "FAIL",
                    "reasons": screening.content["content"]["reasons"],
                    "report_id": str(screening.report_id),
                }
            elif intake is not None and intake.content["content"]["status"] in (
                "FAIL",
                "DUPLICATE",
            ):
                status = intake.content["content"]["status"]
                reasons = intake.content["content"]["reasons"]
                m.status = "archived"
                # A quota expiry rejects the version without judging it, so it leaves the
                # population but is not a failure for the fitness or the bandit.
                m.archived_reason = (
                    "DUPLICATE"
                    if status == "DUPLICATE"
                    else "QUOTA_EXPIRED"
                    if "QUOTA_EXPIRED" in reasons
                    else "INTAKE_FAILED"
                )
                m.metrics = {
                    "source": "intake",
                    "status": status,
                    "reasons": reasons,
                    "report_id": str(intake.report_id),
                }
            if (m.status, m.archived_reason) != (before, before_reason):
                changes.append(
                    {
                        "version_id": str(m.version_id),
                        "island": m.island,
                        "from": before,
                        "to": m.status,
                        "reason": m.archived_reason,
                    }
                )
        return changes

    def _fitness(self, members: list[Member], settings: dict[str, Any]) -> None:
        official = [m for m in members if m.status == "official" and m.w1 is not None]
        inputs = [
            w1_input(
                str(m.member_id),
                m.island,
                m.sign,
                m.nodes,
                m.w1 or {},
                settings,
                w2_status=(m.metrics or {}).get("w2_status"),
            )
            for m in official
        ]
        scored = score(inputs, settings)
        for m in official:
            result = scored[str(m.member_id)]
            m.fitness, m.detail = result.value, result.detail
            m.descriptors = descriptors(m.expression, m.fields, m.sign, m.w1 or {}, settings)
        for m in members:
            if m.status == "archived" and m.archived_reason in FAILED_REASONS:
                m.fitness = 0.0
                m.detail = {
                    "multiplier": 0.0,
                    "multiplier_reasons": [m.archived_reason],
                }
            elif m.status == "archived" and m.w1 is not None and m.descriptors is None:
                m.descriptors = descriptors(m.expression, m.fields, m.sign, m.w1, settings)
        pending = [
            m for m in members if m.status == "provisional" and m.fitness is None and m.expression
        ]
        if pending:
            w0: list[FitnessInput] = []
            for m in pending:
                metrics = (m.metrics or {}).get("metrics") if m.metrics else None
                if not metrics:
                    metrics = self._w0(m)
                    m.metrics = {"source": "W0", "metrics": metrics, "pool_similarity": None}
                w0.append(w0_input(str(m.member_id), m.island, m.sign, m.nodes, metrics, None))
            provisional = score(w0, settings, provisional=True)
            for m in pending:
                result = provisional[str(m.member_id)]
                m.fitness, m.detail = result.value, result.detail
        for m in members:
            if m.originality is None and m.expression:
                others = [
                    o.expression
                    for o in members
                    if o.island == m.island and o.version_id != m.version_id and o.expression
                ]
                tree = canonicalize(parse(m.expression))
                m.originality = round(
                    1.0
                    - max(
                        (ast_similarity(tree, canonicalize(parse(o))) for o in others[:60]),
                        default=0.0,
                    ),
                    6,
                )

    def _w0(self, m: Member) -> dict[str, Any]:
        from qfr_research.tools import WORKBENCH_FIELDS, factor_report

        analysis = validate(m.expression, self.env.limits).analysis
        if analysis is None:
            return {}
        try:
            report = factor_report(self.env, analysis.canonical, 1 if m.sign >= 0 else -1)
        except Exception:  # noqa: BLE001 - a member without W0 numbers ranks last
            return {}
        values = report.metrics.model_dump(mode="json")
        return {k: values.get(k) for k in WORKBENCH_FIELDS}

    def _write_members(self, conn: Connection, members: list[Member]) -> None:
        now = self.env.clock.now()
        for m in members:
            conn.execute(
                text(
                    "UPDATE population_members SET status = :s, fitness = :f, metrics = "
                    "CAST(:met AS jsonb), fitness_detail = CAST(:d AS jsonb), descriptors = "
                    "CAST(:desc AS jsonb), originality = :o, archived_reason = :ar, "
                    "updated_at = :now WHERE member_id = :m"
                ),
                {
                    "s": m.status,
                    "f": m.fitness,
                    "met": None if m.metrics is None else dumps(m.metrics),
                    "d": None if m.detail is None else dumps(m.detail),
                    "desc": None if m.descriptors is None else dumps(m.descriptors),
                    "o": m.originality,
                    "ar": m.archived_reason,
                    "now": now,
                    "m": m.member_id,
                },
            )

    def _migrate(
        self,
        conn: Connection,
        gen: GenerationRef,
        members: list[Member],
        active: list[str],
        settings: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Every 5 generations each island's best official member is copied into the
        next island of the ring, as a parent candidate (Section 12.6)."""
        every = int(settings["bandit"]["migration_generations"])
        if gen.seq <= 0 or every <= 0 or gen.seq % every or len(active) < 2:
            return []
        if any(m.source == "migrant" and m.joined_seq == gen.seq for m in members):
            return []
        moved = []
        for i, island in enumerate(active):
            ranked = sorted(
                (m for m in members if m.island == island and m.status == "official"),
                key=Member.key,
            )
            if not ranked:
                continue
            best, target = ranked[0], active[(i + 1) % len(active)]
            if any(m.island == target and m.version_id == best.version_id for m in members):
                continue
            conn.execute(
                text(
                    "INSERT INTO population_members (member_id, program_id, island_key, "
                    "version_id, candidate_id, status, source, kind, expression, analysis, "
                    "expected_sign, joined_seq, metrics, originality, updated_at, created_at) "
                    "VALUES (:m, :p, :i, :v, :c, 'official', 'migrant', 'factor', :e, "
                    "CAST(:a AS jsonb), :sign, :seq, CAST(:met AS jsonb), :o, :now, :now) "
                    "ON CONFLICT DO NOTHING"
                ),
                {
                    "m": uuid7(),
                    "p": gen.program_id,
                    "i": target,
                    "v": best.version_id,
                    "c": best.candidate_id,
                    "e": best.expression,
                    "a": dumps(best.analysis),
                    "sign": best.sign,
                    "seq": gen.seq,
                    "met": dumps(best.metrics),
                    "o": best.originality,
                    "now": self.env.clock.now(),
                },
            )
            moved.append(
                {
                    "version_id": str(best.version_id),
                    "from": island,
                    "to": target,
                    "fitness": best.fitness,
                }
            )
        return moved

    def _capacity(self, members: list[Member], settings: dict[str, Any]) -> list[dict[str, Any]]:
        limit = int(settings["population"]["members_per_island"])
        evicted = []
        for island in sorted({m.island for m in members}):
            live = [m for m in members if m.island == island and m.status != "archived"]
            excess = len(live) - limit
            if excess <= 0:
                continue
            officials = sorted((m for m in live if m.status == "official"), key=Member.key)
            for m in reversed(officials[-excess:] if excess <= len(officials) else officials):
                m.status, m.archived_reason = "archived", "CAPACITY"
                evicted.append({"version_id": str(m.version_id), "island": island})
        return evicted

    def _rebuild_archive(
        self, conn: Connection, gen: GenerationRef, members: list[Member], settings: dict[str, Any]
    ) -> dict[str, Any]:
        """Each cell keeps its best official elite with a positive fitness."""
        eligible = [
            m
            for m in members
            if m.descriptors
            and m.w1 is not None
            and (m.fitness or 0.0) > 0
            and (m.status == "official" or m.archived_reason in ARCHIVE_KEEP)
        ]
        cells: dict[str, Member] = {}
        for m in sorted(eligible, key=Member.key):
            cells.setdefault(str((m.descriptors or {})["cell_key"]), m)
        conn.execute(text("DELETE FROM archive_cells WHERE program_id = :p"), {"p": gen.program_id})
        now = self.env.clock.now()
        for key, m in sorted(cells.items()):
            conn.execute(
                text(
                    "INSERT INTO archive_cells (program_id, cell_key, elite_version_id, fitness, "
                    "updated_at, island_key, descriptors) VALUES (:p, :k, :v, :f, :now, :i, "
                    "CAST(:d AS jsonb))"
                ),
                {
                    "p": gen.program_id,
                    "k": key,
                    "v": m.version_id,
                    "f": float(m.fitness or 0.0),
                    "now": now,
                    "i": m.island,
                    "d": dumps(m.descriptors),
                },
            )
        total = cell_count(settings)
        return {
            "cells": len(cells),
            "total": total,
            "coverage": round(len(cells) / total, 6) if total else 0.0,
            "elites": {k: str(m.version_id) for k, m in sorted(cells.items())},
        }

    def _update_bandit(
        self,
        conn: Connection,
        gen: GenerationRef,
        members: list[Member],
        islands: dict[str, Any],
        settings: dict[str, Any],
    ) -> dict[str, Any]:
        """A published child counts once, when its first W1 (or failed screening) report
        is in: success when its official fitness is at or above the island's 75th
        percentile. Each arm forgets by the factor once per generation."""
        bandit = settings["bandit"]
        forgetting = float(bandit["forgetting"])
        q = float(bandit["success_percentile"])
        counted = {
            r.version_id
            for r in conn.execute(
                text("SELECT version_id FROM bandit_outcomes WHERE program_id = :p"),
                {"p": gen.program_id},
            ).all()
        }
        operators = {
            r.version_id: r.operator
            for r in conn.execute(
                text(
                    "SELECT v.version_id, c.operator FROM candidate_versions v JOIN candidates c "
                    "ON c.candidate_id = v.candidate_id WHERE c.program_id = :p"
                ),
                {"p": gen.program_id},
            ).all()
        }
        new: dict[str, list[dict[str, Any]]] = {}
        for m in members:
            if m.source != "program" or m.version_id in counted:
                continue
            if operators.get(m.version_id) in (None, "human_seed"):
                continue
            failed = m.status == "archived" and m.archived_reason in FAILED_REASONS
            if not (failed or (m.w1 is not None and m.status in ("official", "archived"))):
                continue
            fitness = 0.0 if failed else float(m.fitness or 0.0)
            island_values = [
                float(o.fitness or 0.0)
                for o in members
                if o.island == m.island and o.status == "official"
            ]
            threshold = quantile(island_values, q) if island_values else math.inf
            success = (not failed) and fitness >= threshold
            report_id = (m.metrics or {}).get("report_id")
            conn.execute(
                text(
                    "INSERT INTO bandit_outcomes (program_id, version_id, island_key, "
                    "generation_seq, success, fitness, threshold, report_id, counted_at) VALUES "
                    "(:p, :v, :i, :seq, :s, :f, :t, :r, :now) ON CONFLICT DO NOTHING"
                ),
                {
                    "p": gen.program_id,
                    "v": m.version_id,
                    "i": m.island,
                    "seq": gen.seq,
                    "s": success,
                    "f": fitness,
                    "t": threshold if math.isfinite(threshold) else -1.0,
                    "r": report_id,
                    "now": self.env.clock.now(),
                },
            )
            counted.add(m.version_id)
            new.setdefault(m.island, []).append(
                {
                    "version_id": str(m.version_id),
                    "success": success,
                    "fitness": fitness,
                    "threshold": threshold if math.isfinite(threshold) else None,
                }
            )
        states = {
            r.island_key: r
            for r in conn.execute(
                text("SELECT * FROM bandit_state WHERE program_id = :p"), {"p": gen.program_id}
            ).all()
        }
        out: dict[str, Any] = {}
        for island in sorted(islands):
            state = states.get(island)
            alpha = float(state.alpha) if state else 1.0
            beta = float(state.beta) if state else 1.0
            if state is None or int(state.updated_generation) < gen.seq:
                alpha = 1.0 + forgetting * (alpha - 1.0)
                beta = 1.0 + forgetting * (beta - 1.0)
            outcomes = new.get(island, [])
            alpha += sum(1 for o in outcomes if o["success"])
            beta += sum(1 for o in outcomes if not o["success"])
            conn.execute(
                text(
                    "INSERT INTO bandit_state (program_id, island_key, alpha, beta, "
                    "updated_generation) VALUES (:p, :i, :a, :b, :g) ON CONFLICT (program_id, "
                    "island_key) DO UPDATE SET alpha = EXCLUDED.alpha, beta = EXCLUDED.beta, "
                    "updated_generation = EXCLUDED.updated_generation"
                ),
                {"p": gen.program_id, "i": island, "a": alpha, "b": beta, "g": gen.seq},
            )
            out[island] = {"alpha": round(alpha, 9), "beta": round(beta, 9), "outcomes": outcomes}
        return out

    def _track_best(
        self,
        conn: Connection,
        gen: GenerationRef,
        members: list[Member],
        islands: dict[str, Any],
        settings: dict[str, Any],
    ) -> dict[str, Any]:
        limit = int(settings["bandit"]["stagnation_generations"])
        out: dict[str, Any] = {}
        for island, row in sorted(islands.items()):
            values = [
                float(m.fitness or 0.0)
                for m in members
                if m.island == island and m.status == "official"
            ]
            best = max(values) if values else None
            best_fitness, best_seq = row.best_fitness, row.best_seq
            if best_seq is None:
                best_fitness, best_seq = best, gen.seq
            elif best is not None and (best_fitness is None or best > best_fitness + 1e-12):
                best_fitness, best_seq = best, gen.seq
            conn.execute(
                text("UPDATE islands SET best_fitness = :f, best_seq = :s WHERE island_id = :i"),
                {"f": best_fitness, "s": best_seq, "i": row.island_id},
            )
            out[island] = {
                "status": row.status,
                "best_fitness": best_fitness,
                "best_seq": best_seq,
                "current_best": best,
                "official": len(values),
                "generations_without_improvement": gen.seq - best_seq,
                "stagnant": row.status == "active" and gen.seq - best_seq >= limit,
            }
        return out

    # P5.3 and P5.6: the proposal -------------------------------------------------------

    def propose(
        self,
        gen: GenerationRef,
        refresh: dict[str, Any],
        strategy_parents: list[str],
        remaining: Decimal,
        per_task: Decimal,
    ) -> Proposal:
        env = self.env
        settings = self.settings(gen.charter)
        throughput = settings["throughput"]
        bandit = settings["bandit"]
        islands = self.islands(gen.program_id)
        active = sorted(k for k, r in islands.items() if r.status == "active")
        themes = {
            k: r.theme + (f" ({r.guidance})" if r.guidance else "") for k, r in islands.items()
        }
        quota = int(throughput["publications"])
        max_slots = min(int(throughput["candidate_slots_max"]), 3 * quota)
        mode = settings["mode"]
        compose_max = int(throughput["compose_strategy_tasks_max"]) if mode in STRATEGY_MODES else 0
        if not strategy_parents:
            compose_max = 0
        with env.db.read() as conn:
            members = load_members(conn, gen.program_id)
            archive_rows = conn.execute(
                text("SELECT * FROM archive_cells WHERE program_id = :p ORDER BY cell_key"),
                {"p": gen.program_id},
            ).all()
            repair_rows = self._repair_targets(conn, gen, settings)

        # Thompson sampling: publication slots per island (Section 12.6).
        states = refresh.get("bandit", {})
        bandit_seed = derive_seed(gen.program_id, gen.seq, "bandit")
        rng = generator(bandit_seed)
        samples = {}
        for island in active:
            state = states.get(island, {"alpha": 1.0, "beta": 1.0})
            samples[island] = float(rng.beta(float(state["alpha"]), float(state["beta"])))
        publication = allocate(
            quota, samples, int(bandit["floor_slots"]), float(bandit["cap_fraction"])
        )
        allocations = candidate_slots(publication, max_slots, active)

        # The operator mix, the mode bias (already in the charter) and the guardrail.
        coverage = float(refresh.get("archive", {}).get("coverage", 0.0))
        top_similarity = self._top_similarity(members, int(bandit["top_similarity_count"]))
        guardrail = coverage < float(bandit["archive_coverage_min"]) or (
            top_similarity is not None and top_similarity > float(bandit["top_similarity_max"])
        )
        base = dict(settings["operator_mix"])
        mix = raise_explore(base, float(bandit["guardrail_exploration"])) if guardrail else base
        stagnant = sorted(
            k for k, v in refresh.get("islands", {}).items() if v.get("stagnant") and k in active
        )

        by_island = {
            island: sorted(
                (
                    m
                    for m in members
                    if m.island == island and m.status in ("official", "provisional")
                ),
                key=Member.key,
            )
            for island in active
        }
        archive = []
        member_by_version = {str(m.version_id): m for m in members}
        for row in archive_rows:
            elite = member_by_version.get(str(row.elite_version_id))
            if elite is not None:
                archive.append(elite.choice())
        provisional_left = {
            str(m.version_id): int(settings["population"]["provisional_children_max"])
            for m in members
            if m.status == "provisional"
        }
        plan_slots = {island: split_slots(allocations[island], mix) for island in active}
        ensure_explore(plan_slots, float(mix["explore"]))
        # Stagnation (Section 12.6): reseed with at least 2 explore tasks, or pause an
        # island too small for that while another island stays active.
        need_explore = int(bandit["stagnation_explore_tasks"])
        pauses: list[IslandPause] = []
        stale = {k: int(refresh["islands"][k]["generations_without_improvement"]) for k in stagnant}
        for island in stagnant:
            if allocations[island] >= need_explore:
                ensure_island_explore(plan_slots[island], need_explore)
            elif len(active) - len(pauses) > 1:
                pauses.append(
                    IslandPause(
                        island_id=island,
                        reason=(
                            f"Stagnant for {stale[island]} generations with "
                            f"{allocations[island]} slot(s), fewer than the "
                            f"{need_explore} explore tasks a reseed needs."
                        ),
                    )
                )
        paused = {p.island_id for p in pauses}
        llm_tasks_estimate = sum(
            math.ceil(counts.get("explore", 0) / 3)
            + counts.get("llm_mutation", 0)
            + counts.get("crossover", 0)
            + counts.get("repair", 0)
            for island, counts in plan_slots.items()
            if island not in paused
        )
        low_budget = per_task > 0 and remaining < per_task * max(1, llm_tasks_estimate)

        tasks: list[PlanTask] = []
        selections: list[dict[str, Any]] = []
        variants: list[dict[str, Any]] = []
        parents_offered: dict[str, dict[str, Any]] = {}
        realised: dict[str, dict[str, int]] = {}

        def offer(choice: Choice, role: str) -> None:
            m = member_by_version.get(choice.version_id)
            parents_offered.setdefault(
                choice.version_id,
                {
                    "island": choice.island,
                    "fitness": choice.fitness,
                    "status": choice.status,
                    "expression": choice.expression,
                    "member_id": None if m is None else str(m.member_id),
                    "flags": list((m.w1 or {}).get("flags", [])) if m is not None else [],
                    "offered_as": role,
                },
            )

        for island in active:
            if island in paused:
                continue
            counts = dict(plan_slots[island])
            island_rng = generator(derive_seed(gen.program_id, gen.seq, "parents", island))
            ranked = [m.choice() for m in by_island[island]]

            def eligible(choices: list[Choice]) -> list[Choice]:
                return [c for c in choices if provisional_left.get(c.version_id, 1) > 0]

            def pick(
                rng: Any = island_rng, ranked: list[Choice] = ranked
            ) -> tuple[Choice, dict[str, Any]] | None:
                picked = select_parent(rng, eligible(ranked), eligible(archive), settings)
                if picked is not None and picked[0].version_id in provisional_left:
                    provisional_left[picked[0].version_id] -= 1
                return picked

            explore = counts.pop("explore", 0)
            mutation_parents: dict[str, list[dict[str, Any]]] = {}
            island_variants: list[dict[str, Any]] = []
            for _ in range(counts.pop("llm_mutation", 0)):
                picked = pick()
                if picked is None:
                    explore += 1
                    continue
                offer(picked[0], "llm_mutation")
                mutation_parents.setdefault(picked[0].version_id, []).append(picked[1])
            for slot in range(counts.pop("crossover", 0)):
                first = pick()
                if first is None:
                    explore += 1
                    continue
                partner = self._partner(island_rng, first[0], members, archive, settings)
                if partner is None:
                    offer(first[0], "llm_mutation")
                    mutation_parents.setdefault(first[0].version_id, []).append(
                        first[1] | {"fallback_from": "crossover", "reason": "NO_PARTNER"}
                    )
                    continue
                offer(first[0], "crossover")
                offer(partner[0], "crossover")
                if low_budget:
                    seed = derive_seed(gen.program_id, gen.seq, "crossover", island, slot)
                    variant = subtree_crossover(
                        [
                            (first[0].version_id, first[0].expression),
                            (partner[0].version_id, partner[0].expression),
                        ],
                        seed,
                        env.limits,
                        settings["constraints"],
                        settings["variation"],
                    )
                    if variant is not None:
                        island_variants.append(
                            self._variant_json(variant, island, [first[1], partner[1]])
                            | {"reason": "LOW_LLM_BUDGET"}
                        )
                        continue
                parents = [first[0].version_id, partner[0].version_id]
                tasks.append(
                    PlanTask(
                        type="crossover",
                        island_id=island,  # type: ignore[arg-type]
                        brief=(
                            "Merge the mechanisms of the two parents into one coherent "
                            "expression with a merged rationale."
                        ),
                        parent_version_ids=[UUID(p) for p in parents],
                        hypothesis_id=None,
                        max_candidates=1,
                    )
                )
                selections.append(
                    {
                        "type": "crossover",
                        "island": island,
                        "parent_version_ids": parents,
                        "selection": [first[1], partner[1]],
                        "parent_fitness": [first[0].fitness, partner[0].fitness],
                    }
                )
            for slot in range(counts.pop("syntactic_mutation", 0)):
                picked = pick()
                if picked is None:
                    explore += 1
                    continue
                seed = derive_seed(gen.program_id, gen.seq, "syntactic", island, slot)
                variant = syntactic_mutation(
                    picked[0].version_id,
                    picked[0].expression,
                    seed,
                    env.limits,
                    settings["constraints"],
                    settings["variation"],
                )
                if variant is None:
                    explore += 1
                    continue
                offer(picked[0], "syntactic_mutation")
                island_variants.append(self._variant_json(variant, island, [picked[1]]))
            repairs = [r for r in repair_rows if r["island"] == island]
            for _ in range(counts.pop("repair", 0)):
                if not repairs:
                    explore += 1
                    continue
                target = repairs.pop(int(island_rng.integers(len(repairs))))
                parents_offered.setdefault(
                    target["version_id"],
                    {
                        "island": island,
                        "fitness": 0.0,
                        "status": "archived",
                        "expression": target["expression"],
                        "member_id": target["member_id"],
                        "flags": target["reasons"],
                        "offered_as": "repair",
                    },
                )
                tasks.append(
                    PlanTask(
                        type="repair",
                        island_id=island,  # type: ignore[arg-type]
                        brief="Repair the screening failure of this promising factor: "
                        + ", ".join(target["reasons"])
                        + ".",
                        parent_version_ids=[UUID(target["version_id"])],
                        hypothesis_id=target["hypothesis_id"],
                        max_candidates=1,
                    )
                )
                selections.append(
                    {
                        "type": "repair",
                        "island": island,
                        "parent_version_ids": [target["version_id"]],
                        "selection": [{"rule": "repair_target", "reasons": target["reasons"]}],
                        "parent_fitness": [0.0],
                    }
                )
            for parent, picks in mutation_parents.items():
                remaining_count = len(picks)
                while remaining_count > 0:
                    take = min(3, remaining_count)
                    tasks.append(
                        PlanTask(
                            type="llm_mutation",
                            island_id=island,  # type: ignore[arg-type]
                            brief="Revise the parent's weakest decision, targeted by its flags.",
                            parent_version_ids=[UUID(parent)],
                            hypothesis_id=None,
                            max_candidates=take,
                        )
                    )
                    selections.append(
                        {
                            "type": "llm_mutation",
                            "island": island,
                            "parent_version_ids": [parent],
                            "selection": picks[:take],
                            "parent_fitness": [parents_offered[parent]["fitness"]],
                            "targeted_flags": parents_offered[parent]["flags"],
                        }
                    )
                    picks = picks[take:]
                    remaining_count -= take
            for start in range(0, len(island_variants), 3):
                batch = island_variants[start : start + 3]
                parents = sorted({p for v in batch for p in v["parent_version_ids"]})
                tasks.append(
                    PlanTask(
                        type="syntactic_batch",
                        island_id=island,  # type: ignore[arg-type]
                        brief="Ready-made deterministic variants: "
                        + ", ".join(v["rule"] for v in batch)
                        + ".",
                        parent_version_ids=[UUID(p) for p in parents],
                        hypothesis_id=None,
                        max_candidates=len(batch),
                    )
                )
            variants += island_variants
            need = int(bandit["stagnation_explore_tasks"]) if island in stagnant else 1
            explore_tasks = explore_task_sizes(explore, need)
            for size in explore_tasks:
                tasks.append(
                    PlanTask(
                        type="explore",
                        island_id=island,  # type: ignore[arg-type]
                        brief=f"Explore a new mechanism for the theme: {themes[island]}.",
                        parent_version_ids=[],
                        hypothesis_id=None,
                        max_candidates=size,
                    )
                )
            realised[island] = {
                "explore": sum(explore_tasks),
                "llm_mutation": sum(len(v) for v in mutation_parents.values()),
                "crossover": sum(
                    1 for t in tasks if t.island_id == island and t.type == "crossover"
                )
                + sum(1 for v in island_variants if v["operator"] == "crossover"),
                "syntactic_mutation": sum(
                    1 for v in island_variants if v["operator"] == "syntactic_mutation"
                ),
                "repair": sum(1 for t in tasks if t.island_id == island and t.type == "repair"),
            }
        working = [k for k in active if k not in paused]
        for i in range(compose_max):
            tasks.append(
                PlanTask(
                    type="compose_strategy",
                    island_id=working[i % len(working)],  # type: ignore[arg-type]
                    brief="Compose a strategy from the published factors listed.",
                    parent_version_ids=[],
                    hypothesis_id=None,
                    max_candidates=1,
                )
            )
        factor_allocations = {
            k: sum(
                t.max_candidates for t in tasks if t.island_id == k and t.type != "compose_strategy"
            )
            for k in working
        }
        plan = GenerationPlan(
            objectives=["Follow the evolution engine's proposal on every active island."],
            allocations=factor_allocations,  # type: ignore[arg-type]
            allocation_reasons={},
            tasks=sorted(tasks, key=lambda t: (t.island_id, _TYPE_ORDER[t.type])),
            islands_to_pause=pauses,
            rationale=(
                "Deterministic default plan from the evolution engine: Thompson-sampled "
                "slots, the operator mix and the selected parents."
            ),
        )
        min_explore = float(mix["explore"])
        return Proposal(
            islands=active,
            allocations=factor_allocations,
            operator_mix=mix,
            parents=sorted(set(parents_offered) | set(strategy_parents)),
            publication_quota=quota,
            max_slots=max_slots,
            min_explore_share=min_explore,
            compose_strategy_max=compose_max,
            default_plan=plan,
            engine={
                "engine": "evolution/1",
                "bandit_seed": bandit_seed,
                "bandit_samples": {k: round(v, 12) for k, v in samples.items()},
                "publication_slots": publication,
                "operator_slots": plan_slots,
                "realised_slots": realised,
                "guardrail": {
                    "raised": guardrail,
                    "archive_coverage": coverage,
                    "top_similarity": top_similarity,
                },
                "stagnant_islands": stagnant,
                "stagnation_choice": {k: ("pause" if k in paused else "reseed") for k in stagnant},
                "low_llm_budget": low_budget,
                "remaining_cny": float(remaining),
                "task_estimate_cny": float(per_task),
                "themes": {k: themes[k] for k in active},
            },
            publication_slots=publication,
            parent_info=parents_offered,
            selections=selections,
            variants=variants,
            stagnant_islands=stagnant,
            provisional_parents=sorted(
                v for v, info in parents_offered.items() if info["status"] == "provisional"
            ),
            provisional_children_max=int(settings["population"]["provisional_children_max"]),
            stagnation_explore_tasks=int(bandit["stagnation_explore_tasks"]),
        )

    def _variant_json(
        self, variant: Variant, island: str, selection: list[dict[str, Any]]
    ) -> dict[str, Any]:
        body = variant.as_json()
        body["variant_id"] = variant.canonical_hash[:16] + f"-{variant.seed % 10**6:06d}"
        body["island"] = island
        body["selection"] = selection
        return body

    def _partner(
        self,
        rng: Any,
        first: Choice,
        members: list[Member],
        archive: list[Choice],
        settings: dict[str, Any],
    ) -> tuple[Choice, dict[str, Any]] | None:
        """A second parent from another island or an archive cell, behaviorally at most
        crossover_similarity_max similar to the first (Section 12.3)."""
        limit = float(settings["selection"]["crossover_similarity_max"])
        offered: dict[str, Choice] = {}
        for m in sorted(members, key=Member.key):
            if m.status == "official" and m.island != first.island:
                offered.setdefault(str(m.version_id), m.choice())
        for choice in archive:
            offered.setdefault(choice.version_id, choice)
        ranked = []
        similarities = {}
        for version_id, choice in offered.items():
            if version_id == first.version_id:
                continue
            similarity = self.similarity(first.expression, choice.expression)
            if similarity is None or similarity > limit:
                continue
            similarities[version_id] = round(similarity, 6)
            ranked.append(choice)
        ranked.sort(key=lambda c: (-c.fitness, c.version_id))
        picked = tournament(
            rng,
            ranked,
            int(settings["selection"]["tournament_size"]),
            int(settings["selection"]["tournament_top"]),
        )
        if picked is None:
            return None
        choice, detail = picked
        return choice, detail | {
            "rule": "crossover_partner",
            "similarity": similarities[choice.version_id],
            "similarity_max": limit,
            "eligible": len(ranked),
        }

    def _top_similarity(self, members: list[Member], count: int) -> float | None:
        """Mean pairwise behavioral similarity among the top official members."""
        top: list[Member] = []
        seen: set[UUID] = set()
        for m in sorted((m for m in members if m.status == "official"), key=Member.key):
            if m.version_id not in seen:
                seen.add(m.version_id)
                top.append(m)
            if len(top) >= count:
                break
        values = []
        for i, a in enumerate(top):
            for b in top[i + 1 :]:
                similarity = self.similarity(a.expression, b.expression)
                if similarity is not None:
                    values.append(similarity)
        return round(sum(values) / len(values), 6) if values else None

    def _repair_targets(
        self, conn: Connection, gen: GenerationRef, settings: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Program versions whose screening failed for a repairable reason, whose
        hypothesis is still open or supported, and that no repair task has taken yet."""
        reasons = set(settings["variation"]["repair_reasons"])
        rows = conn.execute(
            text(
                "SELECT m.member_id, m.island_key, m.version_id, m.expression, m.metrics, "
                "c.hypothesis_id FROM population_members m JOIN candidates c ON "
                "c.candidate_id = m.candidate_id LEFT JOIN hypotheses h ON "
                "h.hypothesis_id = c.hypothesis_id WHERE m.program_id = :p AND "
                "m.status = 'archived' AND m.archived_reason = 'SCREENING_FAILED' AND "
                "(h.status IS NULL OR h.status IN ('open', 'supported')) AND NOT EXISTS ("
                "SELECT 1 FROM tasks t JOIN generations g ON g.generation_id = t.generation_id "
                "WHERE g.program_id = m.program_id AND t.type = 'repair' AND "
                "t.parent_version_ids @> to_jsonb(ARRAY[CAST(m.version_id AS text)])) "
                "ORDER BY m.version_id"
            ),
            {"p": gen.program_id},
        ).all()
        out = []
        for r in rows:
            found = sorted(set((r.metrics or {}).get("reasons", [])) & reasons)
            if found:
                out.append(
                    {
                        "member_id": str(r.member_id),
                        "island": r.island_key,
                        "version_id": str(r.version_id),
                        "expression": r.expression,
                        "hypothesis_id": r.hypothesis_id,
                        "reasons": found,
                    }
                )
        return out


_TYPE_ORDER = {
    "llm_mutation": 0,
    "crossover": 1,
    "repair": 2,
    "syntactic_batch": 3,
    "explore": 4,
    "compose_strategy": 5,
}


def allocate(
    quota: int, samples: dict[str, float], floor: int, cap_fraction: float
) -> dict[str, int]:
    """Split the publication quota in proportion to the sampled values, with a floor per
    active island and a cap per island (Section 12.6). When the floor cannot be met for
    every island, the islands with the highest samples get it. The cap never forces
    slots to go unused: it is at least the quota's even share."""
    islands = sorted(samples)
    if not islands:
        return {}
    cap = max(math.ceil(quota / len(islands)), math.floor(cap_fraction * quota))
    order = sorted(islands, key=lambda k: (-samples[k], k))
    slots = {k: 0 for k in islands}
    budget = quota
    for k in order:
        give = min(floor, budget)
        slots[k] += give
        budget -= give
    total = sum(samples.values()) or 1.0
    while budget > 0:
        open_ = [k for k in order if slots[k] < cap]
        if not open_:
            break
        # The island furthest below its proportional target gets the next slot.
        k = max(open_, key=lambda i: (samples[i] / total * quota - slots[i], samples[i], i))
        slots[k] += 1
        budget -= 1
    return slots


def candidate_slots(
    publication: dict[str, int], max_slots: int, islands: list[str]
) -> dict[str, int]:
    """Three candidate slots per publication slot, at least one per active island, and no
    more than the generation's candidate cap."""
    slots = {k: max(1, 3 * publication.get(k, 0)) for k in islands}
    while sum(slots.values()) > max_slots and any(v > 1 for v in slots.values()):
        k = max(slots, key=lambda i: (slots[i], i))
        slots[k] -= 1
    return slots


def raise_explore(mix: dict[str, float], share: float) -> dict[str, float]:
    """The guardrail's mix: explore at least `share`, the other operators scaled down."""
    base = float(mix.get("explore", 0.0))
    if base >= share:
        return dict(mix)
    rest = 1.0 - base
    scale = (1.0 - share) / rest if rest > 0 else 0.0
    return {k: (share if k == "explore" else round(float(v) * scale, 12)) for k, v in mix.items()}


def split_slots(slots: int, mix: dict[str, float]) -> dict[str, int]:
    """Largest-remainder rounding of an island's slots over the operator mix."""
    keys = sorted(mix)
    total = sum(float(mix[k]) for k in keys) or 1.0
    exact = {k: slots * float(mix[k]) / total for k in keys}
    out = {k: int(math.floor(v)) for k, v in exact.items()}
    left = slots - sum(out.values())
    for k in sorted(keys, key=lambda k: (-(exact[k] - out[k]), -float(mix[k]), k))[:left]:
        out[k] += 1
    return out


def ensure_explore(plan_slots: dict[str, dict[str, int]], share: float) -> None:
    """Rounding per island must not push the generation's explore slots below the mix's
    share: the shortfall moves from the largest other operator counts (deterministic)."""
    total = sum(sum(c.values()) for c in plan_slots.values())
    need = math.ceil(share * total - 1e-9)
    have = sum(c.get("explore", 0) for c in plan_slots.values())
    while have < need:
        donors = [
            (n, island, op)
            for island, counts in plan_slots.items()
            for op, n in counts.items()
            if op != "explore" and n > 0
        ]
        if not donors:
            return
        _, island, op = max(donors)
        plan_slots[island][op] -= 1
        plan_slots[island]["explore"] = plan_slots[island].get("explore", 0) + 1
        have += 1


def ensure_island_explore(counts: dict[str, int], need: int) -> None:
    """A stagnant island's reseed: at least `need` explore slots."""
    while counts.get("explore", 0) < need:
        donors = [(n, op) for op, n in counts.items() if op != "explore" and n > 0]
        if not donors:
            return
        _, op = max(donors)
        counts[op] -= 1
        counts["explore"] = counts.get("explore", 0) + 1


def explore_task_sizes(slots: int, minimum_tasks: int) -> list[int]:
    """Explore tasks of at most 3 candidates, at least minimum_tasks of them when there
    are enough slots."""
    if slots <= 0:
        return []
    tasks = max(math.ceil(slots / 3), min(minimum_tasks, slots))
    base, extra = divmod(slots, tasks)
    return [base + (1 if i < extra else 0) for i in range(tasks)]
