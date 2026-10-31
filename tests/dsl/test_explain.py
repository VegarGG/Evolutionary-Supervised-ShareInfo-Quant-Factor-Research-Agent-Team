"""The plain-language explanation behind qfr.dsl.validate is deterministic and complete."""

import pytest
from qfr_core.dsl import canonicalize, parse, validate
from qfr_core.dsl.catalog import FIELD_COLUMNS, OPERATORS
from qfr_core.dsl.explain import ARITHMETIC_MEANINGS, FIELD_MEANINGS, OPERATOR_MEANINGS, explain

from tests.registry_rig import LIMITS


def test_every_operator_and_field_has_a_meaning():
    assert set(OPERATOR_MEANINGS) == set(OPERATORS)
    assert set(FIELD_MEANINGS) == set(FIELD_COLUMNS)
    assert all(text and text == text.strip() for text in OPERATOR_MEANINGS.values())
    assert set(ARITHMETIC_MEANINGS) >= {"+", "-", "*", "/"}


def described(expression):
    check = validate(expression, LIMITS)
    assert check.ok and check.analysis is not None, check.errors
    return explain(canonicalize(parse(expression)), check.analysis)


def test_explanation_names_fields_windows_lookback_and_size():
    result = described("Mean($close, 20) / Mean($close, 60) - 1")
    assert result.fields == {"close": FIELD_MEANINGS["close"]}
    assert [(o.name, o.windows) for o in result.operators] == [("Mean", [20, 60])]
    assert "Mean over 20/60 days" in result.summary
    assert "subtraction and division" in result.summary
    assert "59 trading days of history" in result.summary
    assert "close t+1" in result.summary


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("Mean($close, 20) / Mean($close, 60) - 1", "Mean($close,20)/Mean($close,60)-1"),
        ("Corr($close, $volume, 20)", "Corr( $close , $volume , 20 )"),
    ],
)
def test_equivalent_spellings_explain_identically(first, second):
    assert described(first) == described(second)


def test_operators_are_listed_in_name_order():
    result = described("Rank($volume) - Rank(Mean($volume, 20)) + Std($close, 10)")
    names = [o.name for o in result.operators]
    assert names == sorted(names) == ["Mean", "Rank", "Std"]
