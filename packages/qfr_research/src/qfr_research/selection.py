"""SELECTING: the publication pre-screen, deduplication and the per-generation quota
(PLAN Sections 11.6 and 12.5).

The pre-screen thresholds come from the charter (Section 12.5). Phase 4 ranks the
survivors by their W0 sign-adjusted RankIC IR and then by originality, and fills the
publication quota round-robin across islands so each island with a survivor gets a
place first. Phase 5 replaces the ranking with provisional fitness (Section 12.2).
Every decision is a trace step with the values it used.
"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Screened:
    candidate_id: Any
    island: str
    passed: bool
    checks: dict[str, dict[str, Any]]
    score: float
    originality: float


def prescreen(candidate: Any, thresholds: dict[str, Any]) -> Screened:
    """One candidate's pre-screen: each check with its value and threshold."""
    workbench = candidate.workbench or {}
    metrics = workbench.get("metrics") or {}
    similarity = candidate.similarity or {}
    checks: dict[str, dict[str, Any]] = {}

    def add(name: str, value: float | None, threshold: float, above: bool = True) -> None:
        ok = value is not None and (value >= threshold if above else value <= threshold)
        checks[name] = {"value": value, "threshold": threshold, "passed": bool(ok)}

    originality = float(similarity.get("originality", 1.0))
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
        score = sign * ir if ir is not None else float("-inf")
    else:
        sharpe = workbench.get("reference_sharpe")
        add("strategy_net_sharpe", sharpe, float(thresholds["strategy_net_sharpe_min"]))
        components = len((candidate.payload or {}).get("components", []))
        add("components", float(components), float(thresholds["strategy_components_max"]), False)
        score = float(sharpe) if sharpe is not None else float("-inf")
    passed = all(c["passed"] for c in checks.values())
    return Screened(candidate.candidate_id, candidate.island_key, passed, checks, score, originality)


def select(survivors: list[Screened], quota: int) -> tuple[list[Screened], dict[Any, int]]:
    """Up to quota survivors, round-robin over islands by score; returns ranks too."""
    ranked = sorted(survivors, key=lambda s: (-s.score, -s.originality, str(s.candidate_id)))
    ranks = {s.candidate_id: i + 1 for i, s in enumerate(ranked)}
    by_island: dict[str, list[Screened]] = {}
    for item in ranked:
        by_island.setdefault(item.island, []).append(item)
    chosen: list[Screened] = []
    while len(chosen) < quota and any(by_island.values()):
        for island in sorted(by_island):
            if by_island[island] and len(chosen) < quota:
                chosen.append(by_island[island].pop(0))
    return chosen, ranks
