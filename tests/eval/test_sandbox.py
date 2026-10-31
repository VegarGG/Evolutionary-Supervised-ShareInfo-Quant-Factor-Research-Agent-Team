"""eval-sandbox (P8.1): Python factors run only in fresh, hardened child processes.

The escape tests run each attempt twice: once as a factor (the static check and the
restricted namespace refuse it before it runs) and once as raw code after harden() with
full builtins, so the runtime layer is shown to hold on its own.
"""

import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np
import pytest
from qfr_core.ids import uuid7
from qfr_core.pyfactor import PythonLimits
from qfr_eval import sandbox
from qfr_eval.compute import ComputeRequest, InlineRunner
from qfr_eval.sandbox import (
    ExchangeTransport,
    LocalTransport,
    PythonComputeRequest,
    PythonRunner,
    SandboxJob,
    SandboxServer,
    run_job,
)

from tests.registry_rig import MOMENTUM_PY
from tests.synthetic_fixtures import ELIGIBILITY, PROTOCOL

GB = 1024**3
LIMITS = PythonLimits.from_protocol(PROTOCOL)
LOOKAHEAD_PY = """import numpy as np


def factor(close):
    out = np.full_like(close, np.nan)
    out[:-1] = close[1:] / close[:-1] - 1
    return out
"""
# Uses every row before the cut, not the declared 20: its value depends on how much
# history it is given, i.e. on its absolute row position.
CUMULATIVE_PY = """import numpy as np


def factor(close):
    return np.nancumsum(close, axis=0) / np.arange(1, close.shape[0] + 1)[:, np.newaxis]
"""
# Marks the first column it is given: shows the sandbox never sees the real order.
FIRST_COLUMN_PY = """import numpy as np


def factor(close):
    out = np.zeros_like(close)
    out[:, 0] = 1.0
    return out
"""


def job(source, rows=60, prefix=(), window=(), lookback=5, cpu=20.0, memory=2 * GB, **kw):
    return SandboxJob(
        job_id=str(uuid7()), source=source, parameters=kw.get("parameters", ["close"]),
        limits=LIMITS, rows=rows, prefix_cuts=list(prefix), window_cuts=list(window),
        lookback=lookback, cpu_seconds=cpu, memory_bytes=memory, wall_clock_factor=3.0,
    )  # fmt: skip


def inputs(tmp_path: Path, rows=60, columns=8) -> Path:
    rng = np.random.default_rng(1)
    path = tmp_path / "inputs.npz"
    np.savez(path, close=10 + rng.random((rows, columns)).cumsum(axis=0))
    return path


def run(tmp_path, source, **kw):
    return run_job(job(source, **kw), inputs(tmp_path), tmp_path)


def test_a_factor_runs_in_fresh_children_for_the_full_run_and_each_probe(tmp_path):
    result, arrays = run(tmp_path, MOMENTUM_PY, prefix=[30, 45], window=[40], lookback=20)
    assert result.status == "ok"
    assert [(r.kind, r.cut) for r in result.runs] == [
        ("full", None), ("prefix", 30), ("prefix", 45), ("window", 40),
    ]  # fmt: skip
    full = arrays["full"]
    assert full.shape == (60, 8)
    for cut, row in arrays["prefix"].items():
        np.testing.assert_array_equal(row, full[cut])
    np.testing.assert_array_equal(arrays["window"][40], full[40])


@pytest.mark.parametrize(
    ("name", "source"),
    [
        ("network", "import socket\ndef factor(close):\n    socket.socket()\n    return close"),
        ("network_via_import", "def factor(close):\n    return __import__('socket')"),
        ("filesystem_read", "def factor(close):\n    open('/etc/passwd')\n    return close"),
        ("filesystem_write", "import numpy as np\ndef factor(close):\n"
                             "    np.save('/tmp/x', close)\n    return close"),
        ("fork_bomb", "import os\ndef factor(close):\n    while True:\n        os.fork()"),
        ("subprocess", "import subprocess\ndef factor(close):\n"
                       "    subprocess.run(['true'])\n    return close"),
        ("introspection", "def factor(close):\n    return close.__class__.__mro__"),
    ],
)  # fmt: skip
def test_escape_attempts_are_refused_before_they_run(tmp_path, name, source):
    result, arrays = run(tmp_path, source)
    assert (result.status, result.error_code) == ("refused", "FORBIDDEN_CONSTRUCT"), name
    assert arrays == {} and result.runs[0].status == "refused"


