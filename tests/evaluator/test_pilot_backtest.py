from datetime import date

import polars as pl
import pytest
from qfr_core.pilot.parity import assert_parity
from qfr_eval.backtest.pilot import PriceBook, assign_split, eligible_pool_hash
from qfr_eval.backtest.schedule import publications

KEYS = ["model_cycle", "period_key"]


@pytest.mark.pilot
@pytest.mark.parametrize("variant,package", [("baseline", "P0"), ("P1_reversal_momentum", "P1")])
def test_pil_02_all_period_metrics_from_raw_inputs(pilot_sources, pilot_runs, variant, package):
    root, _, protocol = pilot_sources
    expected = pl.read_csv(
        root
        / f"{package}_English_Delivery_20261022/validation/source_evidence"
        / "algorithm_v4/evaluation_v1/period_metrics.csv",
        try_parse_dates=True,
        infer_schema_length=None,
    )
    actual = pilot_runs[variant].periods
    exact = [
        c
        for c in expected.columns
        if c in actual.columns
        and (not expected.schema[c].is_float() or c.endswith(("_hits", "_count")))
        and c not in KEYS
    ]
    numeric = [
        c
        for c in expected.columns
        if c in actual.columns and expected.schema[c].is_float() and c not in exact
    ]
    assert assert_parity(actual, expected, keys=KEYS, columns=exact, atol=0, rtol=0) > 0
    assert (
        assert_parity(
            actual, expected, keys=KEYS, columns=numeric, atol=protocol.atol, rtol=protocol.rtol
        )
        > 0
    )


@pytest.mark.pilot
def test_pil_02_p1_membership_and_outcome_ranks_exact(pilot_sources, pilot_runs):
    root, _, _ = pilot_sources
    base = root / "P1_English_Delivery_20261022/validation/robustness_results_v1"
    for filename, actual, columns in [
        (
            "predictions.csv",
            pilot_runs["P1_reversal_momentum"].predictions,
            ["rank", "selected", "factor_score", "original"],
        ),
        (
            "industry_outcomes.csv",
            pilot_runs["P1_reversal_momentum"].outcomes,
            ["actual_rank", "actual_bucket", "selection_bucket"],
        ),
    ]:
        expected = pl.read_csv(
            base / filename, try_parse_dates=True, infer_schema_length=None
        ).filter(pl.col("variant") == "P1_reversal_momentum")
        assert_parity(actual, expected, keys=[*KEYS, "code"], columns=columns, atol=0, rtol=0)


@pytest.mark.pilot
def test_pil_02_2026_coverage_retains_immature_and_outside_slots(pilot_sources, pilot_runs):
    root, _, _ = pilot_sources
    for variant, package in [("baseline", "P0"), ("P1_reversal_momentum", "P1")]:
        path = (
            root
            / f"{package}_English_Delivery_20261022/validation/report_2026/evaluation_ledger.csv"
        )
        expected = pl.read_csv(path, try_parse_dates=True, infer_schema_length=None)
        actual = pilot_runs[variant].ledger.join(expected.select(KEYS), on=KEYS, how="inner")
        columns = [
            "publication_date",
            "execution_date",
            "exit_date",
            "status",
            "eligible_pool_hash",
            "prediction_count",
            "feature_source_date",
            "snapshot_available",
        ]
        assert_parity(actual, expected, keys=KEYS, columns=columns, atol=0, rtol=0)
        cohort = actual.filter(pl.col("execution_date") >= date(2026, 1, 1))
        assert cohort.filter(pl.col("status") == "pending_exit").height == 3
        counts = cohort.filter(pl.col("status") == "evaluated").group_by("model_cycle").len()
        assert dict(counts.iter_rows()) == {"weekly": 39, "monthly": 9, "quarterly": 9}


def test_publication_waits_for_completed_calendar_month_and_does_not_backfill():
    dates = [date(2024, 1, 26), date(2024, 2, 2), date(2024, 5, 3)]
    events = publications(dates)
    monthly = [e for e in events if e["model_cycle"] == "monthly"]
    assert [(e["period_key"], e["publication_date"]) for e in monthly] == [
        ("2024-01", date(2024, 2, 2)),
        ("2024-02", date(2024, 5, 3)),
    ]
    assert not any(e["period_key"] == "2024-03" for e in events)


def test_purging_prices_and_pool_fail_explicitly(pilot_sources):
    _, _, protocol = pilot_sources
    assert assign_split(date(2023, 12, 29), date(2024, 1, 5), protocol.windows) == "purged_boundary"
    assert assign_split(date(2024, 1, 5), None, protocol.windows) == "unmatured"
    assert eligible_pool_hash(["b", "a"]) == eligible_pool_hash(["a", "b"])
    with pytest.raises(ValueError, match="unique"):
        eligible_pool_hash(["a", "a"])
    book = PriceBook(pl.DataFrame({"date": [date(2024, 1, 1)], "code": ["a"], "close": [10.0]}))
    with pytest.raises(ValueError, match="missing"):
        book.returns(["a"], date(2024, 1, 1), date(2024, 1, 2))


def test_pairing_preserves_mismatches_and_never_fabricates_delta():
    from qfr_eval.backtest.pairing import pair_periods

    a = pl.DataFrame(
        dict(
            model_cycle=["weekly", "weekly"],
            period_key=["a", "b"],
            execution_date=[date(2024, 1, 1), date(2024, 1, 8)],
            exit_date=[date(2024, 1, 8), date(2024, 1, 15)],
            eligible_pool_hash=["pool", "pool"],
            score=[0.3, 0.2],
        )
    )
    b = a.head(1).with_columns(pl.lit("different").alias("eligible_pool_hash"))
    with pytest.raises(ValueError, match="eligible_pool_mismatch"):
        pair_periods(a, b, ["score"])
    paired = pair_periods(a, b, ["score"], strict=False)
    assert paired["pair_status"].to_list() == ["eligible_pool_mismatch", "missing_challenger"]
    assert paired["delta_score"].null_count() == 2


@pytest.mark.pilot
def test_pil_02_fixed_quarter_separate_original_convention(pilot_sources):
    from qfr_eval.backtest.pairing import window_periods
    from qfr_eval.backtest.pilot import evaluate_pilot
    from qfr_eval.backtest.scorers import ScorerSpec, built_in_history

    root, tables, protocol = pilot_sources
    panel, history = built_in_history(
        tables["features"],
        tables["prices_daily"],
        tables["universe"]["code"].to_list(),
        protocol,
        spec=ScorerSpec("P1_reversal_momentum", 0.5, 5, 20, 120),
    )
    run = evaluate_pilot(
        panel,
        history,
        tables["prices_daily"],
        tables["calendar"],
        tables["universe"],
        protocol,
        variant="P1_reversal_momentum",
        fixed_quarter=True,
    )
    expected = pl.read_csv(
        root
        / "P1_English_Delivery_20261022/validation/robustness_results_v1"
        / "existing_P1_fixed_quarter_windows.csv"
    )
    for row in expected.iter_rows(named=True):
        years = list(map(int, row["window"].split("-")))
        start, end = date(years[0], 1, 1), min(date(years[-1], 12, 31), date(2026, 10, 16))
        frame = window_periods(run.periods, start, end)
        assert frame.height == row["periods"]
        for metric in [
            "top_recall",
            "bottom_recall",
            "extreme_macro_recall",
            "rank_ic",
            "action_rank_ic",
            "top_excess_equal31_net_10bps",
        ]:
            assert frame[metric].mean() == pytest.approx(
                row[metric], abs=protocol.atol, rel=protocol.rtol
            )
