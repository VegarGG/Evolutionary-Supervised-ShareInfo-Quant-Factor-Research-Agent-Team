"""The research workbench facade (PLAN P1.11).

Computes W0-only metrics for factors and composites on the research snapshot, using
exactly the evaluator's definitions (the same qfr_core metric, backtest and composite
code). It opens data only through the BND-06 guard, reads protocol values only from the
public protocol card, and labels every number research_non_official: the evaluator
never uses these values in decisions.
"""

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, JsonValue

from qfr_core.backtest import BacktestMetrics, BacktestSettings, run_backtest
from qfr_core.composite import CompositePart, ContributionRow, composite, contribution_table
from qfr_core.data.snapshot import DateRange, Snapshot, open_research_snapshot
from qfr_core.dsl import DslAnalysis, DslLimits, compile_expression
from qfr_core.eligibility import Eligibility
from qfr_core.metrics.factor import FactorMetrics, MetricSettings, evaluate_factor
from qfr_core.metrics.fingerprint import Fingerprint, fingerprint, fingerprint_dates
from qfr_core.metrics.matrix import Array, Market
from qfr_core.operators import evaluate

VISIBILITY: Literal["research_non_official"] = "research_non_official"


class FactorReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)
    visibility: Literal["research_non_official"]
    window: Literal["W0"]
    snapshot_id: str
    expression: str
    analysis: DslAnalysis
    metrics: FactorMetrics
    reference_strategy: BacktestMetrics


class CompositeReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    visibility: Literal["research_non_official"]
    window: Literal["W0"]
    snapshot_id: str
    components: list[dict[str, JsonValue]]
    metrics: FactorMetrics
    contributions: list[ContributionRow]
    reference_strategy: BacktestMetrics


@dataclass(frozen=True)
class ComponentInput:
    expression: str
    sign: Literal[1, -1]
    weight: float


class Workbench:
    def __init__(self, snapshot_path: Path, public_card: Path | dict[str, JsonValue]) -> None:
        card = (
            json.loads(public_card.read_text(encoding="utf-8"))
            if isinstance(public_card, Path)
            else public_card
        )
        protocol = card["protocol"]
        assert isinstance(protocol, dict)
        self.snapshot: Snapshot = open_research_snapshot(snapshot_path)
        window = self.snapshot.manifest.research_window
        assert window is not None
        self.window: DateRange = window
        universe, eligibility = protocol["universe"], protocol["eligibility"]
        assert isinstance(universe, dict) and isinstance(eligibility, dict)
        self.eligibility = Eligibility.from_protocol(universe, eligibility)
        dsl = protocol["dsl"]
        assert isinstance(dsl, dict)
        self.limits = DslLimits.from_protocol(dsl)
        self.settings = MetricSettings.from_protocol(protocol)
        self.protocol = protocol
        self.panel = self.snapshot.panel()
        self.market = Market.from_panel(self.panel, self.eligibility, self.snapshot.calendar())
        self._fingerprint_dates: list[date] | None = None

    def values(self, expression: str) -> tuple[Array, DslAnalysis]:
        compiled = compile_expression(expression, self.limits)
        factor = evaluate(self.panel, compiled.tree, self.eligibility)
        return self.market.matrix(factor), compiled.analysis

    def _backtest(self, scores: Array, top_k: int | None, dropout: int | None) -> BacktestMetrics:
        settings = BacktestSettings.from_protocol(self.protocol, top_k, dropout)
        return run_backtest(
            scores, self.market, self.window.start, self.window.end, settings
        ).metrics

    def factor(
        self, expression: str, sign: Literal[1, -1], library: dict[str, str] | None = None
    ) -> FactorReport:
        values, analysis = self.values(expression)
        others = {name: self.values(text)[0] for name, text in (library or {}).items()}
        result = evaluate_factor(
            values, self.market, self.window.start, self.window.end, sign, self.settings, others
        )
        return FactorReport(
            visibility=VISIBILITY,
            window="W0",
            snapshot_id=self.snapshot.snapshot_id,
            expression=expression,
            analysis=analysis,
            metrics=result.metrics,
            reference_strategy=self._backtest(sign * values, None, None),
        )

    def composite(
        self,
        components: list[ComponentInput],
        top_k: int | None = None,
        dropout: int | None = None,
    ) -> CompositeReport:
        parts = [
            CompositePart(f"c{i + 1}", c.sign, c.weight, self.values(c.expression)[0])
            for i, c in enumerate(components)
        ]
        scores = composite(parts, self.market, self.settings)
        start, end = self.window.start, self.window.end
        result = evaluate_factor(scores, self.market, start, end, 1, self.settings)
        _, contributions = contribution_table(parts, self.market, start, end, self.settings)
        return CompositeReport(
            visibility=VISIBILITY,
            window="W0",
            snapshot_id=self.snapshot.snapshot_id,
            components=[
                {"name": p.name, "expression": c.expression, "sign": c.sign, "weight": c.weight}
                for p, c in zip(parts, components, strict=True)
            ],
            metrics=result.metrics,
            contributions=contributions,
            reference_strategy=self._backtest(scores, top_k, dropout),
        )

    def fingerprint_dates(self) -> list[date]:
        if self._fingerprint_dates is None:
            spec = self.protocol["fingerprint"]
            assert isinstance(spec, dict)
            count, seed = spec["dates"], spec["seed"]
            assert isinstance(count, int) and isinstance(seed, int)
            days = np.array(self.market.dates, dtype="datetime64[D]")
            inside = (days >= np.datetime64(self.window.start)) & (
                days <= np.datetime64(self.window.end)
            )
            w0 = [d for d, ok in zip(self.market.dates, inside, strict=True) if ok]
            self._fingerprint_dates = fingerprint_dates(w0, count, seed)
        return self._fingerprint_dates

    def fingerprint(self, expression: str) -> Fingerprint:
        return fingerprint(self.values(expression)[0], self.market, self.fingerprint_dates())
