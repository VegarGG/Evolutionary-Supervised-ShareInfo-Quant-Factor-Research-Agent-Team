"""Fitness, MAP-Elites descriptors and the ranking order (PLAN Sections 12.1 and 12.2).

Official fitness uses released W1 values, which are already coarsened:

    F = 0.40 pct(s RankIC_IR) + 0.25 pct(LS net Sharpe) + 0.15 pct(1 - max library corr)
      + 0.10 pct(monotonicity) + 0.10 pct(1 - top turnover) - 0.01 max(0, nodes - 15)

times 0 when screening failed or SIGN_MISMATCH was flagged, 1.1 after a W2 PASS and
0.5 after a W2 FAIL. pct is the mid-rank percentile among the official members of the
same island, or among all official members when the island has fewer than 5. When the
library is empty the library term is 0.5 for every member. Provisional fitness is the
same formula on W0 workbench metrics times 0.5; it ranks candidates for publication and
never enters the archive. Every weight and threshold comes from the charter. Ties
(coarsening produces many) are broken by originality, then by lower complexity, then by
id, so every ordering is deterministic.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from qfr_core.dsl import canonicalize, parse
from qfr_core.dsl.ast import Call, walk

TERMS = ("rankic_ir", "ls_net_sharpe", "library", "monotonicity", "turnover")


@dataclass(frozen=True)
class FitnessInput:
    """One member's values for the formula. rankic_ir is sign-adjusted; library_corr is
    None when there is no library value (an empty library or nothing to compare with)."""

    key: str
    island: str
    rankic_ir: float | None
    ls_net_sharpe: float | None
    library_corr: float | None
    monotonicity: float | None
    top_turnover: float | None
    nodes: int
    multiplier: float = 1.0
    multiplier_reasons: tuple[str, ...] = ()

    def value(self, term: str) -> float | None:
        if term == "rankic_ir":
            return self.rankic_ir
        if term == "ls_net_sharpe":
            return self.ls_net_sharpe
        if term == "library":
            return None if self.library_corr is None else 1.0 - self.library_corr
        if term == "monotonicity":
            return self.monotonicity
        return None if self.top_turnover is None else 1.0 - self.top_turnover


@dataclass(frozen=True)
class Fitness:
    value: float
    detail: dict[str, Any] = field(default_factory=dict)


def percentile(value: float, values: Sequence[float]) -> float:
    """Mid-rank percentile in (0, 1): ties share the middle of their ranks."""
    if not values:
        return 0.5
    below = sum(1 for v in values if v < value)
    equal = sum(1 for v in values if v == value)
    return (below + 0.5 * equal) / len(values)


def score(
    members: Sequence[FitnessInput], settings: dict[str, Any], *, provisional: bool = False
) -> dict[str, Fitness]:
    """Fitness of every member, with the percentiles, basis and multiplier it used."""
    weights = settings["fitness"]["weights"]
    penalty = float(settings["fitness"]["complexity_penalty"])
    free = int(settings["fitness"]["complexity_free_nodes"])
    neutral = float(settings["fitness"]["empty_library_pct"])
    factor = float(settings["fitness"]["provisional_factor"]) if provisional else 1.0
    minimum = int(settings["population"]["island_percentile_min"])
    by_island: dict[str, list[FitnessInput]] = {}
    for member in members:
        by_island.setdefault(member.island, []).append(member)
    out: dict[str, Fitness] = {}
    for member in members:
        local = by_island[member.island]
        basis, basis_name = (local, "island") if len(local) >= minimum else (members, "global")
        pcts: dict[str, float] = {}
        for term in TERMS:
            mine = member.value(term)
            if term == "library" and mine is None:
                pcts[term] = neutral
                continue
            if mine is None:
                pcts[term] = 0.0
                continue
            values = [v for m in basis if (v := m.value(term)) is not None]
            pcts[term] = percentile(mine, values)
        weighted = sum(float(weights[t]) * pcts[t] for t in TERMS)
        complexity = penalty * max(0, member.nodes - free)
        value = (weighted - complexity) * member.multiplier * factor
        out[member.key] = Fitness(
            round(value, 12),
            {
                "basis": basis_name,
                "basis_size": len(basis),
                "pct": {t: round(p, 6) for t, p in pcts.items()},
                "values": {t: member.value(t) for t in TERMS},
                "complexity_penalty": round(complexity, 6),
                "multiplier": member.multiplier,
                "multiplier_reasons": list(member.multiplier_reasons),
                "provisional_factor": factor,
                "provisional": provisional,
            },
        )
    return out


def rank_key(
    fitness: float | None, originality: float | None, nodes: int, key: str
) -> tuple[float, float, int, str]:
    """Sort key: higher fitness, then higher originality, then fewer nodes, then id."""
    return (
        -(fitness if fitness is not None else float("-inf")),
        -(originality if originality is not None else 0.0),
        nodes,
        key,
    )


def quantile(values: Iterable[float], q: float) -> float:
    """Linear-interpolation quantile (numpy's default), without numpy for small lists."""
    ordered = sorted(values)
    if not ordered:
        return float("inf")
    position = (len(ordered) - 1) * q
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


# Released W1 values to fitness inputs ---------------------------------------------------


def w1_input(
    key: str,
    island: str,
    sign: int,
    nodes: int,
    w1: dict[str, Any],
    settings: dict[str, Any],
    *,
    w2_status: str | None = None,
) -> FitnessInput:
    """Fitness inputs from a released W1 content (and the latest W2 status, if any)."""
    multipliers = settings["fitness"]["multipliers"]
    multiplier, reasons = 1.0, []
    if "SIGN_MISMATCH" in (w1.get("flags") or []):
        multiplier, reasons = float(multipliers["sign_mismatch"]), ["SIGN_MISMATCH"]
    elif w2_status == "PASS":
        multiplier, reasons = float(multipliers["w2_pass"]), ["W2_PASS"]
    elif w2_status == "FAIL":
        multiplier, reasons = float(multipliers["w2_fail"]), ["W2_FAIL"]
    library = None if w1.get("library_empty") else w1.get("max_library_correlation")
    ir = w1.get("rankic_ir")
    return FitnessInput(
        key=key,
        island=island,
        rankic_ir=None if ir is None else sign * float(ir),
        ls_net_sharpe=w1.get("ls_net_sharpe"),
        library_corr=None if library is None else float(library),
        monotonicity=w1.get("monotonicity"),
        top_turnover=w1.get("top_turnover"),
        nodes=nodes,
        multiplier=multiplier,
        multiplier_reasons=tuple(reasons),
    )


def w0_input(
    key: str,
    island: str,
    sign: int,
    nodes: int,
    metrics: dict[str, Any],
    pool_similarity: float | None,
) -> FitnessInput:
    """Provisional inputs from W0 workbench metrics. The library term uses the maximum
    behavioral similarity to the factor pool, research's view of the library; with an
    empty pool it is neutral."""
    ir = metrics.get("rankic_ir")
    return FitnessInput(
        key=key,
        island=island,
        rankic_ir=None if ir is None else sign * float(ir),
        ls_net_sharpe=metrics.get("ls_net_sharpe"),
        library_corr=pool_similarity,
        monotonicity=metrics.get("monotonicity"),
        top_turnover=metrics.get("top_turnover"),
        nodes=nodes,
    )


def screening_failed_input(key: str, island: str, nodes: int, reason: str) -> FitnessInput:
    return FitnessInput(key, island, None, None, None, None, None, nodes, 0.0, (reason,))


# MAP-Elites descriptors -------------------------------------------------------------------


def field_group(expression: str, fields: Iterable[str], settings: dict[str, Any]) -> str:
    """price_only, volume_only, price_volume or range_volatility (Section 12.1).

    An expression on volume-type fields alone is volume_only; one mixing price-type and
    volume-type fields is price_volume; a price-only expression that uses a dispersion
    operator or both range fields is range_volatility; everything else is price_only.
    """
    archive = settings["archive"]
    groups = list(archive["field_groups"])
    volume = set(archive["volume_fields"])
    used = set(fields)
    has_volume, has_price = bool(used & volume), bool(used - volume)
    if has_volume and has_price:
        return str(groups[2])
    if has_volume:
        return str(groups[1])
    operators = {n.name for n in walk(canonicalize(parse(expression))) if isinstance(n, Call)}
    if operators & set(archive["volatility_operators"]) or set(archive["range_fields"]) <= used:
        return str(groups[3])
    return str(groups[0])


def descriptors(
    expression: str, fields: Iterable[str], sign: int, w1: dict[str, Any], settings: dict[str, Any]
) -> dict[str, Any]:
    archive = settings["archive"]
    horizons = [int(h) for h in archive["horizons"]]
    decay = w1.get("decay_profile") or {}
    best, best_value = horizons[0], float("-inf")
    for horizon in horizons:
        value = decay.get(str(horizon))
        if value is not None and sign * float(value) > best_value:
            best, best_value = horizon, sign * float(value)
    turnover = float(w1.get("top_turnover") or 0.0)
    edges = [float(e) for e in archive["turnover_edges"]]
    bucket = sum(1 for edge in edges if turnover >= edge)
    group = field_group(expression, fields, settings)
    return {
        "horizon": best,
        "turnover_bucket": bucket,
        "field_group": group,
        "cell_key": f"h{best}|t{bucket}|{group}",
    }


def cell_count(settings: dict[str, Any]) -> int:
    shape = settings["population"]["archive_shape"]
    count = 1
    for size in shape:
        count *= int(size)
    return count
