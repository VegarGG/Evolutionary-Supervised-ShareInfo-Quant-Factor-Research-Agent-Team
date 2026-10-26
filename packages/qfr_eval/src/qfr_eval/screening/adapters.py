"""Kind-specific interpretation of actual outputs, with evaluator-owned grids."""

from dataclasses import dataclass

import polars as pl
from qfr_core.contracts.artifacts import FactorPayload, ModelPayload, StrategyPayload
from qfr_core.contracts.enums import ArtifactKind, ReasonCode
from qfr_core.contracts.execution import RunnerInput, RunnerOutput
from qfr_core.contracts.publication import PublishedArtifact
from qfr_core.pilot.parity import assert_parity
from qfr_core.runner_tables import pack_table, unpack_table

from qfr_eval.backtest.prefix import CausalOutput
from qfr_eval.protocols.models import FrozenProtocol
from qfr_eval.scheduler.models import DevelopmentBehavior
from qfr_eval.screening.coverage import RequiredTable, check_coverage
from qfr_eval.screening.models import CoverageEvidence, KindAdapterProfile
from qfr_eval.screening.pilot import PilotOutputError, validate_pilot_output


def prices_input(request: RunnerInput) -> pl.DataFrame:
    prices = unpack_table(request.tables["prices"]).sort("date", "code")
    if (
        prices.schema.get("date") != pl.Date
        or prices.schema.get("code") != pl.String
        or prices.select(pl.struct("date", "code").is_duplicated().any()).item()
        or prices.select(pl.any_horizontal(pl.col("date", "code").is_null()).any()).item()
    ):
        raise ValueError("input prices require unique complete typed keys")
    return prices


def declared_warmup(artifact: PublishedArtifact) -> int:
    payload = artifact.manifest.payload
    if isinstance(payload, FactorPayload):
        return payload.max_lookback_days
    if isinstance(payload, ModelPayload):
        lookbacks = [r.lookback for r in artifact.manifest.data_requirements if r.table == "prices"]
        if len(lookbacks) != 1 or lookbacks[0] is None:
            raise ValueError("price-panel model requires its declared finite lookback")
        return lookbacks[0]
    return 0


@dataclass(frozen=True)
class OutputAdapter:
    artifact: PublishedArtifact
    profile: KindAdapterProfile
    protocol: FrozenProtocol

    @property
    def pilot_model(self) -> bool:
        return (
            self.profile.adapter == "pilot_rotation_v1"
            and self.artifact.manifest.kind == ArtifactKind.MODEL
        )

    def _frame(self, output: RunnerOutput, request: RunnerInput) -> pl.DataFrame:
        kind = self.artifact.manifest.kind
        if output.kind != kind or set(output.tables) != {"output"}:
            raise PilotOutputError(ReasonCode.DECLARATION_MISMATCH)
        frame = unpack_table(output.tables["output"])
        value = (
            "weight"
            if kind == ArtifactKind.STRATEGY
            else "close"
            if kind == ArtifactKind.DATA_PRODUCT
            else "score"
        )
        if (
            frame.columns != ["date", "code", value]
            or frame.schema["date"] != pl.Date
            or frame.schema["code"] != pl.String
            or not frame.schema[value].is_float()
            or frame.select(pl.struct("date", "code").is_duplicated().any()).item()
        ):
            raise PilotOutputError(ReasonCode.DECLARATION_MISMATCH)
        prices = prices_input(request)
        # Do not accept dates/assets supplied only by the candidate. Warm-up rows
        # may have null scores but still retain their original input keys.
        if (
            not frame.select("date", "code")
            .sort("date", "code")
            .equals(prices.select("date", "code"))
        ):
            raise PilotOutputError(ReasonCode.LOW_COVERAGE)
        if kind == ArtifactKind.DATA_PRODUCT:
            try:
                assert_parity(
                    frame,
                    prices.select("date", "code", "close"),
                    keys=("date", "code"),
                    columns=["close"],
                    atol=self.protocol.atol,
                    rtol=self.protocol.rtol,
                )
            except AssertionError as exc:
                raise PilotOutputError(ReasonCode.DECLARATION_MISMATCH) from exc
        if kind == ArtifactKind.STRATEGY:
            payload = self.artifact.manifest.payload
            assert isinstance(payload, StrategyPayload)
            if (
                frame["weight"].null_count()
                or not frame["weight"].is_finite().all()
                or (frame["weight"] < 0).any()
                or frame.group_by("date")
                .agg(pl.col("weight").sum())
                .select((pl.col("weight") > 1 + self.protocol.atol).any())
                .item()
            ):
                raise PilotOutputError(ReasonCode.DECLARATION_MISMATCH)
            if (
                payload.position_state_rules
                == "equal weights over declared contemporaneous eligible universe"
            ):
                if frame.select(
                    (
                        (pl.col("weight") - 1 / pl.len().over("date")).abs() > self.protocol.atol
                    ).any()
                ).item():
                    raise PilotOutputError(ReasonCode.DECLARATION_MISMATCH)
        return frame.sort("date", "code")

    def project(self, output: RunnerOutput, request: RunnerInput) -> dict[str, CausalOutput]:
        if self.pilot_model:
            return validate_pilot_output(output, request, self.protocol).project()
        frame = self._frame(output, request)
        return {
            "output": CausalOutput(
                frame.with_columns(pl.col("date").alias("_available_date")), ("date", "code")
            )
        }

    def quality(self, output: RunnerOutput, request: RunnerInput) -> CoverageEvidence:
        if self.pilot_model:
            return validate_pilot_output(output, request, self.protocol).quality(self.protocol)
        self._frame(output, request)
        kind = self.artifact.manifest.kind
        prices = (
            prices_input(request)
            .sort("code", "date")
            .with_columns((pl.col("date").cum_count().over("code") - 1).alias("_observation"))
        )
        window = self.protocol.windows["development"]
        grid = prices.filter(
            (pl.col("_observation") >= declared_warmup(self.artifact))
            & pl.col("date").is_between(window.start, window.end)
        ).select("date", "code")
        value = (
            "weight"
            if kind == ArtifactKind.STRATEGY
            else "close"
            if kind == ArtifactKind.DATA_PRODUCT
            else "score"
        )
        required = {
            "output": RequiredTable(
                grid,
                ("date", "code"),
                (value,),
                (value,) if kind in (ArtifactKind.FACTOR, ArtifactKind.MODEL) else (),
            )
        }
        return check_coverage(
            output, required, fixed_position_strategy=kind == ArtifactKind.STRATEGY
        )

    def behavior(
        self, output: RunnerOutput, request: RunnerInput, scope: str
    ) -> DevelopmentBehavior:
        if self.quality(output, request).status != "passed":
            raise ValueError("incomplete development outputs cannot be duplicate references")
        window = self.protocol.windows["development"]
        tables = {}
        scores: dict[str, list[str]] = {}
        for name, projected in self.project(output, request).items():
            frame = projected.frame.filter(
                pl.col("_available_date").is_between(window.start, window.end)
            ).sort(list(projected.keys))
            tables[name] = pack_table(frame)
            scores[name] = [c for c in ("score", "factor_score") if c in frame.columns]
        return DevelopmentBehavior(
            schema_version="1",
            semantic_scope_sha256=scope,
            complete_original_eligible_outputs=True,
            tables=tables,
            score_columns=scores,
        )


