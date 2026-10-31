"""Deterministic variation and parent selection (PLAN Sections 12.3 and 12.4).

Everything here is deterministic code with an explicit seed: the same seed and inputs
give the same choice, and every result carries the rule, the seed and what was chosen,
so the workflow can trace it. No LLM is involved.

Syntactic mutation rules (Section 12.4): window jitter of one step within the allowed
set; operator swap within a class (Mean, EMA, WMA, Med; Std, Var, max minus min);
wrapping a subtree with Rank, TsZ or EMA; replacing a subtree with a random depth-2
subtree; field substitution within a group (close and vwap). Deterministic crossover is
a subtree exchange between two parents. A result must validate under the evaluator's
DSL limits and the brief's constraints and differ from its parents in canonical form;
otherwise another attempt is drawn from the same generator.
"""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from qfr_core.dsl import DslLimits, ast_diff, canonicalize, parse, to_string, validate
from qfr_core.dsl.ast import BinOp, Call, Compare, Field, Neg, Node, Window, children, walk
from qfr_core.dsl.ast import with_children as rebuild
from qfr_core.dsl.catalog import OPERATORS

MAX_MINUS_MIN = "MaxMinusMin"
Path = tuple[int, ...]


def derive_seed(*parts: object) -> int:
    """A 63-bit seed from named parts (program, generation, purpose, index)."""
    digest = hashlib.sha256(":".join(str(p) for p in parts).encode()).digest()
    return int.from_bytes(digest[:8], "big") >> 1


def generator(seed: int) -> np.random.Generator:
    return np.random.default_rng(seed)


# Tree helpers --------------------------------------------------------------------------


def _paths(node: Node, prefix: Path = ()) -> list[tuple[Path, Node]]:
    out = [(prefix, node)]
    for i, child in enumerate(children(node)):
        out += _paths(child, (*prefix, i))
    return out


def _get(node: Node, path: Path) -> Node:
    for i in path:
        node = children(node)[i]
    return node


def _set(node: Node, path: Path, new: Node) -> Node:
    if not path:
        return new
    kids = list(children(node))
    kids[path[0]] = _set(kids[path[0]], path[1:], new)
    return rebuild(node, tuple(kids))


def _series(node: Node) -> bool:
    """Nodes that can stand for a series argument: fields and computed values."""
    return isinstance(node, (Field, Call, BinOp, Neg, Compare))


def operators_used(tree: Node) -> set[str]:
    return {n.name for n in walk(tree) if isinstance(n, Call)}


def within_constraints(
    expression: str, limits: DslLimits, constraints: dict[str, Any]
) -> tuple[bool, list[str], Any]:
    """The evaluator's DSL limits plus the brief's stricter constraints (Section 13.3)."""
    check = validate(expression, limits)
    if not check.ok or check.analysis is None:
        return False, [str(e.get("code")) for e in check.errors], None
    analysis = check.analysis
    problems = []
    if analysis.nodes > int(constraints.get("max_nodes") or analysis.nodes):
        problems.append("MAX_NODES")
    if analysis.max_lookback_days > int(
        constraints.get("max_lookback_days") or analysis.max_lookback_days
    ):
        problems.append("MAX_LOOKBACK")
    allowed_fields = set(constraints.get("fields_allowed") or [])
    if allowed_fields and not set(analysis.fields) <= allowed_fields:
        problems.append("FIELDS_NOT_ALLOWED")
    allowed_ops = set(constraints.get("operators_allowed") or [])
    if allowed_ops and not operators_used(parse(expression)) <= allowed_ops:
        problems.append("OPERATORS_NOT_ALLOWED")
    return not problems, problems, analysis


