"""The sandbox child: one run of one qfr-python/1 factor (PLAN P8.1, Section 17.2).

The sandbox server starts this module as a fresh interpreter for every run, so nothing
can carry over between the full computation and the probe runs. The child
  1. reads its request from stdin and loads the input matrices it was given;
  2. keeps only the rows of its run (a prefix or a trailing window) and drops the rest;
  3. checks the source again (qfr_core.pyfactor) and compiles it;
  4. hardens itself: CPU seconds, address space, no file writes, no new processes or
     threads, no core files, and an audit hook that refuses imports, file opens,
     sockets, subprocesses, ctypes and any further exec or compile;
  5. runs the module in a namespace that holds only the allowed builtins, an np object
     with the allowed numpy names and the math names, and calls factor(...);
  6. writes the result matrix to stdout (rows and columns as two little-endian int64,
     then the float64 values in C order), and nothing else.
The exit status is the only other output: the parent maps it to an enum code. Anything
the code prints or raises goes to stderr, which the parent discards (INV-12).

In the eval-sandbox container these limits add to the container's own: no network
(network_mode: none), a read-only root filesystem, no capabilities, a process limit
and memory and CPU limits. gVisor is not available on Docker Desktop for Mac, so these
layers are the isolation (decisions.md, Phase 8).
"""

import json
import math
import resource
import sys
import types
from typing import Any

EXIT_OK = 0
EXIT_MEMORY = 77
EXIT_VIOLATION = 78
EXIT_RAISED = 79
EXIT_OUTPUT = 80
EXIT_REFUSED = 81
EXIT_REQUEST = 82

# Audit events the factor may never trigger. "exec" and "compile" are allowed once each,
# for the module itself, before the hook is armed.
BLOCKED_EVENTS = (
    "open", "import", "exec", "compile", "socket.", "subprocess.", "os.", "shutil.",
    "ctypes.", "urllib.", "http.", "ftplib.", "smtplib.", "poplib.", "imaplib.", "nntplib.",
    "telnetlib.", "webbrowser.", "glob.", "pty.", "fcntl.", "mmap.", "resource.",
    "signal.", "sys._getframe", "sys._current_frames", "sys.setprofile", "sys.settrace",
    "sys.addaudithook", "code.", "marshal.", "pickle.", "builtins.input", "cpython.",
    "function.__new__", "object.__setattr__", "object.__delattr__", "sqlite3.",
    "tempfile.", "syslog.", "winreg.", "msvcrt.", "_winapi.", "array.__new__",
    "gc.get_referrers", "gc.get_referents", "gc.get_objects",
)  # fmt: skip


class Violation(RuntimeError):
    pass


VIOLATIONS: list[str] = []
# The one exec the child itself performs after the hook is armed: the module body.
ALLOWANCES = {"exec": 1}


def _hook(event: str, args: tuple[Any, ...]) -> None:
    if ALLOWANCES.get(event, 0) > 0:
        ALLOWANCES[event] -= 1
        return
    for blocked in BLOCKED_EVENTS:
        if event == blocked or (blocked.endswith(".") and event.startswith(blocked)):
            VIOLATIONS.append(event)
            raise Violation(f"blocked by the sandbox: {event}")


def harden(cpu_seconds: float, memory_bytes: int) -> None:
    """Resource limits, then the audit hook. Irreversible for this process."""
    soft = max(1, int(math.ceil(cpu_seconds)))
    used = resource.getrusage(resource.RUSAGE_SELF)
    spent = int(math.ceil(used.ru_utime + used.ru_stime))
    resource.setrlimit(resource.RLIMIT_CPU, (spent + soft, spent + soft + 2))
    resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NPROC, (0, 0))
    sys.addaudithook(_hook)


def safe_builtins() -> dict[str, Any]:
    import builtins

    from qfr_core.pyfactor import BUILTINS

    out = {name: getattr(builtins, name) for name in BUILTINS if hasattr(builtins, name)}
    out["True"], out["False"], out["None"] = True, False, None
    # The import statement calls __import__; this one hands out only the allowed objects.
    return out


