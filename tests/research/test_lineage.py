"""TRC-03 (INV-13, Phase 5 acceptance): every operator application has its parents and
an AST diff, and the iteration history of a delivered version reconstructs every hop of
a five-generation synthetic lineage including one crossover.

The lineage is built on the planted world through the whole offline stack (MCP front
door, research, evaluator). Only the engine's choice of parents is scripted, so that the
lineage is known in advance: generation 1 explores A on I1 and P on I2; generation 2
mutates A into B; generation 3 crosses B with P into C; generations 4 and 5 mutate C
into D and D into E; the task that makes D also drafts a weak sibling, which the
pre-screen discards. Everything else is the production path: the plan validator, the
operators and their trace steps, the packager's lineage edges and family, the job
monitor's deliverable, qfr.trace.export and the history it carries. BM-PLANTED checks
the same properties on the lineages the unscripted engine produces.
"""

import json
import re
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.function import AgentInfo
from qfr_core.dsl import validate
from qfr_research.engine import EvolutionEngine, GenerationRef
from qfr_research.outputs import GenerationPlan, PlanTask
from qfr_research.planning import Proposal
from sqlalchemy import text

from tests.benchmarks.harness import (
    PARENT_LINE,
    BenchmarkModels,
    BenchmarkScript,
    Draw,
    lineage_report,
    operator_steps,
    run_benchmark,
)
from tests.benchmarks.pool import canonical, limits
from tests.research.rig import research_stack
from tests.research.scripted import UUID as UUID_RE
from tests.research.scripted import answer

pytestmark = pytest.mark.postgres

# Test data on the planted world (each passes the W0 pre-screen against the others);
# none is a product default.
A = "-Pct($close,5)"
P = "Clip(Sign($ret)*($volume/Mean($volume,20)-1),-3,3)"
B = "-Pct($close,10)"
C = "Rank(-Pct($close,10))+Rank(Sign($ret)*$volume/Mean($volume,20))"
D = "Rank(-Sum($ret,3))+Rank(Sign($ret)*$volume/Mean($volume,10))"
E = "Rank(-Sum($ret,5))*Rank($volume/Mean($volume,10))"
WEAK = "Std($amount,120)"  # fails the pre-screen: later I2 explores add no member
SIBLING = "Rank(Std($amount,120))"  # D's discarded sibling: fails the pre-screen too
SIBLING_SEQ = 4
SCHEDULE = {
    2: ("llm_mutation", A),
    3: ("crossover", B),
    4: ("llm_mutation", C),
    5: ("llm_mutation", D),
}
LIMITS = limits()
CHILD = {canonical(A): B, canonical(B): C, canonical(C): D, canonical(D): E}


def canonical_hash(expression: str) -> str:
    analysis = validate(expression, LIMITS).analysis
    assert analysis is not None, expression
    return analysis.canonical_hash


