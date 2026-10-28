"""Small stdlib-only bridge. The Linux isolation backend is the security boundary.

No evaluator imports, secrets or protocol values belong here. Candidate exception
text and stdout are never diagnostics. Only one bounded JSON envelope is exported.
"""

import errno
import importlib.util
import json
import os
import random
import resource
import signal
import stat
import subprocess
import sys
from pathlib import Path


def _code(error: BaseException) -> str:
    if isinstance(error, MemoryError):
        return "failed:memory"
    if isinstance(error, OSError):
        if error.errno in (errno.ENETUNREACH, errno.EHOSTUNREACH, errno.ECONNREFUSED):
            return "failed:network"
        if error.errno == errno.EAGAIN:
            return "failed:process_limit"
        if error.errno in (errno.EFBIG, errno.ENOSPC):
            return "failed:output_limit"
        if error.errno in (errno.EACCES, errno.EPERM, errno.EROFS, errno.ENOENT):
            return "failed:filesystem"
    return "failed:runtime"


def main() -> None:
    # This process runs inside the selected validated sandbox. The evaluator
    # enforces external cleanup. Even a candidate that exits or tampers with this bridge
    # cannot cause host execution or bypass the parent's output validation.
    options = json.loads(Path("/input/options.json").read_bytes())
    if options.get("process_accounting", "rlimit_nproc") == "cgroup_total_tasks":
        # Linux RLIMIT_NPROC counts a real UID across containers. The native
        # backend instead bounds *all* container tasks, including trusted ones.
        actual = Path("/sys/fs/cgroup/pids.max").read_text().strip()
        if actual != str(options["pids_limit"]):
            raise RuntimeError("native task limit not established")
    elif options.get("process_accounting", "rlimit_nproc") == "rlimit_nproc":
        resource.setrlimit(resource.RLIMIT_NPROC, (options["process_limit"],) * 2)
    else:
        raise RuntimeError("unsupported task accounting")
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.umask(0o077)
    os.chdir("/input/package")
    signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
    result = Path("/tmp/qfr-result.json")
    for fd in (0, 1, 2):
        with open(os.devnull, "rb" if fd == 0 else "wb") as stream:
            os.dup2(stream.fileno(), fd)
    try:
        request = json.loads(Path("/input/request.json").read_bytes())
        random.seed(request["seed"])
        if importlib.util.find_spec("numpy") is not None:
            import numpy as np

            np.random.seed(request["seed"])
        if options["interface"] == "function":
            module_path, function = options["function"].split(":")
            spec = importlib.util.spec_from_file_location("qfr_candidate", module_path)
            if spec is None or spec.loader is None:
                raise ValueError("invalid module")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            value = getattr(module, function)(request)
        else:
            stdout = Path("/tmp/command-output.json")
            with stdout.open("wb") as stream:
                completed = subprocess.run(
                    options["command"],
                    input=json.dumps(request, allow_nan=False).encode(),
                    stdout=stream,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            if completed.returncode:
                code = {
                    -signal.SIGXCPU: "failed:cpu_limit",
                    -signal.SIGXFSZ: "failed:output_limit",
                }.get(completed.returncode, "failed:runtime")
                result.write_text(json.dumps({"code": code, "output": None}))
                return
            if stdout.stat().st_size > options["max_output_bytes"]:
                raise OSError(errno.EFBIG, "bounded output")
            value = json.loads(stdout.read_bytes())
            stdout.unlink()
        # Iterative encoding enforces the cap without constructing a second
        # unbounded serialized copy in memory. The OS also limits every file.
        total = 0
        with result.open("wb") as stream:
            for chunk in json.JSONEncoder(allow_nan=False, separators=(",", ":")).iterencode(
                {"code": "ok", "output": value}
            ):
                data = chunk.encode()
                total += len(data)
                if total > options["max_output_bytes"]:
                    raise OSError(errno.EFBIG, "bounded output")
                stream.write(data)
    except BaseException as exc:
        # No exception message, traceback, source or execution-produced text.
        result.write_text(json.dumps({"code": _code(exc), "output": None}))


def read_result() -> None:
    """Read one regular tmpfs file through the parent's bounded stdout channel.

    Docker archive/cp reads its mount namespace, which is not gVisor's tmpfs.
    This reader stays inside the same sandbox and follows no candidate symlink.
    """
    try:
        limit = json.loads(Path("/input/options.json").read_bytes())["max_output_bytes"]
        fd = os.open("/tmp/qfr-result.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
                raise ValueError("invalid result file")
            data = stream.read(limit + 1)
            if len(data) > limit or len(data) != before.st_size:
                raise ValueError("unstable result file")
        sys.stdout.buffer.write(data)
    except (OSError, ValueError, KeyError):
        raise SystemExit(94) from None


if __name__ == "__main__":
    if sys.argv[1:] == ["--read"]:
        read_result()
    else:
        main()
