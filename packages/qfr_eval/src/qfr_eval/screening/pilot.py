"""Validate actual runner scores against the original pilot business contract.

Quarterly review events depend on the candidate's holdings. Their required rows
must be rebuilt from its submitted scores and the frozen rules, not copied from
P0's realized trades. Latest rankings are derived snapshots, not time series.
"""

from dataclasses import dataclass

import polars as pl
from qfr_core.contracts.enums import ArtifactKind, ReasonCode
from qfr_core.contracts.execution import RunnerInput, RunnerOutput, RunnerTable
from qfr_core.metrics.core import Array
from qfr_core.pilot.baseline import Cycle, P0History, p0_history, p0_signals
from qfr_core.pilot.parity import assert_parity
from qfr_core.runner_tables import pack_table, unpack_table

from qfr_eval.backtest.prefix import CausalOutput
from qfr_eval.backtest.schedule import period_end
from qfr_eval.backtest.scorers import built_in_history
from qfr_eval.protocols.models import FrozenProtocol
from qfr_eval.screening.coverage import RequiredTable, check_coverage
from qfr_eval.screening.models import CoverageEvidence

CYCLES: tuple[Cycle, ...] = ("weekly", "monthly", "quarterly")


class PilotOutputError(ValueError):
    def __init__(self, code: ReasonCode):
        super().__init__(code.value)
        self.code = code


def actions_frame(frame: pl.DataFrame) -> pl.DataFrame:
    if not frame.columns and frame.is_empty():
        return pl.DataFrame(
            schema={
                "date": pl.Date,
                "quarter_signal": pl.Date,
                "removed": pl.String,
                "added": pl.String,
                "action": pl.String,
            }
        )
    return frame


def _same(
    actual: pl.DataFrame, expected: pl.DataFrame, keys: tuple[str, ...], protocol: FrozenProtocol
) -> None:
    if actual.schema != expected.schema:
        raise PilotOutputError(ReasonCode.DECLARATION_MISMATCH)
    exact = [
        c
        for c in expected.columns
        if c not in keys and (not expected.schema[c].is_float() or c == "rank")
    ]
    numeric = [c for c in expected.columns if c not in keys and c not in exact]
    try:
        assert_parity(actual, expected, keys=keys, columns=exact, atol=0, rtol=0)
        assert_parity(
            actual, expected, keys=keys, columns=numeric, atol=protocol.atol, rtol=protocol.rtol
        )
    except AssertionError as exc:
        raise PilotOutputError(ReasonCode.DECLARATION_MISMATCH) from exc


@dataclass(frozen=True)
class PilotArtifactOutput:
    panel: pl.DataFrame
    history: P0History
    base_scores: dict[Cycle, pl.DataFrame]
    original_grids: dict[Cycle, pl.DataFrame]

    def quality(self, protocol: FrozenProtocol) -> CoverageEvidence:
        window = protocol.windows["development"]
        required: dict[str, RequiredTable] = {}
        output: dict[str, RunnerTable] = {}
        for cycle in CYCLES:
            grid = self.original_grids[cycle].filter(
                pl.col("date").is_between(window.start, window.end)
            )
            required[cycle] = RequiredTable(
                grid, ("date", "code"), ("factor_score",), ("factor_score",)
            )
            output[cycle] = pack_table(self.base_scores[cycle])
        return check_coverage(
            RunnerOutput(schema_version="1", kind=ArtifactKind.MODEL, tables=output),
            required,
            fixed_position_strategy=False,
        )

    def project(self) -> dict[str, CausalOutput]:
        result = {
            "panel": CausalOutput(
                self.panel.with_columns(pl.col("date").alias("_available_date")), ("date", "code")
            )
        }
        for cycle, frame in self.history.signals.items():
            available = (
                pl.col("date")
                if cycle == "weekly"
                else pl.col("date").map_elements(period_end, return_dtype=pl.Date)
            )
            result[cycle] = CausalOutput(
                frame.with_columns(available.alias("_available_date")), ("date", "code")
            )
        result["review_actions"] = CausalOutput(
            self.history.review_actions.with_columns(
                pl.col("date")
                .map_elements(period_end, return_dtype=pl.Date)
                .alias("_available_date")
            ),
            ("date", "removed"),
        )
        return result


def validate_pilot_output(
    output: RunnerOutput, request: RunnerInput, protocol: FrozenProtocol
) -> PilotArtifactOutput:
    names = {"panel", "review_actions"} | {
        c + suffix for c in CYCLES for suffix in ("_signals", "_rankings")
    }
    if output.kind != "model" or set(output.tables) != names:
        raise PilotOutputError(ReasonCode.LOW_COVERAGE)
    inputs = {name: unpack_table(table) for name, table in request.tables.items()}
    panel, _ = built_in_history(
        inputs["features"],
        inputs["prices"],
        sorted(inputs["universe"]["code"].unique().to_list()),
        protocol,
        allow_empty_history=True,
    )
    frames = {name: unpack_table(table) for name, table in output.tables.items()}
    _same(frames["panel"], panel, ("date", "code"), protocol)
    original_grids: dict[Cycle, pl.DataFrame] = {}
    scores: dict[Cycle, Array] = {}
    submitted: dict[Cycle, pl.DataFrame] = {}
    panel_keys = panel.select("date", "code").with_row_index("_position")
    for cycle in CYCLES:
        grid = p0_signals(panel, cycle, protocol.p0, allow_empty=True).select("date", "code")
        original_grids[cycle] = grid
        frame = frames[cycle + "_signals"]
        if cycle == "quarterly":
            if "event_type" not in frame.columns:
                raise PilotOutputError(ReasonCode.DECLARATION_MISMATCH)
            frame = frame.filter(pl.col("event_type") == "quarter_reset")
        if (
            not {"date", "code", "factor_score"} <= set(frame.columns)
            or frame.select(pl.struct("date", "code").is_duplicated().any()).item()
        ):
            raise PilotOutputError(ReasonCode.DECLARATION_MISMATCH)
        required = grid.join(
            frame.select("date", "code", "factor_score"),
            on=["date", "code"],
            how="left",
            validate="1:1",
        )
        if (
            required["factor_score"].null_count()
            or not required["factor_score"].is_finite().all()
            or frame.height != grid.height
        ):
            raise PilotOutputError(ReasonCode.LOW_COVERAGE)
        submitted[cycle] = required
        indexed = panel_keys.join(required, on=["date", "code"], how="left", validate="1:1").sort(
            "_position"
        )
        scores[cycle] = indexed["factor_score"].to_numpy()
    # Rebuild only the fixed ranking/position/review rules from the actual
    # candidate's scores. No built-in candidate replaces or supplies those scores.
    expected = p0_history(panel, protocol.p0, scores, allow_empty=True)
    signals, rankings = {}, {}
    for cycle in CYCLES:
        signals[cycle], rankings[cycle] = frames[cycle + "_signals"], frames[cycle + "_rankings"]
        _same(signals[cycle], expected.signals[cycle], ("date", "code"), protocol)
        _same(rankings[cycle], expected.rankings[cycle], ("date", "code"), protocol)
    actions = actions_frame(frames["review_actions"])
    _same(actions, actions_frame(expected.review_actions), ("date", "removed"), protocol)
    return PilotArtifactOutput(
        panel, P0History(signals, rankings, actions), submitted, original_grids
    )
