"""Every operator against its naive reference, plus prefix invariance (PLAN 7.3, 18.1)."""

from datetime import date, timedelta

import numpy as np
import polars as pl
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from qfr_core.dsl import DslLimits, compile_expression
from qfr_core.dsl.catalog import OPERATORS
from qfr_core.eligibility import Eligibility
from qfr_core.operators import evaluate

from tests.dsl_strategies import LIMITS, expressions
from tests.reference_ops import Reference, assert_matches

pytestmark = pytest.mark.filterwarnings("ignore:Generating overly large repr")

ELIGIBILITY = Eligibility(
    universe="csi300", listed_days_min=3, exclude_suspended=True, cross_section_min=4
)


def random_panel(seed: int, instruments: int = 9, days: int = 70) -> pl.DataFrame:
    """Dense rows between each instrument's first and last date, with nulls and ties."""
    rng = np.random.default_rng(seed)
    calendar = [date(2020, 1, 1) + timedelta(days=i) for i in range(days)]
    frames = []
    for i in range(instruments):
        first = int(rng.integers(0, days // 3))
        last = int(rng.integers(2 * days // 3, days))
        n = last - first + 1
        suspended = rng.random(n) < 0.08
        close = np.round(10 * np.exp(np.cumsum(rng.normal(0, 0.03, n))), 2)
        volume = np.round(rng.lognormal(12, 0.6, n), -2)
        amount = 3e9 + rng.normal(0, 1e4, n)  # Large magnitude, small variation.
        frame = pl.DataFrame(
            {
                "instrument": f"SY{i:06d}",
                "date": calendar[first : last + 1],
                "open": np.where(suspended, np.nan, close * (1 + rng.normal(0, 0.01, n))),
                "high": np.where(suspended, np.nan, close * 1.02),
                "low": np.where(suspended, np.nan, close * 0.98),
                "close": np.where(suspended, np.nan, close),
                "vwap": np.where(suspended, np.nan, close),
                "volume": np.where(suspended, np.nan, volume),
                "amount": np.where(suspended, np.nan, amount),
                "ret_1d": np.where(suspended, np.nan, np.round(rng.normal(0, 0.02, n), 3)),
                "adv20": np.where(rng.random(n) < 0.05, np.nan, rng.lognormal(18, 1, n)),
                "close_raw": np.where(suspended, np.nan, close / 2),
                "in_csi300": rng.random(n) < 0.85,
                "listed_days": np.arange(n, dtype=np.int32),
                "is_suspended": suspended,
            },
            nan_to_null=True,
        )
        frames.append(frame)
    return pl.concat(frames).sort("instrument", "date")


PANEL = random_panel(7)
REFERENCE = Reference(PANEL, "csi300", ELIGIBILITY.listed_days_min, ELIGIBILITY.cross_section_min)


def single_operator_expressions() -> list[str]:
    cases = []
    for name, spec in OPERATORS.items():
        if spec.kind == "ts":
            for days in LIMITS.windows:
                if days < spec.min_window or days > 40:
                    continue
                if spec.params[1] == "series":
                    cases.append(f"{name}($close,$volume,{days})")
                    cases.append(f"{name}($amount,$ret,{days})")
                else:
                    cases.append(f"{name}($close,{days})")
                    cases.append(f"{name}($amount,{days})")
        elif spec.kind == "cs":
            cases += [f"{name}($close)", f"{name}($ret)", f"{name}($amount)"]
    cases += [
        "Abs($ret)",
        "Sign($ret)",
        "Log($ret+0.01)",
        "Sqrt($ret)",
        "SignedPower($ret,0.5)",
        "SignedPower($ret,2)",
        "SignedPower($ret,3)",
        "Clip($ret,-0.01,0.02)",
        "Max2($open,$close)",
        "Min2($open,$close)",
        "If($ret>0,$close,$open)",
        "$close/($open-$open)",
        "($close>=$open)+($close<$open)*2",
        "(-$close)*$volume-$amount/$close",
    ]
    return cases


@pytest.mark.parametrize("expression", single_operator_expressions())
def test_operator_matches_reference(expression):
    tree = compile_expression(expression, LIMITS).tree
    actual = evaluate(PANEL, tree, ELIGIBILITY).to_list()
    assert_matches(actual, REFERENCE.evaluate(tree), expression)


def test_every_catalog_operator_is_covered():
    covered = {e.split("(")[0] for e in single_operator_expressions()}
    assert set(OPERATORS) <= covered | {"Max2", "Min2", "If"}


def test_nested_expressions_match_reference():
    for expression in [
        "Rank(Corr(Rank($close),Rank($volume),10))",
        "Mean(Rank($ret),5)-TsZ($close,10)",
        "Neutralize(Zscore(Delta($close,3)))",
        "WMA(Max2($high-$low,0.1),20)/EMA($close,10)",
        "Resi(Log($close),20)*Skew($ret,20)",
    ]:
        tree = compile_expression(expression, LIMITS).tree
        actual = evaluate(PANEL, tree, ELIGIBILITY).to_list()
        assert_matches(actual, REFERENCE.evaluate(tree), expression)


def truncated(panel: pl.DataFrame, cut: date) -> pl.DataFrame:
    return panel.filter(pl.col("date") <= cut)


def assert_prefix_invariant(expression: str, panel: pl.DataFrame, cut: date) -> None:
    tree = compile_expression(expression, LIMITS).tree
    full = panel.with_columns(evaluate(panel, tree, ELIGIBILITY)).filter(pl.col("date") <= cut)
    part = truncated(panel, cut)
    part = part.with_columns(evaluate(part, tree, ELIGIBILITY))
    assert_matches(part["factor"].to_list(), full["factor"].to_list(), f"{expression} @ {cut}")


@pytest.mark.parametrize("expression", single_operator_expressions())
def test_prefix_invariance_per_operator(expression):
    for cut in (date(2020, 1, 25), date(2020, 2, 20)):
        assert_prefix_invariant(expression, PANEL, cut)


@settings(
    max_examples=60,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)
@given(expression=expressions(), cut=st.integers(min_value=10, max_value=65))
def test_prefix_invariance_random_expressions(expression, cut):
    assert_prefix_invariant(expression, PANEL, date(2020, 1, 1) + timedelta(days=cut))


def test_a_lookahead_series_is_detected_by_the_same_comparison():
    peek = PANEL.with_columns(pl.col("close").shift(-1).over("instrument").alias("factor"))
    cut = date(2020, 2, 1)
    full = peek.filter(pl.col("date") <= cut)["factor"].to_list()
    part = (
        truncated(PANEL, cut)
        .with_columns(pl.col("close").shift(-1).over("instrument").alias("factor"))["factor"]
        .to_list()
    )
    with pytest.raises(AssertionError):
        assert_matches(part, full, "lookahead")


def test_unsorted_panel_is_rejected():
    with pytest.raises(ValueError, match="sorted"):
        evaluate(
            PANEL.reverse(),
            compile_expression("$close", LIMITS).tree,
            ELIGIBILITY,
        )


def test_limits_come_from_protocol_configuration():
    import yaml

    protocol = yaml.safe_load(open("configs/protocols/cn_csi300_daily_v1.yaml"))
    assert DslLimits.from_protocol(protocol["dsl"]) == LIMITS
