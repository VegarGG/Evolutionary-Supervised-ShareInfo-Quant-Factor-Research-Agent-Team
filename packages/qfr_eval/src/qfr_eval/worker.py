"""eval-worker (PLAN Sections 8.4 to 8.10): fingerprints, screening, W1, W2 and the holdout.

A worker claims one job at a time from the eval_db queue. An evaluation job screens the
version and, if it passes, runs W1; a w2 job runs W2 validation and the Ladder; a holdout
job runs the private W3 check once per version. Everything a run produced is written in
one transaction: runs, full-precision metrics, series files, the official record, the
trial-ledger row, burn accounting and the report queued for release. A strategy is
measured on the composite of its components, which the worker recomputes from the
evaluator's own copy of each component's expression (Section 7.8). Workers hold no LLM
keys and have no network route outside eval_net; measurement uses fixed seeds and no
wall clock.
"""

import os
import time
import traceback
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, cast
from uuid import UUID

import numpy as np
import polars as pl
from pydantic import TypeAdapter
from qfr_core.config import RuntimeSettings, canonical_json
from qfr_core.contracts import FactorManifest, Manifest, ReasonCode, StrategyManifest
from qfr_core.correlation import bind, current
from qfr_core.data.snapshot import read_snapshot
from qfr_core.dsl import DslError, compile_expression
from qfr_core.ids import uuid7
from qfr_core.logging import JsonLogger
from qfr_core.metrics.fingerprint import fingerprint_dates, fingerprint_rows
from qfr_core.metrics.matrix import Array, Market
from sqlalchemy import bindparam, text
from sqlalchemy.engine import Connection

from qfr_eval import queue
from qfr_eval.compute import (
    ComputeOutput,
    ComputeRequest,
    ComputeResult,
    InlineRunner,
    ProbeResult,
    Runner,
    SubprocessRunner,
)
from qfr_eval.configs import ActiveState, Window, active_state, record_event
from qfr_eval.contracts import OfficialRecord
from qfr_eval.plugins import (
    FactorPlugin,
    LazyLibrary,
    StageOutcome,
    StrategyPlugin,
    ladder_step,
    plugin_for,
    probe_cuts,
    quantize,
    results_hash,
    run_seed,
)
from qfr_eval.reports import queue_report
from qfr_eval.runtime import (
    Clock,
    Database,
    EvalConfig,
    EvalEnvironment,
    SystemClock,
    eval_config,
    service_logger,
    start_heartbeat,
)
from qfr_eval.store import ArtifactStore

SERVICE = "eval-worker"
# The discriminated union is passed untyped; the annotation carries the parsed type.
MANIFEST: TypeAdapter[Manifest] = TypeAdapter(cast(Any, Manifest))
GB = 1024**3
WindowName = Literal["W1", "W2", "W3"]


@dataclass(frozen=True)
class LibraryMember:
    version_id: str
    uri: str
    sha256: str


@dataclass(frozen=True)
class Component:
    """A strategy component as the evaluator knows it: its own copy of the expression."""

    version_id: str
    kind: str
    state: str
    expression: str | None


@dataclass(frozen=True)
class EvaluationOutcome:
    seed: int
    complexity: int | None
    screening: StageOutcome
    w1: StageOutcome | None
    w1_values: Array | None  # The version's W1 rows (a strategy's composite), for the library.
    library: list[LibraryMember]


@dataclass(frozen=True)
class WindowOutcome:
    """A W2 or W3 run: the stage outcome and the window's rows of the version's values."""

    seed: int
    outcome: StageOutcome
    values: Array
    columns: Any = field(default=None)


class MarketCache:
    """One verified full snapshot and its Market per worker process."""

    def __init__(self, full_dir: Path) -> None:
        self.full_dir = full_dir
        self._key: tuple[str, str] | None = None
        self._market: Market | None = None

    def get(self, snapshot_id: str, plugin: FactorPlugin) -> Market:
        key = (snapshot_id, canonical_json(plugin.eligibility.model_dump(mode="json")))
        if self._key != key or self._market is None:
            snapshot = read_snapshot(self.full_dir / snapshot_id)
            self._market = Market.from_panel(
                snapshot.panel(), plugin.eligibility, snapshot.calendar()
            )
            self._key = key
        return self._market


def read_components(conn: Connection, manifest: Manifest) -> dict[str, Component]:
    """The evaluator's intake rows for a strategy's components (none for a factor)."""
    if not isinstance(manifest, StrategyManifest):
        return {}
    ids = [c.version_id for c in manifest.implementation.components]
    rows = conn.execute(
        text(
            "SELECT version_id, kind, state, manifest FROM eval.intake WHERE version_id IN :ids"
        ).bindparams(bindparam("ids", expanding=True)),
        {"ids": ids},
    ).all()
    out = {}
    for row in rows:
        body = (row.manifest or {}).get("manifest") or {}
        expression = (body.get("implementation") or {}).get("expression")
        out[str(row.version_id)] = Component(
            str(row.version_id),
            row.kind,
            row.state,
            expression if isinstance(expression, str) else None,
        )
    return out


