"""Real pilot tables, trusted generated outputs; not a sandbox replay claim."""

from datetime import date
from pathlib import Path

import polars as pl
import pytest
from qfr_core.configuration import load_yaml
from qfr_core.contracts.execution import RunnerInput, RunnerOutput
from qfr_core.runner_tables import pack_table, unpack_table
from qfr_eval.backtest.prefix import slice_inputs
from qfr_eval.backtest.scorers import ScorerSpec, built_in_history
from qfr_eval.protocols.models import FrozenProtocol
from qfr_eval.screening.pilot import PilotOutputError, validate_pilot_output


def prepared(tables, protocol, variant, cutoff):
    data = slice_inputs(tables, cutoff)
    spec = None if variant == "P0" else ScorerSpec("P1_reversal_momentum", 0.5, 5, 20, 120)
    panel, history = built_in_history(
        data["features"],
        data["prices_daily"],
        data["universe"]["code"].to_list(),
        protocol,
        spec=spec,
        allow_empty_history=True,
    )
    inputs = RunnerInput(
        schema_version="1",
        seed=protocol.diagnostics.root_seed,
        tables={
            "features": pack_table(data["features"]),
            "prices": pack_table(data["prices_daily"]),
            "universe": pack_table(data["universe"]),
        },
    )
    output = {"panel": pack_table(panel), "review_actions": pack_table(history.review_actions)}
    for cycle in ("weekly", "monthly", "quarterly"):
        output[cycle + "_signals"] = pack_table(history.signals[cycle])
        output[cycle + "_rankings"] = pack_table(history.rankings[cycle])
    return inputs, RunnerOutput(schema_version="1", kind="model", tables=output)


@pytest.fixture(scope="module", params=["P0", "P1"])
def pilot_output_case(pilot_sources, request):
    _, tables, _ = pilot_sources
    protocol = load_yaml(
        Path("configs/evaluation/pilot_p0_p1_verification_v1.yaml"), FrozenProtocol
    )
    inputs, output = prepared(tables, protocol, request.param, date(2022, 12, 31))
    return protocol, inputs, output, tables, request.param


@pytest.mark.pilot
def test_pilot_adapter_keeps_original_eligible_grids_candidate_reviews_and_latest_snapshots(
    pilot_output_case,
):
    protocol, inputs, output, _, _ = pilot_output_case
    parsed = validate_pilot_output(output, inputs, protocol)
    quality = parsed.quality(protocol)
    assert (
        quality.status == "passed"
        and quality.required_observations == quality.complete_observations
    )
    assert set(parsed.project()) == {"panel", "weekly", "monthly", "quarterly", "review_actions"}
    assert all(parsed.original_grids[cycle].height for cycle in parsed.original_grids)


@pytest.mark.pilot
@pytest.mark.parametrize("mode", ["missing", "null", "mask", "ranking"])
def test_pilot_adapter_rejects_missing_scores_changed_eligibility_or_snapshot_claims(
    pilot_output_case, mode
):
    protocol, inputs, output, _, _ = pilot_output_case
    tables = dict(output.tables)
    if mode in ("missing", "null"):
        frame = unpack_table(tables["weekly_signals"])
        frame = (
            frame.head(frame.height - 1)
            if mode == "missing"
            else frame.with_columns(pl.lit(None, dtype=pl.Float64).alias("factor_score"))
        )
        tables["weekly_signals"] = pack_table(frame)
    elif mode == "mask":
        frame = unpack_table(tables["panel"])
        tables["panel"] = pack_table(
            frame.with_columns((~pl.col("eligible_weekly")).alias("eligible_weekly"))
        )
    else:
        frame = unpack_table(tables["quarterly_rankings"])
        tables["quarterly_rankings"] = pack_table(
            frame.with_columns(pl.lit(date(2020, 1, 1)).alias("last_review_date"))
        )
    with pytest.raises(PilotOutputError) as caught:
        validate_pilot_output(
            RunnerOutput(schema_version="1", kind="model", tables=tables), inputs, protocol
        )
    assert caught.value.code.value == (
        "LOW_COVERAGE" if mode in ("missing", "null") else "DECLARATION_MISMATCH"
    )


@pytest.mark.pilot
def test_pilot_adapter_retains_empty_early_monthly_quarterly_outputs(pilot_output_case):
    protocol, _, _, tables, variant = pilot_output_case
    inputs, output = prepared(tables, protocol, variant, protocol.diagnostics.prefix_cutoffs[0])
    parsed = validate_pilot_output(output, inputs, protocol)
    assert parsed.history.signals["monthly"].is_empty()
    assert parsed.project()["review_actions"].frame.schema["date"] == pl.Date