def test_a_timeout_ends_the_child_with_the_cpu_limit(tmp_path):
    spin = "def factor(close):\n    while True:\n        pass\n"
    result, _ = run(tmp_path, spin, cpu=1.0)
    assert (result.status, result.error_code, result.limit) == (
        "runtime_limit", "RUNTIME_LIMIT", "cpu",
    )  # fmt: skip


def test_the_wall_clock_ends_a_child_the_cpu_limit_has_not(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox, "START_SECONDS", 0.0)
    spin = "def factor(close):\n    while True:\n        pass\n"
    result, _ = run_job(job(spin, cpu=30.0).model_copy(update={"wall_clock_factor": 0.05}),
                        inputs(tmp_path), tmp_path)  # fmt: skip
    assert (result.status, result.limit) == ("runtime_limit", "wall_clock")


def test_a_memory_bomb_ends_with_the_memory_limit(tmp_path):
    bomb = "import numpy as np\ndef factor(close):\n    return np.ones((200000, 200000))\n"
    result, _ = run(tmp_path, bomb, memory=1 * GB)
    assert (result.status, result.limit) == ("runtime_limit", "memory")


@pytest.mark.parametrize(
    "source",
    [
        "def factor(close):\n    return close[1:]",
        "def factor(close):\n    return 1.0",
        "def factor(close):\n    return close[10 ** 9]",
        "def factor(close):\n    return [x for x in range(10 ** 12)][0]",
    ],
)
def test_wrong_output_or_a_raised_error_is_a_type_error_without_detail(tmp_path, source):
    result, _ = run(tmp_path, source, memory=1 * GB, cpu=5.0)
    assert result.error_code in ("TYPE_ERROR", "RUNTIME_LIMIT")
    assert "message" not in result.model_dump_json()


RUNTIME_LAYER = r"""
import json, os, socket, subprocess, sys
from qfr_eval import sandbox_child as child
child.harden(30, 2 * 1024 ** 3)
child.ALLOWANCES.clear()
results = {}
def attempt(name, fn):
    try:
        fn()
        results[name] = "allowed"
    except BaseException as error:
        results[name] = type(error).__name__
attempt("open_read", lambda: open("/etc/hostname").read())
attempt("open_write", lambda: open("/tmp/sandbox-escape", "w").write("x"))
attempt("socket", lambda: socket.socket())
attempt("connect", lambda: socket.create_connection(("127.0.0.1", 9)))
attempt("fork", lambda: os.fork())
attempt("system", lambda: os.system("true"))
attempt("subprocess", lambda: subprocess.run(["true"]))
attempt("import_new_module", lambda: __import__("ctypes"))
attempt("compile", lambda: compile("1", "x", "eval"))
attempt("exec", lambda: exec("1"))
attempt("listdir", lambda: os.listdir("/"))
attempt("remove", lambda: os.remove("/tmp/anything"))
attempt("frames", lambda: sys._getframe())
sys.stdout.write(json.dumps(results))
"""


def test_the_runtime_layer_blocks_escapes_even_without_the_static_check(tmp_path):
    completed = subprocess.run(
        [sys.executable, "-I", "-c", RUNTIME_LAYER], capture_output=True, text=True,
        timeout=60, cwd=tmp_path, env=sandbox.CHILD_ENV | {"PYTHONPATH": ":".join(sys.path)},
    )  # fmt: skip
    results = json.loads(completed.stdout)
    assert len(results) == 13 and set(results.values()) == {"Violation"}, results
    assert not (tmp_path / "sandbox-escape").exists()
    assert not Path("/tmp/sandbox-escape").exists()


