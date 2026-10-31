"""SELECTING: the publication pre-screen, deduplication and the per-generation quota
(PLAN Sections 11.6, 12.2 and 12.5, task P5.5).

The pre-screen thresholds come from the charter (Section 12.5): W0 coverage, the
sign-adjusted W0 RankIC mean and IR, the maximum behavioral similarity to the
population and the pools, AST originality, and complexity within the brief's caps;
strategies need a W0 composite net Sharpe and at most 8 components. Survivors are
deduplicated canonically against the program's publications and the population, and
behaviorally against each other. Factors are ranked by provisional fitness (the
Section 12.2 formula on W0 metrics times 0.5), ties broken by originality, then lower
complexity, then id; each island first gets up to its Thompson-sampled publication
slots in rank order, and what is left of the quota goes to the best remaining
candidates. Strategy survivors, at most the charter's compose_strategy tasks, are
selected first. Every decision is a trace step with the values it used.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from qfr_research.fitness import rank_key, score, w0_input


@dataclass(frozen=True)
class Screened:
    candidate_id: Any
    island: str
    passed: bool
    checks: dict[str, dict[str, Any]]
    score: float
    originality: float
    kind: str = "factor"
    nodes: int = 0
    expression: str | None = None
    fitness: float | None = None
    fitness_detail: dict[str, Any] = field(default_factory=dict)

    def key(self) -> tuple[Any, ...]:
        return rank_key(self.fitness, self.originality, self.nodes, str(self.candidate_id))


def prescreen(
    candidate: Any, thresholds: dict[str, Any], constraints: dict[str, Any] | None = None
) -> Screened:
    """One candidate's pre-screen: each check with its value and threshold."""
    workbench = candidate.workbench or {}
    metrics = workbench.get("metrics") or {}
    similarity = candidate.similarity or {}
    analysis = candidate.analysis or {}
    constraints = constraints or {}
    checks: dict[str, dict[str, Any]] = {}

    def add(name: str, value: float | None, threshold: float, above: bool = True) -> None:
        ok = value is not None and (value >= threshold if above else value <= threshold)
        checks[name] = {"value": value, "threshold": threshold, "passed": bool(ok)}

    originality = float(similarity.get("originality", 1.0))
    nodes = int(analysis.get("nodes", 0))
    if candidate.kind == "factor":
        sign = int((candidate.payload or {}).get("expected_sign", 1))
        rankic, ir = metrics.get("rankic_mean"), metrics.get("rankic_ir")
        add("coverage", metrics.get("coverage"), float(thresholds["coverage_min"]))
        add("rankic", None if rankic is None else sign * rankic, float(thresholds["rankic_min"]))
        add("rankic_ir", None if ir is None else sign * ir, float(thresholds["ir_min"]))
        behavioral = similarity.get("max_behavioral_similarity")
        if behavioral is None:  # nothing to compare with: the check is vacuous
            checks["similarity"] = {
                "value": None,
                "threshold": float(thresholds["similarity_max"]),
                "passed": True,
                "vacuous": True,
            }
        else:
            add("similarity", float(behavioral), float(thresholds["similarity_max"]), above=False)
        add("originality", originality, float(thresholds["originality_min"]))
        if constraints.get("max_nodes"):
            add("complexity", float(nodes), float(constraints["max_nodes"]), above=False)
        if constraints.get("max_lookback_days"):
            lookback = analysis.get("max_lookback_days")
            add(
                "lookback",
                None if lookback is None else float(lookback),
                float(constraints["max_lookback_days"]),
                above=False,
            )
        value = sign * ir if ir is not None else float("-inf")
    else:
        sharpe = workbench.get("reference_sharpe")
        add("strategy_net_sharpe", sharpe, float(thresholds["strategy_net_sharpe_min"]))
        components = len((candidate.payload or {}).get("components", []))
        add("components", float(components), float(thresholds["strategy_components_max"]), False)
        value = float(sharpe) if sharpe is not None else float("-inf")
    passed = all(c["passed"] for c in checks.values())
    return Screened(
        candidate.candidate_id,
        candidate.island_key,
        passed,
        checks,
        value,
        originality,
        candidate.kind,
        nodes,
        candidate.expression,
    )


def provisional_fitness(
    survivors: list[Screened], rows: dict[Any, Any], settings: dict[str, Any]
) -> list[Screened]:
    """Section 12.2 on W0 metrics times the provisional factor, with percentiles among
    this generation's factor survivors (per island once it has 5 of them)."""
    inputs = []
    for s in survivors:
        if s.kind != "factor":
            continue
        row = rows[s.candidate_id]
        metrics = (row.workbench or {}).get("metrics") or {}
        sign = int((row.payload or {}).get("expected_sign", 1))
        pool = (row.similarity or {}).get("max_pool_behavioral_similarity")
        inputs.append(w0_input(str(s.candidate_id), s.island, sign, s.nodes, metrics, pool))
    scored = score(inputs, settings, provisional=True)
    out = []
    for s in survivors:
        result = scored.get(str(s.candidate_id))
        if result is None:
            out.append(s)
            continue
        out.append(
            Screened(
                s.candidate_id,
                s.island,
                s.passed,
                s.checks,
                s.score,
                s.originality,
                s.kind,
                s.nodes,
                s.expression,
                result.value,
                result.detail,
            )
        )
    return out


def behavioral_dedup(
    ranked: list[Screened],
    similarity: Callable[[str, str], float | None],
    limit: float,
) -> tuple[list[Screened], dict[Any, dict[str, Any]]]:
    """Keep the better-ranked of two factor survivors behaviorally more similar than the
    limit; returns the kept list and, for each dropped one, what it duplicated."""
    kept: list[Screened] = []
    dropped: dict[Any, dict[str, Any]] = {}
    for item in ranked:
        twin = None
        if item.kind == "factor" and item.expression:
            for other in kept:
                if other.kind != "factor" or not other.expression:
                    continue
                value = similarity(item.expression, other.expression)
                if value is not None and value > limit:
                    twin = {"candidate_id": str(other.candidate_id), "similarity": round(value, 6)}
                    break
        if twin is None:
            kept.append(item)
        else:
            dropped[item.candidate_id] = twin | {"limit": limit}
    return kept, dropped


def select(
    survivors: list[Screened],
    quota: int,
    island_slots: dict[str, int] | None = None,
) -> tuple[list[Screened], dict[Any, int]]:
    """Up to quota survivors: strategies first, then each island's best factors up to its
    publication slots, then the best remaining factors. Returns the ranks too."""
    ranked = sorted(survivors, key=Screened.key)
    ranks = {s.candidate_id: i + 1 for i, s in enumerate(ranked)}
    chosen: list[Screened] = [s for s in ranked if s.kind != "factor"][:quota]
    factors = [s for s in ranked if s.kind == "factor"]
    if island_slots is None:
        # Without slots each island with a survivor gets a place first (round-robin).
        by_island: dict[str, list[Screened]] = {}
        for item in factors:
            by_island.setdefault(item.island, []).append(item)
        while len(chosen) < quota and any(by_island.values()):
            for island in sorted(by_island):
                if by_island[island] and len(chosen) < quota:
                    chosen.append(by_island[island].pop(0))
        return chosen, ranks
    taken: dict[str, int] = {}
    for item in factors:
        if len(chosen) >= quota:
            break
        if taken.get(item.island, 0) < int(island_slots.get(item.island, 0)):
            chosen.append(item)
            taken[item.island] = taken.get(item.island, 0) + 1
    for item in factors:
        if len(chosen) >= quota:
            break
        if item not in chosen:
            chosen.append(item)
    return chosen, ranks
