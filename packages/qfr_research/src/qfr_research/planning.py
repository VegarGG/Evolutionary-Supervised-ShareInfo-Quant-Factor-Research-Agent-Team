"""The generation proposal and the plan validator (PLAN Sections 11.6 and 12).

The evolution engine (engine.py) emits the proposal: publication slots per island from
the Thompson-sampling bandit, candidate slots, the operator mix after the mode bias and
the diversity guardrail, the parents it selected for each operator, ready-made
deterministic variants and a default plan. The deterministic validator enforces the
Section 11.6 rules (slot cap, exploration share, a slot for every active island, the
remaining budget), the "at most 1 slot per island away from the proposal, with a reason"
rule of Section 11.4, and the evolution rules of Section 12: parents come from the
proposal with the right arity for their operator, a crossover pairs parents the engine
paired (their behavioral similarity was checked), a provisional parent has at most 1
child, a syntactic batch takes variants the engine made, and a stagnant island is either
reseeded with at least 2 explore tasks or paused. An invalid plan gets one repair attempt
and then falls back to the proposal's default plan.
"""

import math
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from qfr_research.outputs import GenerationPlan, PlanTask

STRATEGY_MODES = frozenset({"new_strategy", "improve_strategy", "review_and_iterate"})
# Task types that call an LLM; a syntactic batch does not.
LLM_TASKS = frozenset({"explore", "llm_mutation", "crossover", "repair", "compose_strategy"})
# Roles under which the engine offers population members (or archive elites) as parents.
MEMBER_ROLES = frozenset({"llm_mutation", "crossover", "syntactic_mutation"})


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
    engine: dict[str, Any] = field(default_factory=dict)
    publication_slots: dict[str, int] = field(default_factory=dict)
    # version id -> island, fitness, status, expression, flags and the role it was
    # offered for (llm_mutation, crossover, syntactic_mutation, repair or strategy).
    parent_info: dict[str, dict[str, Any]] = field(default_factory=dict)
    selections: list[dict[str, Any]] = field(default_factory=list)
    variants: list[dict[str, Any]] = field(default_factory=list)
    stagnant_islands: list[str] = field(default_factory=list)
    provisional_parents: list[str] = field(default_factory=list)
    provisional_children_max: int = 1
    stagnation_explore_tasks: int = 2

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
            "engine": self.engine,
            "publication_slots": self.publication_slots,
            "parent_info": self.parent_info,
            "selections": self.selections,
            "variants": self.variants,
            "stagnant_islands": self.stagnant_islands,
            "provisional_parents": self.provisional_parents,
            "provisional_children_max": self.provisional_children_max,
            "stagnation_explore_tasks": self.stagnation_explore_tasks,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Proposal":
        """The proposal PROPOSING stored, so PLANNING validates against the same one."""
        return cls(
            islands=list(data["islands"]),
            allocations={k: int(v) for k, v in data["allocations"].items()},
            operator_mix={k: float(v) for k, v in data["operator_mix"].items()},
            parents=list(data["parents"]),
            publication_quota=int(data["publication_quota"]),
            max_slots=int(data["max_slots"]),
            min_explore_share=float(data["min_explore_share"]),
            compose_strategy_max=int(data["compose_strategy_max"]),
            default_plan=GenerationPlan.model_validate(data["default_plan"]),
            engine=dict(data.get("engine") or {}),
            publication_slots={k: int(v) for k, v in (data.get("publication_slots") or {}).items()},
            parent_info=dict(data.get("parent_info") or {}),
            selections=list(data.get("selections") or []),
            variants=list(data.get("variants") or []),
            stagnant_islands=list(data.get("stagnant_islands") or []),
            provisional_parents=list(data.get("provisional_parents") or []),
            provisional_children_max=int(data.get("provisional_children_max", 1)),
            stagnation_explore_tasks=int(data.get("stagnation_explore_tasks", 2)),
        )

    def available_types(self) -> set[str]:
        """Task types this generation can run: explore always; the parent operators only
        when the engine offered parents for them."""
        types = {"explore"}
        if any(i.get("offered_as") in MEMBER_ROLES for i in self.parent_info.values()):
            types.add("llm_mutation")
        if any(s["type"] == "crossover" for s in self.selections):
            types.add("crossover")
        if any(i.get("offered_as") == "repair" for i in self.parent_info.values()):
            types.add("repair")
        if self.variants:
            types.add("syntactic_batch")
        if self.compose_strategy_max > 0:
            types.add("compose_strategy")
        return types

    def crossover_pairs(self) -> set[frozenset[str]]:
        return {
            frozenset(s["parent_version_ids"]) for s in self.selections if s["type"] == "crossover"
        }

    def selection_for(self, task_type: str, parents: list[str]) -> dict[str, Any] | None:
        """The engine's record of how it chose these parents, when it did."""
        wanted = sorted(parents)
        for selection in self.selections:
            if selection["type"] == task_type and sorted(selection["parent_version_ids"]) == wanted:
                return selection
        if task_type == "llm_mutation" and len(parents) == 1:
            for selection in self.selections:
                if parents[0] in selection["parent_version_ids"]:
                    return selection
        return None


