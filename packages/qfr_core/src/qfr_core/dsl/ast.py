"""Immutable syntax tree of qfr-dsl/1 (PLAN Section 7.2).

Window arguments are a separate node type so that window edits, lookback and the
"integer literal from the allowed set" rule never depend on argument position
heuristics later on.
"""

from dataclasses import dataclass, field
from typing import Literal

BinaryOp = Literal["+", "-", "*", "/"]
CompareOp = Literal[">", "<", ">=", "<="]


@dataclass(frozen=True, slots=True)
class Num:
    """A numeric constant outside a window position."""

    value: float
    # The literal as written, kept for the "at most 2 decimals" rule; not part of identity.
    text: str | None = field(default=None, compare=False)


@dataclass(frozen=True, slots=True)
class Window:
    """An integer window argument of a time-series operator."""

    days: int


@dataclass(frozen=True, slots=True)
class Field:
    """A panel field such as $close; name is stored without the dollar sign."""

    name: str


@dataclass(frozen=True, slots=True)
class Call:
    name: str
    args: tuple["Node", ...]


@dataclass(frozen=True, slots=True)
class BinOp:
    op: BinaryOp
    left: "Node"
    right: "Node"


@dataclass(frozen=True, slots=True)
class Compare:
    op: CompareOp
    left: "Node"
    right: "Node"


@dataclass(frozen=True, slots=True)
class Neg:
    operand: "Node"


Node = Num | Window | Field | Call | BinOp | Compare | Neg


def children(node: Node) -> tuple[Node, ...]:
    if isinstance(node, Call):
        return node.args
    if isinstance(node, (BinOp, Compare)):
        return (node.left, node.right)
    if isinstance(node, Neg):
        return (node.operand,)
    return ()


def with_children(node: Node, new: tuple[Node, ...]) -> Node:
    """Return a copy of node with replaced children (same arity)."""
    if isinstance(node, Call):
        return Call(node.name, new)
    if isinstance(node, BinOp):
        return BinOp(node.op, new[0], new[1])
    if isinstance(node, Compare):
        return Compare(node.op, new[0], new[1])
    if isinstance(node, Neg):
        return Neg(new[0])
    if new:
        raise ValueError("leaf nodes have no children")
    return node


def label(node: Node) -> str:
    """Identity of a node without its children, used by similarity and diff."""
    if isinstance(node, Num):
        return f"num:{node.value!r}"
    if isinstance(node, Window):
        return f"window:{node.days}"
    if isinstance(node, Field):
        return f"field:{node.name}"
    if isinstance(node, Call):
        return f"call:{node.name}"
    if isinstance(node, BinOp):
        return f"binop:{node.op}"
    if isinstance(node, Compare):
        return f"compare:{node.op}"
    return "neg"


def walk(node: Node) -> list[Node]:
    """Pre-order list of all nodes."""
    out = [node]
    for child in children(node):
        out.extend(walk(child))
    return out


def size(node: Node) -> int:
    return 1 + sum(size(c) for c in children(node))
