"""Type checking, static constraints and the one-call validation API (PLAN 7.2 to 7.5)."""

from dataclasses import dataclass
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from qfr_core.contracts import ReasonCode
from qfr_core.dsl.ast import BinOp, Call, Compare, Neg, Node, Num, Window, children
from qfr_core.dsl.ast import Field as FieldNode
from qfr_core.dsl.canonical import canonical_hash, canonicalize, to_string
from qfr_core.dsl.catalog import (
    CONSTANT_DECIMALS,
    CONSTANT_MAX,
    CONSTANT_MIN,
    CORR_COV,
    DIVISION_EPSILON,
    LANGUAGE,
    NEUTRALIZE_FIELD,
    OPERATORS,
    SIGNED_POWER_EXPONENTS,
    lookback_days,
)
from qfr_core.dsl.parser import DslError, parse

ValueType = Literal["series", "const"]


class DslLimits(BaseModel):
    """Static limits from the protocol's dsl section (PLAN Section 7.4 and Section 20)."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    max_nodes: int = Field(gt=0)
    max_depth: int = Field(gt=0)
    max_fields: int = Field(gt=0)
    max_constants: int = Field(ge=0)
    max_lookback_days: int = Field(ge=0)
    max_corr_cov_nesting: int = Field(ge=0)
    windows: tuple[int, ...] = Field(min_length=1)

    @classmethod
    def from_protocol(cls, dsl: dict[str, JsonValue]) -> Self:
        return cls.model_validate(dsl)


class DslAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    language: Literal["qfr-dsl/1"] = LANGUAGE
    canonical: str
    canonical_hash: str
    nodes: int
    depth: int
    fields: list[str]
    constants: int
    max_lookback_days: int
    corr_cov_nesting: int
    complexity: int


class DslValidation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    ok: bool
    analysis: DslAnalysis | None
    errors: list[dict[str, str | int | None]]


@dataclass(frozen=True, slots=True)
class CompiledExpression:
    """A validated canonical tree with its static analysis."""

    tree: Node
    analysis: DslAnalysis


def _literal_ok(value: float, text: str | None) -> bool:
    if not CONSTANT_MIN <= value <= CONSTANT_MAX:
        return False
    if text is not None and "." in text:
        return len(text.split(".", 1)[1]) <= CONSTANT_DECIMALS
    scaled = value * (10.0**CONSTANT_DECIMALS)
    return bool(abs(scaled - round(scaled)) < 1e-9)


def _check(node: Node, limits: DslLimits) -> ValueType:
    if isinstance(node, Num):
        if not _literal_ok(node.value, node.text):
            raise DslError(
                ReasonCode.FORBIDDEN_CONSTRUCT,
                f"constant {node.text or node.value} must lie in [{CONSTANT_MIN:g}, "
                f"{CONSTANT_MAX:g}] with at most {CONSTANT_DECIMALS} decimals",
            )
        return "const"
    if isinstance(node, FieldNode):
        return "series"
    if isinstance(node, Window):
        raise DslError(ReasonCode.TYPE_ERROR, "a window is only valid as an operator argument")
    if isinstance(node, Neg):
        return _check(node.operand, limits)
    if isinstance(node, (BinOp, Compare)):
        kinds = {_check(node.left, limits), _check(node.right, limits)}
        return "series" if "series" in kinds else "const"
    assert isinstance(node, Call)
    spec = OPERATORS[node.name]
    any_series = False
    for arg, kind in zip(node.args, spec.params, strict=True):
        if kind == "window":
            assert isinstance(arg, Window)
            if arg.days not in limits.windows:
                raise DslError(
                    ReasonCode.FORBIDDEN_CONSTRUCT,
                    f"{node.name}: window {arg.days} is not in the allowed set "
                    f"{list(limits.windows)}",
                )
            if arg.days < spec.min_window:
                raise DslError(
                    ReasonCode.TYPE_ERROR,
                    f"{node.name}: the window must be at least {spec.min_window}",
                )
            continue
        value_type = _check(arg, limits)
        if kind == "series" and value_type != "series":
            raise DslError(ReasonCode.TYPE_ERROR, f"{node.name}: argument must depend on a field")
        if kind == "const" and value_type != "const":
            raise DslError(ReasonCode.TYPE_ERROR, f"{node.name}: argument must be a constant")
        any_series = any_series or value_type == "series"
    if spec.kind != "elementwise":
        return "series"
    return "series" if any_series else "const"


def _check_canonical(node: Node) -> None:
    if isinstance(node, BinOp) and node.op == "/" and isinstance(node.right, Num):
        if abs(node.right.value) < DIVISION_EPSILON:
            raise DslError(ReasonCode.TYPE_ERROR, "division by a zero constant")
    if isinstance(node, Call):
        spec = OPERATORS[node.name]
        for arg, kind in zip(node.args, spec.params, strict=True):
            if kind == "const" and not isinstance(arg, Num):
                raise DslError(ReasonCode.TYPE_ERROR, f"{node.name}: constant did not fold")
        if node.name == "SignedPower":
            exponent = node.args[1]
            assert isinstance(exponent, Num)
            if exponent.value not in SIGNED_POWER_EXPONENTS:
                raise DslError(
                    ReasonCode.TYPE_ERROR,
                    f"SignedPower exponent must be one of {list(SIGNED_POWER_EXPONENTS)}",
                )
        if node.name == "Clip":
            low, high = node.args[1], node.args[2]
            assert isinstance(low, Num) and isinstance(high, Num)
            if not low.value < high.value:
                raise DslError(ReasonCode.TYPE_ERROR, "Clip requires lo < hi")
    for child in children(node):
        _check_canonical(child)


def _depth(node: Node) -> int:
    return 1 + max((_depth(c) for c in children(node)), default=0)


def _fields(node: Node) -> set[str]:
    found: set[str] = set()
    if isinstance(node, FieldNode):
        found.add(node.name)
    if isinstance(node, Call) and node.name == "Neutralize":
        found.add(NEUTRALIZE_FIELD)
    for child in children(node):
        found |= _fields(child)
    return found


def _lookback(node: Node) -> int:
    own = 0
    if isinstance(node, Call):
        spec = OPERATORS[node.name]
        windows = [a.days for a in node.args if isinstance(a, Window)]
        own = lookback_days(spec, windows[0]) if windows else 0
    return own + max((_lookback(c) for c in children(node)), default=0)


def _corr_nesting(node: Node) -> int:
    own = 1 if isinstance(node, Call) and node.name in CORR_COV else 0
    return own + max((_corr_nesting(c) for c in children(node)), default=0)


def _constants(node: Node) -> list[Num]:
    found = [node] if isinstance(node, Num) else []
    for child in children(node):
        found.extend(_constants(child))
    return found


def _nodes(node: Node) -> int:
    return 1 + sum(_nodes(c) for c in children(node))


def analyze(tree: Node) -> DslAnalysis:
    canonical = to_string(tree)
    fields = sorted(_fields(tree))
    constants = len(_constants(tree))
    nodes = _nodes(tree)
    return DslAnalysis(
        canonical=canonical,
        canonical_hash=canonical_hash(canonical),
        nodes=nodes,
        depth=_depth(tree),
        fields=fields,
        constants=constants,
        max_lookback_days=_lookback(tree),
        corr_cov_nesting=_corr_nesting(tree),
        complexity=nodes + 2 * constants + 3 * len(fields),
    )


def limit_violations(analysis: DslAnalysis, tree: Node, limits: DslLimits) -> list[DslError]:
    checks = [
        (analysis.nodes, limits.max_nodes, "AST nodes"),
        (analysis.depth, limits.max_depth, "depth"),
        (len(analysis.fields), limits.max_fields, "distinct fields"),
        (analysis.constants, limits.max_constants, "numeric constants"),
        (analysis.max_lookback_days, limits.max_lookback_days, "total lookback days"),
        (analysis.corr_cov_nesting, limits.max_corr_cov_nesting, "Corr/Cov nesting"),
    ]
    errors = [
        DslError(ReasonCode.COMPLEXITY_LIMIT, f"{name} {value} exceeds the limit {limit}")
        for value, limit, name in checks
        if value > limit
    ]
    for constant in _constants(tree):
        if not _literal_ok(constant.value, None):
            errors.append(
                DslError(
                    ReasonCode.FORBIDDEN_CONSTRUCT,
                    f"folded constant {constant.value!r} must lie in [{CONSTANT_MIN:g}, "
                    f"{CONSTANT_MAX:g}] with at most {CONSTANT_DECIMALS} decimals",
                )
            )
    return errors


def compile_expression(text: str, limits: DslLimits) -> CompiledExpression:
    """Parse, type check, canonicalize and enforce limits. Raises the first DslError."""
    raw = parse(text)
    if _check(raw, limits) != "series":
        raise DslError(ReasonCode.TYPE_ERROR, "the expression must depend on at least one field")
    tree = canonicalize(raw)
    _check_canonical(tree)
    analysis = analyze(tree)
    errors = limit_violations(analysis, tree, limits)
    if errors:
        raise errors[0]
    return CompiledExpression(tree, analysis)


def validate(text: str, limits: DslLimits) -> DslValidation:
    """Non-raising validation with every limit violation listed."""
    try:
        raw = parse(text)
        if _check(raw, limits) != "series":
            raise DslError(
                ReasonCode.TYPE_ERROR, "the expression must depend on at least one field"
            )
        tree = canonicalize(raw)
        _check_canonical(tree)
    except DslError as error:
        return DslValidation(ok=False, analysis=None, errors=[error.as_dict()])
    analysis = analyze(tree)
    errors = limit_violations(analysis, tree, limits)
    return DslValidation(ok=not errors, analysis=analysis, errors=[e.as_dict() for e in errors])


def declaration_mismatches(
    analysis: DslAnalysis, fields_used: list[str], max_lookback_days: int
) -> list[DslError]:
    """Section 7.7: declared fields and lookback must equal the parsed values."""
    errors = []
    if sorted(set(fields_used)) != analysis.fields or len(fields_used) != len(set(fields_used)):
        errors.append(
            DslError(
                ReasonCode.DECLARATION_MISMATCH,
                f"declared fields {sorted(fields_used)} differ from parsed {analysis.fields}",
            )
        )
    if max_lookback_days != analysis.max_lookback_days:
        errors.append(
            DslError(
                ReasonCode.DECLARATION_MISMATCH,
                f"declared lookback {max_lookback_days} differs from parsed "
                f"{analysis.max_lookback_days}",
            )
        )
    return errors
