"""DSL grammar, checks, canonical form, similarity and diff (PLAN 7.2 to 7.5, 18.1)."""

import hashlib

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from qfr_core.contracts import ReasonCode
from qfr_core.dsl import (
    DslError,
    apply_diff,
    ast_diff,
    ast_similarity,
    canonicalize,
    compile_expression,
    declaration_mismatches,
    originality,
    parse,
    to_string,
    validate,
)
from qfr_core.dsl.ast import BinOp, Call, Field, Num, Window

from tests.dsl_strategies import LIMITS, expressions

pytestmark = pytest.mark.filterwarnings("ignore:Generating overly large repr")

SETTINGS = settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])


def canonical(text: str) -> str:
    return compile_expression(text, LIMITS).analysis.canonical


def unchecked(text: str) -> str:
    """Canonical string without limit checks (combined expressions may exceed limits)."""
    return to_string(canonicalize(parse(text)))


def code(text: str) -> ReasonCode:
    with pytest.raises(DslError) as error:
        compile_expression(text, LIMITS)
    return error.value.code


def test_grammar_covers_every_construct():
    tree = parse("-Mean($close, 5) * 2 + ($open > $close) - Ref($ret, 1) / 0.5")
    assert isinstance(tree, BinOp) and tree.op == "-"
    assert parse("Mean($close, 20)") == Call("Mean", (Field("close"), Window(20)))
    assert parse("1.25") == Num(1.25)


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("Ref($close, -1)", ReasonCode.PARSE_ERROR),
        ("Mean($close 5)", ReasonCode.PARSE_ERROR),
        ("$close >", ReasonCode.PARSE_ERROR),
        ("$close > $open > $high", ReasonCode.PARSE_ERROR),
        ("'text'", ReasonCode.PARSE_ERROR),
        ("1e3 * $close", ReasonCode.PARSE_ERROR),
        ("$date", ReasonCode.FORBIDDEN_CONSTRUCT),
        ("$instrument", ReasonCode.FORBIDDEN_CONSTRUCT),
        ("Lambda($close)", ReasonCode.FORBIDDEN_CONSTRUCT),
        ("Mean($close, 7)", ReasonCode.FORBIDDEN_CONSTRUCT),
        ("Mean($close, 2.5)", ReasonCode.TYPE_ERROR),
        ("Mean($close, $volume)", ReasonCode.TYPE_ERROR),
        ("Mean($close)", ReasonCode.TYPE_ERROR),
        ("Std($close, 1)", ReasonCode.TYPE_ERROR),
        ("Kurt($close, 3)", ReasonCode.TYPE_ERROR),
        ("Rank(2)", ReasonCode.TYPE_ERROR),
        ("SignedPower($close, $open)", ReasonCode.TYPE_ERROR),
        ("SignedPower($close, 4)", ReasonCode.TYPE_ERROR),
        ("Clip($close, 2, 1)", ReasonCode.TYPE_ERROR),
        ("1 + 2", ReasonCode.TYPE_ERROR),
        ("$close / (1 - 1)", ReasonCode.TYPE_ERROR),
        ("11 * $close", ReasonCode.FORBIDDEN_CONSTRUCT),
        ("0.125 * $close", ReasonCode.FORBIDDEN_CONSTRUCT),
        ("$close * (1 / 3)", ReasonCode.FORBIDDEN_CONSTRUCT),
        ("$close + 1 + $open * 2 + $high * 3 + $low * 4", ReasonCode.COMPLEXITY_LIMIT),
        ("$close + $open + $high + $low + $volume", ReasonCode.COMPLEXITY_LIMIT),
        ("Mean(Mean($close, 250), 3)", ReasonCode.COMPLEXITY_LIMIT),
        ("Ref(Mean($close, 250), 2)", ReasonCode.COMPLEXITY_LIMIT),
        ("Corr(Corr(Corr($close,$open,5),$high,5),$low,5)", ReasonCode.COMPLEXITY_LIMIT),
        ("Abs(Abs(Abs(Abs(Abs(Abs(Abs($close)))))))", ReasonCode.COMPLEXITY_LIMIT),
        ("$close" + " + $close" * 15, ReasonCode.COMPLEXITY_LIMIT),
        ("$close + " + "1" * 1000, ReasonCode.COMPLEXITY_LIMIT),
    ],
)
def test_rejections_carry_reason_codes(text, reason):
    assert code(text) == reason


def test_static_analysis_values():
    analysis = compile_expression("Corr(Rank($close), Mean($volume, 20), 10) * 2", LIMITS).analysis
    # Nodes: *, Corr, Rank, $close, Mean, $volume, 20, 10, 2 = 9.
    assert analysis.nodes == 9
    assert analysis.depth == 4
    assert analysis.fields == ["close", "volume"]
    assert analysis.constants == 1
    # Rolling windows read d - 1 earlier days: 9 (Corr) + 19 (Mean).
    assert analysis.max_lookback_days == 28
    assert analysis.corr_cov_nesting == 1
    assert analysis.complexity == 9 + 2 * 1 + 3 * 2
    assert compile_expression("Delta(Ref($close, 5), 3)", LIMITS).analysis.max_lookback_days == 8
    assert compile_expression("Neutralize($ret)", LIMITS).analysis.fields == ["adv20", "ret"]
    assert analysis.canonical_hash == hashlib.sha256(analysis.canonical.encode()).hexdigest()


