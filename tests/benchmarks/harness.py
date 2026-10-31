"""The benchmark harness for BM-PLANTED and BM-NULL at W1 level (PLAN Section 18.3, P5.8).

A scripted client submits the job through the MCP front door; research runs its normal
generations with a scripted LLM; the evaluator measures every publication on W1 and the
release engine releases the reports. Nothing here reaches a provider.

The scripted LLM follows the engine's proposal (the supervisor returns the proposed
tasks) and drafts from the 300-expression pool (tests/benchmarks/pool.py) the way an
engineer with tools would:

- it picks options: explore draws pool entries at random; llm_mutation and crossover
  first try moving a planted-family parent one window step towards the planted form
  (what a flag-targeted revision would do), then draw at random; repair draws at random;
- it checks every option with workbench.evaluate (W0, in-sample) and similarity.search;
- it drafts the options with the strongest in-sample RankIC_IR that are not near
  duplicates, each with the sign its in-sample RankIC shows.

On the null world the in-sample signs fit noise, which is what BM-NULL measures.

Its draws come from one seeded generator, so the scripted answers are fixed for a fixed
seed and a fixed call order. The engine derives its own draws from the program id, which
is fresh in every run; fix_engine_seeds puts the benchmark's seed in its place, so the
engine's draws are fixed too (Section 18.3: fixed seeds), and the job runs one task at a
time so the scripted roles are asked in the same order. Every engine draw is also
recorded in the PROPOSAL_EMITTED steps.
"""

import json
import random
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import qfr_research.engine
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo
from qfr_core.metrics.matrix import row_spearman
from qfr_research.variation import derive_seed

from tests.benchmarks.pool import A1, A2, Entry, canonical, index, pool, towards_planted
from tests.research.rig import ResearchStack, brief
from tests.research.scripted import UUID, Script, ScriptedModels, answer

PARENT_LINE = re.compile(rf"^- parent ({UUID}): (\{{.*\}})$", re.MULTILINE)
HORIZONS = (1, 5, 10, 20)
DISCOVERY_CORRELATION = 0.7
OPTIONS_PER_DRAFT = 3  # options checked with the tools per draft asked for
OPTIONS_MAX = 9  # 2 tool calls per option, within the engineer's 20 tool calls
NEAR_DUPLICATE = 0.9  # the pre-screen's behavioral similarity limit
LOW_ORIGINALITY = 0.2  # the pre-screen's AST originality minimum


def fix_engine_seeds(monkeypatch: pytest.MonkeyPatch, seed: int) -> None:
    """The engine's seeds are derive_seed(program_id, generation, purpose, ...); in a
    benchmark the benchmark's seed stands in for the fresh program id."""
    monkeypatch.setattr(
        qfr_research.engine, "derive_seed", lambda _program, *parts: derive_seed(seed, *parts)
    )


@dataclass
class Draw:
    operator: str
    family: str
    expression: str
    parents: list[str]


@dataclass
class BenchmarkScript(Script):
    """The scripted roles of a benchmark run: no fixed expressions; the pool instead."""

    seed: int = 0
    draws: list[Draw] = field(default_factory=list)
    hypotheses: int = 0