def replay_strategy(
    output: RunnerOutput, request: RunnerInput, profile: KindAdapterProfile
) -> pl.DataFrame:
    """Replay submitted target weights at next closes; retain immature decisions.

    This contract fixture's private quality ledger is not a financial trial or a
    new pilot metric. Cash is included in one-way turnover; holdings drift between
    executions. No evaluator-selected replacement portfolio is constructed.
    """
    prices = prices_input(request)
    weights = unpack_table(output.tables["output"])
    dates = sorted(prices["date"].unique().to_list())
    lookup = {(d, c): p for d, c, p in prices.select("date", "code", "close").iter_rows()}
    old: dict[str, float] = {}
    rows = []
    for i, day in enumerate(dates):
        target = dict(weights.filter(pl.col("date") == day).select("code", "weight").iter_rows())
        if i + 2 >= len(dates):
            rows.append(
                (
                    day,
                    dates[i + 1] if i + 1 < len(dates) else None,
                    None,
                    None,
                    None,
                    None,
                    "unmatured",
                )
            )
            continue
        entry, exit_day = dates[i + 1], dates[i + 2]
        buy_sell = sum(abs(target.get(c, 0) - old.get(c, 0)) for c in target.keys() | old.keys())
        turnover = (buy_sell + abs(sum(old.values()) - sum(target.values()))) / 2
        relatives = {}
        for code in target:
            a, b = lookup.get((entry, code)), lookup.get((exit_day, code))
            if a is None or b is None or a <= 0 or b <= 0:
                raise ValueError("missing strategy execution price; no silent row deletion")
            relatives[code] = b / a
        gross = sum(target[c] * (relatives[c] - 1) for c in target)
        cost = turnover * profile.strategy_cost_bps / 10000
        wealth = 1 + gross
        if wealth <= 0:
            raise ValueError("invalid strategy wealth")
        old = {c: target[c] * relatives[c] / wealth for c in target}
        rows.append((day, entry, exit_day, gross, turnover, gross - cost, "mature"))
    return pl.DataFrame(
        rows,
        schema={
            "date": pl.Date,
            "entry_date": pl.Date,
            "exit_date": pl.Date,
            "gross_return": pl.Float64,
            "one_way_turnover": pl.Float64,
            "net_return": pl.Float64,
            "status": pl.String,
        },
        orient="row",
    )
