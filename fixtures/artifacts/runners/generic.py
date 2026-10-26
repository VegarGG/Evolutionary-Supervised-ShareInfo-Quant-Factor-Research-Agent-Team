"""Small declared kind fixtures; no training, network or evaluator access."""

import json
from pathlib import Path

import polars as pl
from qfr_core.contracts.execution import RunnerInput, RunnerOutput
from qfr_core.runner_tables import pack_table, unpack_table


def run(value):
    request = RunnerInput.model_validate(value)
    weights = json.loads(Path(__file__).with_name("weights.json").read_text())
    kind = weights["kind"]
    frame = unpack_table(request.tables["prices"]).sort("code", "date")
    if kind == "factor":
        result = frame.select("date", "code", pl.col("close").shift(1).over("code").alias("score"))
    elif kind == "model":
        result = frame.select(
            "date",
            "code",
            (
                weights["coefficient"]
                * (pl.col("close") / pl.col("close").shift(1).over("code") - 1)
            ).alias("score"),
        )
    elif kind == "strategy":
        result = frame.select("date", "code", (1.0 / pl.len().over("date")).alias("weight"))
    elif kind == "data_product":
        result = frame.select("date", "code", "close")
    else:
        raise ValueError("unsupported fixture kind")
    return RunnerOutput(
        schema_version="1", kind=kind, tables={"output": pack_table(result.sort("date", "code"))}
    ).model_dump(mode="json")
