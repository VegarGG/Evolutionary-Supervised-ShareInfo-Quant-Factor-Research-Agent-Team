"""Pilot fingerprints use the complete frozen P0 development decision grid."""

import hashlib
import json
from collections.abc import Callable
from pathlib import Path

import polars as pl
from qfr_core.data_layer.snapshots import canonical_json
from qfr_core.pilot.baseline import P0History

from qfr_eval.backtest.pairing import window_periods
from qfr_eval.backtest.pilot import evaluate_pilot
from qfr_eval.backtest.prefix import slice_inputs
from qfr_eval.backtest.scorers import built_in_history
from qfr_eval.protocols.models import FrozenProtocol
from qfr_eval.records import EvaluationRequest
from qfr_eval.runtime import builtin_definition
from qfr_eval.statistics.clustering import BehavioralFingerprint


def pilot_fingerprint(
    request: EvaluationRequest,
    protocol: FrozenProtocol,
    tables: dict[str, pl.DataFrame],
    *,
    candidate_history: Callable[[dict[str, pl.DataFrame]], tuple[pl.DataFrame, P0History]]
    | None = None,
) -> BehavioralFingerprint:
    if request.protocol_hash != protocol.sha256 or protocol.scope != "P0_P1_verification_only":
        raise ValueError("fingerprint requires the approved pilot protocol")
    if (request.variant == "registry") != (candidate_history is not None):
        raise ValueError("fingerprint candidate execution binding differs")
    window = protocol.windows[protocol.diagnostics.fingerprint_window]
    data = slice_inputs(tables, window.end)
    runs = {}
    for variant in dict.fromkeys([protocol.calibration_reference, request.variant]):
        if variant == "registry":
            assert candidate_history is not None
            panel, history = candidate_history(data)
        else:
            _, _, spec = builtin_definition(variant)
            panel, history = built_in_history(
                data["features"],
                data["prices_daily"],
                data["universe"]["code"].to_list(),
                protocol,
                spec=spec,
            )
        runs[variant] = evaluate_pilot(
            panel,
            history,
            data["prices_daily"],
            data["calendar"],
            data["universe"],
            protocol,
            variant=variant,
        )
    reference = runs[protocol.calibration_reference]
    periods = window_periods(reference.periods, window.start, window.end).filter(
        pl.col("model_cycle") == "weekly"
    )
    keys = ["model_cycle", "period_key"]
    expected = (
        reference.predictions.join(periods.select(keys), on=keys, how="inner")
        .select(pl.col("execution_date").alias("date"), pl.col("code").alias("instrument"))
        .sort("date", "instrument")
    )
    pinned_grid = json.loads((Path(__file__).parents[1] / "builtin_artifacts.json").read_text())[
        "fingerprint_reference"
    ]
    grid_hash = hashlib.sha256(
        canonical_json([(day.isoformat(), code) for day, code in expected.rows()])
    ).hexdigest()
    if (
        grid_hash != pinned_grid["grid_sha256"]
        or periods.height != pinned_grid["periods"]
        or expected.height != pinned_grid["points"]
    ):
        raise ValueError("reference data no longer cover the frozen original P0 development grid")
    candidate = (
        runs[request.variant]
        .predictions.join(periods.select(keys), on=keys, how="inner")
        .select(
            pl.col("execution_date").alias("date"),
            pl.col("code").alias("instrument"),
            "factor_score",
        )
        .sort("date", "instrument")
    )
    if (
        not candidate.select("date", "instrument").equals(expected)
        or candidate.select(
            (pl.col("factor_score").is_null() | ~pl.col("factor_score").is_finite()).any()
        ).item()
    ):
        raise ValueError("candidate lacks part of the frozen development grid")
    # Include initial construction: its exclusion is specific to turnover.
    ranks = candidate.select(pl.col("factor_score").rank(method="average").over("date")).to_series()
    return BehavioralFingerprint(
        schema_version="1",
        definition="pilot_full_development_weekly_v1",
        protocol_hash=protocol.sha256,
        snapshot_id=request.snapshot_id,
        epoch_id=request.epoch_id,
        artifact_version_id=str(request.artifact_version_id),
        content_hash=request.content_hash,
        seed=protocol.diagnostics.purpose_seeds["fingerprint"],
        start=window.start,
        end=window.end,
        grid=expected.rows(),
        ranks=ranks.to_list(),
    )
