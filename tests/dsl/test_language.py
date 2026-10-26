"""P1.5 grammar, static policy and canonicalization properties."""

from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st
from qfr_core.dsl.language import (
    DSLConfig,
    analyze,
    ast_similarity,
    canonical,
    canonical_hash,
    parse,
)

CONFIG = DSLConfig.load(Path(__file__).resolve().parents[2] / "configs/dsl/stock_daily_v1.json")


@pytest.mark.parametrize(
    "expression",
    [
        "$date",
        "$instrument",
        "__import__('os')",
        "Ref($close,-1)",
        "Mean($close,4)",
        "Ref($close,1+1)",
        "Unknown($close)",
        "Corr($close,5)",
        "0.123",
        "11",
        "SignedPower($close,4)",
        "Clip($close,2,1)",
        "If($close,$open,$low)",
    ],
)
def test_reject_unsafe_or_ill_typed_expression(expression):
    with pytest.raises(ValueError):
        parse(expression, CONFIG)


def test_static_analysis_and_caps():
    result = analyze(parse("Mean($close,20)+Ref($open,5)", CONFIG), CONFIG)
    assert result.fields == {"close", "open"}
    assert result.lookback == 20 and result.constants == 0
    assert result.complexity == result.nodes + 6
    for expression in [
        "Ref(Mean($close,250),1)",
        "$close+1+2+3+4",
        "Corr(Corr(Corr($close,$open,5),$high,5),$low,5)",
        "$close+$open+$high+$low+$volume",
    ]:
        with pytest.raises(ValueError):
            parse(expression, CONFIG)
    assert analyze(parse("EMA($close,20)", CONFIG), CONFIG).recursive_history


@given(
    st.sampled_from(["$close", "$open", "Ref($close,5)", "Rank($volume)"]),
    st.sampled_from(["$close", "$low", "Mean($close,5)"]),
    st.sampled_from(["+", "*"]),
)
def test_canonical_commutation_roundtrip_and_idempotence(left, right, op):
    value = canonical(f"{left}{op}{right}", CONFIG)
    assert value == canonical(f"{right}{op}{left}", CONFIG)
    assert value == canonical(value, CONFIG)
    assert canonical_hash(value, CONFIG) == canonical_hash(f"{left}{op}{right}", CONFIG)


def test_canonical_folding_without_precision_loss_and_subtree_similarity():
    assert canonical("Rank(Rank(-(-$close)))", CONFIG) == "Rank($close)"
    assert canonical("0.1+0.2", CONFIG) == "0.3"
    assert canonical("1/3", CONFIG) == "(1/3)"
    assert canonical("1/0", CONFIG) == "(1/0)"
    a, b = parse("$close+$open", CONFIG), parse("$close+$high", CONFIG)
    assert ast_similarity(a, b) == 1 / 3
    assert ast_similarity(a, a) == 1
