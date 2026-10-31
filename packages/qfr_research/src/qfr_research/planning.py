"""The generation proposal and the plan validator (PLAN Sections 11.6 and 12).

Phase 4 has no evolution engine yet (Phase 5), so the proposal is the empty-start rule of
Section 12.1 applied every generation: all candidate slots are explore slots, spread
evenly over the active islands, plus at most the charter's compose_strategy tasks in the
strategy modes. The deterministic validator enforces the four Section 11.6 rules and the
"at most 1 slot per island away from the proposal, with a reason" rule of Section 11.4;
an invalid plan gets one repair attempt and then falls back to the proposal's default.
"""

import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from qfr_research.outputs import GenerationPlan, PlanTask

# Task types Phase 4 can execute. The others arrive with the evolution engine (Phase 5).
PHASE4_TYPES = frozenset({"explore", "compose_strategy"})
STRATEGY_MODES = frozenset({"new_strategy", "improve_strategy", "review_and_iterate"})


@dataclass(frozen=True)
class Proposal:
    islands: list[str]
    allocations: dict[str, int]
    operator_mix: dict[str, float]
    parents: list[str]
    publication_quota: int
    max_slots: int
    min_explore_share: float
    compose_strategy_max: int
    default_plan: GenerationPlan

    def as_json(self) -> dict[str, Any]:
        return {
            "islands": self.islands,
            "allocations": self.allocations,
            "operator_mix": self.operator_mix,
            "parents": self.parents,
            "publication_quota": self.publication_quota,
            "max_slots": self.max_slots,
            "min_explore_share": self.min_explore_share,
            "compose_strategy_max": self.compose_strategy_max,
            "default_plan": self.default_plan.model_dump(mode="json"),
            "engine": "phase4-empty-start",
        }


def propose(
    charter: dict[str, Any], islands: list[str], themes: dict[str, str], strategy_parents: list[str]
) -> Proposal:
    throughput = charter["throughput"]
    quota = int(throughput["publications"])
    max_slots = min(int(throughput["candidate_slots_max"]), 3 * quota)
    min_explore = float(charter["operator_mix"]["explore"])
    mode = str(charter.get("mode", "new_factors"))
    compose_max = int(throughput["compose_strategy_tasks_max"]) if mode in STRATEGY_MODES else 0
    if not strategy_parents:
        compose_max = 0
    compose_slots = compose_max  # one strategy draft per compose task
    explore_slots = max(len(islands), max_slots - compose_slots)
    base, extra = divmod(explore_slots, len(islands))
    allocations = {key: base + (1 if i < extra else 0) for i, key in enumerate(islands)}
    tasks: list[PlanTask] = []
    for key in islands:
        slots = allocations[key]
        while slots > 0:
            take = min(3, slots)
            tasks.append(
                PlanTask(
                    type="explore",
                    island_id=key,  # type: ignore[arg-type]
                    brief=f"Explore a new mechanism for the theme: {themes[key]}.",
                    parent_version_ids=[],
                    hypothesis_id=None,
                    max_candidates=take,
                )
            )
            slots -= take
    for i in range(compose_max):
        tasks.append(
            PlanTask(
                type="compose_strategy",
                island_id=islands[i % len(islands)],  # type: ignore[arg-type]
                brief="Compose a strategy from the published factors listed.",
                parent_version_ids=[],
                hypothesis_id=None,
                max_candidates=1,
            )
        )
    mix = {"explore": 1.0} | ({"compose_strategy": 0.0} if compose_max else {})
    plan = GenerationPlan(
        objectives=["Explore new mechanisms on every active island."],
        allocations=allocations,  # type: ignore[arg-type]
        allocation_reasons={},
        tasks=tasks,
        islands_to_pause=[],
        rationale="Deterministic default plan from the proposal (empty-start rule).",
    )
    return Proposal(
        islands=islands,
        allocations=allocations,
        operator_mix=mix,
        parents=strategy_parents,
        publication_quota=quota,
        max_slots=max_slots,
        min_explore_share=min_explore,
        compose_strategy_max=compose_max,
        default_plan=plan,
    )