class LineageEngine(EvolutionEngine):
    """The engine with its parent choice scripted by SCHEDULE: one operator task on I1
    with the newest chain member as parent (and P as the crossover partner), one explore
    task on I2. Refresh, slots and the rest of the proposal are the engine's own."""

    def propose(
        self,
        gen: GenerationRef,
        refresh: dict[str, Any],
        strategy_parents: list[str],
        remaining: Decimal,
        per_task: Decimal,
    ) -> Proposal:
        real = super().propose(gen, refresh, strategy_parents, remaining, per_task)
        if gen.seq not in SCHEDULE:
            return real
        operator, head_expression = SCHEDULE[gen.seq]
        head = self._version(gen.program_id, head_expression)
        parents = [head] + ([self._version(gen.program_id, P)] if operator == "crossover" else [])
        tasks = [
            PlanTask(
                type=operator,  # type: ignore[arg-type]
                island_id="I1",
                brief="Scripted lineage step.",
                parent_version_ids=[UUID(p) for p in parents],
                hypothesis_id=None,
                max_candidates=2 if gen.seq == SIBLING_SEQ else 1,
            ),
            PlanTask(
                type="explore",
                island_id="I2",
                brief="Explore.",
                parent_version_ids=[],
                hypothesis_id=None,
                max_candidates=1,
            ),
        ]
        plan = GenerationPlan(
            objectives=["Extend the scripted lineage."],
            allocations={"I1": 1, "I2": 1},
            allocation_reasons={},
            tasks=tasks,
            islands_to_pause=[],
            rationale="Scripted parents for TRC-03.",
        )
        record = {"rule": "scripted_lineage", "generation": gen.seq}
        return Proposal(
            islands=real.islands,
            allocations={"I1": 1, "I2": 1},
            operator_mix=real.operator_mix,
            parents=parents,
            publication_quota=real.publication_quota,
            max_slots=real.max_slots,
            min_explore_share=real.min_explore_share,
            compose_strategy_max=0,
            default_plan=plan,
            engine=real.engine | {"scripted_lineage": SCHEDULE[gen.seq][0]},
            publication_slots=real.publication_slots,
            parent_info={
                p: {"island": "I1", "status": "provisional", "offered_as": operator}
                for p in parents
            },
            selections=[
                {
                    "type": operator,
                    "island": "I1",
                    "parent_version_ids": parents,
                    "selection": [record for _ in parents],
                    "parent_fitness": [None for _ in parents],
                }
            ],
            variants=[],
            stagnant_islands=[],
            provisional_parents=[],
            provisional_children_max=real.provisional_children_max,
            stagnation_explore_tasks=real.stagnation_explore_tasks,
        )

    def _version(self, program_id: UUID, expression: str) -> str:
        with self.env.db.read() as conn:
            row = conn.execute(
                text(
                    "SELECT v.version_id FROM candidate_versions v JOIN candidates c ON "
                    "c.candidate_id = v.candidate_id WHERE c.program_id = :p AND "
                    "c.canonical_hash = :h"
                ),
                {"p": program_id, "h": canonical_hash(expression)},
            ).one()
        return str(row.version_id)


class LineageModels(BenchmarkModels):
    """Drafts the scripted lineage: A and P first, then each parent's scripted child."""

    def _engineer(self, text: str, messages: list[ModelMessage], info: AgentInfo) -> Any:
        island = re.search(r"Island: (I\d)", text)
        operator = re.search(r"the operator \((\w+)\)", text)
        op = operator.group(1) if operator else "explore"
        hypothesis = re.search(rf"hypothesis_id ({UUID_RE})", text)
        parents = [(v, json.loads(b)) for v, b in PARENT_LINE.findall(text)]
        if op == "explore":
            first = island is not None and island.group(1) == "I1"
            drafted = {d.expression for d in self.script.draws}
            expression = A if first else (P if canonical(P) not in drafted else WEAK)
        else:
            expression = CHILD[canonical(str(parents[0][1]["expression"]))]
        expressions = [expression] + ([SIBLING] if expression == D else [])
        for e in expressions:
            self.script.draws.append(Draw(op, "lineage", canonical(e), [v for v, _ in parents]))
        return answer(
            info,
            {
                "drafts": [
                    {
                        "hypothesis_id": hypothesis.group(1) if hypothesis else None,
                        "expression": e,
                        "description": "Each part of the expression maps to the mechanism.",
                        "expected_sign": 1,
                        "horizon_days": 5,
                        "parameter_rationale": "The windows match the horizon.",
                        "operator": op,
                        "parent_version_ids": [v for v, _ in parents],
                        "change_summary": None if op == "explore" else f"Scripted {op} step.",
                    }
                    for e in expressions
                ]
            },
        )