def namespace(np_module: Any) -> dict[str, Any]:
    """The module's globals: the allowed builtins, np and math, nothing else."""
    from numpy.lib.stride_tricks import sliding_window_view
    from qfr_core.pyfactor import MATH_NAMES, NUMPY_NAMES

    np_view = types.SimpleNamespace()
    for name in sorted(NUMPY_NAMES):
        value = sliding_window_view if name == "sliding_window_view" else getattr(np_module, name)
        setattr(np_view, name, value)
    math_view = types.SimpleNamespace(**{name: getattr(math, name) for name in MATH_NAMES})
    allowed = {"numpy": np_view, "math": math_view}

    def importer(name: str, *args: Any, **kwargs: Any) -> Any:
        if name not in allowed:
            raise Violation(f"import {name} is not allowed")
        return allowed[name]

    builtins = safe_builtins() | {"__import__": importer}
    return {"__builtins__": builtins, "__name__": "factor_module", "np": np_view, "math": math_view}


def _warm(np_module: Any) -> None:
    """Touch every allowed numpy routine once so no lazy import happens after hardening."""
    a = np_module.arange(24, dtype=np_module.float64).reshape(6, 4)
    a[0, 0] = np_module.nan
    np_module.nanquantile(a, 0.5, axis=0)
    np_module.nanpercentile(a, 50, axis=1)
    np_module.nanmedian(a, axis=0)
    np_module.argsort(a, axis=1)
    np_module.corrcoef(a[1:].T)
    np_module.cov(a[1:].T)
    np_module.einsum("ij,ij->i", a, a)
    np_module.pad(a, 1, mode="edge")
    np_module.unique(a)
    np_module.lib.stride_tricks.sliding_window_view(a, 2, axis=0)
    np_module.searchsorted(np_module.arange(3), 1)
    np_module.round(a, 2)
    np_module.isclose(a, a)
    np_module.take_along_axis(a, np_module.argsort(a, axis=0), axis=0)
    np_module.average(a[1:], axis=0)
    np_module.ptp(a[1:], axis=0)
    np_module.heaviside(a, 0.5)


def main() -> int:
    try:
        request = json.loads(sys.stdin.buffer.read().decode("utf-8"))
        import numpy as np
        from qfr_core.pyfactor import PythonLimits, check_source

        with np.load(request["inputs_path"], allow_pickle=False) as archive:
            start, stop = int(request["start"]), int(request["stop"])
            matrices = {
                name: np.ascontiguousarray(archive[name][start:stop])
                for name in request["parameters"]
            }
        limits = PythonLimits.model_validate(request["limits"])
        source = str(request["source"])
        shape = next(iter(matrices.values())).shape
    except Exception:  # noqa: BLE001 - the request itself is the parent's; no detail leaves
        return EXIT_REQUEST
    check = check_source(source, limits)
    if not check.ok or check.analysis is None:
        return EXIT_REFUSED
    if check.analysis.parameters != list(request["parameters"]):
        return EXIT_REFUSED
    code = compile(source, "<factor>", "exec", dont_inherit=True)
    globals_ = namespace(np)
    _warm(np)
    out = sys.stdout.buffer
    harden(float(request["cpu_seconds"]), int(request["memory_bytes"]))
    try:
        exec(code, globals_)  # noqa: S102 - checked source, restricted namespace, hardened
        values = globals_["factor"](*[matrices[p] for p in request["parameters"]])
        if VIOLATIONS:
            return EXIT_VIOLATION
        if not isinstance(values, np.ndarray) or values.shape != shape:
            return EXIT_OUTPUT
        result = np.asarray(values, dtype=np.float64)
    except MemoryError:
        return EXIT_VIOLATION if VIOLATIONS else EXIT_MEMORY
    except Violation:
        return EXIT_VIOLATION
    except BaseException:  # noqa: BLE001 - any failure of the factor is one code
        return EXIT_VIOLATION if VIOLATIONS else EXIT_RAISED
    if VIOLATIONS:
        return EXIT_VIOLATION
    header = np.array(result.shape, dtype="<i8").tobytes()
    out.write(header + np.ascontiguousarray(result, dtype="<f8").tobytes())
    out.flush()
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