def assign_variants(
    tasks: list[PlanTask] | list[Any], proposal: Proposal
) -> dict[int, list[dict[str, Any]]]:
    """Which ready-made variants each syntactic_batch task takes, by task position:
    in task order, the first unused variants of the task's island whose parents are all
    among the task's parents. The workflow and the validator use the same assignment."""
    used: set[str] = set()
    out: dict[int, list[dict[str, Any]]] = {}
    for index, task in enumerate(tasks):
        if task.type != "syntactic_batch":
            continue
        island = getattr(task, "island_id", None) or getattr(task, "island_key", None)
        parents = {str(p) for p in task.parent_version_ids}
        taken: list[dict[str, Any]] = []
        for variant in proposal.variants:
            if len(taken) >= int(task.max_candidates):
                break
            if variant["variant_id"] in used or variant["island"] != island:
                continue
            if set(variant["parent_version_ids"]) <= parents:
                taken.append(variant)
                used.add(variant["variant_id"])
        out[index] = taken
    return out


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
    paused = {p.island_id for p in plan.islands_to_pause}
    active = set(proposal.islands) - paused
    factor_tasks = [t for t in plan.tasks if t.type != "compose_strategy"]
    total_slots = sum(t.max_candidates for t in factor_tasks)
    explore_slots = sum(t.max_candidates for t in factor_tasks if t.type == "explore")
    if total_slots > proposal.max_slots:
        violations.append(f"SLOTS_OVER_CAP: {total_slots} > {proposal.max_slots}")
    share = explore_slots / total_slots if total_slots else 0.0
    if share < proposal.min_explore_share - 1e-9:
        violations.append(f"EXPLORE_SHARE: {share:.2f} < {proposal.min_explore_share:.2f}")
    if not active:
        violations.append("NO_ACTIVE_ISLAND: every island would be paused")
    covered = {t.island_id for t in plan.tasks}
    for island in sorted(active - covered):
        violations.append(f"ISLAND_WITHOUT_SLOT: {island}")
    for island in sorted(paused & covered):
        violations.append(f"PAUSED_ISLAND_WITH_TASKS: {island}")
    available = proposal.available_types()
    pairs = proposal.crossover_pairs()
    children: dict[str, int] = {}
    for task in plan.tasks:
        parents = [str(p) for p in task.parent_version_ids]
        if task.type not in available:
            violations.append(f"TASK_TYPE_UNAVAILABLE: {task.type}")
        if task.island_id not in proposal.islands:
            violations.append(f"ISLAND_UNKNOWN: {task.island_id}")
        unknown = set(parents) - set(proposal.parents)
        if unknown:
            violations.append(f"PARENT_NOT_PROPOSED: {sorted(unknown)}")
            continue
        violations += _arity(task, parents, proposal, pairs)
        if task.type == "llm_mutation" and parents:
            children[parents[0]] = children.get(parents[0], 0) + task.max_candidates
        elif task.type in ("crossover", "repair"):
            for parent in set(parents):
                children[parent] = children.get(parent, 0) + 1
    for index, taken in assign_variants(plan.tasks, proposal).items():
        task = plan.tasks[index]
        if len(taken) < task.max_candidates:
            violations.append(
                f"SYNTACTIC_BATCH_WITHOUT_VARIANTS: task {index} on {task.island_id} asks for "
                f"{task.max_candidates}, the proposal has {len(taken)} left"
            )
        for variant in taken:
            for parent in set(variant["parent_version_ids"]):
                children[parent] = children.get(parent, 0) + 1
    for parent in sorted(set(proposal.provisional_parents) & set(children)):
        if children[parent] > proposal.provisional_children_max:
            violations.append(
                f"PROVISIONAL_PARENT_OVER_LIMIT: {parent} has {children[parent]} children "
                f"> {proposal.provisional_children_max}"
            )
    for island in proposal.stagnant_islands:
        if island in paused:
            continue
        explore_tasks = sum(1 for t in plan.tasks if t.island_id == island and t.type == "explore")
        if explore_tasks < proposal.stagnation_explore_tasks:
            violations.append(
                f"STAGNANT_ISLAND_NOT_HANDLED: {island} needs {proposal.stagnation_explore_tasks} "
                f"explore tasks or a pause, has {explore_tasks} explore tasks"
            )
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
    llm_tasks = sum(1 for t in plan.tasks if t.type in LLM_TASKS)
    estimate = task_cost_estimate * llm_tasks
    if estimate > remaining_cny:
        violations.append(f"BUDGET: plan estimate {estimate} > remaining {remaining_cny}")
    return Verdict(
        not violations,
        violations,
        {
            "total_slots": total_slots,
            "explore_share": round(share, 4),
            "tasks": len(plan.tasks),
            "llm_tasks": llm_tasks,
            "estimate_cny": float(estimate),
            "remaining_cny": float(remaining_cny),
            "active_islands": sorted(active),
            "stagnant_islands": proposal.stagnant_islands,
            "stagnation_choice": stagnation_choices(plan, proposal),
            "available_types": sorted(available),
        },
    )


