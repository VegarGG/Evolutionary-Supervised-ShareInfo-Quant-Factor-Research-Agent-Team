from itertools import permutations

import numpy as np
import pytest
from qfr_eval.statistics.detectability import minimum_detectable_effect, null_variance


def test_stat_01_closed_form_rankic_detectability_matches_plan():
    for n, expected in [
        (354, 0.019407133324712648),
        (82, 0.04032474321079631),
        (27, 0.07027283689263066),
    ]:
        result = minimum_detectable_effect(
            "rank_ic", universe=31, selected=7, periods=n, critical_t=2
        )
        assert result.value == pytest.approx(2 / np.sqrt(30 * n), abs=1e-15)
        assert abs(result.value - expected) < 1e-6
    assert (
        minimum_detectable_effect("rank_ic", universe=31, selected=7, periods=0, critical_t=2).value
        is None
    )


def test_null_extreme_group_variances_against_exhaustive_rank_permutations():
    # Every random ranking on five names: independent calculation, including
    # covariance between disjoint predicted top and bottom groups.
    recalls, macros = [], []
    for order in permutations(range(5)):
        top = float(order[0] == 0)
        bottom = float(order[-1] == 4)
        recalls.append(top)
        macros.append((top + bottom) / 2)
    assert null_variance("top_recall", 5, 1) == pytest.approx(np.var(recalls), abs=1e-15)
    assert null_variance("extreme_macro_recall", 5, 1) == pytest.approx(np.var(macros), abs=1e-15)
    assert np.sqrt(null_variance("top_recall", 31, 7)) == pytest.approx(0.141, abs=0.001)
