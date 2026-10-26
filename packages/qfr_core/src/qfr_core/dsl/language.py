"""Closed numeric DSL. Parsing never invokes Python evaluation or user code."""

import hashlib
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from functools import cache
from pathlib import Path
from typing import Literal, cast

from lark import Lark, Token, Tree, UnexpectedInput
from pydantic import Field, PositiveInt

from qfr_core.contracts.base import Contract

TIME_UNARY = frozenset(
    {
        "Ref",
        "Delta",
        "Pct",
        "Mean",
        "Sum",
        "Std",
        "Var",
        "Min",
        "Max",
        "Med",
        "EMA",
        "WMA",
        "TsRank",
        "TsZ",
        "ArgMax",
        "ArgMin",
        "Slope",
        "Rsq",
        "Resi",
        "Skew",
        "Kurt",
    }
)
TIME_BINARY = frozenset({"Corr", "Cov"})
CROSS = frozenset({"Rank", "Zscore", "Demean", "Scale", "Neutralize"})
UNARY = frozenset({"Abs", "Sign", "Log", "Sqrt"})
BINARY = frozenset({"Max2", "Min2", "SignedPower"})
INFIX = frozenset({"+", "-", "*", "/", ">", "<", ">=", "<="})
COMMUTATIVE = frozenset({"+", "*", "Max2", "Min2"})


class DSLConfig(Contract):
    revision: PositiveInt
    profile: Literal["stock_daily_v1", "pilot_industry_v1"]
    language: Literal["qfr-dsl/1"]
    max_expression_length: PositiveInt
    max_nodes: PositiveInt
    max_depth: PositiveInt
    max_fields: PositiveInt
    max_constants: PositiveInt
    max_lookback: PositiveInt
    max_corr_nesting: PositiveInt
    windows: list[PositiveInt]
    fields: list[str]
    constant_min: float
    constant_max: float
    constant_decimals: int = Field(ge=0)
    zero_epsilon: float = Field(gt=0)
    rolling_valid_fraction: float = Field(gt=0, le=1)
    full_window_below: PositiveInt
    rank_convention: Literal["average_rank_divided_by_valid_count"]
    extremum_ties: Literal["most_recent"]

    @classmethod
    def load(cls, path: Path) -> "DSLConfig":
        return cls.model_validate_json(path.read_bytes())


@dataclass(frozen=True)
class Node:
    op: str
    args: tuple["Node", ...] = ()
    value: str = ""

    def text(self) -> str:
        if self.op in {"number", "field"}:
            return self.value
        if self.op == "neg":
            return f"(-{self.args[0].text()})"
        if self.op in INFIX:
            return f"({self.args[0].text()}{self.op}{self.args[1].text()})"
        return f"{self.op}({','.join(child.text() for child in self.args)})"


GRAMMAR = r"""
?start: comparison
?comparison: sum
           | sum COMP sum -> binary
?sum: product
    | sum ADD product -> binary
?product: unary
        | product MUL unary -> binary
?unary: "-" unary -> negative
      | atom
?atom: NUMBER -> number
     | FIELD -> field
     | NAME "(" [comparison ("," comparison)*] ")" -> function
     | "(" comparison ")"
COMP: ">=" | "<=" | ">" | "<"
ADD: "+" | "-"
MUL: "*" | "/"
NUMBER: /(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)/
FIELD: /\$[a-z][a-z0-9_]*/
NAME: /[A-Za-z][A-Za-z0-9_]*/
%import common.WS
%ignore WS
"""
_PARSER = Lark(GRAMMAR, parser="lalr", maybe_placeholders=False)


def _node(tree: Tree[Token]) -> Node:
    if tree.data in {"number", "field"}:
        return Node(str(tree.data), value=str(tree.children[0]))
    if tree.data == "negative":
        child = tree.children[0]
        assert isinstance(child, Tree)
        return Node("neg", (_node(child),))
    if tree.data == "binary":
        left, operator, right = tree.children
        assert isinstance(left, Tree) and isinstance(right, Tree)
        return Node(str(operator), (_node(left), _node(right)))
    return Node(
        str(tree.children[0]),
        tuple(_node(child) for child in tree.children[1:] if isinstance(child, Tree)),
    )


def _literal(node: Node) -> Decimal | None:
    if node.op == "number":
        return Decimal(node.value)
    if node.op == "neg" and node.args[0].op == "number":
        return -Decimal(node.args[0].value)
    return None


@dataclass(frozen=True)
class Analysis:
    nodes: int
    depth: int
    fields: frozenset[str]
    constants: int
    lookback: int
    corr_nesting: int
    recursive_history: bool

    @property
    def complexity(self) -> int:
        return self.nodes + 2 * self.constants + 3 * len(self.fields)


