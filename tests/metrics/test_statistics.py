import math
from pathlib import Path

import numpy as np
import pytest
from qfr_core.metrics.statistics import (
    SharpeMoments,
    StatisticsConfig,
    deflated_sharpe,
    expected_maximum_sharpe,
    probabilistic_sharpe,
    probability_of_overfit,
    sharpe_moments,
)


def config(**changes):
    data = StatisticsConfig.model_validate_json(
        Path("configs/statistics/stock_daily_v1.json").read_text()
    ).model_dump()
    return StatisticsConfig.model_validate(data | changes)


def test_psr_worked_moments():
    # Independent normal-CDF calculation of z=.4*sqrt(99)/sqrt(1.2875).
    moments = SharpeMoments(100, 0.5, -0.2, 4)
    assert probabilistic_sharpe(moments, 0.1).value == pytest.approx(0.9997738740025285)
    assert probabilistic_sharpe(moments, 0.5).value == 0.5
    # [-1, 0, 1, 2]: mean=.5, sample variance=5/3; m2=5/4, m4=41/16.
    result = sharpe_moments([-1, 0, 1, 2], config())
    assert result.sharpe == pytest.approx(0.5 / math.sqrt(5 / 3))
    assert result.skewness == 0
    assert result.pearson_kurtosis == pytest.approx(41 / 25)


def test_dsr_worked_example_and_trial_counts():
    assert expected_maximum_sharpe(0.04, 10) == pytest.approx(0.31491966026915)
    assert probabilistic_sharpe(
        SharpeMoments(100, 0.5, -0.2, 4), 0.31491966026915
    ).value == pytest.approx(0.9476996040618102)
    # Ten equally spaced values normalized to an independently known sample variance .04.
    scale = 0.2 / math.sqrt(55 / 6)
    trials = [(i - 4.5) * scale for i in range(10)]
    result = deflated_sharpe(SharpeMoments(100, 0.5, -0.2, 4), trials, effective_trials=10)
    assert result.raw_trials == result.effective_trials == 10
    assert result.sharpe_variance.value == pytest.approx(0.04)
    assert result.probability.value == pytest.approx(0.9476996040618102)
    clustered = deflated_sharpe(SharpeMoments(100, 0.5, -0.2, 4), trials, effective_trials=1)
    assert clustered.expected_maximum_sharpe.value == 0
    assert clustered.raw_trials == 10 and clustered.effective_trials == 1
    assert clustered.probability.value > result.probability.value


def test_cscv_six_split_worked_fixture():
    matrix = np.array(
        [
            [0.04, 0.01, -0.02, 0.02],
            [0.06, 0.02, 0, -0.01],
            [0.02, 0.03, 0.01, -0.01],
            [0.03, 0.05, 0.04, 0.01],
            [-0.03, 0.02, 0.05, 0],
            [-0.01, 0, 0.06, 0.03],
            [-0.02, -0.01, 0.02, 0.04],
            [0, -0.02, 0.04, 0.05],
        ]
    )
    result = probability_of_overfit(matrix, config(pbo_blocks=4))
    # Six hand-enumerated IS winners: A,B,D,C,C,C. Their OOS ranks: 1,2,2,2,3,2.
    assert result.logits == pytest.approx(
        [
            -math.log(4),
            -math.log(1.5),
            -math.log(1.5),
            -math.log(1.5),
            math.log(1.5),
            -math.log(1.5),
        ]
    )
    assert result.combinations == 6 and result.invalid_combinations == 0
    assert result.probability.value == pytest.approx(5 / 6)


def test_default_cscv_enumerates_all_12870_splits():
    matrix = np.tile(np.array([[0.01] * 4, [0.02] * 4]), (16, 1))
    result = probability_of_overfit(matrix, config())
    assert result.combinations == 12870 and result.invalid_combinations == 0
    assert len(result.logits) == 12870
    assert result.probability.value == 1  # all equal Sharpes => average rank => lambda=0


def test_insufficient_statistics_remain_missing():
    for sample in ([1, 2], [0, 0, 0], [1, 2, float("nan")]):
        assert (
            probabilistic_sharpe(sharpe_moments(sample, config()), 0).missing_reason
            == "insufficient_data"
        )
    assert deflated_sharpe(None, [1, float("nan")], effective_trials=1).probability.value is None
    assert probability_of_overfit(np.zeros((32, 4)), config()).invalid_combinations == 12870
    assert probability_of_overfit(np.ones((32, 3)), config()).probability.value is None
    with pytest.raises(ValueError):
        deflated_sharpe(None, [1], effective_trials=2)