class BenchmarkModels(ScriptedModels):
    """ScriptedModels whose supervisor follows the proposal and whose engineer drafts from
    the benchmark pool."""

    script: BenchmarkScript

    def __init__(self, config: Any, script: BenchmarkScript) -> None:
        super().__init__(config, script)
        self.rng = random.Random(script.seed)
        self.entries = pool()
        self.by_expression = index()

    def _supervisor(self, text: str, messages: list[ModelMessage], info: AgentInfo) -> Any:
        view = json.loads(text.split("Proposal:\n", 1)[1].split("\n", 1)[0])
        choice = (view.get("engine") or {}).get("stagnation_choice") or {}
        pauses = [
            {"island_id": k, "reason": "Stagnant and too small to reseed, as proposed."}
            for k, v in sorted(choice.items())
            if v == "pause"
        ]
        return answer(
            info,
            {
                "objectives": ["Follow the engine's proposal on every island."],
                "allocations": view["allocations"],
                "allocation_reasons": {},
                "tasks": view["tasks"],
                "islands_to_pause": pauses,
                "rationale": "The proposed tasks, unchanged.",
            },
        )

    def _hypothesis(self, text: str, messages: list[ModelMessage], info: AgentInfo) -> Any:
        self.script.hypotheses += 1
        n = self.script.hypotheses
        island = re.search(r"Island: (I\d)", text)
        return answer(
            info,
            {
                "hypotheses": [
                    {
                        "title": f"Benchmark mechanism {n}",
                        "observation": "Recent price and volume moves carry information.",
                        "mechanism": "Investors under- or overreact to short-term moves.",
                        "expected_sign": 1,
                        "horizon_days": 5,
                        "fields_required": ["close"],
                        "falsification": "No relation to forward returns out of sample.",
                        "novelty_note": f"Scripted benchmark hypothesis {n}.",
                        "risks": "Crowding and transaction costs.",
                        "island_id": island.group(1) if island else "I6",
                        "tags": ["benchmark"],
                    }
                ]
            },
        )

    def _engineer(self, text: str, messages: list[ModelMessage], info: AgentInfo) -> Any:
        operator_found = re.search(r"the operator \((\w+)\)", text)
        operator = operator_found.group(1) if operator_found else "explore"
        limit = re.search(r"into 1 to (\d+) qfr-dsl", text)
        count = int(limit.group(1)) if limit else 1
        found = re.search(rf"hypothesis_id ({UUID})", text)
        parents = [(version_id, json.loads(body)) for version_id, body in PARENT_LINE.findall(text)]
        parent_ids = [p for p, _ in parents]
        parent_expressions = [str(b.get("expression", "")) for _, b in parents]
        calls, returns = tool_exchange(messages)
        tools = {t.name for t in info.function_tools}
        if not calls and {"workbench_evaluate", "similarity_search"} <= tools:
            options = self.options(operator, parent_expressions, count)
            parts = []
            for i, entry in enumerate(options):
                parts.append(
                    ToolCallPart(
                        "workbench_evaluate",
                        {"expression": entry.expression, "expected_sign": 1},
                        tool_call_id=f"wb-{i}",
                    )
                )
                parts.append(
                    ToolCallPart(
                        "similarity_search",
                        {"expression": entry.expression, "limit": 1},
                        tool_call_id=f"sim-{i}",
                    )
                )
            return ModelResponse(parts=parts)
        checked = []
        for call_id, (name, args) in calls.items():
            if name != "workbench_evaluate":
                continue
            entry = self.by_expression[args["expression"]]
            bench = returns.get(call_id) or {}
            similar = returns.get("sim-" + call_id.removeprefix("wb-")) or {}
            metrics = bench.get("metrics") or {}
            ic, ir = metrics.get("rankic_mean"), metrics.get("rankic_ir")
            duplicate = (similar.get("max_behavioral_similarity") or 0.0) > NEAR_DUPLICATE or (
                float(similar.get("originality", 1.0)) < LOW_ORIGINALITY
            )
            sign = -1 if (ic is not None and ic < 0) else 1
            checked.append((duplicate, -abs(float(ir or 0.0)), call_id, entry, sign))
        checked.sort(key=lambda c: (c[0], c[1], c[2]))
        chosen = [c for c in checked if not c[0]][:count] or checked[:1]
        drafts = []
        for _, _, _, entry, sign in chosen:
            horizon = 5 if entry.family == "A1" else self.rng.choice(HORIZONS)
            self.script.draws.append(Draw(operator, entry.family, entry.expression, parent_ids))
            drafts.append(
                {
                    "hypothesis_id": found.group(1) if found else None,
                    "expression": entry.expression,
                    "description": "Each part of the expression maps to the mechanism.",
                    "expected_sign": sign,
                    "horizon_days": horizon,
                    "parameter_rationale": "The windows match the horizon of the mechanism.",
                    "operator": operator,
                    "parent_version_ids": parent_ids,
                    "change_summary": None
                    if operator == "explore"
                    else f"Moved to the {entry.family} variant at window {entry.window}.",
                }
            )
        return answer(info, {"drafts": drafts})

    def options(self, operator: str, parent_expressions: list[str], count: int) -> list[Entry]:
        """Distinct pool entries to check: towards the planted form from a planted-family
        parent first (mutation and crossover), then random draws."""
        wanted = min(OPTIONS_MAX, OPTIONS_PER_DRAFT * count)
        parents = {_canonical(e) for e in parent_expressions}
        out: list[Entry] = []
        if operator in ("llm_mutation", "crossover"):
            known = [self.by_expression.get(e) for e in sorted(parents)]
            for entry in (e for e in known if e is not None and e.family != "noise"):
                moved = towards_planted(entry)
                if moved.expression not in parents and moved not in out:
                    out.append(moved)
        while len(out) < wanted:
            entry = self.entries[self.rng.randrange(len(self.entries))]
            if entry not in out and entry.expression not in parents:
                out.append(entry)
        return out[:wanted]


