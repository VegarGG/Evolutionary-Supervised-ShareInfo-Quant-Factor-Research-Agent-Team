"""Canonical form, serialization and canonical hash (PLAN Section 7.5).

Canonicalization: children of commutative operators (+, *, Max2, Min2) are sorted by
their canonical string, double negation is removed, constants are folded and
Rank(Rank(x)) becomes Rank(x). The serialized string re-parses to the same tree, and
canonical_hash is the SHA-256 of that string.
"""

import hashlib
import math

from qfr_core.contracts import ReasonCode
from qfr_core.dsl.ast import BinOp, Call, Compare, Field, Neg, Node, Num, Window
from qfr_core.dsl.catalog import (
    COMMUTATIVE_BINARY,
    CONSTANT_DECIMALS,
    DIVISION_EPSILON,
    OPERATORS,
)
from qfr_core.dsl.parser import DslError

_SNAP_TOLERANCE = 1e-9  # Folded constants within this of a 2-decimal value snap to it.


def format_number(value: float) -> str:
    if value == 0:
        return "0"
    if value.is_integer() and abs(value) < 1e15:
        return str(int(value))
    return repr(value)


def to_string(node: Node) -> str:
    """Compact, fully parenthesized source text that parses back to the same tree."""
    if isinstance(node, Num):
        text = format_number(node.value)
        return f"({text})" if node.value < 0 else text
    if isinstance(node, Window):
        return str(node.days)
    if isinstance(node, Field):
        return "$" + node.name
    if isinstance(node, Call):
        return node.name + "(" + ",".join(to_string(a) for a in node.args) + ")"
    if isinstance(node, (BinOp, Compare)):
        return "(" + to_string(node.left) + node.op + to_string(node.right) + ")"
    return "(-" + to_string(node.operand) + ")"


def _snap(value: float) -> float:
    rounded = round(value, CONSTANT_DECIMALS)
    if abs(value - rounded) < _SNAP_TOLERANCE:
        value = rounded
    return 0.0 if value == 0 else value


def _const(value: float | None, what: str) -> Num:
    if value is None or not math.isfinite(value):
        raise DslError(ReasonCode.TYPE_ERROR, f"constant expression {what} is undefined")
    return Num(_snap(value))


def fold_elementwise(name: str, args: tuple[float, ...]) -> float | None:
    """Element-wise semantics on scalars; None is null. Mirrors the panel operators."""
    if name == "Abs":
        return abs(args[0])
    if name == "Sign":
        return float((args[0] > 0) - (args[0] < 0))
    if name == "Log":
        return math.log(args[0]) if args[0] > 0 else None
    if name == "Sqrt":
        return math.sqrt(args[0]) if args[0] >= 0 else None
    if name == "SignedPower":
        x, p = args
        return math.copysign(abs(x) ** p, x) if x != 0 else 0.0
    if name == "Clip":
        return min(max(args[0], args[1]), args[2])
    if name == "Max2":
        return max(args)
    if name == "Min2":
        return min(args)
    if name == "If":
        return args[1] if args[0] != 0 else args[2]
    raise DslError(ReasonCode.TYPE_ERROR, f"{name} cannot be applied to constants")


def fold_binary(op: str, left: float, right: float) -> float | None:
    if op == "+":
        return left + right
    if op == "-":
        return left - right
    if op == "*":
        return left * right
    if abs(right) < DIVISION_EPSILON:
        return None
    return left / right


def fold_compare(op: str, left: float, right: float) -> float:
    result = {
        ">": left > right,
        "<": left < right,
        ">=": left >= right,
        "<=": left <= right,
    }[op]
    return 1.0 if result else 0.0


def canonicalize(node: Node) -> Node:
    """Return the canonical tree. Assumes the tree passed the type checker."""
    if isinstance(node, (Num, Window, Field)):
        return Num(_snap(node.value)) if isinstance(node, Num) else node
    if isinstance(node, Neg):
        inner = canonicalize(node.operand)
        if isinstance(inner, Neg):
            return inner.operand
        if isinstance(inner, Num):
            return Num(_snap(-inner.value))
        return Neg(inner)
    if isinstance(node, BinOp):
        left, right = canonicalize(node.left), canonicalize(node.right)
        if isinstance(left, Num) and isinstance(right, Num):
            return _const(fold_binary(node.op, left.value, right.value), to_string(node))
        if node.op in COMMUTATIVE_BINARY and to_string(right) < to_string(left):
            left, right = right, left
        return BinOp(node.op, left, right)
    if isinstance(node, Compare):
        left, right = canonicalize(node.left), canonicalize(node.right)
        if isinstance(left, Num) and isinstance(right, Num):
            return Num(fold_compare(node.op, left.value, right.value))
        return Compare(node.op, left, right)
    args = tuple(canonicalize(a) for a in node.args)
    spec = OPERATORS[node.name]
    if spec.kind == "elementwise" and all(isinstance(a, Num) for a in args):
        values = tuple(a.value for a in args if isinstance(a, Num))
        return _const(fold_elementwise(node.name, values), to_string(node))
    if spec.commutative:
        args = tuple(sorted(args, key=to_string))
    if node.name == "Rank" and isinstance(args[0], Call) and args[0].name == "Rank":
        return args[0]
    return Call(node.name, args)


def canonical_string(node: Node) -> str:
    return to_string(canonicalize(node))


def canonical_hash(canonical: str) -> str:
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
