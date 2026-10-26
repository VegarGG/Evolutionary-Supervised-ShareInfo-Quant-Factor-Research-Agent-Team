import json
from datetime import date
from pathlib import Path

import numpy as np
import polars as pl
import pytest
from qfr_core.pilot.parity import assert_parity
from qfr_eval.backtest.pairing import pair_periods, window_periods
from qfr_eval.backtest.pilot import evaluate_pilot
from qfr_eval.backtest.scorers import ScorerSpec, built_in_history
from qfr_eval.statistics.bootstrap import oracle_interval
from qfr_eval.statistics.diagnostics import (
    CrossSections,
    aligned_cross_sections,
    calendar_shift,
    exclude_year,
    within_date_permutation,
    yearly_deltas,
)

P1 = "P1_reversal_momentum"


def test_permutation_preserves_paired_arms_and_reports_finite_resolution():
    score = np.tile(np.arange(5.0), (8, 1))
    top, bottom = score >= 3, score <= 1
    data = CrossSections(
        tuple(map(str, range(8))),
        tuple(map(str, range(5))),
        score,
        top,
        bottom,
        {"a": score, "b": score.copy()},
        {"a": top, "b": top.copy()},
        {"a": bottom, "b": bottom.copy()},
    )
    a = within_date_permutation(data, baseline="a", candidate="b", draws=99, seed=612)
    assert a == within_date_permutation(data, baseline="a", candidate="b", draws=99, seed=612)
    assert a["observed"] == {"extreme_macro_recall": 0.0, "rank_ic": 0.0}
    assert a["empirical_upper_tail"] == {"extreme_macro_recall": 1.0, "rank_ic": 1.0}
    assert a["resolution"] == 0.01 and not a["inferential_p_value_claimed"]
    with pytest.raises(ValueError, match="insufficient"):
        calendar_shift(data, baseline="a", candidate="b", minimum_distance=5, equality_atol=1e-12)


def test_year_exclusion_preserves_gaps_and_purges_crossing_labels():
    frame = pl.DataFrame(
        {
            "execution_date": [date(2023, 12, 29), date(2024, 2, 2), date(2025, 2, 7)],
            "exit_date": [date(2024, 1, 5), date(2024, 2, 9), date(2025, 2, 14)],
            "delta": [1.0, 2.0, -3.0],
        }
    )
    np.testing.assert_equal(exclude_year(frame, "delta", 2024), [np.nan, np.nan, -3.0])
    assert yearly_deltas(frame, "delta") == {"2023": None, "2024": 2.0, "2025": -3.0}


@pytest.mark.pilot
def test_pil_02_all_original_leave_one_year_out_rows(pilot_sources, pilot_runs):
    root, _, protocol = pilot_sources
    expected = pl.read_csv(
        root / "P1_English_Delivery_20261022/validation/audit/leave_one_year_out.csv"
    )
    metrics = expected["metric"].unique().to_list()
    pairs = window_periods(
        pair_periods(pilot_runs["baseline"].periods, pilot_runs[P1].periods, metrics),
        date(2024, 1, 1),
        date(2026, 10, 16),
    )
    for row in expected.iter_rows(named=True):
        frame = pairs.filter(pl.col("model_cycle") == row["model_cycle"])
        a = exclude_year(frame, row["metric"] + "_baseline", row["removed_year"])
        b = exclude_year(frame, row["metric"] + "_challenger", row["removed_year"])
        result = oracle_interval(
            b - a,
            length={"weekly": 4, "monthly": 2, "quarterly": 3}[row["model_cycle"]],
            draws=4000,
            seed=20261020,
        )
        assert len(a) == row["primary_slots"]
        assert result.valid_periods == row["retained_periods"]
        assert len(a) - result.valid_periods == row["excluded_periods"]
        assert result.valid_draws == row["valid_bootstrap_draws"]
        for actual, name in [
            (np.nanmean(a), "baseline_mean"),
            (np.nanmean(b), "P1_mean"),
            (result.estimate, "paired_delta"),
            (result.ci_lower, "ci_lower"),
            (result.ci_upper, "ci_upper"),
        ]:
            assert actual == pytest.approx(row[name], abs=protocol.atol, rel=protocol.rtol)
    assert expected.height == 45
    monthly = expected.filter(
        (pl.col("model_cycle") == "monthly")
        & (pl.col("removed_year") == 2026)
        & (pl.col("metric") == "extreme_macro_recall")
    )
    assert round(100 * monthly["paired_delta"][0], 2) == -1.24


