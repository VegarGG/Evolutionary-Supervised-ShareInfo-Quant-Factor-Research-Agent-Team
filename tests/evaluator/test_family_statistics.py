from pathlib import Path

import numpy as np
import pytest
from qfr_core.configuration import load_yaml
from qfr_eval.protocols.models import FrozenProtocol
from qfr_eval.statistics.family import (
    TrialObservation,
    child_parent_interval,
    family_statistics,
    hac_standard_error,
    simultaneous_critical_value,
    stepdown_max_t,
    studentized_family,
)


def protocol():
    return load_yaml(Path("configs/evaluation/pilot_p0_p1_verification_v1.yaml"), FrozenProtocol)


def test_hac_bartlett_denominator_and_constant_hand_fixture():
    assert float(hac_standard_error(np.array([1.0, 2.0, 4.0, 3.0]), 1)) == pytest.approx(
        np.sqrt(23 / 64)
    )
    assert float(hac_standard_error(np.full(122, 0.2), 4)) == 0


def test_romano_wolf_stepdown_worked_family_and_no_zero_p():
    # Largest observed |t| uses both columns; the second uses its remaining column.
    observed = np.array([3.0, 1.0])
    draws = np.array([[0.5, 0.2], [2.0, 1.2], [4.0, 0.3], [1.5, 2.0]])
    adjusted, critical = stepdown_max_t(observed, draws, 0.75)
    np.testing.assert_allclose(adjusted, [2 / 5, 3 / 5])
    np.testing.assert_allclose(critical, [4.0, 2.0])
    assert stepdown_max_t(np.array([100.0, 100.0]), draws, 0.95)[0].min() == 1 / 5


def test_studentized_pairing_zero_difference_and_failed_trial_are_not_passes():
    cfg = protocol().bootstrap
    rng = np.random.Generator(np.random.PCG64(883))
    parent = rng.normal(size=80)
    child = parent + rng.normal(0.3, 0.2, size=80)
    result = child_parent_interval(child, parent, cfg, "weekly", seed=81)
    assert result.status == "estimated" and result.ci_lower[0] > 0
    repeated = child_parent_interval(child, parent, cfg, "weekly", seed=81)
    assert result == repeated
    assert (
        child_parent_interval(parent, parent, cfg, "weekly", seed=81).status == "insufficient_data"
    )
    family = np.column_stack([child - parent, np.full(80, np.nan)])
    result = studentized_family(family, cfg, "weekly", seed=81, raw_trials=2)
    assert result.status == "insufficient_data" and result.raw_trials == 2
    with pytest.raises(ValueError, match="all declared"):
        studentized_family(family, cfg, "weekly", seed=81, raw_trials=1)


def test_joint_intervals_use_family_envelope_without_step_order_undercoverage():
    # With two independent Gaussian coordinates, mixed 97.468%/95% marginal
    # coverages yield sqrt(.95)*.95 = .925945..., not a joint 95% interval.
    # A full-family max-|T| envelope protects the joint event instead.
    draws = np.array([[0.5, 0.2], [2.0, 1.2], [4.0, 0.3], [1.5, 2.0]])
    assert simultaneous_critical_value(draws, 0.75) == 4.0
    assert simultaneous_critical_value(draws[:, ::-1], 0.75) == 4.0
    rng = np.random.Generator(np.random.PCG64(57))
    values = rng.normal(size=(80, 2)) + [5, 0.2]
    result = studentized_family(values, protocol().bootstrap, "weekly", seed=81, raw_trials=2)
    assert result.status == "estimated"
    scales = (np.array(result.means) - np.array(result.ci_lower)) / np.array(result.standard_errors)
    assert scales[0] == pytest.approx(scales[1], abs=1e-12)
    assert result.interval_method == "simultaneous_full_family_maxT_envelope"