def test_trc_03_history_of_a_delivered_version_reconstructs_a_five_generation_dag(
    tmp_path, monkeypatch, small_zones
):
    monkeypatch.setenv("QFR_EXPORTS_DIR", str(tmp_path / "exports"))
    monkeypatch.setattr("qfr_research.workflow.EvolutionEngine", LineageEngine)
    script = BenchmarkScript(expressions=[], engineer_uses_tool=False)
    with research_stack(tmp_path, monkeypatch, small_zones, script, LineageModels) as full:
        run = run_benchmark(full, 5, ["I1", "I2"])
        by_expression = {canonical(p["expression"]): p for p in run.published}
        chain = [by_expression.get(canonical(e)) for e in (A, P, B, C, D, E)]
        assert all(chain), sorted(by_expression)
        a, p, b, c, d, e = chain
        assert [x["generation_seq"] for x in (a, b, c, d, e)] == [1, 2, 3, 4, 5]
        assert [x["operator"] for x in (a, b, c, d, e)] == [
            "explore",
            "llm_mutation",
            "crossover",
            "llm_mutation",
            "llm_mutation",
        ]
        assert sorted(c["parent_version_ids"]) == sorted([b["version_id"], p["version_id"]])

        # Every operator application names its parents and records an AST diff from each.
        applications = operator_steps(full)
        assert applications["missing"] == [], applications
        # (D's sibling is an application too.)
        assert applications["counts"] == {"MUTATION_APPLIED": 4, "CROSSOVER_APPLIED": 1}

        # Every published version's exported history reconstructs every hop of its DAG.
        lineage = lineage_report(full, run)
        assert lineage["mismatches"] == [], lineage["mismatches"]
        assert lineage["spans"][e["version_id"]] == {
            "generations": 5,
            "hops": 6,
            "crossover": True,
            "operators": ["crossover", "explore", "llm_mutation"],
        }

        # E is delivered, and the deliverable's history is the same DAG: it reaches back
        # to the explore hypotheses of A and P, parents come before children, and the
        # crossover hop is from B and P.
        assert run.deliverable is not None
        items = {i["version_id"]: i for i in run.deliverable["deliverable"]["items"]}
        history = items[e["version_id"]]["iteration_history"]
        hypotheses = {
            str(r.version_id): str(r.hypothesis_id)
            for r in full.research.db.rows(
                "SELECT v.version_id, c.hypothesis_id FROM candidate_versions v JOIN "
                "candidates c USING (candidate_id) WHERE c.operator = 'explore'"
            )
        }
        assert set(history["roots"]) == {hypotheses[a["version_id"]], hypotheses[p["version_id"]]}
        hops = {h["to_version_id"]: h for h in history["hops"]}
        assert list(hops)[-1] == e["version_id"]
        assert set(hops) == {x["version_id"] for x in chain}
        cross = hops[c["version_id"]]
        assert cross["operator"] == "crossover" and len(cross["ast_diff"]) > 0
        assert sorted(cross["from_version_ids"]) == sorted([b["version_id"], p["version_id"]])
        assert len(cross["expression_before"]) == 2
        for x, parent in ((b, a), (d, c), (e, d)):
            hop = hops[x["version_id"]]
            assert hop["from_version_ids"] == [parent["version_id"]]
            assert hop["expression_before"] == [parent["expression"]]
            assert hop["expression_after"] == x["expression"] and hop["ast_diff"]
        assert [h["generation_seq"] for h in history["hops"]] == sorted(
            h["generation_seq"] for h in history["hops"]
        )
        # The history lists D's discarded sibling with the pre-screen checks it failed.
        (sibling,) = history["discarded"]
        assert sibling["sibling_of"] == d["version_id"]
        assert (sibling["generation_seq"], sibling["operator"]) == (SIBLING_SEQ, "llm_mutation")
        assert canonical(sibling["expression"]) == canonical(SIBLING)
        assert sibling["state"] == "not_selected" and sibling["prescreen_failed"]
        assert sibling["reason"].startswith("PRESCREEN_FAILED:")
