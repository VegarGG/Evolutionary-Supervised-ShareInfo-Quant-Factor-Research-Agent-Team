"""Factor computation under runtime limits, with the prefix-invariance probe (PLAN 8.4).

The factor is computed once over the whole full snapshot in a single pass, so artifact
code can never tell which segment is being scored. The probe then recomputes it on data
truncated at seeded cut dates and compares the values at each cut date.

Production runs the computation in a child process (`python -m qfr_eval.compute`): the
CPU budget is an RLIMIT_CPU soft limit raised step by step (snapshot load, the full
computation, then the probes), and a watchdog thread ends the child when its peak
resident memory passes the limit. Either way the parent sees RUNTIME_LIMIT. Tests may
use the in-process runner, which applies the same checks without the hard limits.
"""

import math
import os
import resource
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal, Protocol

import numpy as np
import polars as pl
from pydantic import BaseModel, ConfigDict, Field
from qfr_core.data.snapshot import read_snapshot
from qfr_core.dsl import DslError, DslLimits, compile_expression
from qfr_core.dsl.ast import Node
from qfr_core.eligibility import Eligibility
from qfr_core.operators import evaluate

MEMORY_EXIT = 77
EvaluateFn = Callable[[pl.DataFrame, Node, Eligibility], pl.Series]


class ComputeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    snapshot_path: str
    expression: str
    dsl: dict[str, object]
    eligibility: Eligibility
    rows: list[int]  # Date indices whose values are returned.
    probe_cuts: list[int]  # Date indices of the prefix-invariance cut dates.
    tolerance: float = Field(gt=0)
    cpu_seconds: float = Field(gt=0)
    memory_bytes: int = Field(gt=0)
    load_cpu_seconds: float = Field(gt=0)
    output_path: str


class ProbeResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    cut: date
    compared: int
    mismatches: int
    max_abs_diff: float | None


class ComputeResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: Literal["ok", "dsl_error", "runtime_limit", "error"]
    error_code: str | None = None
    error_type: str | None = None
    limit: Literal["cpu", "memory", "wall_clock"] | None = None
    cpu_seconds: float | None = None
    probe_cpu_seconds: float | None = None
    peak_rss_bytes: int | None = None
    probes: list[ProbeResult] = Field(default_factory=list)
    instruments: int | None = None


@dataclass(frozen=True)
class ComputeOutput:
    result: ComputeResult
    values: np.ndarray | None  # (len(rows), instruments) when status is ok


def _cpu() -> float:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return usage.ru_utime + usage.ru_stime


def _peak_rss() -> int:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(peak if sys.platform == "darwin" else peak * 1024)


def _same(a: float, b: float, tolerance: float) -> bool:
    if math.isnan(a) and math.isnan(b):
        return True
    if math.isnan(a) or math.isnan(b):
        return False
    return abs(a - b) <= tolerance * max(1.0, abs(a), abs(b))


class _Layout:
    """Panel rows to (date, instrument) cells, exactly as Market.from_panel lays them out."""

    def __init__(self, panel: pl.DataFrame, calendar: pl.DataFrame) -> None:
        self.dates: list[date] = calendar.get_column("date").to_list()
        instruments = panel.get_column("instrument").unique().sort()
        self.instruments: list[str] = instruments.to_list()
        self.rows = (
            calendar.get_column("date")
            .search_sorted(panel.get_column("date"), side="left")
            .to_numpy()
            .astype(np.int64)
        )
        self.cols = (
            instruments.search_sorted(panel.get_column("instrument"), side="left")
            .to_numpy()
            .astype(np.int64)
        )

    def matrix(self, values: pl.Series) -> np.ndarray:
        out = np.full((len(self.dates), len(self.instruments)), np.nan)
        out[self.rows, self.cols] = values.cast(pl.Float64).fill_null(np.nan).to_numpy()
        return out