def _merge_results(results: list[ComputeResult]) -> ComputeResult:
    """One screening view of a strategy's component computations: CPU adds up, the peak
    is the largest, and each probe cut sums its components' comparisons."""
    probes: dict[Any, ProbeResult] = {}
    for result in results:
        for probe in result.probes:
            seen = probes.get(probe.cut)
            if seen is None:
                probes[probe.cut] = probe
                continue
            worst = max(seen.max_abs_diff or 0.0, probe.max_abs_diff or 0.0)
            probes[probe.cut] = ProbeResult(
                cut=probe.cut,
                compared=seen.compared + probe.compared,
                mismatches=seen.mismatches + probe.mismatches,
                max_abs_diff=worst,
            )
    return ComputeResult(
        status="ok",
        cpu_seconds=sum(r.cpu_seconds or 0.0 for r in results),
        probe_cpu_seconds=sum(r.probe_cpu_seconds or 0.0 for r in results),
        peak_rss_bytes=max((r.peak_rss_bytes or 0 for r in results), default=0),
        probes=[probes[c] for c in sorted(probes)],
        instruments=results[0].instruments if results else None,
    )


class Evaluator:
    """The measurement itself; used by the worker, the simulation engine and
    `qfr eval reproduce`."""

    def __init__(self, env: EvalEnvironment, runner: Runner, markets: MarketCache) -> None:
        self.env, self.runner, self.markets = env, runner, markets
        self.store = ArtifactStore(env.store_dir)

    def _request(
        self,
        plugin: FactorPlugin,
        snapshot_id: str,
        expression: str,
        rows: list[int],
        cuts: list[int],
        load_cpu_seconds: float,
    ) -> ComputeRequest:
        screening = plugin.screening
        output = self.store.scratch() / f"{uuid7()}.npy"
        return ComputeRequest(
            snapshot_path=str(self.env.full_snapshot_dir / snapshot_id),
            expression=expression,
            dsl=dict(plugin.protocol["dsl"]),
            eligibility=plugin.eligibility,
            rows=rows,
            probe_cuts=cuts,
            tolerance=float(screening["prefix_tolerance"]),
            cpu_seconds=float(screening["cpu_seconds"]),
            memory_bytes=int(float(screening["memory_gb"]) * GB),
            load_cpu_seconds=load_cpu_seconds,
            output_path=str(output),
        )

    def compute(
        self,
        plugin: FactorPlugin,
        manifest: Manifest,
        components: Mapping[str, Component],
        snapshot_id: str,
        market: Market,
        rows: list[int],
        cuts: list[int],
        load_cpu_seconds: float,
    ) -> tuple[ComputeOutput, dict[str, Array]]:
        """The version's values at rows. A strategy's components are computed one by one
        from their expressions and combined; the second item holds each component's
        values on the whole market (rows filled), for the contribution table."""
        if isinstance(manifest, FactorManifest):
            request = self._request(
                plugin, snapshot_id, manifest.implementation.expression, rows, cuts,
                load_cpu_seconds,
            )  # fmt: skip
            return self.runner.run(request), {}
        assert isinstance(manifest, StrategyManifest) and isinstance(plugin, StrategyPlugin)
        results: list[ComputeResult] = []
        values: dict[str, Array] = {}
        for item in manifest.implementation.components:
            component = components.get(str(item.version_id))
            if component is None or component.expression is None:
                raise RuntimeError("a strategy component has no expression in intake")
            request = self._request(
                plugin, snapshot_id, component.expression, rows, cuts, load_cpu_seconds
            )
            output = self.runner.run(request)
            if output.result.status != "ok" or output.values is None:
                return output, {}
            results.append(output.result)
            full = np.full(market.shape, np.nan)
            full[rows] = output.values
            values[str(item.version_id)] = full
        combined = plugin.compose(values, market)
        return ComputeOutput(_merge_results(results), combined[rows]), values

    def fingerprint(
        self,
        manifest: Manifest,
        protocol: dict[str, Any],
        windows: dict[str, Window],
        snapshot_id: str,
        load_cpu_seconds: float,
        components: Mapping[str, Component] | None = None,
    ) -> tuple[Any, str | None]:
        plugin = plugin_for(protocol, manifest)
        market = self.markets.get(snapshot_id, plugin)
        spec = protocol["fingerprint"]
        w0 = [d for d in market.dates if windows["W0"].start <= d <= windows["W0"].end]
        dates = fingerprint_dates(w0, int(spec["dates"]), int(spec["seed"]))
        index = {d: i for i, d in enumerate(market.dates)}
        rows = [index[d] for d in dates]
        output, _ = self.compute(
            plugin, manifest, components or {}, snapshot_id, market, rows, [], load_cpu_seconds
        )
        if output.result.status != "ok" or output.values is None:
            return None, output.result.error_code or output.result.status
        return fingerprint_rows(
            output.values, market.eligible[rows], market.instruments, dates
        ), None

    def _static(
        self,
        plugin: FactorPlugin,
        manifest: Manifest,
        components: Mapping[str, Component],
    ) -> tuple[list[ReasonCode], int | None]:
        if isinstance(manifest, FactorManifest):
            return plugin.static_checks(manifest)
        assert isinstance(plugin, StrategyPlugin)
        reasons = plugin.component_checks({k: (c.kind, c.state) for k, c in components.items()})
        if reasons:
            return reasons, None
        complexity = 0
        for component in components.values():
            try:
                compiled = compile_expression(component.expression or "", plugin.limits)
            except DslError:
                return [ReasonCode.COMPONENT_INVALID], None
            complexity += compiled.analysis.complexity
        return [], complexity

    def evaluate(
        self,
        manifest: Manifest,
        version_id: str,
        protocol: dict[str, Any],
        windows: dict[str, Window],
        snapshot_id: str,
        library: list[LibraryMember],
        load_cpu_seconds: float,
        seed: int | None = None,
        components: Mapping[str, Component] | None = None,
    ) -> EvaluationOutcome:
        plugin = plugin_for(protocol, manifest)
        components = components or {}
        seed = run_seed(int(protocol["fingerprint"]["seed"]), version_id) if seed is None else seed
        reasons, complexity = self._static(plugin, manifest, components)
        if reasons:
            outcome = StageOutcome(
                "screening",
                False,
                reasons,
                {},
                {"status": "FAIL", "reasons": [r.value for r in reasons], "static": True},
            )
            return EvaluationOutcome(seed, complexity, outcome, None, None, [])
        market = self.markets.get(snapshot_id, plugin)
        w1 = windows["W1"]
        first, last = market.window(w1.start, w1.end)
        cuts = probe_cuts((first, last), int(plugin.screening["prefix_probe_dates"]), seed)
        rows = list(range(first, last + 1))
        output, component_values = self.compute(
            plugin, manifest, components, snapshot_id, market, rows, cuts, load_cpu_seconds
        )
        if output.result.status == "error":
            raise RuntimeError(f"computation failed: {output.result.error_type}")
        screening = plugin.screen(output.result, output.values, market, (first, last))
        if not screening.passed or output.values is None:
            return EvaluationOutcome(seed, complexity, screening, None, None, [])
        factor = np.full(market.shape, np.nan)
        factor[first : last + 1] = output.values
        instruments = len(market.instruments)

        def loader(member: LibraryMember) -> Callable[[], Array]:
            return lambda: self.store.read_window_values(member.uri, member.sha256, instruments)

        lazy = LazyLibrary({m.version_id: loader(m) for m in library})
        coverage = screening.metrics.get("coverage")
        if isinstance(plugin, StrategyPlugin):
            assert isinstance(manifest, StrategyManifest)
            w1_outcome, _ = plugin.run_w1(
                manifest, factor, market, w1.start, w1.end, lazy, coverage,
                int(complexity or 0), component_values,
            )  # fmt: skip
        else:
            assert isinstance(manifest, FactorManifest)
            w1_outcome, _ = plugin.run_w1(
                manifest, factor, market, w1.start, w1.end, lazy, coverage, int(complexity or 0)
            )
        w1_outcome.summary["library"]["members"] = [
            {"version_id": m.version_id, "uri": m.uri, "sha256": m.sha256} for m in library
        ]
        return EvaluationOutcome(seed, complexity, screening, w1_outcome, output.values, library)

    def window_values(
        self,
        manifest: Manifest,
        protocol: dict[str, Any],
        snapshot_id: str,
        window: Window,
        load_cpu_seconds: float,
        components: Mapping[str, Component] | None = None,
    ) -> tuple[Market, int, int, Array]:
        """The version's values on one window's rows (no probes: screening ran on W1)."""
        plugin = plugin_for(protocol, manifest)
        market = self.markets.get(snapshot_id, plugin)
        first, last = market.window(window.start, window.end)
        rows = list(range(first, last + 1))
        output, _ = self.compute(
            plugin, manifest, components or {}, snapshot_id, market, rows, [], load_cpu_seconds
        )
        if output.result.status != "ok" or output.values is None:
            raise RuntimeError(
                f"computation failed on a later window: {output.result.status} "
                f"{output.result.error_code or output.result.limit or ''}".strip()
            )
        return market, first, last, output.values

    def run_window(
        self,
        manifest: Manifest,
        version_id: str,
        protocol: dict[str, Any],
        windows: dict[str, Window],
        snapshot_id: str,
        window_name: Literal["W2", "W3"],
        load_cpu_seconds: float,
        seed: int | None = None,
        components: Mapping[str, Component] | None = None,
    ) -> WindowOutcome:
        """W2 validation or the private W3 holdout of a version that passed W1."""
        plugin = plugin_for(protocol, manifest)
        seed = run_seed(int(protocol["fingerprint"]["seed"]), version_id) if seed is None else seed
        window = windows[window_name]
        market, first, last, values = self.window_values(
            manifest, protocol, snapshot_id, window, load_cpu_seconds, components
        )
        scores = np.full(market.shape, np.nan)
        scores[first : last + 1] = values
        sign = 1 if isinstance(manifest, StrategyManifest) else manifest.declared.expected_sign
        outcome = plugin.run_window(window_name, sign, scores, market, window.start, window.end)
        columns = np.flatnonzero(market.eligible[first : last + 1].any(axis=0))
        return WindowOutcome(seed, outcome, values, columns)