def stagnation_choices(plan: GenerationPlan, proposal: Proposal) -> dict[str, str]:
    """For each stagnant island: pause, reseed (enough explore tasks) or unhandled."""
    paused: set[str] = {p.island_id for p in plan.islands_to_pause}
    out: dict[str, str] = {}
    for island in proposal.stagnant_islands:
        explore = sum(1 for t in plan.tasks if t.island_id == island and t.type == "explore")
        if island in paused:
            out[island] = "pause"
        elif explore >= proposal.stagnation_explore_tasks:
            out[island] = "reseed"
        else:
            out[island] = "unhandled"
    return out


def _arity(
    task: PlanTask, parents: list[str], proposal: Proposal, pairs: set[frozenset[str]]
) -> list[str]:
    """Each operator's parents (Sections 12.3 and 12.4)."""
    info = proposal.parent_info
    if task.type == "explore":
        return ["PARENTS_NOT_ALLOWED: explore takes no parents"] if parents else []
    if task.type == "compose_strategy":
        return []  # the components come from the job's published factors and seeds
    if task.type == "llm_mutation":
        if len(parents) != 1:
            return [f"PARENT_ARITY: llm_mutation takes 1 parent, got {len(parents)}"]
        if info.get(parents[0], {}).get("offered_as") not in MEMBER_ROLES:
            return [f"PARENT_NOT_ELIGIBLE: {parents[0]} is not a selected population member"]
        return []
    if task.type == "repair":
        if len(parents) != 1:
            return [f"PARENT_ARITY: repair takes 1 parent, got {len(parents)}"]
        if info.get(parents[0], {}).get("offered_as") != "repair":
            return [f"PARENT_NOT_ELIGIBLE: {parents[0]} is not a repair target"]
        if task.max_candidates != 1:
            return ["REPAIR_CANDIDATES: a repair task makes 1 candidate"]
        return []
    if task.type == "crossover":
        if len(set(parents)) != 2 or len(parents) != 2:
            return [f"PARENT_ARITY: crossover takes 2 distinct parents, got {len(parents)}"]
        if frozenset(parents) not in pairs:
            return [f"CROSSOVER_PAIR_NOT_PROPOSED: {sorted(parents)}"]
        if task.max_candidates != 1:
            return ["CROSSOVER_CANDIDATES: a crossover task makes 1 candidate"]
        return []
    if task.type == "syntactic_batch" and not parents:
        return ["PARENT_ARITY: a syntactic batch names its variants' parents"]
    return []


def fit_to_budget(plan: GenerationPlan, remaining: Decimal, per_task: Decimal) -> GenerationPlan:
    """Trim the default plan when the remaining budget cannot pay for its LLM tasks: keep
    one task per island first, then the rest in order. Syntactic batches cost no LLM call
    and are always kept."""
    if per_task <= 0:
        return plan
    affordable = max(0, math.floor(remaining / per_task))
    llm = [t for t in plan.tasks if t.type in LLM_TASKS]
    if affordable >= len(llm):
        return plan
    first: list[PlanTask] = []
    rest: list[PlanTask] = []
    seen: set[str] = set()
    for task in llm:
        (rest if task.island_id in seen else first).append(task)
        seen.add(task.island_id)
    kept_llm = {id(t) for t in (first + rest)[:affordable]}
    kept = [t for t in plan.tasks if t.type not in LLM_TASKS or id(t) in kept_llm]
    if not kept:
        return plan
    islands = {t.island_id for t in kept}
    allocations = {i: sum(t.max_candidates for t in kept if t.island_id == i) for i in islands}
    return plan.model_copy(
        update={
            "tasks": kept,
            "allocations": {k: v for k, v in allocations.items() if v},
            "rationale": plan.rationale + " Trimmed to the remaining budget.",
        }
    )
