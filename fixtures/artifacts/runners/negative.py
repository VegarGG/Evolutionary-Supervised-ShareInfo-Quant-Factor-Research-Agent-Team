"""Bounded negative fixtures. Never run outside the validated isolated runner."""

import json
import os
import socket
import time
from pathlib import Path

import polars as pl
from qfr_core.contracts.execution import RunnerInput, RunnerOutput
from qfr_core.runner_tables import pack_table, unpack_table


def run(value):
    request = RunnerInput.model_validate(value)
    case = json.loads(Path(__file__).with_name("weights.json").read_text())["case"]
    frame = unpack_table(request.tables["prices"]).sort("date", "code")
    if case == "network":
        with socket.socket() as connection:
            connection.settimeout(0.25)
            connection.connect(("203.0.113.1", 80))
    elif case == "filesystem":
        Path("/eval/private-protocol.yaml").read_bytes()
    elif case == "readonly":
        Path("/forbidden-output").write_bytes(b"fixture")
    elif case == "fork":
        # Finite attempt count; every child remains inside the container boundary.
        for _ in range(128):
            pid = os.fork()
            if pid == 0:
                time.sleep(60)
                os._exit(0)
    elif case == "timeout":
        time.sleep(60)
    elif case == "nondeterminism":
        return RunnerOutput(
            schema_version="1",
            kind="factor",
            tables={
                "output": pack_table(
                    frame.select(
                        "date", "code", pl.lit(int.from_bytes(os.urandom(6))).alias("score")
                    )
                )
            },
        ).model_dump(mode="json")
    elif case != "lookahead":
        raise ValueError("unknown negative fixture")
    result = frame.select("date", "code", pl.lit(frame["close"].mean()).alias("score"))
    return RunnerOutput(
        schema_version="1", kind="factor", tables={"output": pack_table(result)}
    ).model_dump(mode="json")