def test_trial_family_counts_failed_withheld_diagnostics_and_generation_pbo():
    rng = np.random.Generator(np.random.PCG64(714))
    rows = []
    for i in range(4):
        rows.append(
            TrialObservation(
                trial_id=str(i),
                artifact_version_id=str(i),
                family_id=str(i),
                economic_lineage_id=str(i),
                generation_id="generation",
                program_id="program",
                protocol_hash="protocol",
                snapshot_id="snapshot",
                window="validation",
                cohort_id="cohort",
                status="diagnostic" if i == 3 else "withheld" if i == 2 else "evaluated",
                selectable=i != 3,
                sampling_unit="mature_matched_decision",
                returns=rng.normal(size=64).tolist(),
                observation_ids=[str(j) for j in range(64)],
            )
        )
    stats = family_statistics(
        rows,
        "0",
        2,
        protocol().diagnostics,
        block_length=4,
        minimum_periods=10,
        minimum_blocks=5,
        zero_epsilon=1e-12,
    )
    assert stats.raw_trials == 4 and stats.effective_trials == 2
    assert stats.withheld_trials == stats.diagnostic_trials == 1
    assert stats.dsr.value is not None and stats.pbo.value is not None
    assert stats.pbo_cohort == "generation"
    rows[3] = rows[3].model_copy(update={"status": "failed", "returns": [None] * 64})
    stats = family_statistics(
        rows,
        "0",
        None,
        protocol().diagnostics,
        block_length=4,
        minimum_periods=10,
        minimum_blocks=5,
        zero_epsilon=1e-12,
    )
    assert stats.raw_trials == 4 and stats.failed_trials == 1
    assert stats.dsr.value is None and stats.pbo.value is None
    assert stats.dsr.missing_reason == "insufficient_data"


def test_turnover_strict_threshold_both_baskets_and_small_window_discretization():
    from qfr_eval.statistics.hurdles import turnover_flag

    p = protocol()
    q = p.turnover.top_threshold
    for n, allowed in [(20, 1), (39, 1), (40, 2), (121, 6)]:
        vals = [q] * (n - allowed) + [np.nextafter(q, 1.0)] * allowed
        passed = turnover_flag(
            [1.0, *vals], [True, *([False] * n)], p, cycle="weekly", basket="top"
        )
        assert passed.status == "pass" and passed.exceedances == allowed
        vals[0] = np.nextafter(q, 1.0)
        assert turnover_flag(vals, [False] * n, p, cycle="weekly", basket="top").status == "fail"
    assert (
        turnover_flag([q] * 19, [False] * 19, p, cycle="weekly", basket="top").status
        == "insufficient_data"
    )
    assert (
        turnover_flag([None, *([q] * 39)], [False] * 40, p, cycle="weekly", basket="top").status
        == "insufficient_data"
    )
    assert (
        turnover_flag([q] * 40, [False] * 40, p, cycle="monthly", basket="top").status
        == "not_applicable"
    )
    with pytest.raises(ValueError, match="genuine initial"):
        turnover_flag([1.0, 1.0], [True, True], p, cycle="weekly", basket="top")


def test_stat_02_missing_required_evidence_never_passes_hurdle():
    from qfr_core.metrics.core import measurement
    from qfr_eval.statistics.hurdles import fold_majority, pilot_hurdle, turnover_flag

    p = protocol()
    rng = np.random.Generator(np.random.PCG64(48))
    delta = rng.normal(0.4, 0.3, size=80)
    family = studentized_family(delta[:, None], p.bootstrap, "weekly", seed=81, raw_trials=1)
    turnover = turnover_flag([0.1] * 80, [False] * 80, p, cycle="weekly", basket="top")
    flags = pilot_hurdle(
        family,
        0,
        p,
        incremental_rank_ic=measurement(None),
        placebo_percentile=measurement(99),
        max_pool_correlation=measurement(0.2),
        folds=fold_majority([0.1, 0.2], [0.2, 0.1]),
        top_turnover=turnover,
        bottom_turnover=turnover,
        block_sensitivity=[],
    )
    assert flags["overall"] == "insufficient_data"
    assert fold_majority([0.1, -0.1], [0.1, 0.2]) == "fail"
    assert fold_majority([0.1, 0.2], [None, 0.2]) == "insufficient_data"