@pytest.mark.pilot
def test_pil_02_exhaustive_calendar_shift_matches_original(pilot_sources, pilot_runs):
    root, _, protocol = pilot_sources
    expected = pl.read_csv(
        root / "P1_English_Delivery_20261022/validation/audit/circular_shift_summary.csv"
    )
    rows = []
    for cycle, distance in [("weekly", 4), ("monthly", 2), ("quarterly", 3)]:
        arms = {
            arm: window_periods(run.outcomes, date(2024, 1, 1), date(2026, 10, 16)).filter(
                pl.col("model_cycle") == cycle
            )
            for arm, run in pilot_runs.items()
        }
        data = aligned_cross_sections(arms)
        summary, _ = calendar_shift(
            data, baseline="baseline", candidate=P1, minimum_distance=distance, equality_atol=1e-12
        )
        rows.extend(
            {
                **r,
                "model_cycle": cycle,
                "variant": "P1_minus_baseline"
                if r["variant"] == "candidate_minus_baseline"
                else r["variant"],
            }
            for r in summary
        )
        with pytest.raises(ValueError, match="identical complete|missing outcome"):
            aligned_cross_sections({"a": arms["baseline"], "b": arms[P1].slice(1)})
        with pytest.raises(ValueError, match="missing prediction"):
            aligned_cross_sections(
                {"a": arms["baseline"].with_columns(pl.lit(float("inf")).alias("factor_score"))}
            )
    actual = pl.DataFrame(rows)
    keys = ["model_cycle", "variant", "metric"]
    exact = [c for c in actual.columns if c not in keys and not actual.schema[c].is_float()]
    numeric = [c for c in actual.columns if actual.schema[c].is_float()]
    assert_parity(actual, expected, keys=keys, columns=exact, atol=0, rtol=0)
    assert_parity(
        actual, expected, keys=keys, columns=numeric, atol=protocol.atol, rtol=protocol.rtol
    )


@pytest.fixture(scope="module")
def neighbor_runs(pilot_sources):
    _, tables, protocol = pilot_sources
    config = json.loads(Path("configs/pilot/robustness.json").read_text())
    result = {}
    for name, values in config["neighbors"].items():
        spec = ScorerSpec(
            name,
            values["reversal_weight"],
            values["weekly_reversal_lag"],
            values["monthly_quarterly_reversal_lag"],
            values["momentum_lookback"],
        )
        panel, history = built_in_history(
            tables["features"],
            tables["prices_daily"],
            tables["universe"]["code"].to_list(),
            protocol,
            spec=spec,
        )
        result[name] = evaluate_pilot(
            panel,
            history,
            tables["prices_daily"],
            tables["calendar"],
            tables["universe"],
            protocol,
            variant=name,
        )
    return result


@pytest.mark.pilot
def test_pil_02_six_frozen_neighbors_all_periods_and_membership(pilot_sources, neighbor_runs):
    root, _, protocol = pilot_sources
    base = root / "P1_English_Delivery_20261022/validation/robustness_results_v1"
    for filename, attr, keys in [
        ("period_metrics.csv", "periods", ["variant", "model_cycle", "period_key"]),
        ("predictions.csv", "predictions", ["variant", "model_cycle", "period_key", "code"]),
        ("industry_outcomes.csv", "outcomes", ["variant", "model_cycle", "period_key", "code"]),
    ]:
        expected = pl.read_csv(base / filename, try_parse_dates=True, infer_schema_length=None)
        expected = expected.filter(pl.col("variant").is_in(list(neighbor_runs)))
        actual = pl.concat([getattr(r, attr) for r in neighbor_runs.values()])
        columns = [c for c in expected.columns if c in actual.columns and c not in keys]
        exact = [c for c in columns if not expected.schema[c].is_float() or c.endswith("_hits")]
        numeric = [c for c in columns if c not in exact]
        assert_parity(actual, expected, keys=keys, columns=exact, atol=0, rtol=0)
        assert_parity(
            actual, expected, keys=keys, columns=numeric, atol=protocol.atol, rtol=protocol.rtol
        )


@pytest.mark.pilot
def test_pil_02_all_144_parameter_sensitivity_rows(pilot_sources, pilot_runs, neighbor_runs):
    root, _, protocol = pilot_sources
    expected = pl.read_csv(
        root
        / "P1_English_Delivery_20261022/validation/robustness_results_v1/parameter_sensitivity.csv",
        schema_overrides={"window": pl.String},
    )
    for row in expected.iter_rows(named=True):
        years = list(map(int, row["window"].split("-")))
        start = date(years[0], 1, 1)
        end = min(date(years[-1], 12, 31), date(2026, 10, 16))
        means = {}
        for variant, run in {P1: pilot_runs[P1], **neighbor_runs}.items():
            frame = window_periods(run.periods, start, end).filter(
                pl.col("model_cycle") == row["model_cycle"]
            )
            means[variant] = float(frame[row["metric"]].mean())
        values = np.array([means[v] for v in neighbor_runs])
        deltas = values - means[P1]
        actual = dict(
            P1=means[P1],
            neighbor_mean=values.mean(),
            neighbor_std=values.std(ddof=0),
            neighbor_min=values.min(),
            neighbor_max=values.max(),
            delta_min=deltas.min(),
            delta_max=deltas.max(),
        )
        for name, value in actual.items():
            assert value == pytest.approx(row[name], abs=protocol.atol, rel=protocol.rtol)
        assert row["neighbor_count"] == 6
        assert int((deltas > 1e-14).sum()) == row["positive_neighbors"]
        assert int((deltas < -1e-14).sum()) == row["negative_neighbors"]
        assert int((np.abs(deltas) <= 1e-14).sum()) == row["unchanged_neighbors"]
    assert expected.height == 144
