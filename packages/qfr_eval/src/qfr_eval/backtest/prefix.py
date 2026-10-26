"""Causal prefix checks for trusted built-ins; not an executable sandbox."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import polars as pl
from pydantic import NonNegativeInt
from qfr_core.contracts.base import Contract, Sha256, Text
from qfr_core.data_layer.snapshots import logical_hash
from qfr_core.pilot.parity import assert_parity

from qfr_eval.backtest.schedule import period_end
from qfr_eval.backtest.scorers import ScorerSpec, built_in_history
from qfr_eval.protocols.models import FrozenProtocol


@dataclass(frozen=True)
class CausalOutput:
    frame: pl.DataFrame
    keys: tuple[str, ...]


class PrefixCheck(Contract):
    cutoff: date
    compared_cells: NonNegativeInt
    full_prefix_hashes: dict[Text, Sha256]
    rebuilt_hashes: dict[Text, Sha256]


def slice_inputs(tables: dict[str, pl.DataFrame], cutoff: date) -> dict[str, pl.DataFrame]:
    result = {}
    for name, frame in tables.items():
        for column in ("date", "available_date"):
            if column in frame.columns:
                if frame.schema[column] != pl.Date:
                    raise ValueError("prefix inputs require canonical dates")
                frame = frame.filter(pl.col(column).is_not_null() & (pl.col(column) <= cutoff))
        result[name] = frame
    return result


def check_prefixes(
    tables: dict[str, pl.DataFrame],
    build: Callable[[dict[str, pl.DataFrame]], dict[str, CausalOutput]],
    cutoffs: list[date],
    *,
    atol: float,
    rtol: float,
) -> list[PrefixCheck]:
    if not cutoffs or len(set(cutoffs)) != len(cutoffs):
        raise ValueError("explicit unique prefix cutoffs required")
    complete = build(tables)
    checks = []
    for cutoff in cutoffs:
        rebuilt = build(slice_inputs(tables, cutoff))
        if set(complete) != set(rebuilt):
            raise AssertionError("failed:lookahead output tables changed")
        cells = 0
        hashes, prefix_hashes = {}, {}
        for name, output in complete.items():
            prefix = rebuilt[name]
            expected = output.frame.filter(pl.col("_available_date") <= cutoff)
            actual = prefix.frame
            if (
                output.keys != prefix.keys
                or expected.schema != actual.schema
                or actual["_available_date"].null_count()
                or (actual["_available_date"] > cutoff).any()
            ):
                raise AssertionError(f"failed:lookahead {name} schema or availability changed")
            exact = [
                c
                for c in actual.columns
                if c not in output.keys
                and (not actual.schema[c].is_float() or c in {"rank", "actual_rank"})
            ]
            numeric = [c for c in actual.columns if c not in output.keys and c not in exact]
            try:
                cells += assert_parity(
                    actual, expected, keys=output.keys, columns=exact, atol=0, rtol=0
                )
                cells += assert_parity(
                    actual, expected, keys=output.keys, columns=numeric, atol=atol, rtol=rtol
                )
            except AssertionError as error:
                raise AssertionError(f"failed:lookahead {name} at {cutoff}: {error}") from error
            hashes[name] = logical_hash(actual, output.keys)
            prefix_hashes[name] = logical_hash(expected, output.keys)
        checks.append(
            PrefixCheck(
                cutoff=cutoff,
                compared_cells=cells,
                full_prefix_hashes=prefix_hashes,
                rebuilt_hashes=hashes,
            )
        )
    return checks


def pilot_prefix_builder(
    protocol: FrozenProtocol, spec: ScorerSpec | None
) -> Callable[[dict[str, pl.DataFrame]], dict[str, CausalOutput]]:
    def build(tables: dict[str, pl.DataFrame]) -> dict[str, CausalOutput]:
        panel, history = built_in_history(
            tables["features"],
            tables["prices_daily"],
            tables["universe"]["code"].to_list(),
            protocol,
            spec=spec,
            allow_empty_history=True,
        )
        outputs = {
            "features": CausalOutput(
                panel.with_columns(pl.col("date").alias("_available_date")), ("date", "code")
            )
        }
        for cycle, frame in history.signals.items():
            available = (
                pl.col("date")
                if cycle == "weekly"
                else pl.col("date").map_elements(period_end, return_dtype=pl.Date)
            )
            outputs[cycle] = CausalOutput(
                frame.with_columns(available.alias("_available_date")), ("date", "code")
            )
        actions = history.review_actions
        if actions.is_empty() and not actions.columns:
            actions = pl.DataFrame(
                schema={
                    "date": pl.Date,
                    "quarter_signal": pl.Date,
                    "removed": pl.String,
                    "added": pl.String,
                    "action": pl.String,
                }
            )
        outputs["review_actions"] = CausalOutput(
            actions.with_columns(
                pl.col("date")
                .map_elements(period_end, return_dtype=pl.Date)
                .alias("_available_date")
            ),
            ("date", "removed"),
        )
        return outputs

    return build
