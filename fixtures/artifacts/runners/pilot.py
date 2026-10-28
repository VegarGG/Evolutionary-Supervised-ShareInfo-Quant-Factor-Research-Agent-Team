"""Frozen P0/P1 adapter. Loaded only inside an accepted sandbox."""

import json
from pathlib import Path

import numpy as np
import polars as pl
from qfr_core.contracts.execution import RunnerInput, RunnerOutput
from qfr_core.pilot.baseline import P0Config, p0_history, p0_scores
from qfr_core.pilot.features import PilotFeatureConfig, enrich_p0, price_features
from qfr_core.runner_tables import pack_table, unpack_table


def run(value):
    request = RunnerInput.model_validate(value)
    weights = json.loads(Path(__file__).with_name("weights.json").read_text())
    p0 = P0Config.model_validate(weights["p0"])
    features_config = PilotFeatureConfig.model_validate(weights["features"])
    features = unpack_table(request.tables["features"])
    prices = unpack_table(request.tables["prices"])
    codes = sorted(unpack_table(request.tables["universe"])["code"].unique().to_list())
    if features.filter(pl.col("available_date") > pl.col("date")).height:
        raise ValueError("fundamental availability exceeds observation date")
    panel = enrich_p0(features, prices, features_config)
    panel = price_features(panel, prices, codes, features_config)
    scores = None
    if weights["variant"] == "P1":
        scores = {}
        for cycle in ("weekly", "monthly", "quarterly"):
            lag = 5 if cycle == "weekly" else 20
            values = (
                0.5 * panel[f"v4_p_reverse{lag}"].to_numpy()
                + (1 - 0.5) * panel["v4_p_momentum120_20"].to_numpy()
            )
            ready = panel["v4_ready"].to_numpy()
            if not np.isfinite(values[ready]).all():
                raise ValueError("original-ready scorer has missing features")
            scores[cycle] = np.where(ready, values, p0_scores(panel, cycle, p0))
    elif weights["variant"] != "P0":
        raise ValueError("unsupported frozen variant")
    history = p0_history(panel, p0, scores, allow_empty=True)
    tables = {"panel": pack_table(panel), "review_actions": pack_table(history.review_actions)}
    for cycle in ("weekly", "monthly", "quarterly"):
        tables[cycle + "_signals"] = pack_table(history.signals[cycle])
        tables[cycle + "_rankings"] = pack_table(history.rankings[cycle])
    return RunnerOutput(schema_version="1", kind="model", tables=tables).model_dump(mode="json")
