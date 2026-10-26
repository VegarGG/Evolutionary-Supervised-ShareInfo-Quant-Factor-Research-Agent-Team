"""Research-only, in-sample facade over the shared deterministic metric definitions."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Literal

import numpy as np
import polars as pl

from qfr_core.contracts.data import DateRange, SnapshotManifest
from qfr_core.data_layer.snapshots import Snapshot, canonical_json
from qfr_core.dsl.language import DSLConfig, canonical_hash, parse
from qfr_core.dsl.operators import evaluate
from qfr_core.metrics.core import MetricConfig, StockMetrics, fingerprint, stock_metrics
from qfr_core.metrics.pilot import PilotMetricConfig, PilotMetrics, pilot_metrics


@dataclass(frozen=True)
class WorkbenchResult:
    snapshot_id: str
    window: DateRange
    expression_hash: str
    settings_hash: str
    scores: pl.DataFrame
    metrics: StockMetrics
    fingerprint: pl.DataFrame
    official: Literal[False] = False
    warning: Literal["in_sample_optimistic"] = "in_sample_optimistic"


@dataclass(frozen=True)
class PilotWorkbenchResult:
    snapshot_id: str
    window: DateRange
    metrics: PilotMetrics
    official: Literal[False] = False
    warning: Literal["in_sample_optimistic"] = "in_sample_optimistic"


class Workbench:
    def __init__(self, root: Path, window: DateRange):
        manifest = SnapshotManifest.model_validate_json((root / "manifest.json").read_bytes())
        if manifest.zone != "research" or manifest.research_cutoff is None:
            raise ValueError("workbench requires a research-zone snapshot")
        if window.end > min(manifest.research_cutoff, manifest.as_of):
            raise ValueError("W0 window extends beyond the research snapshot cutoff")
        self.snapshot = Snapshot.load(root)
        self.window = window
        self.tables = self.snapshot.slice(window.end)

    def stock(
        self,
        expression: str,
        dsl: DSLConfig,
        metrics: MetricConfig,
        *,
        fingerprint_seed: int,
        library: Mapping[str, str] | None = None,
    ) -> WorkbenchResult:
        if self.snapshot.manifest.profile != "stock_daily_v1":
            raise ValueError("stock workbench requires the stock profile")
        panel = self.tables["panel"].with_columns(
            (
                pl.col(metrics.universe_column)
                & (pl.col("listed_days") >= metrics.min_listed_days)
                & ~pl.col("is_suspended")
            ).alias("eligible")
        )
        node = parse(expression, dsl)
        scores = evaluate(node, panel, dsl, eligible_column="eligible")
        factors = {
            name: evaluate(value, panel, dsl, eligible_column="eligible")
            for name, value in (library or {}).items()
        }
        result = stock_metrics(
            panel, scores, metrics, start=self.window.start, end=self.window.end, library=factors
        )
        w0_scores = scores.filter(pl.col("date").is_between(self.window.start, self.window.end))
        settings = {
            "dsl": dsl.model_dump(mode="json"),
            "metrics": metrics.model_dump(mode="json"),
            "fingerprint_seed": fingerprint_seed,
        }
        return WorkbenchResult(
            self.snapshot.manifest.snapshot_id,
            self.window,
            canonical_hash(expression, dsl),
            sha256(canonical_json(settings)).hexdigest(),
            w0_scores,
            result,
            fingerprint(
                w0_scores.join(
                    panel.filter(pl.col("eligible")).select("instrument", "date"),
                    on=["instrument", "date"],
                    validate="1:1",
                ),
                cutoff=self.window.end,
                seed=fingerprint_seed,
                dates=metrics.fingerprint_dates,
            ),
        )

    def pilot_period(
        self,
        predictions: pl.DataFrame,
        *,
        decision: date,
        entry: date,
        exit: date,
        benchmark_code: str,
        config: PilotMetricConfig,
    ) -> PilotWorkbenchResult:
        """An explicitly supplied, already-mature W0 interval; no protocol scheduling.

        The owner/caller chooses the interval. This does not create publication,
        execution or forward-observation evidence.
        """
        if self.snapshot.manifest.profile != "pilot_industry_v1":
            raise ValueError("pilot workbench requires the pilot profile")
        if not self.window.start <= decision < entry < exit <= self.window.end:
            raise ValueError("pilot interval must be mature and entirely inside W0")
        prices = self.tables["prices_daily"]
        entered = prices.filter(pl.col("date") == entry).select(
            "code", pl.col("close").alias("entry")
        )
        ended = prices.filter(pl.col("date") == exit).select("code", pl.col("close").alias("exit"))
        realized = entered.join(ended, on="code", validate="1:1").with_columns(
            (pl.col("exit") / pl.col("entry") - 1).alias("return")
        )
        benchmark = realized.filter(pl.col("code") == benchmark_code)
        if benchmark.height != 1:
            raise ValueError("benchmark missing from mature W0 interval")
        industries = self.tables["universe"].select("code", "industry")
        result = pilot_metrics(
            predictions,
            realized.join(industries, on="code", validate="1:1").select(
                "code", "industry", "return"
            ),
            benchmark_return=float(benchmark["return"][0]),
            config=config,
        )
        return PilotWorkbenchResult(self.snapshot.manifest.snapshot_id, self.window, result)

    def prefix_check(
        self,
        expression: str,
        dsl: DSLConfig,
        *,
        cuts: Sequence[date],
        atol: float,
        rtol: float,
    ) -> None:
        if atol < 0 or rtol < 0 or not cuts:
            raise ValueError("explicit nonnegative tolerances and cut dates required")
        panel = self.tables["panel"]
        full = evaluate(expression, panel, dsl)
        for cut in cuts:
            if not self.window.start <= cut <= self.window.end:
                raise ValueError("prefix cut outside W0")
            prefix = evaluate(expression, panel.filter(pl.col("date") <= cut), dsl)
            expected = full.filter(pl.col("date") <= cut)
            if not prefix.select("instrument", "date").equals(
                expected.select("instrument", "date")
            ):
                raise ValueError(f"prefix keys differ at {cut}")
            if not np.allclose(
                prefix["value"].to_numpy(),
                expected["value"].to_numpy(),
                atol=atol,
                rtol=rtol,
                equal_nan=True,
            ):
                raise ValueError(f"prefix values differ at {cut}")

    def profile(self) -> dict[str, dict[str, object]]:
        return {
            name: {
                "rows": frame.height,
                "columns": {key: str(dtype) for key, dtype in frame.schema.items()},
                "nulls": frame.null_count().to_dicts()[0],
            }
            for name, frame in self.tables.items()
        }
