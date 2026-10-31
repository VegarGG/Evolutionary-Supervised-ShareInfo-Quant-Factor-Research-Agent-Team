"""Deterministic AST diff between two canonical trees (PLAN Section 7.5).

The edit script uses six operations, each addressed by a path of child indices in the
tree as it stands when the edit is applied:

- window: change a window literal;
- relabel: change a node's operator, field or constant while keeping its children;
- swap: exchange the two children of a commutative node;
- wrap: insert a new node above a subtree (node insertion);
- unwrap: replace a node by one of its children (node deletion);
- substitute: replace a whole subtree.

Costs count touched nodes (window 1, relabel 1, swap 0, wrap 1 plus the new sibling
nodes, unwrap 1 plus the removed sibling nodes, substitute both subtree sizes). Dynamic
programming picks the cheapest script; ties prefer the operations in the order above.
Applying the script to the parent reproduces the child exactly.
"""

from collections.abc import Callable
from typing import Any

from pydantic import JsonValue

from qfr_core.contracts import ReasonCode
from qfr_core.dsl.ast import (
    BinOp,
    Call,
    Compare,
    Field,
    Neg,
    Node,
    Num,
    Window,
    children,
    label,
    size,
    with_children,
)
from qfr_core.dsl.canonical import canonicalize, to_string
from qfr_core.dsl.catalog import COMMUTATIVE_BINARY, OPERATORS
from qfr_core.dsl.parser import DslError, parse

Edit = dict[str, JsonValue]
Path = tuple[int, ...]
_INFEASIBLE = 10**9


def _window_positions(node: Node) -> tuple[int, ...]:
    if isinstance(node, Call):
        return OPERATORS[node.name].window_positions
    return ()


def _commutative_label(node: Node) -> bool:
    if isinstance(node, BinOp):
        return node.op in COMMUTATIVE_BINARY
    return isinstance(node, Call) and OPERATORS[node.name].commutative


def _prefix(edits: list[Edit], prefix: Path) -> list[Edit]:
    out = []
    for edit in edits:
        relative = edit["path"]
        assert isinstance(relative, list)
        out.append(edit | {"path": [*prefix, *relative]})
    return out


def ast_diff(parent: Node, child: Node) -> list[Edit]:
    """Return the edit script that turns the canonical parent into the canonical child."""
    memo: dict[tuple[int, int], tuple[int, list[Edit]]] = {}

    def best(a: Node, b: Node) -> tuple[int, list[Edit]]:
        key = (id(a), id(b))
        if key in memo:
            return memo[key]
        result = _best(a, b)
        memo[key] = result
        return result

    def _best(a: Node, b: Node) -> tuple[int, list[Edit]]:
        if a == b:
            return 0, []
        if isinstance(a, Window) or isinstance(b, Window):
            if isinstance(a, Window) and isinstance(b, Window):
                return 1, [{"op": "window", "path": [], "from": a.days, "to": b.days}]
            return _INFEASIBLE, []
        options: list[tuple[int, list[Edit]]] = []
        xs, ys = children(a), children(b)
        if len(xs) == len(ys) and _window_positions(a) == _window_positions(b):
            relabel: list[Edit] = []
            if label(a) != label(b):
                relabel = [{"op": "relabel", "path": [], "from": label(a), "to": label(b)}]
            straight_cost, straight = len(relabel), list(relabel)
            for i, (x, y) in enumerate(zip(xs, ys, strict=True)):
                cost, edits = best(x, y)
                straight_cost += cost
                straight += _prefix(edits, (i,))
            options.append((straight_cost, straight))
            if len(xs) == 2 and _commutative_label(b):
                crossed_cost = len(relabel)
                crossed: list[Edit] = [*relabel, {"op": "swap", "path": []}]
                for i, (x, y) in enumerate(((xs[1], ys[0]), (xs[0], ys[1]))):
                    cost, edits = best(x, y)
                    crossed_cost += cost
                    crossed += _prefix(edits, (i,))
                options.append((crossed_cost, crossed))
        windows_b = _window_positions(b)
        for i, y in enumerate(ys):
            if i in windows_b:
                continue
            cost, edits = best(a, y)
            others: list[JsonValue] = [[j, to_string(z)] for j, z in enumerate(ys) if j != i]
            extra = sum(size(z) for j, z in enumerate(ys) if j != i)
            wrap: Edit = {"op": "wrap", "path": [], "node": label(b), "keep": i, "others": others}
            options.append((1 + extra + cost, [wrap, *_prefix(edits, (i,))]))
        windows_a = _window_positions(a)
        for i, x in enumerate(xs):
            if i in windows_a:
                continue
            cost, edits = best(x, b)
            extra = sum(size(z) for j, z in enumerate(xs) if j != i)
            unwrap: Edit = {"op": "unwrap", "path": [], "node": label(a), "keep": i}
            options.append((1 + extra + cost, [unwrap, *edits]))
        substitute: Edit = {
            "op": "substitute",
            "path": [],
            "from": to_string(a),
            "to": to_string(b),
        }
        options.append((size(a) + size(b), [substitute]))
        # min() keeps the first of equal costs, which encodes the documented preference.
        return min(options, key=lambda option: option[0])

    return best(parent, child)[1]


