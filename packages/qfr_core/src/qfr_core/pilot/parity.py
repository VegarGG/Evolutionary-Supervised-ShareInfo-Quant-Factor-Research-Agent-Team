"""Strict first-differing-cell comparison. Tolerances are supplied, never adapted."""

import math
from collections.abc import Sequence

import polars as pl


def assert_parity(
    actual: pl.DataFrame,
    expected: pl.DataFrame,
    *,
    keys: Sequence[str],
    columns: Sequence[str],
    atol: float,
    rtol: float,
) -> int:
    if atol < 0 or rtol < 0:
        raise ValueError("parity tolerances must be nonnegative")
    left, right = actual.sort(keys), expected.sort(keys)
    if left.height != right.height or not left.select(keys).equals(right.select(keys)):
        raise AssertionError("parity row count or keys differ")
    for i, (a, b) in enumerate(
        zip(left.select(columns).iter_rows(), right.select(columns).iter_rows(), strict=True)
    ):
        for column, x, y in zip(columns, a, b, strict=True):
            if x is None or y is None:
                same = x is None and y is None
            elif isinstance(x, float) and isinstance(y, float):
                same = (
                    math.isnan(x)
                    and math.isnan(y)
                    or math.isclose(x, y, abs_tol=atol, rel_tol=rtol)
                )
            else:
                same = x == y
            if not same:
                raise AssertionError(
                    f"first differing cell: keys={left.select(keys).row(i)} column={column} "
                    f"actual={x!r} expected={y!r} atol={atol} rtol={rtol}"
                )
    return left.height * len(columns)
