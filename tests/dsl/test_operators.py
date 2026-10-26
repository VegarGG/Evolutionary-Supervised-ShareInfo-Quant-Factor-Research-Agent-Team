"""All catalogue operators: independent references and causal-prefix properties."""

from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from qfr_core.dsl.language import CROSS, TIME_BINARY, TIME_UNARY, DSLConfig, parse
from qfr_core.dsl.operators import evaluate

from .reference import reference

CONFIG = DSLConfig.load(Path(__file__).resolve().parents[2] / "configs/dsl/stock_daily_v1.json")
EXPRESSIONS = (
    [f"{op}($close,5)" for op in sorted(TIME_UNARY)]
    + [f"{op}($close,$open,5)" for op in sorted(TIME_BINARY)]
    + [f"{op}($close)" for op in sorted(CROSS | {"Abs", "Sign", "Log", "Sqrt"})]
    + [f"$close{op}$open" for op in ["+", "-", "*", "/", ">", "<", ">=", "<="]]
    + [
        "SignedPower($close,0.5)",
        "Clip($close,-1,2)",
        "Max2($close,$open)",
        "Min2($close,$open)",
        "If($close>0,$open,$close)",
        "-$close",
    ]
)


def panel(seed=10):
    rng = np.random.default_rng(seed)
    rows = []
    for industry in range(4):
        for day in range(15):
            rows.append(
                dict(
                    instrument=str(industry),
                    date=date(2020, 1, 1) + timedelta(days=day),
                    close=None if (day + industry) % 7 == 0 else float(rng.integers(-3, 6)),
                    open=None if (day + industry) % 11 == 0 else float(rng.integers(-2, 8)),
                    adv20=float((industry + 1) * 100 + day),
                    eligible=industry < 3,
                )
            )
    return pl.DataFrame(rows)


@pytest.mark.parametrize("expression", EXPRESSIONS)
def test_every_operator_matches_independent_loop_reference(expression):
    frame = panel()
    actual = evaluate(expression, frame, CONFIG, eligible_column="eligible")["value"].to_numpy()
    expected = np.asarray(
        reference(parse(expression, CONFIG), frame, CONFIG, "eligible"), dtype=float
    )
    np.testing.assert_allclose(actual, expected, rtol=1e-10, atol=1e-12, equal_nan=True)


@pytest.mark.parametrize("expression", EXPRESSIONS)
@settings(max_examples=6, deadline=None)
@given(st.integers(1, 1000), st.integers(4, 13))
def test_all_operators_prefix_invariance(expression, seed, cutoff):
    frame = panel(seed)
    boundary = date(2020, 1, 1) + timedelta(days=cutoff)
    full = evaluate(expression, frame, CONFIG).filter(pl.col("date") <= boundary)
    prefix = evaluate(expression, frame.filter(pl.col("date") <= boundary), CONFIG)
    np.testing.assert_allclose(
        full["value"].to_numpy(), prefix["value"].to_numpy(), rtol=0, atol=1e-12, equal_nan=True
    )


@settings(max_examples=20, deadline=None)
@given(
    st.sampled_from(["Mean", "Ref", "TsRank", "Std"]),
    st.sampled_from(["Rank", "Abs", "Demean"]),
    st.integers(1, 500),
)
def test_random_nested_dsl_expressions_prefix_and_future_perturbation(outer, inner, seed):
    expression = f"{outer}({inner}($close),5)"
    frame = panel(seed)
    boundary = date(2020, 1, 10)
    expected = evaluate(expression, frame, CONFIG).filter(pl.col("date") <= boundary)
    perturbed = frame.with_columns(
        pl.when(pl.col("date") > boundary)
        .then(pl.col("close") * 100 + 10)
        .otherwise(pl.col("close"))
        .alias("close")
    )
    actual = evaluate(expression, perturbed, CONFIG).filter(pl.col("date") <= boundary)
    np.testing.assert_allclose(
        actual["value"].to_numpy(), expected["value"].to_numpy(), rtol=0, atol=1e-12, equal_nan=True
    )


def test_safe_division_and_no_numeric_fallback():
    frame = panel().with_columns(pl.lit(1e-13).alias("open"))
    assert evaluate("$close/$open", frame, CONFIG)["value"].null_count() == frame.height
    assert evaluate("Log(-1)", frame, CONFIG)["value"].null_count() == frame.height