def parse_fragment(text: str) -> Node:
    """Parse and canonicalize a serialized subtree (no top-level type requirement)."""
    return canonicalize(parse(text))


def _from_label(text: str, args: tuple[Node, ...]) -> Node:
    kind, _, value = text.partition(":")
    if kind == "call" and value in OPERATORS:
        return Call(value, args)
    if kind == "binop" and value in {"+", "-", "*", "/"} and len(args) == 2:
        return BinOp(value, args[0], args[1])  # type: ignore[arg-type]
    if kind == "compare" and value in {">", "<", ">=", "<="} and len(args) == 2:
        return Compare(value, args[0], args[1])  # type: ignore[arg-type]
    if kind == "neg" and len(args) == 1:
        return Neg(args[0])
    if kind == "num" and not args:
        return Num(float(value))
    if kind == "field" and not args:
        return Field(value)
    raise DslError(ReasonCode.PARSE_ERROR, f"invalid node label {text!r} in an AST diff")


def _replace(tree: Node, path: list[int], fn: Callable[[Node], Node]) -> Node:
    if not path:
        return fn(tree)
    kids = list(children(tree))
    kids[path[0]] = _replace(kids[path[0]], path[1:], fn)
    return with_children(tree, tuple(kids))


def _apply_one(node: Node, edit: dict[str, Any]) -> Node:
    op = edit["op"]
    if op == "window":
        if not isinstance(node, Window) or node.days != edit["from"]:
            raise DslError(ReasonCode.PARSE_ERROR, "AST diff does not match the parent window")
        return Window(int(edit["to"]))
    if op == "relabel":
        if label(node) != edit["from"]:
            raise DslError(ReasonCode.PARSE_ERROR, "AST diff does not match the parent node")
        return _from_label(edit["to"], children(node))
    if op == "swap":
        first, second = children(node)
        return with_children(node, (second, first))
    if op == "wrap":
        texts = {int(index): text for index, text in edit["others"]}
        spec_windows: tuple[int, ...] = ()
        kind, _, name = str(edit["node"]).partition(":")
        if kind == "call" and name in OPERATORS:
            spec_windows = OPERATORS[name].window_positions
        arity = len(texts) + 1
        args = tuple(
            node
            if i == edit["keep"]
            else Window(int(texts[i]))
            if i in spec_windows
            else parse_fragment(texts[i])
            for i in range(arity)
        )
        return _from_label(str(edit["node"]), args)
    if op == "unwrap":
        if label(node) != edit["node"]:
            raise DslError(ReasonCode.PARSE_ERROR, "AST diff does not match the parent node")
        return children(node)[int(edit["keep"])]
    if op == "substitute":
        if to_string(node) != edit["from"]:
            raise DslError(ReasonCode.PARSE_ERROR, "AST diff does not match the parent subtree")
        return parse_fragment(str(edit["to"]))
    raise DslError(ReasonCode.PARSE_ERROR, f"unknown AST diff operation {op!r}")


def apply_diff(parent: Node, edits: list[Edit]) -> Node:
    tree = parent
    for edit in edits:
        path = edit["path"]
        assert isinstance(path, list) and all(isinstance(p, int) for p in path)
        indices = [p for p in path if isinstance(p, int)]
        tree = _replace(tree, indices, lambda n, e=edit: _apply_one(n, e))  # type: ignore[misc]
    return tree
