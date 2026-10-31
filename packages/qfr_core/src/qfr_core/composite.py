"""The v1 strategy composite and its canonical hash (PLAN Section 7.8).

zscore_weighted_sum: per day, winsorize and z-score each component over the eligible
names with a value, multiply by its sign and normalized weight, and sum. A component
without a value for a name contributes 0 (its cross-sectional mean) to that name; the
composite is missing only where every component is missing.
"""

import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, JsonValue

from qfr_core.config import canonical_json
from qfr_core.contracts import StrategyImplementation, StrategyRulesImplementation
from qfr_core.metrics.factor import MetricSettings, preprocess, rank_ic_series
from qfr_core.metrics.matrix import Array, Market


@dataclass(frozen=True)
class CompositePart:
    name: str
    sign: Literal[1, -1]
    weight: float
    values: Array  # (T, N) factor matrix.


def normalized_weights(weights: Sequence[float]) -> list[float]:
    if not weights or any(not w > 0 for w in weights):
        raise ValueError("composite weights must be positive")
    total = float(sum(weights))
    return [float(w) / total for w in weights]


def composite(parts: Sequence[CompositePart], market: Market, settings: MetricSettings) -> Array:
    weights = normalized_weights([p.weight for p in parts])
    total = np.zeros(market.shape)
    seen = np.zeros(market.shape, dtype=bool)
    for part, weight in zip(parts, weights, strict=True):
        sample = market.eligible & np.isfinite(part.values)
        z = preprocess(part.values, sample, settings)
        valid = np.isfinite(z)
        total += np.where(valid, part.sign * weight * z, 0.0)
        seen |= valid
    return np.where(seen, total, np.nan)


class ContributionRow(BaseModel):
    """The composite's RankIC with one component removed, and the change it causes."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    component: str
    rankic_without: float | None
    rankic_change: float | None


def contribution_table(
    parts: Sequence[CompositePart],
    market: Market,
    start: date,
    end: date,
    settings: MetricSettings,
    transform: Callable[[Array], Array] | None = None,
) -> tuple[float | None, list[ContributionRow]]:
    """Full-composite RankIC_mean and the leave-one-out table (PLAN 8.6). transform is
    applied to every composite first (a qfr-strategy/2 industry neutralization)."""

    def rankic(selection: Sequence[CompositePart]) -> float | None:
        combined = composite(selection, market, settings)
        if transform is not None:
            combined = transform(combined)
        series = rank_ic_series(combined, market, start, end, settings)
        finite = series[np.isfinite(series)]
        return float(finite.mean()) if finite.size else None

    full = rankic(parts)
    rows = []
    for index, part in enumerate(parts):
        rest = [p for i, p in enumerate(parts) if i != index]
        without = rankic(rest) if rest else None
        change = None if full is None or without is None else full - without
        rows.append(
            ContributionRow(component=part.name, rankic_without=without, rankic_change=change)
        )
    return full, rows


StrategyCode = StrategyImplementation | StrategyRulesImplementation


def strategy_canonical_hash(implementation: StrategyCode) -> str:
    """SHA-256 over sorted (version id, sign, normalized weight rounded to 0.01) and the
    portfolio parameters (PLAN 7.8); a qfr-strategy/2 hash also covers neutralize."""
    weights = normalized_weights([c.weight for c in implementation.components])
    components = sorted(
        (str(c.version_id), int(c.sign), round(w, 2))
        for c, w in zip(implementation.components, weights, strict=True)
    )
    payload: dict[str, JsonValue] = {
        "language": implementation.language,
        "combination": implementation.combination,
        "components": [{"version_id": v, "sign": s, "weight": w} for v, s, w in components],
        "portfolio": implementation.portfolio.model_dump(mode="json"),
    }
    if isinstance(implementation, StrategyRulesImplementation):
        payload["neutralize"] = implementation.neutralize
    return hashlib.sha256(canonical_json(payload).encode()).hexdigest()


def strategy_diff(parent: StrategyCode, child: StrategyCode) -> list[dict[str, JsonValue]]:
    """Deterministic edit script between two strategies, the strategy analogue of the
    AST diff stored on lineage edges: components removed, added or reweighted (signs
    and normalized weights rounded to 0.01, as in the canonical hash) and portfolio
    parameter changes. Sorted by version id, then by field."""

    def components(impl: StrategyCode) -> dict[str, dict[str, JsonValue]]:
        weights = normalized_weights([c.weight for c in impl.components])
        return {
            str(c.version_id): {"sign": int(c.sign), "weight": round(w, 2)}
            for c, w in zip(impl.components, weights, strict=True)
        }

    before, after = components(parent), components(child)
    edits: list[dict[str, JsonValue]] = []
    for version_id in sorted(set(before) | set(after)):
        old, new = before.get(version_id), after.get(version_id)
        if old is None:
            edits.append({"op": "component_added", "version_id": version_id, "to": new})
        elif new is None:
            edits.append({"op": "component_removed", "version_id": version_id, "from": old})
        elif old != new:
            edits.append(
                {"op": "component_changed", "version_id": version_id, "from": old, "to": new}
            )
    old_portfolio = parent.portfolio.model_dump(mode="json")
    new_portfolio = child.portfolio.model_dump(mode="json")
    for key in sorted(set(old_portfolio) | set(new_portfolio)):
        if old_portfolio.get(key) != new_portfolio.get(key):
            edits.append(
                {
                    "op": "portfolio_changed",
                    "field": key,
                    "from": old_portfolio.get(key),
                    "to": new_portfolio.get(key),
                }
            )
    if parent.combination != child.combination:
        edits.append(
            {"op": "combination_changed", "from": parent.combination, "to": child.combination}
        )
    if parent.language != child.language:
        edits.append({"op": "language_changed", "from": parent.language, "to": child.language})
    before_n = getattr(parent, "neutralize", "none")
    after_n = getattr(child, "neutralize", "none")
    if before_n != after_n:
        edits.append({"op": "neutralize_changed", "from": before_n, "to": after_n})
    return edits
