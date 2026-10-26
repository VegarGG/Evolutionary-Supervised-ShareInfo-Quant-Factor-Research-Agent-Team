from datetime import date
from pathlib import Path

import numpy as np
import polars as pl
import pytest
from qfr_core.configuration import load_yaml
from qfr_eval.backtest.pairing import pair_periods, window_periods
from qfr_eval.protocols.models import FrozenProtocol
from qfr_eval.statistics.bootstrap import (
    automatic_block_length,
    block_indices,
    derived_seed,
    official_interval,
    oracle_interval,
    sensitivity_intervals,
)


def test_circular_blocks_preserve_pairs_and_declared_random_stream():
    indices = block_indices(5, 2, 3, 17)
    rng = np.random.Generator(np.random.PCG64(17))
    expected = []
    for _ in range(3):
        row = []
        for _ in range(3):
            start = int(rng.integers(0, 5))
            row.extend([start, (start + 1) % 5])
        expected.append(row[:5])
    np.testing.assert_array_equal(indices, expected)
    a = np.arange(5.0)
    b = a + 7
    np.testing.assert_array_equal((b - a)[indices], b[indices] - a[indices])
    assert automatic_block_length(122, 4) == 5
    assert automatic_block_length(125, 4) == 5
    assert automatic_block_length(126, 4) == 6


def test_official_rules_reject_missing_degenerate_or_insufficient_evidence():
    protocol = load_yaml(
        Path("configs/evaluation/pilot_p0_p1_verification_v1.yaml"), FrozenProtocol
    )
    for values in [np.arange(19.0), np.full(122, 0.2), np.r_[np.arange(121.0), np.nan]]:
        result = official_interval(values, protocol.bootstrap, "weekly", seed=123)
        assert result.status == "insufficient_data" and result.ci_lower is None
    values = np.random.Generator(np.random.PCG64(999)).normal(size=122)
    a = official_interval(values, protocol.bootstrap, "weekly", seed=123)
    b = official_interval(values, protocol.bootstrap, "weekly", seed=123)
    assert a == b and a.status == "estimated" and a.valid_draws == 10000
    assert [
        r.block_length
        for r in sensitivity_intervals(values, protocol.bootstrap, "weekly", seed=123)
    ] == [4, 5, 10]
    for purpose, seed in protocol.diagnostics.purpose_seeds.items():
        assert derived_seed(protocol.diagnostics.root_seed, protocol.protocol_id, purpose) == seed


@pytest.mark.pilot
def test_pil_02_display_bootstrap_2026_including_immature_time_slots(pilot_sources, pilot_runs):
    root, _, protocol = pilot_sources
    for variant, package in [("baseline", "P0"), ("P1_reversal_momentum", "P1")]:
        expected = pl.read_csv(
            root / f"{package}_English_Delivery_20261022/validation/report_2026/summary.csv"
        )
        run = pilot_runs[variant]
        for row in expected.iter_rows(named=True):
            cycle = row["model_cycle"]
            ledger = run.ledger.filter(
                (pl.col("execution_date") >= date(2026, 1, 1)) & (pl.col("model_cycle") == cycle)
            )
            data = ledger.select("period_key").join(
                run.periods.filter(pl.col("model_cycle") == cycle), on="period_key", how="left"
            )
            for metric in [c for c in data.columns if c + "_ci_lower" in expected.columns]:
                result = oracle_interval(
                    data[metric].to_numpy(),
                    length=protocol.bootstrap.block_floors[cycle],
                    draws=2000,
                    seed=20260101,
                )
                assert result.estimate == pytest.approx(row[metric], abs=1e-12, rel=1e-12)
                assert result.ci_lower == pytest.approx(
                    row[metric + "_ci_lower"], abs=1e-12, rel=1e-12
                )
                assert result.ci_upper == pytest.approx(
                    row[metric + "_ci_upper"], abs=1e-12, rel=1e-12
                )


@pytest.mark.pilot
def test_pil_02_formal_original_4000_draw_family_intervals(pilot_sources, pilot_runs):
    root, _, _ = pilot_sources
    expected = pl.read_csv(
        root / "P1_English_Delivery_20261022/validation/audit/original_primary_macro_intervals.csv"
    )
    metric = "extreme_macro_recall"
    pairs = pair_periods(
        pilot_runs["baseline"].periods, pilot_runs["P1_reversal_momentum"].periods, [metric]
    )
    pairs = window_periods(pairs, date(2024, 1, 1), date(2026, 10, 16))
    for row in expected.iter_rows(named=True):
        values = pairs.filter(pl.col("model_cycle") == row["model_cycle"])[
            "delta_" + metric
        ].to_numpy()
        result = oracle_interval(
            values,
            length=row["block_length"],
            draws=row["bootstrap_repetitions"],
            seed=row["seed"],
            confidence=row["confidence_level"],
        )
        assert result.valid_periods == row["valid_periods"]
        assert result.estimate == pytest.approx(row["estimate"], abs=1e-12, rel=1e-12)
        assert result.ci_lower == pytest.approx(row["ci_lower"], abs=1e-12, rel=1e-12)
        assert result.ci_upper == pytest.approx(row["ci_upper"], abs=1e-12, rel=1e-12)