def run_compute(
    request: ComputeRequest,
    evaluate_fn: EvaluateFn = evaluate,
    on_budget: Callable[[float], None] | None = None,
) -> ComputeOutput:
    """The computation itself; on_budget(seconds) is called before each budgeted step."""
    snapshot = read_snapshot(Path(request.snapshot_path), verify=False)
    panel = snapshot.panel()
    calendar = snapshot.calendar()
    layout = _Layout(panel, calendar)
    try:
        tree = compile_expression(request.expression, DslLimits.model_validate(request.dsl)).tree
    except DslError as error:
        return ComputeOutput(ComputeResult(status="dsl_error", error_code=error.code.value), None)
    if on_budget is not None:
        on_budget(request.cpu_seconds)
    started = _cpu()
    full = layout.matrix(evaluate_fn(panel, tree, request.eligibility))
    cpu_full = _cpu() - started
    if cpu_full > request.cpu_seconds:
        return ComputeOutput(
            ComputeResult(status="runtime_limit", limit="cpu", cpu_seconds=cpu_full), None
        )
    if on_budget is not None and request.probe_cuts:
        on_budget(request.cpu_seconds * len(request.probe_cuts))
    probes: list[ProbeResult] = []
    started = _cpu()
    dates = panel.get_column("date")
    for cut_index in request.probe_cuts:
        cut = layout.dates[cut_index]
        keep = (dates <= cut).to_numpy()
        part = panel.filter(pl.Series(keep))
        values = evaluate_fn(part, tree, request.eligibility)
        at_cut = (part.get_column("date") == cut).to_numpy()
        cols = layout.cols[keep][at_cut]
        truncated = values.cast(pl.Float64).fill_null(np.nan).to_numpy()[at_cut]
        reference = full[cut_index, cols]
        mismatches, worst = 0, 0.0
        for a, b in zip(reference, truncated, strict=True):
            if not _same(float(a), float(b), request.tolerance):
                mismatches += 1
            if math.isfinite(a) and math.isfinite(b):
                worst = max(worst, abs(float(a) - float(b)))
        probes.append(
            ProbeResult(cut=cut, compared=int(cols.size), mismatches=mismatches, max_abs_diff=worst)
        )
    probe_cpu = _cpu() - started
    if probe_cpu > request.cpu_seconds * max(1, len(request.probe_cuts)):
        return ComputeOutput(
            ComputeResult(status="runtime_limit", limit="cpu", cpu_seconds=cpu_full), None
        )
    result = ComputeResult(
        status="ok",
        cpu_seconds=cpu_full,
        probe_cpu_seconds=probe_cpu,
        peak_rss_bytes=_peak_rss(),
        probes=probes,
        instruments=len(layout.instruments),
    )
    return ComputeOutput(result, full[request.rows])


class Runner(Protocol):
    def run(self, request: ComputeRequest) -> ComputeOutput: ...


class InlineRunner:
    """In-process computation for tests. evaluate_fn can inject a test-only operator."""

    def __init__(self, evaluate_fn: EvaluateFn = evaluate) -> None:
        self.evaluate_fn = evaluate_fn

    def run(self, request: ComputeRequest) -> ComputeOutput:
        output = run_compute(request, self.evaluate_fn)
        peak = _peak_rss()
        if output.result.status == "ok" and peak > request.memory_bytes:
            return ComputeOutput(
                ComputeResult(status="runtime_limit", limit="memory", peak_rss_bytes=peak), None
            )
        return output


class SubprocessRunner:
    """The production runner: a child process under CPU and memory limits."""

    def __init__(self, wall_clock_factor: float, scratch: Path) -> None:
        self.wall_clock_factor, self.scratch = wall_clock_factor, scratch

    def run(self, request: ComputeRequest) -> ComputeOutput:
        self.scratch.mkdir(parents=True, exist_ok=True)
        request_path = Path(request.output_path).with_suffix(".request.json")
        result_path = Path(request.output_path).with_suffix(".result.json")
        request_path.write_text(request.model_dump_json(), encoding="utf-8")
        budget = request.load_cpu_seconds + request.cpu_seconds * (1 + len(request.probe_cuts))
        try:
            completed = subprocess.run(
                [sys.executable, "-m", "qfr_eval.compute", str(request_path), str(result_path)],
                timeout=budget * self.wall_clock_factor,
                capture_output=True,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return ComputeOutput(ComputeResult(status="runtime_limit", limit="wall_clock"), None)
        finally:
            request_path.unlink(missing_ok=True)
        code = completed.returncode
        if code in (-signal.SIGXCPU, -signal.SIGKILL):
            result_path.unlink(missing_ok=True)
            return ComputeOutput(ComputeResult(status="runtime_limit", limit="cpu"), None)
        if code == MEMORY_EXIT:
            result_path.unlink(missing_ok=True)
            return ComputeOutput(ComputeResult(status="runtime_limit", limit="memory"), None)
        if code != 0 or not result_path.is_file():
            return ComputeOutput(
                ComputeResult(status="error", error_type=f"child exit {code}"), None
            )
        result = ComputeResult.model_validate_json(result_path.read_text(encoding="utf-8"))
        result_path.unlink(missing_ok=True)
        values = None
        if result.status == "ok":
            values_path = Path(request.output_path)
            values = np.load(values_path, allow_pickle=False)
            values_path.unlink(missing_ok=True)
        return ComputeOutput(result, values)


def _watch_memory(limit: int) -> None:
    while True:
        if _peak_rss() > limit:
            os._exit(MEMORY_EXIT)
        time.sleep(0.05)


def child_main(request_path: Path, result_path: Path) -> int:
    request = ComputeRequest.model_validate_json(request_path.read_text(encoding="utf-8"))
    total = request.load_cpu_seconds + request.cpu_seconds * (1 + len(request.probe_cuts))
    hard = int(math.ceil(total)) + 5
    resource.setrlimit(resource.RLIMIT_CPU, (int(math.ceil(request.load_cpu_seconds)), hard))
    threading.Thread(target=_watch_memory, args=(request.memory_bytes,), daemon=True).start()

    def budget(seconds: float) -> None:
        soft = min(hard, int(math.ceil(_cpu() + seconds)) + 1)
        resource.setrlimit(resource.RLIMIT_CPU, (soft, hard))

    output = run_compute(request, on_budget=budget)
    if output.values is not None:
        np.save(Path(request.output_path), output.values, allow_pickle=False)
    result_path.write_text(output.result.model_dump_json(), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(child_main(Path(sys.argv[1]), Path(sys.argv[2])))
