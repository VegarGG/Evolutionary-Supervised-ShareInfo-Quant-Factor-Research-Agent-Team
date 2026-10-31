"""Deterministic charter derivation (PLAN Section 11.1). No LLM is involved: the same
brief and the same configuration always give the same charter."""

import re
from typing import Any

from qfr_core.contracts import ResearchBrief
from qfr_core.dsl import DslLimits
from qfr_core.dsl.catalog import FIELD_COLUMNS, OPERATORS

from qfr_research.settings import ISLANDS, ServiceConfig

IMPROVE_MODES = frozenset({"improve_factors", "improve_strategy", "review_and_iterate"})


class BriefRejected(ValueError):
    def __init__(self, code: str, message: str, details: list[Any] | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code, self.message, self.details = code, message, details or []


def check_constraints(brief: ResearchBrief, limits: DslLimits) -> None:
    """Brief constraints may only tighten the evaluator's (Section 13.3)."""
    c = brief.constraints
    problems = []
    if c.max_nodes > limits.max_nodes:
        problems.append(f"max_nodes {c.max_nodes} > evaluator {limits.max_nodes}")
    if c.max_lookback_days > limits.max_lookback_days:
        problems.append(
            f"max_lookback_days {c.max_lookback_days} > evaluator {limits.max_lookback_days}"
        )
    unknown_fields = sorted(set(c.fields_allowed) - set(FIELD_COLUMNS))
    if unknown_fields:
        problems.append(f"unknown fields {unknown_fields}")
    unknown_ops = sorted(set(c.operators_allowed) - set(OPERATORS))
    if unknown_ops:
        problems.append(f"unknown operators {unknown_ops}")
    if problems:
        raise BriefRejected("CONSTRAINTS_INVALID", "; ".join(problems), list(problems))


def select_islands(brief: ResearchBrief, service: ServiceConfig) -> list[str]:
    if brief.islands != "auto":
        return sorted(set(brief.islands))
    words = " ".join(
        [brief.title, brief.objective, brief.seeds.notes]
        + [f"{e.name} {e.rationale}" for e in brief.seeds.expressions]
    ).lower()
    chosen: set[str] = set()
    for keyword, islands in service.island_keywords.items():
        if re.search(rf"\b{re.escape(keyword)}", words):
            chosen.update(islands)
    return sorted(chosen) if chosen else list(ISLANDS)


def derive_charter(
    brief: ResearchBrief,
    defaults: dict[str, Any],
    service: ServiceConfig,
    islands: list[str],
    seed_version_ids: list[str],
) -> dict[str, Any]:
    charter = {k: v for k, v in defaults.items() if k not in ("charter_id", "version", "job")}
    charter["budget"] = dict(defaults["budget"]) | {"job": brief.budget.max_cost}
    charter["operator_mix"] = (
        defaults["improve_mix"] if brief.mode in IMPROVE_MODES else defaults["operator_mix"]
    )
    charter |= {
        "charter_defaults": f"{defaults['charter_id']}/{defaults['version']}",
        "title": brief.title,
        "objective": brief.objective,
        "mode": brief.mode,
        "steering": [],
        "seeds": {
            "pool_entry_ids": [str(i) for i in brief.seeds.pool_entry_ids],
            "version_ids": [str(i) for i in brief.seeds.version_ids],
            "expressions": [e.name for e in brief.seeds.expressions],
            "published_version_ids": seed_version_ids,
        },
        "seed_notes": brief.seeds.notes,
        "islands": islands,
        "island_themes": {k: service.islands[k] for k in islands},  # type: ignore[index]
        "constraints": brief.constraints.model_dump(mode="json"),
        "strategy_spec": None
        if brief.strategy_spec is None
        else brief.strategy_spec.model_dump(mode="json"),
        "deliverable": brief.deliverable.model_dump(mode="json"),
        "stop": brief.budget.model_dump(mode="json"),
        "priority": brief.priority,
    }
    return charter
