"""Hypothesis strategies for random valid qfr-dsl/1 expressions (tests only)."""

from hypothesis import strategies as st
from qfr_core.dsl import DslError, DslLimits, compile_expression
from qfr_core.dsl.catalog import OPERATORS

LIMITS = DslLimits(
    max_nodes=30,
    max_depth=7,
    max_fields=4,
    max_constants=3,
    max_lookback_days=250,
    max_corr_cov_nesting=2,
    windows=(1, 2, 3, 5, 10, 20, 40, 60, 120, 250),
)

FIELDS = ["$close", "$open", "$high", "$low", "$volume", "$amount", "$ret", "$vwap", "$adv20"]
CONSTANTS = ["0.5", "2", "1.5", "3", "0.01", "-1"]
TEST_WINDOWS = [1, 2, 3, 5, 10, 20]
TS_SINGLE = [n for n, s in OPERATORS.items() if s.kind == "ts" and s.params[1] == "window"]
TS_PAIR = [n for n, s in OPERATORS.items() if s.kind == "ts" and s.params[1] == "series"]
CS = [n for n, s in OPERATORS.items() if s.kind == "cs"]
UNARY = ["Abs", "Sign", "Log", "Sqrt"]


def _window_for(op: str):
    minimum = OPERATORS[op].min_window
    return st.sampled_from([w for w in TEST_WINDOWS if w >= minimum])


def _extend(children):
    ts = (
        st.sampled_from(TS_SINGLE)
        .flatmap(lambda op: st.tuples(st.just(op), children, _window_for(op)))
        .map(lambda t: f"{t[0]}({t[1]},{t[2]})")
    )
    pair = (
        st.sampled_from(TS_PAIR)
        .flatmap(lambda op: st.tuples(st.just(op), children, children, _window_for(op)))
        .map(lambda t: f"{t[0]}({t[1]},{t[2]},{t[3]})")
    )
    cs = st.tuples(st.sampled_from(CS), children).map(lambda t: f"{t[0]}({t[1]})")
    unary = st.tuples(st.sampled_from(UNARY), children).map(lambda t: f"{t[0]}({t[1]})")
    operators = st.sampled_from(["+", "-", "*", "/", ">", "<="])
    binary = st.tuples(children, operators, children | st.sampled_from(CONSTANTS)).map(
        lambda t: f"({t[0]}{t[1]}{t[2]})"
    )
    neg = children.map(lambda c: f"-{c}")
    extra = st.one_of(
        st.tuples(children, children).map(lambda t: f"Max2({t[0]},{t[1]})"),
        st.tuples(children, children, children).map(lambda t: f"If({t[0]},{t[1]},{t[2]})"),
        children.map(lambda c: f"Clip({c},-1,1)"),
        children.map(lambda c: f"SignedPower({c},2)"),
    )
    return st.one_of(ts, pair, cs, unary, binary, neg, extra)


def _compiles(text: str) -> bool:
    try:
        compile_expression(text, LIMITS)
    except DslError:
        return False
    return True


def raw_expressions():
    return st.recursive(st.sampled_from(FIELDS), _extend, max_leaves=6)


def expressions():
    """Source strings that pass every static check."""
    return raw_expressions().filter(_compiles)