def tool_exchange(
    messages: list[ModelMessage],
) -> tuple[dict[str, tuple[str, dict[str, Any]]], dict[str, Any]]:
    """The tool calls this run made, by call id, and what each returned."""
    calls: dict[str, tuple[str, dict[str, Any]]] = {}
    returns: dict[str, Any] = {}
    for message in messages:
        for part in message.parts:
            if isinstance(message, ModelResponse) and isinstance(part, ToolCallPart):
                calls[part.tool_call_id] = (part.tool_name, part.args_as_dict())
            elif isinstance(message, ModelRequest) and isinstance(part, ToolReturnPart):
                returns[part.tool_call_id] = part.content
    return calls, returns


def _canonical(expression: str) -> str:
    try:
        return canonical(expression)
    except Exception:  # noqa: BLE001 - an expression outside the pool's grammar
        return expression


# The run -----------------------------------------------------------------------------------


@dataclass
class Generation:
    seq: int
    state: str
    published: int
    plan_source: str | None
    candidates: int
    best_fitness: float | None  # the best current official fitness over the islands
    tracked_best: float | None  # the best fitness any island has reached so far
    coverage: float
    cells: list[str]  # the archive cells with an elite, read at the generation's start
    official: int
    guardrail: bool
    operators: dict[str, int]
    outcomes: dict[str, int]  # why candidates were not published, and how many were


@dataclass
class BenchmarkRun:
    job_id: str
    generations: list[Generation]
    published: list[dict[str, Any]]
    deliverable: dict[str, Any] | None
    job_state: str
    clock_hours: float

    def summary(self) -> dict[str, Any]:
        fitness = [g.best_fitness for g in self.generations if g.best_fitness is not None]
        evaluated = [p for p in self.published if p["evidence_tier"] in ("w1_pass", "w1_fail")]
        passed = [p for p in evaluated if p["evidence_tier"] == "w1_pass"]
        return {
            "generations": len(self.generations),
            "published": len(self.published),
            "w1_evaluated": len(evaluated),
            "w1_passed": len(passed),
            "w1_pass_rate": round(len(passed) / len(evaluated), 6) if evaluated else None,
            "first_best_fitness": fitness[0] if fitness else None,
            "last_best_fitness": fitness[-1] if fitness else None,
            "final_coverage": self.generations[-1].coverage if self.generations else 0.0,
            "job_state": self.job_state,
            "clock_hours": round(self.clock_hours, 2),
        }


def benchmark_brief(generations: int, islands: list[str]) -> dict[str, Any]:
    """A brief that keeps the job running for every generation: the deliverable asks for
    more W1 passes than the run can publish, so research stops on the generation cap."""
    return brief(
        title="Benchmark run",
        objective="Find short-horizon price and volume factors on the synthetic universe.",
        islands=islands,
        deliverable={"tier": "w1_pass", "min_count": 200, "max_candidates": 200},
        budget={"max_cost": 400.0, "max_generations": generations, "max_wall_clock_days": 60},
    )


GENERATION_HOURS = 1  # test-clock time one generation and its evaluation take
DRAIN_HOURS = 6  # test-clock step after the generation cap, a quarter of a quota window


