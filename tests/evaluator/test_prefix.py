from datetime import date

import polars as pl
import pytest
from qfr_eval.backtest.prefix import (
    CausalOutput,
    check_prefixes,
    pilot_prefix_builder,
    slice_inputs,
)
from qfr_eval.backtest.scorers import ScorerSpec, built_in_history


def test_prefix_harness_rejects_injected_future_lookahead():
    tables = {
        "values": pl.DataFrame(
            {
                "date": [date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3)],
                "code": ["a"] * 3,
                "value": [1.0, 2.0, 100.0],
            }
        )
    }

    def build(inputs):
        frame = inputs["values"].with_columns(
            pl.col("date").alias("_available_date"),
            (pl.col("value") / pl.col("value").mean()).alias("lookahead"),
        )
        return {"scores": CausalOutput(frame, ("date", "code"))}

    with pytest.raises(AssertionError, match="failed:lookahead.*first differing cell"):
        check_prefixes(tables, build, [date(2024, 1, 2)], atol=1e-12, rtol=1e-12)


@pytest.mark.pilot
@pytest.mark.parametrize("variant", ["baseline", "P1_reversal_momentum"])
def test_pil_02_six_historical_cutoffs_features_scores_membership_actions(pilot_sources, variant):
    _, tables, protocol = pilot_sources
    spec = None if variant == "baseline" else ScorerSpec(variant, 0.5, 5, 20, 120)
    checks = check_prefixes(
        tables,
        pilot_prefix_builder(protocol, spec),
        protocol.diagnostics.prefix_cutoffs,
        atol=protocol.atol,
        rtol=protocol.rtol,
    )
    assert len(checks) == 6
    assert all(c.compared_cells > 0 for c in checks)
    assert all(
        set(c.rebuilt_hashes) == {"features", "weekly", "monthly", "quarterly", "review_actions"}
        for c in checks
    )
    early = slice_inputs(tables, protocol.diagnostics.prefix_cutoffs[0])
    with pytest.raises(ValueError, match="no eligible P0 monthly dates"):
        built_in_history(
            early["features"],
            early["prices_daily"],
            early["universe"]["code"].to_list(),
            protocol,
            spec=spec,
        )
    assert pilot_prefix_builder(protocol, spec)(early)["monthly"].frame.is_empty()
