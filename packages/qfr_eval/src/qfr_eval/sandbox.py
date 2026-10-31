"""Python factors in the sandbox (PLAN P8.1, Sections 8.4 and 17.2).

The evaluator never runs artifact Python in its own processes. eval-worker (and
sim-engine and `qfr eval reproduce`) build the input matrices a factor asks for, write
them with a job description to the sandbox exchange volume, and wait for the result that
the eval-sandbox service writes back. eval-sandbox has no network (network_mode: none),
no database, no snapshot and no secrets: it sees only numeric matrices without dates or
instrument ids, with the instrument columns in a seeded order that only the evaluator
can undo.

For one evaluation the sandbox runs the factor in a fresh child process for
  - the full computation over every snapshot row (one pass: the code cannot tell which
    segment is scored, Section 8.4);
  - each prefix-probe cut: the rows up to the cut only (prefix invariance, EVL-03);
  - each window-probe cut: only the declared lookback before the cut. The value at the
    cut must not change, which checks the declared lookback and that the code does not
    depend on its absolute row position (it never sees a date).
The evaluator compares the probe rows with the full computation itself. A child that
breaks a rule, runs out of CPU, memory or wall clock, raises, or returns the wrong shape
ends with an exit status the parent maps to an enum code; nothing the code prints or
raises is kept.
"""

import json
import math
import os
import resource
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

import numpy as np
import polars as pl
from pydantic import BaseModel, ConfigDict, Field
from qfr_core.data.snapshot import read_snapshot
from qfr_core.dsl.catalog import FIELD_COLUMNS
from qfr_core.eligibility import Eligibility
from qfr_core.ids import uuid7
from qfr_core.pyfactor import ELIGIBLE, PythonLimits

from qfr_eval import sandbox_child as child
from qfr_eval.compute import ComputeOutput, ComputeResult, ProbeResult, _Layout, _same

ErrorCode = Literal["FORBIDDEN_CONSTRUCT", "RUNTIME_LIMIT", "TYPE_ERROR", "PARSE_ERROR"]
RunKind = Literal["full", "prefix", "window"]
# The child's environment: one BLAS thread (threads count as processes under the child's
# process limit) and nothing else; no secret ever reaches artifact code.
CHILD_ENV = {
    "PATH": "/usr/local/bin:/usr/bin:/bin",
    "OPENBLAS_NUM_THREADS": "1",
    "OMP_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "LANG": "C.UTF-8",
}
# Allowance for interpreter start, numpy import and loading the inputs, in CPU seconds.
START_SECONDS = 30.0


class SandboxJob(BaseModel):
    """What eval-sandbox needs for one evaluation; no dates, no ids, no paths of its own."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    job_id: str
    source: str
    parameters: list[str]
    limits: PythonLimits
    rows: int = Field(gt=0)
    prefix_cuts: list[int]
    window_cuts: list[int]
    lookback: int = Field(ge=0)
    cpu_seconds: float = Field(gt=0)
    memory_bytes: int = Field(gt=0)
    wall_clock_factor: float = Field(gt=0)


class RunOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: RunKind
    cut: int | None
    exit: int
    status: Literal["ok", "violation", "cpu", "memory", "wall_clock", "raised", "output",
                    "refused", "error"]  # fmt: skip
    cpu_seconds: float


class SandboxResult(BaseModel):
    """What eval-sandbox writes back. Values travel beside it as values.npz."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    job_id: str
    status: Literal["ok", "refused", "runtime_limit", "error"]
    error_code: ErrorCode | None = None
    limit: Literal["cpu", "memory", "wall_clock"] | None = None
    runs: list[RunOutcome]
    cpu_seconds: float


def _status(code: int, timed_out: bool) -> str:
    if timed_out:
        return "wall_clock"
    if code in (-signal.SIGXCPU, -signal.SIGKILL):
        return "cpu"
    return {
        child.EXIT_OK: "ok",
        child.EXIT_MEMORY: "memory",
        child.EXIT_VIOLATION: "violation",
        child.EXIT_RAISED: "raised",
        child.EXIT_OUTPUT: "output",
        child.EXIT_REFUSED: "refused",
    }.get(code, "error")


def _children_cpu() -> float:
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return usage.ru_utime + usage.ru_stime