@dataclass
class Variant:
    """A deterministic variation result, ready to become a candidate."""

    operator: str  # syntactic_mutation or crossover
    rule: str
    seed: int
    attempt: int
    parent_version_ids: list[str]
    expressions_before: list[str]
    expression: str
    canonical_hash: str
    ast_diffs: list[list[dict[str, Any]]]
    details: dict[str, Any] = field(default_factory=dict)

    def as_json(self) -> dict[str, Any]:
        return {
            "operator": self.operator,
            "rule": self.rule,
            "seed": self.seed,
            "attempt": self.attempt,
            "parent_version_ids": self.parent_version_ids,
            "expressions_before": self.expressions_before,
            "expression": self.expression,
            "canonical_hash": self.canonical_hash,
            "ast_diffs": self.ast_diffs,
            "details": self.details,
        }


# Syntactic mutation ------------------------------------------------------------------------


def _class_of(name: str, classes: Sequence[Sequence[str]]) -> list[str] | None:
    for group in classes:
        if name in group:
            return [str(g) for g in group]
    return None


def _max_minus_min(node: Node) -> tuple[Node, Window] | None:
    if (
        isinstance(node, BinOp)
        and node.op == "-"
        and isinstance(node.left, Call)
        and isinstance(node.right, Call)
        and node.left.name == "Max"
        and node.right.name == "Min"
        and node.left.args == node.right.args
    ):
        series, window = node.left.args
        if isinstance(window, Window):
            return series, window
    return None


def _swap_target(name: str, series: Node, window: Window) -> Node:
    if name == MAX_MINUS_MIN:
        return BinOp("-", Call("Max", (series, window)), Call("Min", (series, window)))
    return Call(name, (series, window))


def _windows_for(op: str, limits: DslLimits) -> list[int]:
    minimum = OPERATORS[op].min_window
    return [w for w in limits.windows if w >= minimum]


def _rule_window_jitter(
    tree: Node, rng: np.random.Generator, limits: DslLimits, _: dict[str, Any]
) -> Any:
    spots = [(p, n) for p, n in _paths(tree) if isinstance(n, Window)]
    if not spots:
        return None
    path, node = spots[int(rng.integers(len(spots)))]
    allowed = list(limits.windows)
    if node.days not in allowed:
        return None
    index = allowed.index(node.days)
    options = [i for i in (index - 1, index + 1) if 0 <= i < len(allowed)]
    new = allowed[options[int(rng.integers(len(options)))]]
    return _set(tree, path, Window(new)), {"path": list(path), "from": node.days, "to": new}


def _rule_operator_swap(
    tree: Node, rng: np.random.Generator, _: DslLimits, cfg: dict[str, Any]
) -> Any:
    classes = cfg["operator_classes"]
    spots: list[tuple[Path, str, Node, Window]] = []
    for path, node in _paths(tree):
        pair = _max_minus_min(node)
        if pair is not None and _class_of(MAX_MINUS_MIN, classes):
            spots.append((path, MAX_MINUS_MIN, pair[0], pair[1]))
        elif (
            isinstance(node, Call)
            and _class_of(node.name, classes)
            and len(node.args) == 2
            and isinstance(node.args[1], Window)
        ):
            spots.append((path, node.name, node.args[0], node.args[1]))
    if not spots:
        return None
    path, name, series, window = spots[int(rng.integers(len(spots)))]
    group = [g for g in (_class_of(name, classes) or []) if g != name]
    if not group:
        return None
    target = group[int(rng.integers(len(group)))]
    return _set(tree, path, _swap_target(target, series, window)), {
        "path": list(path),
        "from": name,
        "to": target,
    }


def _rule_wrap(tree: Node, rng: np.random.Generator, limits: DslLimits, cfg: dict[str, Any]) -> Any:
    spots = [(p, n) for p, n in _paths(tree) if _series(n)]
    wrappers = [str(w) for w in cfg["wrappers"]]
    if not spots or not wrappers:
        return None
    path, node = spots[int(rng.integers(len(spots)))]
    wrapper = wrappers[int(rng.integers(len(wrappers)))]
    params = OPERATORS[wrapper].params
    detail: dict[str, Any] = {"path": list(path), "wrapper": wrapper}
    if "window" in params:
        windows = _windows_for(wrapper, limits)
        window = windows[int(rng.integers(len(windows)))]
        new: Node = Call(wrapper, (node, Window(window)))
        detail["window"] = window
    else:
        new = Call(wrapper, (node,))
    return _set(tree, path, new), detail