def run_benchmark(
    full: ResearchStack, generations: int, islands: list[str], drain_steps: int = 40
) -> BenchmarkRun:
    """Run the job as research-worker would on the plan v2.2 cadence: a generation starts
    when the previous one's feedback is complete (or after the max wait), the evaluator
    works off what it published, and its reports are released at once. The test clock
    moves GENERATION_HOURS per generation, so the 24-hour quotas see a realistic pace."""
    mcp, research = full.mcp, full.research
    # Fixed seeds give fixed runs only if the scripted roles are asked in the same order
    # every time, so the benchmark job's charter runs one task at a time.
    research.config.charter_values["throughput"]["concurrency"] = 1  # type: ignore[index]
    started_at = full.eval.clock.at
    submitted = mcp.ok("qfr.job.submit", brief=benchmark_brief(generations, islands))["data"]
    job_id = submitted["job"]["job_id"]
    ran = idle = 0
    while ran < generations:
        if research.tick()["ran"]:
            ran += 1
            idle = 0
            full.settle()  # the evaluator pulls, screens and runs W1
            deliver_reports(full, full.eval.clock.at + timedelta(hours=GENERATION_HOURS))
            continue
        # Nothing was due: research stopped, or the feedback is incomplete and the next
        # generation waits for the max wait (or the next day, after the daily cost cap).
        job = research.db.rows(
            "SELECT next_generation_at, daily_wait_until FROM research_jobs WHERE job_id = :j",
            j=job_id,
        )[0]
        if job.next_generation_at is None:
            break
        idle += 1
        assert idle <= 3, "research is not starting generations"
        due = max(d for d in (job.next_generation_at, job.daily_wait_until) if d is not None)
        full.settle()
        deliver_reports(full, max(full.eval.clock.at + timedelta(hours=GENERATION_HOURS), due))
    # Research has stopped on the generation cap; the evaluator works off what is queued
    # (deferred versions wait for their family quota) and the job closes with a deliverable.
    for _ in range(drain_steps):
        state = _job_state(full, job_id)
        if state in ("CLOSED", "DELIVERABLE_READY", "DELIVERED"):
            break
        full.settle()
        deliver_reports(full, full.eval.clock.at + timedelta(hours=DRAIN_HOURS))
        research.tick()
    return BenchmarkRun(
        job_id,
        _generations(full, job_id),
        _published(full, job_id),
        _deliverable(full, job_id),
        _job_state(full, job_id),
        (full.eval.clock.at - started_at).total_seconds() / 3600,
    )


def deliver_reports(full: ResearchStack, at: Any) -> None:
    """Run the release step, then move the shared clock to `at`. Reports are released as
    soon as the evaluator records them (plan v2.2); the clock then stands for the time
    the next generation and its evaluation take."""
    full.eval.release.tick()
    full.eval.clock.at = at


def _job_state(full: ResearchStack, job_id: str) -> str:
    return str(
        full.research.db.scalar("SELECT state FROM research_jobs WHERE job_id = :j", j=job_id)
    )


def _generations(full: ResearchStack, job_id: str) -> list[Generation]:
    db = full.research.db
    rows = db.rows(
        "SELECT g.generation_id, g.seq, g.state, g.summary FROM generations g JOIN programs p "
        "ON p.program_id = g.program_id WHERE p.job_id = :j AND g.seq > 0 ORDER BY g.seq",
        j=job_id,
    )
    out = []
    for row in rows:
        step = db.rows(
            "SELECT payload FROM trace_steps WHERE generation_id = :g AND step_type = "
            "'PROPOSAL_EMITTED' ORDER BY at LIMIT 1",
            g=row.generation_id,
        )
        payload = step[0].payload if step else {}
        refresh = payload.get("refresh") or {}
        islands = refresh.get("islands") or {}
        bests = [v["current_best"] for v in islands.values() if v.get("current_best") is not None]
        tracked = [v["best_fitness"] for v in islands.values() if v.get("best_fitness") is not None]
        operators: dict[str, int] = {}
        for c in db.rows(
            "SELECT operator, count(*) AS n FROM candidates WHERE generation_id = :g GROUP BY "
            "operator",
            g=row.generation_id,
        ):
            operators[c.operator] = int(c.n)
        outcomes: dict[str, int] = {}
        for c in db.rows(
            "SELECT state, reason FROM candidates WHERE generation_id = :g", g=row.generation_id
        ):
            for key in _outcome_keys(c.state, c.reason):
                outcomes[key] = outcomes.get(key, 0) + 1
        out.append(
            Generation(
                seq=int(row.seq),
                state=row.state,
                published=len((row.summary or {}).get("published_version_ids") or []),
                plan_source=(row.summary or {}).get("plan_source"),
                candidates=sum(operators.values()),
                best_fitness=max(bests) if bests else None,
                tracked_best=max(tracked) if tracked else None,
                coverage=float((refresh.get("archive") or {}).get("coverage", 0.0)),
                cells=sorted(((refresh.get("archive") or {}).get("elites") or {}).keys()),
                official=sum(int(v.get("official", 0)) for v in islands.values()),
                guardrail=bool(
                    ((payload.get("engine") or {}).get("guardrail") or {}).get("raised")
                ),
                operators=operators,
                outcomes=dict(sorted(outcomes.items())),
            )
        )
    return out