@dataclass(frozen=True)
class Verdict:
    valid: bool
    violations: list[str]
    values: dict[str, Any]


def validate_plan(
    plan: GenerationPlan,
    proposal: Proposal,
    remaining_cny: Decimal,
    task_cost_estimate: Decimal,
) -> Verdict:
    violations: list[str] = []
    active = set(proposal.islands) - {p.island_id for p in plan.islands_to_pause}
    factor_tasks = [t for t in plan.tasks if t.type != "compose_strategy"]
    total_slots = sum(t.max_candidates for t in factor_tasks)
    explore_slots = sum(t.max_candidates for t in factor_tasks if t.type == "explore")
    if total_slots > proposal.max_slots:
        violations.append(f"SLOTS_OVER_CAP: {total_slots} > {proposal.max_slots}")
    share = explore_slots / total_slots if total_slots else 0.0
    if share < proposal.min_explore_share:
        violations.append(f"EXPLORE_SHARE: {share:.2f} < {proposal.min_explore_share:.2f}")
    if not active:
        violations.append("NO_ACTIVE_ISLAND: every island would be paused")
    covered = {t.island_id for t in plan.tasks}
    for island in sorted(active - covered):
        violations.append(f"ISLAND_WITHOUT_SLOT: {island}")
    for task in plan.tasks:
        if task.type not in PHASE4_TYPES or task.type not in proposal.operator_mix:
            violations.append(f"TASK_TYPE_UNAVAILABLE: {task.type}")
        if task.island_id not in proposal.islands:
            violations.append(f"ISLAND_UNKNOWN: {task.island_id}")
        unknown = {str(p) for p in task.parent_version_ids} - set(proposal.parents)
        if unknown:
            violations.append(f"PARENT_NOT_PROPOSED: {sorted(unknown)}")
    compose = [t for t in plan.tasks if t.type == "compose_strategy"]
    if len(compose) > proposal.compose_strategy_max:
        violations.append(f"COMPOSE_OVER_CAP: {len(compose)} > {proposal.compose_strategy_max}")
    for island, slots in plan.allocations.items():
        expected = proposal.allocations.get(island)
        if expected is None:
            violations.append(f"ALLOCATION_UNKNOWN_ISLAND: {island}")
        elif abs(slots - expected) > 1:
            violations.append(f"ALLOCATION_MOVED_TOO_FAR: {island} {expected} -> {slots}")
        elif slots != expected and island not in plan.allocation_reasons:
            violations.append(f"ALLOCATION_WITHOUT_REASON: {island}")
    estimate = task_cost_estimate * len(plan.tasks)
    if estimate > remaining_cny:
        violations.append(f"BUDGET: plan estimate {estimate} > remaining {remaining_cny}")
    return Verdict(
        not violations,
        violations,
        {
            "total_slots": total_slots,
            "explore_share": round(share, 4),
            "tasks": len(plan.tasks),
            "estimate_cny": float(estimate),
            "remaining_cny": float(remaining_cny),
            "active_islands": sorted(active),
        },
    )


def fit_to_budget(plan: GenerationPlan, remaining: Decimal, per_task: Decimal) -> GenerationPlan:
    """Trim the default plan when the remaining budget cannot pay for all of it: keep one
    task per island first, then the rest in order."""
    if per_task <= 0:
        return plan
    affordable = max(0, math.floor(remaining / per_task))
    if affordable >= len(plan.tasks):
        return plan
    first: list[PlanTask] = []
    rest: list[PlanTask] = []
    seen: set[str] = set()
    for task in plan.tasks:
        (rest if task.island_id in seen else first).append(task)
        seen.add(task.island_id)
    kept = (first + rest)[:affordable]
    if not kept:
        return plan
    allocations = {i: sum(t.max_candidates for t in kept if t.island_id == i) for i in seen}
    return plan.model_copy(
        update={
            "tasks": kept,
            "allocations": {k: v for k, v in allocations.items() if v},
            "rationale": plan.rationale + " Trimmed to the remaining budget.",
        }
    )
