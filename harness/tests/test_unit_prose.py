from fractions import Fraction

import pytest

from qfh.unit_prose import relationships


@pytest.mark.parametrize(
    "text,passed",
    [
        (
            "The raw stored ratio equals the intended dimensionless earnings yield times 10^-4.",
            False,
        ),
        ("The raw stored ratio equals the intended dimensionless earnings yield times 10^4.", True),
        ("The target dimensionless yield equals the raw stored ratio times 1/10000.", True),
        ("raw = target * (10000/1)", True),
        ("target = raw * 1e-4", True),
        ("raw = target * 1e-4", False),
        (
            "The initial 'no conversion needed' claim understated the ratio level "
            "by exactly a factor of 10^4.",
            False,
        ),
        (
            "The initial 'no conversion needed' claim overstated the ratio level "
            "by exactly a factor of 10^4.",
            True,
        ),
        ("The raw ratio overstates the target by a factor of 100.", False),
    ],
)
def test_explicit_relationships_check_source_derived_scale(text, passed):
    checks = relationships({"rationale": text}, Fraction(1, 10000))
    assert checks and all(x["passed"] for x in checks) is passed
    assert all(x["path"] == "/rationale" and x["quote"] in text for x in checks)


def test_correct_appendix_does_not_hide_the_wrong_original_clause():
    text = (
        "The raw stored ratio equals the intended dimensionless earnings yield times 10^-4. "
        "The target dimensionless yield equals the raw stored ratio times 1/10000; "
        "the raw ratio equals the target times 10000/1."
    )
    checks = relationships({"rationale": text}, Fraction(1, 10000))
    assert len(checks) == 3 and [x["passed"] for x in checks] == [False, True, True]


def test_checker_is_not_hardcoded_to_the_counterexample_ratio():
    checks = relationships({"rationale": "raw = target * 2"}, Fraction(1, 2))
    assert checks[0]["passed"]
    assert not relationships({"rationale": "raw = target * 2"}, Fraction(1, 10000))[0]["passed"]
    assert relationships({"hypothesis": "Returns may depend on valuation."}, Fraction(1, 2)) == []


@pytest.mark.parametrize("factor", ["1e999999999", "1e-999999999"])
def test_extreme_prose_exponents_fail_before_fraction_allocation(factor):
    checks = relationships({"rationale": f"raw = target * {factor}"}, Fraction(1, 10000))
    assert checks and not checks[0]["passed"]