def _rule_subtree_replace(
    tree: Node, rng: np.random.Generator, limits: DslLimits, _: dict[str, Any]
) -> Any:
    spots = [(p, n) for p, n in _paths(tree) if p and _series(n)]
    fields = sorted({n.name for n in walk(tree) if isinstance(n, Field)})
    ops = sorted(
        name
        for name, spec in OPERATORS.items()
        if spec.kind == "ts" and spec.params == ("series", "window")
    )
    if not spots or not fields:
        return None
    path, node = spots[int(rng.integers(len(spots)))]
    op = ops[int(rng.integers(len(ops)))]
    name = fields[int(rng.integers(len(fields)))]
    windows = _windows_for(op, limits)
    window = windows[int(rng.integers(len(windows)))]
    new = Call(op, (Field(name), Window(window)))
    return _set(tree, path, new), {
        "path": list(path),
        "replaced": to_string(node),
        "with": to_string(new),
    }


def _rule_field_substitution(
    tree: Node, rng: np.random.Generator, _: DslLimits, cfg: dict[str, Any]
) -> Any:
    groups = [[str(f) for f in g] for g in cfg["field_substitution"]]
    spots = [
        (p, n, g)
        for p, n in _paths(tree)
        if isinstance(n, Field)
        for g in groups
        if n.name in g and len(g) > 1
    ]
    if not spots:
        return None
    path, node, group = spots[int(rng.integers(len(spots)))]
    options = [f for f in group if f != node.name]
    target = options[int(rng.integers(len(options)))]
    return _set(tree, path, Field(target)), {"path": list(path), "from": node.name, "to": target}


RULES = {
    "window_jitter": _rule_window_jitter,
    "operator_swap": _rule_operator_swap,
    "wrap": _rule_wrap,
    "subtree_replace": _rule_subtree_replace,
    "field_substitution": _rule_field_substitution,
}


def _accept(
    tree: Node,
    parents: list[Node],
    limits: DslLimits,
    constraints: dict[str, Any],
) -> tuple[str, Any] | None:
    text = to_string(canonicalize(tree))
    try:
        ok, _, analysis = within_constraints(text, limits, constraints)
    except Exception:  # noqa: BLE001 - an unparseable result is just another failed attempt
        return None
    if not ok or analysis is None:
        return None
    if any(analysis.canonical == to_string(p) for p in parents):
        return None
    return analysis.canonical, analysis


def syntactic_mutation(
    parent_version_id: str,
    expression: str,
    seed: int,
    limits: DslLimits,
    constraints: dict[str, Any],
    cfg: dict[str, Any],
) -> Variant | None:
    """One deterministic mutant of the parent, or None when no attempt validates."""
    rng = generator(seed)
    parent = canonicalize(parse(expression))
    rules = [str(r) for r in cfg["syntactic_rules"] if str(r) in RULES]
    attempts = int(cfg["attempts"])
    for attempt in range(1, attempts + 1):
        rule = rules[int(rng.integers(len(rules)))]
        result = RULES[rule](parent, rng, limits, cfg)
        if result is None:
            continue
        tree, detail = result
        accepted = _accept(tree, [parent], limits, constraints)
        if accepted is None:
            continue
        canonical, analysis = accepted
        return Variant(
            operator="syntactic_mutation",
            rule=rule,
            seed=seed,
            attempt=attempt,
            parent_version_ids=[parent_version_id],
            expressions_before=[to_string(parent)],
            expression=canonical,
            canonical_hash=analysis.canonical_hash,
            ast_diffs=[[dict(e) for e in ast_diff(parent, canonicalize(parse(canonical)))]],
            details=detail,
        )
    return None


