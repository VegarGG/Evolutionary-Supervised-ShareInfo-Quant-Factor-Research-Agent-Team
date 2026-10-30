"""Lark grammar and parser for qfr-dsl/1 (PLAN Section 7.2)."""

from functools import cache
from typing import Any

from lark import Lark, Token, Transformer, v_args
from lark.exceptions import LarkError, UnexpectedInput, VisitError

from qfr_core.contracts import ReasonCode
from qfr_core.dsl.ast import BinOp, Call, Compare, Field, Neg, Node, Num, Window
from qfr_core.dsl.catalog import FIELD_COLUMNS, OPERATORS

MAX_EXPRESSION_CHARS = 1000  # Section 7.7: implementation.expression is 1,000 characters or fewer.
_MAX_PAREN_NESTING = 64  # Parser safety only; the depth limit (7) is enforced by analysis.

GRAMMAR = r"""
?start: expr
?expr: sum
     | sum CMP sum          -> compare
?sum: product
    | sum PLUS product      -> add
    | sum MINUS product     -> sub
?product: unary
        | product STAR unary  -> mul
        | product SLASH unary -> div
?unary: atom
      | MINUS unary         -> neg
?atom: NUMBER               -> number
     | FIELD                -> field
     | NAME "(" [args] ")"  -> call
     | "(" expr ")"
args: expr ("," expr)*
CMP: ">=" | "<=" | ">" | "<"
PLUS: "+"
MINUS: "-"
STAR: "*"
SLASH: "/"
FIELD: /\$[A-Za-z_][A-Za-z0-9_]*/
NAME: /[A-Za-z][A-Za-z0-9]*/
NUMBER: /[0-9]+(\.[0-9]+)?/
%ignore /[ \t\r\n]+/
"""


class DslError(ValueError):
    """A rejected expression with the reason code the evaluator and registry release."""

    def __init__(self, code: ReasonCode, message: str, position: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.position = position

    def as_dict(self) -> dict[str, str | int | None]:
        return {"code": self.code.value, "message": self.message, "position": self.position}


@cache
def _parser() -> Lark:
    return Lark(GRAMMAR, parser="lalr", maybe_placeholders=False, propagate_positions=False)


def _window(arg: Node, op: str, position: int | None) -> Window:
    if isinstance(arg, Neg) and isinstance(arg.operand, Num):
        raise DslError(
            ReasonCode.PARSE_ERROR, f"{op}: negative lags or windows are a parse error", position
        )
    if not isinstance(arg, Num):
        raise DslError(
            ReasonCode.TYPE_ERROR, f"{op}: the window must be an integer literal", position
        )
    if arg.text is None or "." in arg.text:
        raise DslError(
            ReasonCode.TYPE_ERROR, f"{op}: the window must be an integer literal", position
        )
    return Window(int(arg.text))


@v_args(inline=True)
class _Build(Transformer[Token, Node]):
    def number(self, token: Token) -> Node:
        return Num(float(token), text=str(token))

    def field(self, token: Token) -> Node:
        name = str(token)[1:]
        if name not in FIELD_COLUMNS:
            raise DslError(
                ReasonCode.FORBIDDEN_CONSTRUCT, f"unknown field ${name}", token.start_pos
            )
        return Field(name)

    def neg(self, _: Token, operand: Node) -> Node:
        return Neg(operand)

    def add(self, left: Node, _: Token, right: Node) -> Node:
        return BinOp("+", left, right)

    def sub(self, left: Node, _: Token, right: Node) -> Node:
        return BinOp("-", left, right)

    def mul(self, left: Node, _: Token, right: Node) -> Node:
        return BinOp("*", left, right)

    def div(self, left: Node, _: Token, right: Node) -> Node:
        return BinOp("/", left, right)

    def compare(self, left: Node, op: Token, right: Node) -> Node:
        text = str(op)
        if text == ">":
            return Compare(">", left, right)
        if text == "<":
            return Compare("<", left, right)
        if text == ">=":
            return Compare(">=", left, right)
        return Compare("<=", left, right)

    def args(self, *items: Node) -> tuple[Node, ...]:
        return tuple(items)

    def call(self, name: Token, args: tuple[Node, ...] | None = None) -> Node:
        op = str(name)
        spec = OPERATORS.get(op)
        if spec is None:
            raise DslError(ReasonCode.FORBIDDEN_CONSTRUCT, f"unknown operator {op}", name.start_pos)
        values = args or ()
        if len(values) != len(spec.params):
            raise DslError(
                ReasonCode.TYPE_ERROR,
                f"{op} takes {len(spec.params)} arguments, got {len(values)}",
                name.start_pos,
            )
        built = tuple(
            _window(arg, op, name.start_pos) if kind == "window" else arg
            for arg, kind in zip(values, spec.params, strict=True)
        )
        return Call(op, built)


def parse(text: str) -> Node:
    """Parse source text into an unchecked syntax tree. Raises DslError."""
    if not text or not text.strip():
        raise DslError(ReasonCode.PARSE_ERROR, "the expression is empty")
    if len(text) > MAX_EXPRESSION_CHARS:
        raise DslError(
            ReasonCode.COMPLEXITY_LIMIT,
            f"the expression exceeds {MAX_EXPRESSION_CHARS} characters",
        )
    nesting = deepest = 0
    for char in text:
        nesting += 1 if char == "(" else -1 if char == ")" else 0
        deepest = max(deepest, nesting)
    if deepest > _MAX_PAREN_NESTING:
        raise DslError(ReasonCode.COMPLEXITY_LIMIT, "parentheses are nested too deeply")
    try:
        tree: Any = _parser().parse(text)
        result: Node = _Build().transform(tree)
    except VisitError as error:
        if isinstance(error.orig_exc, DslError):
            raise error.orig_exc from None
        raise DslError(ReasonCode.PARSE_ERROR, "the expression could not be parsed") from None
    except UnexpectedInput as error:
        raise DslError(
            ReasonCode.PARSE_ERROR,
            f"unexpected input at position {error.pos_in_stream}",
            error.pos_in_stream,
        ) from None
    except LarkError:
        raise DslError(ReasonCode.PARSE_ERROR, "the expression could not be parsed") from None
    return result