def test_python_values_match_the_same_factor_in_the_dsl(small_zones, tmp_path):
    rows = list(range(400, 440))
    dsl = InlineRunner().run(
        ComputeRequest(
            snapshot_path=str(small_zones.full.path), expression="$close / Ref($close, 20) - 1",
            dsl=PROTOCOL["dsl"], eligibility=ELIGIBILITY, rows=rows, probe_cuts=[405],
            tolerance=1e-9, cpu_seconds=60, memory_bytes=4 * GB, load_cpu_seconds=60,
            output_path=str(tmp_path / "v.npy"),
        )
    )  # fmt: skip
    python = python_run(small_zones, tmp_path, MOMENTUM_PY, rows=rows, probe_cuts=[405, 420])
    assert python.result.status == "ok"
    assert [p.mismatches for p in python.result.probes] == [0, 0]
    assert len(python.result.window_probes) == LIMITS.window_probe_dates
    assert all(p.mismatches == 0 for p in python.result.window_probes)
    np.testing.assert_array_equal(np.isnan(dsl.values), np.isnan(python.values))
    finite = np.isfinite(dsl.values)
    np.testing.assert_allclose(python.values[finite], dsl.values[finite], rtol=1e-12)


def python_run(zones, tmp_path, source, rows=None, probe_cuts=(), lookback=20, seed=7):
    request = PythonComputeRequest(
        snapshot_path=str(zones.full.path), source=source, parameters=["close"], limits=LIMITS,
        eligibility=ELIGIBILITY, rows=rows or list(range(400, 440)), probe_cuts=list(probe_cuts),
        lookback=lookback, tolerance=1e-9, cpu_seconds=30, memory_bytes=4 * GB, seed=seed,
    )  # fmt: skip
    return PythonRunner(LocalTransport(tmp_path / f"sandbox-{seed}"), 3.0).run(request)


def test_evl_03_the_prefix_probe_catches_a_python_lookahead(small_zones, tmp_path):
    output = python_run(small_zones, tmp_path, LOOKAHEAD_PY, probe_cuts=[405, 420])
    assert output.result.status == "ok"
    assert all(p.mismatches > 0 for p in output.result.probes)


def test_the_window_probe_catches_a_dishonest_lookback(small_zones, tmp_path):
    output = python_run(small_zones, tmp_path, CUMULATIVE_PY, probe_cuts=[405])
    assert output.result.status == "ok"
    assert [p.mismatches for p in output.result.probes] == [0]  # prefix-invariant ...
    assert sum(p.mismatches for p in output.result.window_probes) > 0  # ... but not honest


def test_the_sandbox_sees_instruments_in_a_seeded_order_only(small_zones, tmp_path):
    marked = set()
    for seed in range(1, 6):
        output = python_run(small_zones, tmp_path, FIRST_COLUMN_PY, seed=seed)
        columns = np.flatnonzero(output.values[0] == 1.0)
        assert len(columns) == 1
        marked.add(int(columns[0]))
    assert len(marked) > 1


def test_the_exchange_volume_round_trip_and_cleanup(tmp_path):
    root = tmp_path / "exchange"
    served: list[str] = []
    server = SandboxServer(root, lambda j, r: served.append(r.status))
    stop = threading.Event()

    def serve() -> None:
        while not stop.is_set():
            if not server.serve_once():
                time.sleep(0.02)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        source = inputs(tmp_path)
        transport = ExchangeTransport(root, poll_seconds=0.02)
        result, arrays = transport.submit(
            job(MOMENTUM_PY, prefix=[30], window=[40], lookback=20),
            lambda path: path.write_bytes(source.read_bytes()),
        )
        assert result.status == "ok" and arrays["full"].shape == (60, 8)
        np.testing.assert_array_equal(arrays["prefix"][30], arrays["full"][30])
        refused, _ = transport.submit(
            job("import os\ndef factor(close):\n    return close"),
            lambda path: path.write_bytes(source.read_bytes()),
        )
        assert refused.error_code == "FORBIDDEN_CONSTRUCT"
    finally:
        stop.set()
        thread.join(timeout=10)
    assert served == ["ok", "refused"]
    # Nothing is left behind: requests are claimed, results collected and removed.
    for folder in ("requests", "running", "results"):
        assert list((root / folder).iterdir()) == []


def test_the_server_drops_half_done_runs_and_sweeps_uncollected_results(tmp_path):
    root = tmp_path / "exchange"
    (root / "running" / "abc").mkdir(parents=True)
    (root / "results" / "old").mkdir(parents=True)
    server = SandboxServer(root, stale_seconds=60)
    assert server.recover() == 1 and list((root / "running").iterdir()) == []
    assert server.sweep(now=time.time() + 30) == 0
    assert server.sweep(now=time.time() + 120) == 1