def subtree_crossover(
    parents: list[tuple[str, str]],
    seed: int,
    limits: DslLimits,
    constraints: dict[str, Any],
    cfg: dict[str, Any],
) -> Variant | None:
    """Deterministic subtree exchange: a series subtree of the first parent is replaced
    by a series subtree of the second (Section 12.4, when the LLM budget is low)."""
    rng = generator(seed)
    (first_id, first_text), (second_id, second_text) = parents
    a, b = canonicalize(parse(first_text)), canonicalize(parse(second_text))
    targets = [(p, n) for p, n in _paths(a) if p and _series(n)] or [((), a)]
    donors = [(p, n) for p, n in _paths(b) if _series(n)]
    for attempt in range(1, int(cfg["attempts"]) + 1):
        path, replaced = targets[int(rng.integers(len(targets)))]
        donor_path, donor = donors[int(rng.integers(len(donors)))]
        tree = _set(a, path, donor)
        accepted = _accept(tree, [a, b], limits, constraints)
        if accepted is None:
            continue
        canonical, analysis = accepted
        child = canonicalize(parse(canonical))
        return Variant(
            operator="crossover",
            rule="subtree_exchange",
            seed=seed,
            attempt=attempt,
            parent_version_ids=[first_id, second_id],
            expressions_before=[to_string(a), to_string(b)],
            expression=canonical,
            canonical_hash=analysis.canonical_hash,
            ast_diffs=[
                [dict(e) for e in ast_diff(a, child)],
                [dict(e) for e in ast_diff(b, child)],
            ],
            details={
                "path": list(path),
                "replaced": to_string(replaced),
                "donor_path": list(donor_path),
                "donor": to_string(donor),
            },
        )
    return None


# Parent selection --------------------------------------------------------------------------


@dataclass(frozen=True)
class Choice:
    """A member offered for selection, already ranked by fitness."""

    version_id: str
    island: str
    fitness: float
    status: str
    expression: str
    sign: int
    cell_key: str | None = None


def tournament(
    rng: np.random.Generator, ranked: Sequence[Choice], size: int, top: int
) -> tuple[Choice, dict[str, Any]] | None:
    """A tournament of `size` drawn without replacement from the `top` best; the best
    entrant (the earliest in rank order) wins."""
    pool = list(ranked[:top])
    if not pool:
        return None
    picks = sorted(int(i) for i in rng.choice(len(pool), size=min(size, len(pool)), replace=False))
    winner = pool[picks[0]]
    return winner, {
        "rule": "tournament",
        "entrants": [pool[i].version_id for i in picks],
        "pool_size": len(pool),
    }


def select_parent(
    rng: np.random.Generator,
    island_ranked: Sequence[Choice],
    archive: Sequence[Choice],
    settings: dict[str, Any],
) -> tuple[Choice, dict[str, Any]] | None:
    """Section 12.3: with probability 0.7 exploit (tournament of 3 among the island's top
    10), otherwise take the elite of a uniformly random archive cell. An empty side
    falls back to the other; None when both are empty."""
    sel = settings["selection"]
    draw = float(rng.random())
    exploit = draw < float(sel["exploit_probability"])
    record: dict[str, Any] = {"draw": round(draw, 12), "mode": "exploit" if exploit else "explore"}
    if not exploit and archive:
        cell = int(rng.integers(len(archive)))
        chosen = archive[cell]
        return chosen, record | {"rule": "archive_elite", "cell_key": chosen.cell_key}
    picked = tournament(rng, island_ranked, int(sel["tournament_size"]), int(sel["tournament_top"]))
    if picked is not None:
        chosen, detail = picked
        return chosen, record | detail | {"fallback": not exploit}
    if archive:
        chosen = archive[int(rng.integers(len(archive)))]
        return chosen, record | {
            "rule": "archive_elite",
            "cell_key": chosen.cell_key,
            "fallback": True,
        }
    return None


__all__ = [
    "Choice",
    "MAX_MINUS_MIN",
    "Variant",
    "derive_seed",
    "generator",
    "operators_used",
    "select_parent",
    "subtree_crossover",
    "syntactic_mutation",
    "tournament",
    "within_constraints",
]