def analyze(node: Node, config: DSLConfig) -> Analysis:
    def visit(item: Node, window: bool = False) -> Analysis:
        if item.op == "field":
            if item.value[1:] not in config.fields:
                raise ValueError(f"forbidden field: {item.value}")
            return Analysis(1, 1, frozenset({item.value[1:]}), 0, 0, 0, False)
        if item.op == "number":
            value = Decimal(item.value)
            if not window and (
                not config.constant_min <= value <= config.constant_max
                or cast(int, value.as_tuple().exponent) < -config.constant_decimals
            ):
                raise ValueError("numeric constant violates bounds or decimal precision")
            return Analysis(1, 1, frozenset(), int(not window), 0, 0, False)
        if item.op == "neg" and item.args[0].op == "number":
            number = _literal(item)
            assert number is not None
            return visit(Node("number", value=str(number)), window)
        expected = (
            2
            if item.op in TIME_UNARY | BINARY | INFIX
            else 3
            if item.op in TIME_BINARY | {"Clip", "If"}
            else 1
            if item.op in CROSS | UNARY | {"neg"}
            else None
        )
        if expected is None or len(item.args) != expected:
            raise ValueError(f"unknown operator or wrong arity: {item.op}")
        timed = item.op in TIME_UNARY | TIME_BINARY
        distance = 0
        if timed:
            window_node = item.args[-1]
            if (
                window_node.op != "number"
                or not window_node.value.isdecimal()
                or int(window_node.value) not in config.windows
            ):
                raise ValueError("window must be an allowed positive integer literal")
            distance = int(window_node.value)
        if item.op == "SignedPower" and _literal(item.args[1]) not in {
            Decimal("0.5"),
            Decimal(2),
            Decimal(3),
        }:
            raise ValueError("SignedPower exponent must be 0.5, 2 or 3")
        if item.op == "Clip":
            lo, hi = _literal(item.args[1]), _literal(item.args[2])
            if lo is None or hi is None or lo > hi:
                raise ValueError("Clip bounds must be ordered numeric literals")
        if item.op == "If" and item.args[0].op not in {">", "<", ">=", "<="}:
            raise ValueError("If requires a comparison condition")
        children = [
            visit(child, timed and index == len(item.args) - 1)
            for index, child in enumerate(item.args)
        ]
        return Analysis(
            1 + sum(c.nodes for c in children),
            1 + max(c.depth for c in children),
            frozenset().union(*(c.fields for c in children)),
            sum(c.constants for c in children),
            max(c.lookback for c in children) + distance,
            max(c.corr_nesting for c in children) + int(item.op in TIME_BINARY),
            item.op == "EMA" or any(c.recursive_history for c in children),
        )

    result = visit(node)
    for value, limit, name in [
        (result.nodes, config.max_nodes, "nodes"),
        (result.depth, config.max_depth, "depth"),
        (len(result.fields), config.max_fields, "fields"),
        (result.constants, config.max_constants, "constants"),
        (result.lookback, config.max_lookback, "lookback"),
        (result.corr_nesting, config.max_corr_nesting, "Corr/Cov nesting"),
    ]:
        if value > limit:
            raise ValueError(f"DSL {name} exceeds limit {limit}")
    return result


def parse(expression: str, config: DSLConfig) -> Node:
    if len(expression) > config.max_expression_length:
        raise ValueError("DSL expression exceeds length limit")
    try:
        tree = _PARSER.parse(expression)
    except UnexpectedInput as exc:
        raise ValueError(f"invalid DSL syntax at position {exc.pos_in_stream}") from None
    assert isinstance(tree, Tree)
    node = _node(tree)
    analyze(node, config)
    return node


def canonicalize(node: Node, config: DSLConfig) -> Node:
    args = tuple(canonicalize(child, config) for child in node.args)
    if node.op == "number":
        return Node("number", value=format(Decimal(node.value).normalize(), "f"))
    if node.op == "neg":
        if args[0].op == "neg":
            return args[0].args[0]
        if args[0].op == "number":
            return Node("number", value=format(-Decimal(args[0].value), "f"))
    if node.op == "Rank" and args[0].op == "Rank":
        return args[0]
    if node.op in COMMUTATIVE:
        args = tuple(sorted(args, key=Node.text))
    if node.op in {"+", "-", "*", "/"} and all(child.op == "number" for child in args):
        a, b = (Decimal(child.value) for child in args)
        if node.op != "/" or abs(b) >= Decimal(str(config.zero_epsilon)):
            try:
                value = {
                    "+": lambda: a + b,
                    "-": lambda: a - b,
                    "*": lambda: a * b,
                    "/": lambda: a / b,
                }[node.op]().normalize()
                # Keep canonical output within the literal grammar, without rounding.
                if (
                    config.constant_min <= value <= config.constant_max
                    and cast(int, value.as_tuple().exponent) >= -config.constant_decimals
                ):
                    return Node("number", value=format(value, "f"))
            except InvalidOperation:
                pass
    return Node(node.op, args, node.value)


def canonical(expression: str, config: DSLConfig) -> str:
    return canonicalize(parse(expression, config), config).text()


def canonical_hash(expression: str, config: DSLConfig) -> str:
    return hashlib.sha256(canonical(expression, config).encode()).hexdigest()


def ast_similarity(a: Node, b: Node) -> float:
    @cache
    def size(node: Node) -> int:
        return 1 + sum(size(child) for child in node.args)

    @cache
    def common(left: Node, right: Node) -> int:
        if left == right:
            return size(left)
        return max(
            [
                0,
                *(common(child, right) for child in left.args),
                *(common(left, child) for child in right.args),
            ]
        )

    return common(a, b) / max(size(a), size(b))