def spawn(
    request: dict[str, Any], wall_seconds: float, max_bytes: int, workdir: Path
) -> tuple[int, bool, bytes]:
    """One child run; returns (exit status, timed out, stdout). stderr is discarded."""
    process = subprocess.Popen(
        [sys.executable, "-I", "-m", "qfr_eval.sandbox_child"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=CHILD_ENV,
        cwd=workdir,
        start_new_session=True,
    )
    try:
        stdout, _ = process.communicate(json.dumps(request).encode(), timeout=wall_seconds)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        return -signal.SIGKILL, True, b""
    if len(stdout) > max_bytes:
        return child.EXIT_OUTPUT, False, b""
    return process.returncode, False, stdout


def _matrix(data: bytes, rows: int, columns: int) -> np.ndarray | None:
    if len(data) != 16 + rows * columns * 8:
        return None
    shape = np.frombuffer(data[:16], dtype="<i8")
    if tuple(int(x) for x in shape) != (rows, columns):
        return None
    return np.frombuffer(data[16:], dtype="<f8").reshape(rows, columns).astype(np.float64)


def run_job(job: SandboxJob, inputs: Path, workdir: Path) -> tuple[SandboxResult, dict[str, Any]]:
    """Every run of one evaluation, each in a fresh child. Trusted code (eval-sandbox)."""
    with np.load(inputs, allow_pickle=False) as archive:
        columns = int(archive[job.parameters[0]].shape[1])
    plan: list[tuple[RunKind, int | None, int, int]] = [("full", None, 0, job.rows)]
    plan += [("prefix", c, 0, c + 1) for c in job.prefix_cuts]
    plan += [("window", c, max(0, c - job.lookback), c + 1) for c in job.window_cuts]
    runs: list[RunOutcome] = []
    arrays: dict[str, Any] = {"prefix": {}, "window": {}}
    started = _children_cpu()
    for kind, cut, start, stop in plan:
        rows = stop - start
        request = {
            "inputs_path": str(inputs),
            "start": start,
            "stop": stop,
            "parameters": job.parameters,
            "limits": job.limits.model_dump(),
            "source": job.source,
            "cpu_seconds": job.cpu_seconds,
            "memory_bytes": job.memory_bytes,
        }
        before = _children_cpu()
        wall = (START_SECONDS + job.cpu_seconds) * job.wall_clock_factor
        code, timed_out, stdout = spawn(request, wall, 16 + rows * columns * 8, workdir)
        status = _status(code, timed_out)
        values = _matrix(stdout, rows, columns) if status == "ok" else None
        if status == "ok" and values is None:
            status = "output"
        runs.append(
            RunOutcome(
                kind=kind,
                cut=cut,
                exit=code,
                status=status,  # type: ignore[arg-type]
                cpu_seconds=round(_children_cpu() - before, 6),
            )  # fmt: skip
        )
        if status != "ok" or values is None:
            break
        if kind == "full":
            arrays["full"] = values
        else:
            arrays[kind][cut] = values[-1]
    cpu = round(_children_cpu() - started, 6)
    last = runs[-1]
    if last.status == "ok":
        return SandboxResult(job_id=job.job_id, status="ok", runs=runs, cpu_seconds=cpu), arrays
    mapping: dict[str, tuple[str, ErrorCode | None, str | None]] = {
        "violation": ("refused", "FORBIDDEN_CONSTRUCT", None),
        "refused": ("refused", "FORBIDDEN_CONSTRUCT", None),
        "cpu": ("runtime_limit", "RUNTIME_LIMIT", "cpu"),
        "memory": ("runtime_limit", "RUNTIME_LIMIT", "memory"),
        "wall_clock": ("runtime_limit", "RUNTIME_LIMIT", "wall_clock"),
        "raised": ("refused", "TYPE_ERROR", None),
        "output": ("refused", "TYPE_ERROR", None),
    }
    status, error_code, limit = mapping.get(last.status, ("error", None, None))
    result = SandboxResult(
        job_id=job.job_id,
        status=status,  # type: ignore[arg-type]
        error_code=error_code,
        limit=limit,  # type: ignore[arg-type]
        runs=runs,
        cpu_seconds=cpu,
    )
    return result, {}


# The exchange volume ---------------------------------------------------------------------


def _write_values(path: Path, arrays: dict[str, Any]) -> None:
    flat: dict[str, np.ndarray] = {}
    if "full" in arrays:
        flat["full"] = arrays["full"]
    for kind in ("prefix", "window"):
        for cut, row in sorted(arrays.get(kind, {}).items()):
            flat[f"{kind}_{cut}"] = row
    with path.open("wb") as handle:
        np.savez(handle, **flat)  # type: ignore[arg-type]


def _read_values(path: Path) -> dict[str, Any]:
    arrays: dict[str, Any] = {"prefix": {}, "window": {}}
    with np.load(path, allow_pickle=False) as archive:
        for name in archive.files:
            if name == "full":
                arrays["full"] = archive[name]
            else:
                kind, cut = name.split("_")
                arrays[kind][int(cut)] = archive[name]
    return arrays


class Transport(Protocol):
    def submit(
        self, job: SandboxJob, write_inputs: Callable[[Path], None]
    ) -> tuple[SandboxResult, dict[str, Any]]: ...


class LocalTransport:
    """Runs the children directly from this process (tests, and the sandbox server)."""

    def __init__(self, scratch: Path) -> None:
        self.scratch = scratch

    def submit(
        self, job: SandboxJob, write_inputs: Callable[[Path], None]
    ) -> tuple[SandboxResult, dict[str, Any]]:
        folder = self.scratch / f"job-{job.job_id}"
        folder.mkdir(parents=True, exist_ok=False)
        try:
            inputs = folder / "inputs.npz"
            write_inputs(inputs)
            return run_job(job, inputs, folder)
        finally:
            shutil.rmtree(folder, ignore_errors=True)


class ExchangeTransport:
    """The evaluator's side of the exchange volume: requests/<id>/ in, results/<id>/ out."""

    def __init__(self, root: Path, poll_seconds: float = 0.05) -> None:
        self.root, self.poll_seconds = root, poll_seconds

    def submit(
        self, job: SandboxJob, write_inputs: Callable[[Path], None]
    ) -> tuple[SandboxResult, dict[str, Any]]:
        requests, results = self.root / "requests", self.root / "results"
        requests.mkdir(parents=True, exist_ok=True)
        staging = requests / f".{job.job_id}.tmp"
        staging.mkdir()
        write_inputs(staging / "inputs.npz")
        (staging / "job.json").write_text(job.model_dump_json(), encoding="utf-8")
        staging.rename(requests / job.job_id)
        runs = 1 + len(job.prefix_cuts) + len(job.window_cuts)
        deadline = time.monotonic() + (START_SECONDS + job.cpu_seconds) * job.wall_clock_factor * (
            runs + 1
        )
        done = results / job.job_id
        try:
            while not (done / "result.json").is_file():
                if time.monotonic() > deadline:
                    shutil.rmtree(requests / job.job_id, ignore_errors=True)
                    return SandboxResult(
                        job_id=job.job_id, status="runtime_limit", error_code="RUNTIME_LIMIT",
                        limit="wall_clock", runs=[], cpu_seconds=0.0,
                    ), {}  # fmt: skip
                time.sleep(self.poll_seconds)
            result = SandboxResult.model_validate_json((done / "result.json").read_text("utf-8"))
            values = done / "values.npz"
            arrays = _read_values(values) if values.is_file() else {}
            return result, arrays
        finally:
            shutil.rmtree(done, ignore_errors=True)


@dataclass
class SandboxServer:
    """eval-sandbox: claim a request by renaming it, run it, write the result atomically."""

    root: Path
    on_result: Callable[[SandboxJob, SandboxResult], None] | None = None
    claimed: list[str] = field(default_factory=list)
    # Results nobody collected (the evaluator gave up waiting) are removed after this.
    stale_seconds: float = 3600.0

    def recover(self) -> int:
        """At start: drop runs a previous server left half done. Their evaluator times
        out and the job is retried; nothing is answered from a half-finished run."""
        running = self.root / "running"
        stale = [p for p in running.iterdir()] if running.is_dir() else []
        for path in stale:
            shutil.rmtree(path, ignore_errors=True)
        return len(stale)

    def sweep(self, now: float | None = None) -> int:
        results = self.root / "results"
        if not results.is_dir():
            return 0
        cutoff = (now if now is not None else time.time()) - self.stale_seconds
        old = [p for p in results.iterdir() if p.stat().st_mtime < cutoff]
        for path in old:
            shutil.rmtree(path, ignore_errors=True)
        return len(old)

    def serve_once(self) -> int:
        requests, running, results = (self.root / n for n in ("requests", "running", "results"))
        for folder in (requests, running, results):
            folder.mkdir(parents=True, exist_ok=True)
        served = 0
        for path in sorted(p for p in requests.iterdir() if not p.name.startswith(".")):
            target = running / path.name
            try:
                path.rename(target)  # The rename is the claim; another server loses it.
            except OSError:
                continue
            try:
                job = SandboxJob.model_validate_json((target / "job.json").read_text("utf-8"))
                result, arrays = run_job(job, target / "inputs.npz", target)
            except Exception:  # noqa: BLE001 - a malformed request is answered, not fatal
                job = None
                result, arrays = (
                    SandboxResult(job_id=path.name, status="error", runs=[], cpu_seconds=0.0),
                    {},
                )
            staging = results / f".{path.name}.tmp"
            staging.mkdir(exist_ok=True)
            if arrays:
                _write_values(staging / "values.npz", arrays)
            (staging / "result.json").write_text(result.model_dump_json(), encoding="utf-8")
            staging.rename(results / path.name)
            shutil.rmtree(target, ignore_errors=True)
            if job is not None and self.on_result is not None:
                self.on_result(job, result)
            self.claimed.append(path.name)
            served += 1
        return served


# The evaluator's runner -----------------------------------------------------------------


class PythonComputeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    snapshot_path: str
    source: str
    parameters: list[str]
    limits: PythonLimits
    eligibility: Eligibility
    rows: list[int]  # Date indices whose values are returned.
    probe_cuts: list[int]  # Prefix-probe cut indices (empty: no probes at all).
    lookback: int = Field(ge=0)
    tolerance: float = Field(gt=0)
    cpu_seconds: float = Field(gt=0)
    memory_bytes: int = Field(gt=0)
    seed: int


class FieldMatrices:
    """Field matrices of one snapshot, built once per field and kept for later requests."""

    def __init__(self) -> None:
        self._key: tuple[str, str] | None = None
        self._layout: _Layout | None = None
        self._panel: pl.DataFrame | None = None
        self._cache: dict[str, np.ndarray] = {}

    def get(
        self, snapshot_path: str, eligibility: Eligibility, name: str
    ) -> tuple[np.ndarray, _Layout]:
        key = (snapshot_path, eligibility.model_dump_json())
        if self._key != key:
            snapshot = read_snapshot(Path(snapshot_path), verify=False)
            self._panel = snapshot.panel()
            self._layout = _Layout(self._panel, snapshot.calendar())
            self._cache, self._key = {}, key
        assert self._panel is not None and self._layout is not None
        if name not in self._cache:
            if name == ELIGIBLE:
                mask = self._panel.select(eligibility.mask()).to_series()
                matrix = self._layout.matrix(mask.cast(pl.Float64)) == 1.0
            else:
                matrix = self._layout.matrix(self._panel.get_column(FIELD_COLUMNS[name]))
            self._cache[name] = matrix
        return self._cache[name], self._layout


def window_cuts(rows: int, lookback: int, count: int, seed: int) -> list[int]:
    """Window-probe cuts over every row with a full lookback before it (seeded)."""
    first = min(lookback, rows - 1)
    days = np.arange(first, rows)
    picks = np.random.default_rng(seed).choice(days.size, size=min(count, days.size), replace=False)
    return sorted(int(days[p]) for p in picks)


class PythonRunner:
    """Turns a Python compute request into a sandbox job and checks the probes."""

    def __init__(self, transport: Transport, wall_clock_factor: float) -> None:
        self.transport, self.wall_clock_factor = transport, wall_clock_factor
        self.matrices = FieldMatrices()

    def run(self, request: PythonComputeRequest) -> ComputeOutput:
        _, layout = self.matrices.get(request.snapshot_path, request.eligibility, ELIGIBLE)
        total = len(layout.dates)
        columns = len(layout.instruments)
        order = np.random.default_rng(request.seed).permutation(columns)
        inverse = np.argsort(order)
        windows = (
            window_cuts(
                total, request.lookback, request.limits.window_probe_dates, request.seed + 1
            )
            if request.probe_cuts
            else []
        )
        job = SandboxJob(
            job_id=str(uuid7()),
            source=request.source,
            parameters=request.parameters,
            limits=request.limits,
            rows=total,
            prefix_cuts=request.probe_cuts,
            window_cuts=windows,
            lookback=request.lookback,
            cpu_seconds=request.cpu_seconds,
            memory_bytes=request.memory_bytes,
            wall_clock_factor=self.wall_clock_factor,
        )

        def write_inputs(path: Path) -> None:
            arrays = {}
            for name in request.parameters:
                matrix, _ = self.matrices.get(request.snapshot_path, request.eligibility, name)
                arrays[name] = matrix[:, order]  # The sandbox never sees the real order.
            with path.open("wb") as handle:
                np.savez(handle, **arrays)  # type: ignore[arg-type]

        result, arrays = self.transport.submit(job, write_inputs)
        resources = {"sandbox_runs": len(result.runs), "sandbox_cpu_seconds": result.cpu_seconds}
        if result.status != "ok" or "full" not in arrays:
            status: Literal["ok", "dsl_error", "runtime_limit", "error", "refused"] = (
                result.status if result.status != "ok" else "error"
            )
            return ComputeOutput(
                ComputeResult(
                    status=status,
                    error_code=result.error_code,
                    limit=result.limit,
                    error_type=None if result.status != "error" else "sandbox error",
                    cpu_seconds=result.cpu_seconds,
                    sandbox=resources,
                ),
                None,
            )
        full = np.asarray(arrays["full"])[:, inverse]
        probes = [
            self._probe(layout, cut, np.asarray(row)[inverse], full[cut], request.tolerance)
            for cut, row in sorted(arrays["prefix"].items())
        ]
        window_probes = [
            self._probe(layout, cut, np.asarray(row)[inverse], full[cut], request.tolerance)
            for cut, row in sorted(arrays["window"].items())
        ]
        full_cpu = next((r.cpu_seconds for r in result.runs if r.kind == "full"), None)
        return ComputeOutput(
            ComputeResult(
                status="ok",
                cpu_seconds=full_cpu,
                probe_cpu_seconds=round(result.cpu_seconds - (full_cpu or 0.0), 6),
                probes=probes,
                window_probes=window_probes,
                instruments=columns,
                sandbox=resources,
            ),
            full[request.rows],
        )

    @staticmethod
    def _probe(
        layout: _Layout, cut: int, probe: np.ndarray, reference: np.ndarray, tolerance: float
    ) -> ProbeResult:
        mismatches, worst = 0, 0.0
        for a, b in zip(reference, probe, strict=True):
            if not _same(float(a), float(b), tolerance):
                mismatches += 1
            if math.isfinite(a) and math.isfinite(b):
                worst = max(worst, abs(float(a) - float(b)))
        return ProbeResult(
            cut=layout.dates[cut], compared=int(reference.size), mismatches=mismatches,
            max_abs_diff=worst,
        )  # fmt: skip


def main() -> None:
    """eval-sandbox: serve the exchange volume until stopped."""
    from qfr_core.config import RuntimeSettings

    from qfr_eval.runtime import eval_config, service_logger, start_heartbeat

    settings = RuntimeSettings(service="eval-sandbox", zone="eval")
    config = eval_config(settings.config_dir)
    logger = service_logger("eval-sandbox", settings, [])
    root = Path(os.environ.get("QFR_SANDBOX_DIR") or "/sandbox")
    start_heartbeat(Path(os.environ.get("QFR_HEARTBEAT_FILE") or "/tmp/heartbeat"))

    def logged(job: SandboxJob, result: SandboxResult) -> None:
        logger.logger.info(
            "sandbox_job_finished",
            outcome="ok" if result.status == "ok" else "failed",
            error_code=result.error_code,
            payload={
                "job_id": job.job_id,
                "status": result.status,
                "limit": result.limit,
                "runs": [r.model_dump() for r in result.runs],
                "cpu_seconds": result.cpu_seconds,
            },
        )

    server = SandboxServer(root, logged)
    dropped = server.recover()
    logger.logger.info(
        "service_started", outcome="ok", payload={"exchange": str(root), "dropped": dropped}
    )
    swept = time.monotonic()
    while True:
        try:
            if time.monotonic() - swept > 300:
                server.sweep()
                swept = time.monotonic()
            if not server.serve_once():
                time.sleep(config.sandbox.poll_seconds)
        except Exception:  # noqa: BLE001 - keep serving; the log has the trace
            logger.logger.exception("sandbox_loop_failed", outcome="failed")
            time.sleep(config.sandbox.poll_seconds)


if __name__ == "__main__":
    main()
