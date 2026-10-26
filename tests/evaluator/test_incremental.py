import math

import numpy as np
import pytest
from qfr_eval.statistics.diagnostics import CrossSections
from qfr_eval.statistics.incremental import incremental_contribution


def sections(x, y, z):
    x, y, z = (np.tile(a, (6, 1)).astype(float) for a in (x, y, z))
    return CrossSections(
        tuple(map(str, range(6))),
        tuple("abcde"),
        y,
        y >= 4,
        y <= 2,
        {"candidate": x, "baseline": z},
        {"candidate": x >= 4, "baseline": z >= 4},
        {"candidate": x <= 2, "baseline": z <= 2},
    )


def test_incremental_rank_ic_matches_independent_three_correlation_identity():
    data = sections([1, 2, 3, 4, 5], [1, 3, 2, 5, 4], [2, 1, 4, 3, 5])
    # Centered rank dot products / 10: rxy=8/10, rxz=8/10, ryz=3/10.
    expected = (0.8 - 0.8 * 0.3) / math.sqrt((1 - 0.8**2) * (1 - 0.3**2))
    result = incremental_contribution(data, candidate="candidate", pool=["baseline"], epsilon=1e-12)
    assert result.status == "estimated" and result.valid_periods == 6
    assert result.mean_rank_ic.value == pytest.approx(expected, abs=1e-12)
    assert all(
        v.value == pytest.approx(expected, abs=1e-12) for v in result.period_rank_ic.values()
    )
    assert result.max_pool_correlation.value == pytest.approx(0.8, abs=1e-12)
    assert result.pool_argmax == "baseline"


def test_redundant_signal_degenerate_pool_or_missing_period_cannot_pass():
    for data in [
        sections([1, 2, 3, 4, 5], [1, 3, 2, 5, 4], [1, 2, 3, 4, 5]),
        sections([1, 2, 3, 4, 5], [1, 3, 2, 5, 4], [1, 1, 1, 1, 1]),
    ]:
        result = incremental_contribution(
            data, candidate="candidate", pool=["baseline"], epsilon=1e-12
        )
        assert result.status == "insufficient_data" and result.mean_rank_ic.value is None
    data = sections([1, 2, 3, 4, 5], [1, 3, 2, 5, 4], [2, 1, 4, 3, 5])
    data.scores["candidate"][2, 0] = np.nan
    result = incremental_contribution(data, candidate="candidate", pool=["baseline"], epsilon=1e-12)
    assert result.valid_periods == 5 and result.status == "insufficient_data"
    assert result.mean_rank_ic.value is None and result.max_pool_correlation.value is None
    with pytest.raises(ValueError, match="separate"):
        incremental_contribution(data, candidate="candidate", pool=["candidate"], epsilon=1e-12)