def _outcome_keys(state: str, reason: str | None) -> list[str]:
    if reason and reason.startswith("PRESCREEN_FAILED:"):
        return ["prescreen:" + check for check in reason.split(":", 1)[1].split(",")]
    return [f"{state}:{reason}" if reason else state]


def _published(full: ResearchStack, job_id: str) -> list[dict[str, Any]]:
    """Every published factor with its generation, operator, evaluator tier and signed
    rank correlation to A1 and A2 on W0 (the research zone's window)."""
    db = full.research.db
    rows = db.rows(
        "SELECT v.version_id, c.expression, c.operator, c.island_key, c.payload, g.seq FROM "
        "candidate_versions v JOIN candidates c ON c.candidate_id = v.candidate_id JOIN "
        "generations g ON g.generation_id = c.generation_id JOIN programs p ON p.program_id = "
        "c.program_id WHERE p.job_id = :j AND c.kind = 'factor' ORDER BY g.seq, c.island_key, "
        "c.canonical_hash",
        j=job_id,
    )
    if not rows:
        return []
    states = full.admin.get(
        "/v1/versions/state", params={"version_id": [str(r.version_id) for r in rows]}
    ).json()["items"]
    tiers = {s["version_id"]: s["evidence_tier"] for s in states}
    parents: dict[str, list[str]] = {}
    for edge in db.rows(
        "SELECT child_version_id, parent_version_id FROM lineage_edges ORDER BY parent_version_id"
    ):
        parents.setdefault(str(edge.child_version_id), []).append(str(edge.parent_version_id))
    correlate = Correlator(full.research.env.workbench)
    out = []
    for r in rows:
        sign = int((r.payload or {}).get("expected_sign", 1))
        out.append(
            {
                "version_id": str(r.version_id),
                "generation_seq": int(r.seq),
                "operator": r.operator,
                "island": r.island_key,
                "expression": r.expression,
                "expected_sign": sign,
                "evidence_tier": tiers.get(str(r.version_id), "pending"),
                "parent_version_ids": parents.get(str(r.version_id), []),
                "rank_corr_a1": correlate(r.expression, sign, A1),
                "rank_corr_a2": correlate(r.expression, sign, A2),
            }
        )
    return out


def _deliverable(full: ResearchStack, job_id: str) -> dict[str, Any] | None:
    listed = full.mcp.ok("qfr.deliverable.list", job_id=job_id)["data"]["items"]
    if not listed:
        return None
    return dict(
        full.mcp.ok("qfr.deliverable.get", deliverable_id=listed[0]["deliverable_id"])["data"]
    )


class Correlator:
    """Mean cross-sectional Spearman correlation of sign x factor with a planted signal
    over the eligible names of every W0 date."""

    def __init__(self, workbench: Any) -> None:
        self.workbench = workbench
        self.cache: dict[str, Any] = {}
        days = np.array(workbench.market.dates, dtype="datetime64[D]")
        self.rows = (days >= np.datetime64(workbench.window.start)) & (
            days <= np.datetime64(workbench.window.end)
        )

    def values(self, expression: str) -> Any:
        if expression not in self.cache:
            values = self.workbench.values(expression)[0]
            eligible = self.workbench.market.eligible
            self.cache[expression] = np.where(eligible, values, np.nan)[self.rows]
        return self.cache[expression]

    def __call__(self, expression: str, sign: int, planted: str) -> float | None:
        values = row_spearman(sign * self.values(expression), self.values(planted))
        finite = values[np.isfinite(values)]
        return round(float(finite.mean()), 6) if finite.size else None


APPLIED_STEPS = (
    "MUTATION_APPLIED",
    "CROSSOVER_APPLIED",
    "SYNTACTIC_MUTATION_APPLIED",
    "REPAIR_APPLIED",
)


def operator_steps(full: ResearchStack) -> dict[str, Any]:
    """TRC-03, first half: every operator application names its parents and records an
    AST diff from each of them."""
    counts: dict[str, int] = {}
    missing = []
    for step in full.research.db.rows(
        "SELECT step_id, step_type, inputs, payload FROM trace_steps WHERE step_type = "
        "ANY(:t) ORDER BY at",
        t=list(APPLIED_STEPS),
    ):
        counts[step.step_type] = counts.get(step.step_type, 0) + 1
        parents = list((step.inputs or {}).get("parent_version_ids") or [])
        diffs = (step.payload or {}).get("ast_diffs")
        ok = (
            bool(parents)
            and isinstance(diffs, list)
            and len(diffs) == len(parents)
            and any(diffs)
            and len(step.payload.get("expressions_before") or []) == len(parents)
        )
        if not ok:
            missing.append({"step_id": str(step.step_id), "step_type": step.step_type})
    return {"counts": counts, "missing": missing}