def test_canonicalization_rules():
    assert canonical("$volume + $close") == canonical("$close + $volume") == "($close+$volume)"
    assert canonical("Max2($volume, $close)") == "Max2($close,$volume)"
    assert canonical("--$close") == "$close"
    assert canonical("Rank(Rank(Rank($close)))") == "Rank($close)"
    assert canonical("$close * (0.1 + 0.2)") == "($close*0.3)"
    assert canonical("$close * -2") == "($close*(-2))"
    assert canonical("Max2(1, 2) * $close") == "($close*2)"
    assert canonical("$close - $open") != canonical("$open - $close")


def test_validate_lists_every_limit_violation():
    result = validate("Mean(Mean($close,250),250) * 11 + $open*$high*$low*$volume", LIMITS)
    assert not result.ok
    result = validate("Mean(Mean($close,250),250) + $open+$high+$low+$volume", LIMITS)
    codes = [e["code"] for e in result.errors]
    assert codes == ["COMPLEXITY_LIMIT", "COMPLEXITY_LIMIT"]
    assert result.analysis is not None
    assert validate("$close", LIMITS).ok


def test_declared_fields_and_lookback_are_checked():
    analysis = compile_expression("-Pct($close, 5)", LIMITS).analysis
    assert declaration_mismatches(analysis, ["close"], 5) == []
    assert [e.code for e in declaration_mismatches(analysis, ["close", "open"], 4)] == [
        ReasonCode.DECLARATION_MISMATCH,
        ReasonCode.DECLARATION_MISMATCH,
    ]


@SETTINGS
@given(expressions())
def test_parsing_round_trips(text):
    raw = parse(text)
    assert parse(to_string(raw)) == raw
    tree = canonicalize(raw)
    assert canonicalize(parse(to_string(tree))) == tree


@SETTINGS
@given(expressions())
def test_canonicalization_is_idempotent(text):
    once = canonical(text)
    assert canonical(once) == once


@SETTINGS
@given(expressions(), expressions())
def test_canonical_form_ignores_commutative_order(a, b):
    assert unchecked(f"({a})+({b})") == unchecked(f"({b})+({a})")
    assert unchecked(f"({a})*({b})") == unchecked(f"({b})*({a})")
    assert unchecked(f"Max2({a},{b})") == unchecked(f"Max2({b},{a})")


@SETTINGS
@given(expressions(), expressions())
def test_ast_diff_applied_to_parent_reproduces_child(a, b):
    parent = compile_expression(a, LIMITS).tree
    child = compile_expression(b, LIMITS).tree
    edits = ast_diff(parent, child)
    assert apply_diff(parent, edits) == child
    assert ast_diff(parent, parent) == []
    assert ast_diff(parent, child) == edits  # Deterministic.


def test_ast_diff_names_window_changes_and_insertions():
    parent = compile_expression("Mean(Delta($close,5),10)", LIMITS).tree
    child = compile_expression("Rank(Mean(Delta($close,5),20))", LIMITS).tree
    assert ast_diff(parent, child) == [
        {"op": "wrap", "path": [], "node": "call:Rank", "keep": 0, "others": []},
        {"op": "window", "path": [0, 1], "from": 10, "to": 20},
    ]
    flipped = compile_expression("-Mean(Delta($close,5),10)", LIMITS).tree
    assert ast_diff(parent, flipped) == [
        {"op": "wrap", "path": [], "node": "neg", "keep": 0, "others": []}
    ]
    relabelled = compile_expression("Med(Delta($open,5),10)", LIMITS).tree
    assert ast_diff(parent, relabelled) == [
        {"op": "relabel", "path": [], "from": "call:Mean", "to": "call:Med"},
        {"op": "relabel", "path": [0, 0], "from": "field:close", "to": "field:open"},
    ]


def test_similarity_is_largest_common_subtree_over_larger_tree():
    a = compile_expression("Mean($close,5)", LIMITS).tree
    b = compile_expression("Mean($close,10)", LIMITS).tree
    assert ast_similarity(a, b) == pytest.approx(2 / 3)
    assert ast_similarity(a, a) == 1.0
    c = compile_expression("Rank(Mean($close,5))", LIMITS).tree
    assert ast_similarity(a, c) == pytest.approx(3 / 4)
    d = compile_expression("$volume*2", LIMITS).tree
    assert ast_similarity(a, d) == 0.0
    assert originality(a, [b, c]) == pytest.approx(0.25)
    assert originality(a, []) == 1.0


@SETTINGS
@given(expressions(), expressions())
def test_similarity_is_symmetric_and_bounded(a, b):
    x = compile_expression(a, LIMITS).tree
    y = compile_expression(b, LIMITS).tree
    assert ast_similarity(x, y) == ast_similarity(y, x)
    assert 0.0 <= ast_similarity(x, y) <= 1.0


@given(st.sampled_from(["$close", "Rank($close)"]))
def test_hash_is_stable(text):
    assert (
        compile_expression(text, LIMITS).analysis.canonical_hash
        == hashlib.sha256(canonical(text).encode()).hexdigest()
    )