def make_runner(config: EvalConfig, store: ArtifactStore, scratch: Path | None = None) -> Runner:
    """The configured runner. A service that only reads the store (the sim engine) gives
    its own scratch directory."""
    if config.runner.mode == "inline":
        return InlineRunner()
    return SubprocessRunner(config.runner.wall_clock_factor, scratch or store.scratch())


class Worker:
    def __init__(
        self,
        db: Database,
        env: EvalEnvironment,
        config: EvalConfig,
        logger: JsonLogger,
        runner: Runner | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.db, self.env, self.config = db, env, config
        self.logger, self.log = logger, logger.logger
        self.clock = clock or SystemClock()
        self.store = ArtifactStore(env.store_dir)
        self.evaluator = Evaluator(
            env, runner or make_runner(config, self.store), MarketCache(env.full_snapshot_dir)
        )

    # Shared ------------------------------------------------------------------------

    def _state(self) -> ActiveState:
        with self.db.read() as conn:
            state = active_state(conn)
        if state is None:
            raise RuntimeError("no active protocol, policy, quotas and epoch")
        return state

    def _intake(self, version_id: UUID) -> Any:
        with self.db.read() as conn:
            row = conn.execute(
                text(
                    "SELECT version_id, content_hash, family_id, program_id, job_id, kind, "
                    "manifest FROM eval.intake WHERE version_id = :v"
                ),
                {"v": version_id},
            ).first()
        if row is None:
            raise RuntimeError("the job's version has no intake row")
        return row

    def _manifest(self, row: Any) -> tuple[Manifest, dict[str, Component]]:
        manifest = MANIFEST.validate_python(row.manifest["manifest"])
        with self.db.read() as conn:
            components = read_components(conn, manifest)
        return manifest, components

    def run_once(self) -> bool:
        now = self.clock.now()
        with self.db.transaction(lock=False) as conn:
            job = queue.claim(conn, self.env.worker_id, now)
        if job is None:
            return False
        correlation = job.payload.get("correlation") or {}
        ids = {k: v for k, v in correlation.items() if k in ("request_id",)}
        with self.db.read() as conn:
            owner = conn.execute(
                text("SELECT job_id FROM eval.intake WHERE version_id = :v"),
                {"v": job.version_id},
            ).scalar()
        if owner is not None:
            ids["job_id"] = str(owner)
        with bind(**ids, version_id=str(job.version_id)):
            started = time.monotonic()
            self.log.info("job_started", payload={"kind": job.kind, "attempt": job.attempts})
            try:
                if job.kind == "fingerprint":
                    self._fingerprint(job)
                elif job.kind == "evaluate":
                    self._evaluate(job)
                else:
                    self._window(job, "W2" if job.kind == "w2" else "W3")
                self.log.info(
                    "job_completed",
                    outcome="ok",
                    payload={"kind": job.kind, "seconds": round(time.monotonic() - started, 3)},
                )
            except Exception as error:
                self._failed(job, error)
        return True

    def _failed(self, job: queue.Job, error: Exception) -> None:
        now = self.clock.now()
        self.log.error(
            "job_failed",
            outcome="failed",
            error_type=type(error).__name__,
            payload={"kind": job.kind, "attempt": job.attempts, "stack": traceback.format_exc()},
        )
        if job.attempts < self.config.worker.max_attempts:
            backoff = self.config.worker.retry_backoff_seconds
            delay = backoff[min(job.attempts - 1, len(backoff) - 1)] if backoff else 0
            with self.db.transaction(lock=False) as conn:
                queue.retry(conn, job, now, delay, type(error).__name__)
            self.log.warning("job_retried", outcome="retried", payload={"delay_seconds": delay})
            return
        if job.kind == "fingerprint":
            with self.db.transaction() as conn:
                conn.execute(
                    text(
                        "UPDATE eval.intake SET fingerprint_error = 'INTERNAL_ERROR' "
                        "WHERE version_id = :v"
                    ),
                    {"v": job.version_id},
                )
                queue.finish(conn, job, now, "failed")
            return
        state = self._state()
        row = self._intake(job.version_id)
        if job.kind in ("w2", "holdout"):
            self._window_failed(job, row, state, now)
            return
        outcome = StageOutcome(
            "screening",
            False,
            [ReasonCode.INTERNAL_ERROR],
            {},
            {"status": "FAIL", "reasons": [ReasonCode.INTERNAL_ERROR.value]},
        )
        seed = run_seed(int(state.protocol.config["fingerprint"]["seed"]), str(job.version_id))
        result = EvaluationOutcome(seed, None, outcome, None, None, [])
        self._write(job, row, state, result, now, now, failed_state="failed")

    def _refs(self, state: ActiveState) -> dict[str, str]:
        return {
            "protocol_id": state.protocol.id,
            "protocol_version": state.protocol.version,
            "data_snapshot_id": state.epoch.snapshot_id,
            "evaluator_code_version": self.env.code_version,
        }

    # Fingerprints ------------------------------------------------------------------

    def _fingerprint(self, job: queue.Job) -> None:
        state = self._state()
        row = self._intake(job.version_id)
        manifest, components = self._manifest(row)
        value, error = self.evaluator.fingerprint(
            manifest,
            state.protocol.config,
            state.epoch.windows,
            state.epoch.snapshot_id,
            self.config.runner.load_cpu_seconds,
            components,
        )
        now = self.clock.now()
        stored = None
        if value is not None:
            stored = self.store.write_fingerprint(state.epoch.epoch_id, job.version_id, value)
        with self.db.transaction() as conn:
            if stored is not None:
                uri, sha, dates_sha = stored
                conn.execute(
                    text(
                        "INSERT INTO eval.fingerprints (version_id, epoch_id, snapshot_id, uri, "
                        "sha256, dates_sha256, created_at) VALUES (:v, :e, :s, :u, :sha, :d, :at) "
                        "ON CONFLICT DO NOTHING"
                    ),
                    {
                        "v": job.version_id,
                        "e": state.epoch.epoch_id,
                        "s": state.epoch.snapshot_id,
                        "u": uri,
                        "sha": sha,
                        "d": dates_sha,
                        "at": now,
                    },
                )
            else:
                conn.execute(
                    text("UPDATE eval.intake SET fingerprint_error = :e WHERE version_id = :v"),
                    {"e": error, "v": job.version_id},
                )
            queue.finish(conn, job, now, "done")

    # Evaluation --------------------------------------------------------------------

    def library_members(
        self, conn: Connection, version_id: UUID, epoch_id: str, pool: str = "factor"
    ) -> list[LibraryMember]:
        """Effective library entries of one pool with their stored W1 values: factors
        for a factor's library gate, strategies (their composites) for a strategy's."""
        rows = conn.execute(
            text(
                "SELECT l.version_id, s.uri, s.sha256 FROM eval.library l "
                "JOIN eval.official_records r ON r.version_id = l.version_id "
                "  AND r.stage = 'w1' AND r.epoch_id = :e "
                "JOIN eval.series_files s ON s.run_id = r.run_ids[1] AND s.kind = 'factor_values' "
                "WHERE l.pool = :pool AND l.status IN ('seed', 'active') "
                "AND l.effective_from IS NOT NULL AND l.version_id <> :v ORDER BY l.version_id"
            ),
            {"e": epoch_id, "v": version_id, "pool": pool},
        ).all()
        return [LibraryMember(str(r.version_id), r.uri, r.sha256) for r in rows]

    def _evaluate(self, job: queue.Job) -> None:
        state = self._state()
        row = self._intake(job.version_id)
        manifest, components = self._manifest(row)
        with self.db.read() as conn:
            library = self.library_members(
                conn, job.version_id, state.epoch.epoch_id, manifest.kind
            )
        started = self.clock.now()
        outcome = self.evaluator.evaluate(
            manifest,
            str(job.version_id),
            state.protocol.config,
            state.epoch.windows,
            state.epoch.snapshot_id,
            library,
            self.config.runner.load_cpu_seconds,
            components=components,
        )
        self._write(job, row, state, outcome, started, self.clock.now())

    def _run_row(
        self,
        conn: Connection,
        run_id: UUID,
        row: Any,
        state: ActiveState,
        outcome: StageOutcome,
        seed: int,
        started: datetime,
        finished: datetime,
        status: str,
        window: str = "W1",
    ) -> None:
        conn.execute(
            text(
                "INSERT INTO eval.runs (run_id, version_id, stage, window_name, protocol_ref, "
                "epoch_id, snapshot_id, code_version, image_digest, seed, status, started_at, "
                "finished_at, error_code, resources, request_id, content_hash) VALUES (:id, :v, "
                ":stage, :w, :p, :e, :s, :code, :img, :seed, :status, :start, :end, :err, "
                "CAST(:res AS jsonb), :r, :ch)"
            ),
            {
                "id": run_id,
                "v": row.version_id,
                "stage": outcome.stage,
                "w": window,
                "p": state.protocol.ref,
                "e": state.epoch.epoch_id,
                "s": state.epoch.snapshot_id,
                "code": self.env.code_version,
                "img": self.env.image_digest,
                "seed": seed,
                "status": status,
                "start": started,
                "end": finished,
                "err": outcome.reasons[0].value if outcome.reasons else None,
                "res": canonical_json(outcome.resources),
                "r": current()["request_id"],
                "ch": row.content_hash,
            },
        )
        for name, value in outcome.metrics.items():
            horizon = int(name.removeprefix("decay_h")) if name.startswith("decay_h") else None
            conn.execute(
                text(
                    "INSERT INTO eval.metrics (run_id, name, horizon, value) "
                    "VALUES (:r, :n, :h, :v)"
                ),
                {"r": run_id, "n": name, "h": horizon, "v": value},
            )

    def _record(
        self,
        conn: Connection,
        run_id: UUID,
        row: Any,
        state: ActiveState,
        outcome: StageOutcome,
        seed: int,
        at: datetime,
        window: Literal["W1", "W2", "W3"] = "W1",
    ) -> OfficialRecord:
        record = OfficialRecord(
            schema_version="official_record/1",
            record_id=uuid7(),
            version_id=row.version_id,
            content_hash=row.content_hash,
            protocol_id=state.protocol.id,
            protocol_version=state.protocol.version,
            data_snapshot_id=state.epoch.snapshot_id,
            evaluator_code_version=self.env.code_version,
            epoch_id=state.epoch.epoch_id,
            family_id=row.family_id,
            program_id=row.program_id,
            job_id=row.job_id,
            stage=outcome.stage,
            window=window,
            run_ids=[run_id],
            container_image_digest=self.env.image_digest,
            seed=seed,
            summary=outcome.summary,
            metrics=outcome.metrics,
            results_hash=results_hash(outcome.metrics),
            created_at=at,
            principal=SERVICE,
            request_id=current()["request_id"],
        )
        conn.execute(
            text(
                "INSERT INTO eval.official_records (record_id, version_id, content_hash, "
                "family_id, program_id, job_id, stage, window_name, run_ids, protocol_id, "
                "protocol_version, epoch_id, snapshot_id, code_version, image_digest, seed, "
                "summary, metrics, results_hash, created_at, principal, request_id) VALUES "
                "(:id, :v, :ch, :f, :p, :j, :stage, :w, :runs, :pid, :pv, :e, :s, :code, "
                ":img, :seed, CAST(:summary AS jsonb), CAST(:metrics AS jsonb), :hash, :at, "
                ":principal, :r)"
            ),
            {
                "id": record.record_id,
                "v": record.version_id,
                "ch": record.content_hash,
                "f": record.family_id,
                "p": record.program_id,
                "j": record.job_id,
                "stage": record.stage,
                "w": window,
                "runs": [run_id],
                "pid": record.protocol_id,
                "pv": record.protocol_version,
                "e": record.epoch_id,
                "s": record.data_snapshot_id,
                "code": record.evaluator_code_version,
                "img": record.container_image_digest,
                "seed": seed,
                "summary": canonical_json(record.summary),
                "metrics": canonical_json(record.metrics),  # type: ignore[arg-type]
                "hash": record.results_hash,
                "at": at,
                "principal": record.principal,
                "r": record.request_id,
            },
        )
        return record

    def _series(
        self,
        run_id: UUID,
        outcome: StageOutcome,
        values: Array | None,
        epoch_id: str,
        version_id: UUID,
        market_columns: Any,
        window: str = "W1",
    ) -> list[tuple[str, str, str, int]]:
        files = []
        for kind, columns in outcome.series.items():
            frame = pl.DataFrame(columns).with_columns(pl.col("date").str.to_date())
            uri, sha, size = self.store.write_series(run_id, kind, frame)
            files.append((kind, uri, sha, size))
        if values is not None:
            uri, sha = self.store.write_window_values(
                epoch_id, window, version_id, values, market_columns
            )
            files.append(("factor_values", uri, sha, 0))
        return files

    def _series_rows(
        self, conn: Connection, run_id: UUID, files: list[tuple[str, str, str, int]]
    ) -> None:
        for kind, uri, sha, size in files:
            conn.execute(
                text(
                    "INSERT INTO eval.series_files (run_id, kind, uri, sha256, bytes) "
                    "VALUES (:r, :k, :u, :s, :b)"
                ),
                {"r": run_id, "k": kind, "u": uri, "s": sha, "b": size},
            )

    def _ledger(
        self,
        conn: Connection,
        row: Any,
        state: ActiveState,
        record: OfficialRecord,
        ledger: dict[str, Any],
        window: WindowName,
        at: datetime,
    ) -> None:
        """The trial-ledger row (Section 8.9), in the run's transaction (EVL-06)."""
        fingerprint_ref = conn.execute(
            text("SELECT uri FROM eval.fingerprints WHERE version_id = :v AND epoch_id = :e"),
            {"v": row.version_id, "e": state.epoch.epoch_id},
        ).scalar()
        conn.execute(
            text(
                "INSERT INTO eval.trial_ledger (window_name, epoch_id, version_id, "
                "family_id, program_id, job_id, record_id, sharpe_daily, n_obs, skew, "
                "kurt_raw, fingerprint_ref, counted_at) VALUES (:w, :e, :v, :f, :p, "
                ":j, :rec, :sh, :n, :sk, :ku, :fp, :at)"
            ),
            {
                "w": window,
                "e": state.epoch.epoch_id,
                "v": row.version_id,
                "f": row.family_id,
                "p": row.program_id,
                "j": row.job_id,
                "rec": record.record_id,
                "sh": ledger["sharpe_daily"],
                "n": int(ledger["n_obs"] or 0),
                "sk": ledger["skew"],
                "ku": ledger["kurt_raw"],
                "fp": fingerprint_ref,
                "at": at,
            },
        )

    def _write(
        self,
        job: queue.Job,
        row: Any,
        state: ActiveState,
        result: EvaluationOutcome,
        started: datetime,
        finished: datetime,
        failed_state: str = "done",
    ) -> None:
        refs = self._refs(state)
        screening_run = uuid7()
        w1_run = uuid7() if result.w1 is not None else None
        files: list[tuple[str, str, str, int]] = []
        if result.w1 is not None and w1_run is not None:
            market = self.evaluator.markets.get(
                state.epoch.snapshot_id, FactorPlugin(state.protocol.config)
            )
            w1 = state.epoch.windows["W1"]
            first, last = market.window(w1.start, w1.end)
            columns = np.flatnonzero(market.eligible[first : last + 1].any(axis=0))
            files = self._series(
                w1_run, result.w1, result.w1_values, state.epoch.epoch_id, row.version_id, columns
            )
        request_id = current()["request_id"]
        with self.db.transaction() as conn:
            screening = result.screening
            self._run_row(
                conn, screening_run, row, state, screening, result.seed, started, finished,
                "succeeded" if screening.passed else "failed",
            )  # fmt: skip
            screening_record = self._record(
                conn, screening_run, row, state, screening, result.seed, finished
            )
            queue_report(
                conn,
                "screening",
                row.version_id,
                {
                    "content": {
                        "type": "screening",
                        "status": "PASS" if screening.passed else "FAIL",
                        "reasons": [r.value for r in screening.reasons],
                        "duplicate_of": None,
                    },
                    "refs": refs,
                },
                finished,
                request_id,
                screening_record.record_id,
            )
            new_state = "ScreenFailed"
            w1_passed = None
            if result.w1 is not None and w1_run is not None:
                outcome = result.w1
                self._run_row(
                    conn, w1_run, row, state, outcome, result.seed, started, finished, "succeeded"
                )
                self._series_rows(conn, w1_run, files)
                record = self._record(conn, w1_run, row, state, outcome, result.seed, finished)
                self._ledger(conn, row, state, record, outcome.raw["ledger"], "W1", finished)
                raw = {k: v for k, v in outcome.raw.items() if k != "ledger"}
                queue_report(
                    conn, "w1", row.version_id, {"raw": raw, "refs": refs}, finished,
                    request_id, record.record_id,
                )  # fmt: skip
                conn.execute(
                    text(
                        "UPDATE eval.library SET effective_from = :at, updated_at = :at "
                        "WHERE version_id = :v AND effective_from IS NULL"
                    ),
                    {"at": finished, "v": row.version_id},
                )
                self._burn(conn, state, finished)
                w1_passed = outcome.passed
                new_state = "W1Evaluated" if outcome.passed else "W1GateFailed"
            conn.execute(
                text(
                    "UPDATE eval.intake SET state = :s, reason_code = :rc, w1_passed = :w, "
                    "decided_at = :at, updated_at = :at WHERE version_id = :v"
                ),
                {
                    "s": new_state,
                    "rc": screening.reasons[0].value if screening.reasons else None,
                    "w": w1_passed,
                    "at": finished,
                    "v": row.version_id,
                },
            )
            record_event(
                conn, finished, SERVICE, "version_evaluated", "intake", str(row.version_id),
                request_id,
                {"state": new_state, "reasons": [r.value for r in screening.reasons],
                 "screening_record": str(screening_record.record_id)},
            )  # fmt: skip
            queue.finish(conn, job, finished, "done" if failed_state == "done" else "failed")
        self.log.info(
            "version_evaluated",
            outcome="ok",
            payload={
                "state": new_state,
                "reasons": [r.value for r in result.screening.reasons],
                "w1_passed": w1_passed,
            },
        )

    def _burn(self, conn: Connection, state: ActiveState, at: datetime) -> None:
        burn = state.quotas.config["burn"]
        conn.execute(
            text(
                "UPDATE eval.burn_meters SET trials = trials + 1, updated_at = :at, "
                "status = CASE WHEN trials + 1 >= :red THEN 'red' "
                "WHEN trials + 1 >= :amber THEN 'amber' ELSE 'green' END "
                "WHERE epoch_id = :e AND window_name = 'W1'"
            ),
            {"at": at, "red": burn["w1_red"], "amber": burn["w1_amber"], "e": state.epoch.epoch_id},
        )

    # W2 validation and the W3 holdout (Sections 8.8, 9.2 and 10.1) ---------------------

    def _window(self, job: queue.Job, window: Literal["W2", "W3"]) -> None:
        state = self._state()
        row = self._intake(job.version_id)
        manifest, components = self._manifest(row)
        started = self.clock.now()
        result = self.evaluator.run_window(
            manifest,
            str(job.version_id),
            state.protocol.config,
            state.epoch.windows,
            state.epoch.snapshot_id,
            window,
            self.config.runner.load_cpu_seconds,
            components=components,
        )
        finished = self.clock.now()
        run_id = uuid7()
        outcome = result.outcome
        # W3 values are kept for the acceptance novelty gate; they never leave the zone.
        files = self._series(
            run_id, outcome, result.values if window == "W3" else None,
            state.epoch.epoch_id, row.version_id, result.columns, window,
        )  # fmt: skip
        request_id = current()["request_id"]
        with self.db.transaction() as conn:
            self._run_row(
                conn, run_id, row, state, outcome, result.seed, started, finished, "succeeded",
                window,
            )  # fmt: skip
            self._series_rows(conn, run_id, files)
            record = self._record(conn, run_id, row, state, outcome, result.seed, finished, window)
            self._ledger(conn, row, state, record, outcome.raw["ledger"], window, finished)
            self._query_burn(conn, state, window, finished)
            if window == "W2":
                self._w2_decision(conn, row, state, record, outcome, finished, request_id)
            else:
                self._holdout_decision(conn, row, state, record, outcome, finished, request_id)
            queue.finish(conn, job, finished, "done")
        self.log.info(
            "window_evaluated",
            outcome="ok",
            payload={"window": window, "passed": outcome.passed, "record": str(record.record_id)},
        )

    def _query_burn(self, conn: Connection, state: ActiveState, window: str, at: datetime) -> None:
        """A W2 or W3 run is a trial and a query against the window's budget (9.4)."""
        conn.execute(
            text(
                "UPDATE eval.burn_meters SET trials = trials + 1, queries_used = queries_used + 1, "
                "updated_at = :at, status = CASE WHEN budget IS NOT NULL "
                "AND queries_used + 1 >= budget THEN 'red' ELSE status END "
                "WHERE epoch_id = :e AND window_name = :w"
            ),
            {"at": at, "e": state.epoch.epoch_id, "w": window},
        )

    def _w2_decision(
        self,
        conn: Connection,
        row: Any,
        state: ActiveState,
        record: OfficialRecord,
        outcome: StageOutcome,
        at: datetime,
        request_id: str,
    ) -> None:
        """The Ladder (Section 9.2, REL-06): the family best moves, and is released rounded
        to the Ladder step, only when the W2 value beats it by at least eta."""
        policy = state.policy.config
        eta = float(policy["ladder"]["eta"])
        previous = conn.execute(
            text(
                "SELECT best_value FROM eval.ladder_state WHERE epoch_id = :e AND family_id = :f "
                "FOR UPDATE"
            ),
            {"e": state.epoch.epoch_id, "f": row.family_id},
        ).scalar()
        step = ladder_step(previous, outcome.raw.get("ladder_value"), eta)
        released = quantize(step.best, float(policy["rounding"]["ladder_best"]))
        conn.execute(
            text(
                "INSERT INTO eval.ladder_events (event_id, epoch_id, family_id, record_id, "
                "version_id, value, previous_best, eta, improved, released_best, at) VALUES "
                "(:id, :e, :f, :rec, :v, :value, :prev, :eta, :imp, :rel, :at)"
            ),
            {
                "id": uuid7(),
                "e": state.epoch.epoch_id,
                "f": row.family_id,
                "rec": record.record_id,
                "v": row.version_id,
                "value": step.value,
                "prev": step.previous_best,
                "eta": eta,
                "imp": step.improved,
                "rel": released if step.improved else None,
                "at": at,
            },
        )
        if step.improved:
            conn.execute(
                text(
                    "INSERT INTO eval.ladder_state (epoch_id, family_id, best_value, "
                    "released_best, record_id, updated_at) VALUES (:e, :f, :b, :rel, :rec, :at) "
                    "ON CONFLICT (epoch_id, family_id) DO UPDATE SET best_value = :b, "
                    "released_best = :rel, record_id = :rec, updated_at = :at"
                ),
                {
                    "e": state.epoch.epoch_id,
                    "f": row.family_id,
                    "b": step.best,
                    "rel": released,
                    "rec": record.record_id,
                    "at": at,
                },
            )
        raw = {
            "passed": outcome.passed,
            "improved": step.improved,
            "released_best": released if step.improved else None,
        }
        queue_report(
            conn, "w2", row.version_id, {"raw": raw, "refs": self._refs(state)}, at, request_id,
            record.record_id,
        )  # fmt: skip
        new_state = "HoldoutCheck" if outcome.passed else "W2Failed"
        conn.execute(
            text(
                "UPDATE eval.intake SET state = :s, w2_passed = :p, updated_at = :at "
                "WHERE version_id = :v"
            ),
            {"s": new_state, "p": outcome.passed, "at": at, "v": row.version_id},
        )
        record_event(
            conn, at, SERVICE, "w2_evaluated", "intake", str(row.version_id), request_id,
            {"state": new_state, "record": str(record.record_id), "ladder_improved": step.improved},
        )  # fmt: skip

    def _holdout_decision(
        self,
        conn: Connection,
        row: Any,
        state: ActiveState,
        record: OfficialRecord,
        outcome: StageOutcome,
        at: datetime,
        request_id: str,
    ) -> None:
        """The holdout's only release is one bit, ADVANCED or NOT_ADVANCED (INV-6)."""
        status = "ADVANCED" if outcome.passed else "NOT_ADVANCED"
        queue_report(
            conn, "advancement", row.version_id,
            {"content": {"type": "advancement", "status": status}, "refs": self._refs(state)},
            at, request_id, record.record_id,
        )  # fmt: skip
        new_state = "AwaitingSlot" if outcome.passed else "NotAdvanced"
        conn.execute(
            text(
                "UPDATE eval.intake SET state = :s, holdout_passed = :p, updated_at = :at "
                "WHERE version_id = :v"
            ),
            {"s": new_state, "p": outcome.passed, "at": at, "v": row.version_id},
        )
        record_event(
            conn, at, SERVICE, "holdout_checked", "intake", str(row.version_id), request_id,
            {"state": new_state, "record": str(record.record_id)},
        )  # fmt: skip

    def _window_failed(self, job: queue.Job, row: Any, state: ActiveState, at: datetime) -> None:
        """After its retries, an internal error on W2 or W3 is released without detail as a
        failed check (Section 9.2); the quota it used stays used."""
        request_id = current()["request_id"]
        with self.db.transaction() as conn:
            if job.kind == "w2":
                queue_report(
                    conn, "w2", row.version_id,
                    {"raw": {"passed": False, "improved": False, "released_best": None},
                     "refs": self._refs(state)},
                    at, request_id,
                )  # fmt: skip
                new_state, column = "W2Failed", "w2_passed"
            else:
                queue_report(
                    conn, "advancement", row.version_id,
                    {"content": {"type": "advancement", "status": "NOT_ADVANCED"},
                     "refs": self._refs(state)},
                    at, request_id,
                )  # fmt: skip
                new_state, column = "NotAdvanced", "holdout_passed"
            conn.execute(
                text(
                    f"UPDATE eval.intake SET state = :s, {column} = false, "
                    "reason_code = 'INTERNAL_ERROR', updated_at = :at WHERE version_id = :v"
                ),
                {"s": new_state, "at": at, "v": row.version_id},
            )
            record_event(
                conn, at, SERVICE, "window_failed", "intake", str(row.version_id), request_id,
                {"state": new_state, "kind": job.kind},
            )  # fmt: skip
            queue.finish(conn, job, at, "failed")


def main() -> None:
    settings = RuntimeSettings(service=SERVICE, zone="eval")
    env = EvalEnvironment.from_env(os.environ, settings)
    config = eval_config(settings.config_dir)
    url = os.environ.get("EVAL_DB_URL", "")
    logger = service_logger(SERVICE, settings, [url])
    worker = Worker(Database(url), env, config, logger)
    start_heartbeat(Path(os.environ.get("QFR_HEARTBEAT_FILE") or "/tmp/heartbeat"))
    logger.logger.info("service_started", payload={"phase": 6, "code_version": env.code_version})
    while True:
        busy = False
        try:
            busy = worker.run_once()
        except Exception:
            logger.logger.exception("worker_loop_failed", outcome="failed")
        if not busy:
            time.sleep(config.worker.poll_seconds)


if __name__ == "__main__":
    main()