def lineage_report(full: ResearchStack, run: BenchmarkRun) -> dict[str, Any]:
    """TRC-03, second half: qfr.trace.export's iteration history of every published
    version has one hop per node of its lineage DAG, parents before children, each hop
    from exactly the node's parents, a crossover hop from two. Also the generations each
    lineage spans and whether it includes a crossover."""
    parents = {p["version_id"]: list(p["parent_version_ids"]) for p in run.published}
    mismatches: list[dict[str, Any]] = []
    spans: dict[str, dict[str, Any]] = {}
    for item in run.published:
        version_id = item["version_id"]
        nodes, frontier = {version_id}, [version_id]
        while frontier:
            frontier = [q for v in frontier for q in parents.get(v, []) if q not in nodes]
            nodes.update(frontier)
        exported = full.mcp.ok("qfr.trace.export", version_id=version_id)["data"]
        hops = exported["iteration_history"]["hops"]
        seen: set[str] = set()
        problems = []
        if {h["to_version_id"] for h in hops} != nodes:
            problems.append("HOPS_DO_NOT_COVER_THE_DAG")
        for hop in hops:
            to = hop["to_version_id"]
            if sorted(hop["from_version_ids"]) != sorted(parents.get(to, [])):
                problems.append(f"WRONG_PARENTS:{to}")
            if not set(hop["from_version_ids"]) <= seen:
                problems.append(f"PARENT_AFTER_CHILD:{to}")
            if hop["from_version_ids"] and not hop["ast_diff"]:
                problems.append(f"NO_AST_DIFF:{to}")
            if hop["operator"] == "crossover" and len(hop["from_version_ids"]) != 2:
                problems.append(f"CROSSOVER_ARITY:{to}")
            seen.add(to)
        if problems:
            mismatches.append({"version_id": version_id, "problems": problems})
        spans[version_id] = {
            "generations": len({h["generation_seq"] for h in hops}),
            "hops": len(hops),
            "crossover": any(h["operator"] == "crossover" for h in hops),
            "operators": sorted({h["operator"] for h in hops}),
        }
    with_crossover = [(v, s) for v, s in spans.items() if s["crossover"]]
    deepest = max(
        with_crossover, key=lambda x: (x[1]["generations"], x[1]["hops"], x[0]), default=None
    )
    return {
        "checked": len(spans),
        "mismatches": mismatches,
        "spans": spans,
        "deepest_with_crossover": None
        if deepest is None
        else {"version_id": deepest[0]} | deepest[1],
        "deepest": max((s["generations"] for s in spans.values()), default=0),
    }


def discoveries(run: BenchmarkRun) -> list[dict[str, Any]]:
    return [
        p
        for p in run.published
        if p["evidence_tier"] == "w1_pass"
        and max(p["rank_corr_a1"] or -1.0, p["rank_corr_a2"] or -1.0) >= DISCOVERY_CORRELATION
    ]


def write_results(name: str, body: dict[str, Any], tmp_path: Path) -> Path:
    """Results as JSON under QFR_BENCHMARK_DIR (CI uploads it as an artifact), else
    under the test's temporary directory."""
    import os

    root = Path(os.environ.get("QFR_BENCHMARK_DIR") or tmp_path / "benchmarks")
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{name}.json"
    path.write_text(json.dumps(body, indent=2, sort_keys=True, default=str) + "\n")
    return path


def run_body(name: str, run: BenchmarkRun, script: BenchmarkScript, **extra: Any) -> dict[str, Any]:
    draws: dict[str, dict[str, int]] = {}
    for d in script.draws:
        draws.setdefault(d.operator, {}).setdefault(d.family, 0)
        draws[d.operator][d.family] += 1
    return {
        "benchmark": name,
        "script_seed": script.seed,
        "engine_seed": script.seed,
        "summary": run.summary(),
        "generations": [g.__dict__ for g in run.generations],
        "published": run.published,
        "draws": draws,
        "llm_calls": len(script.calls),
        "llm_calls_by_role": dict(sorted(Counter(c["role"] for c in script.calls).items())),
    } | extra
