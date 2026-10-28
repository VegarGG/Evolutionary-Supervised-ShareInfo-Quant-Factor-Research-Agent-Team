"""Trusted native-only supervisor; runs inside the existing capped job container.

The child cannot consume the PID needed to collect its result: this process is
already running. Kernel cgroup events, not exit 137 or a candidate error string,
identify resource exhaustion. No additional limits, privileges or mounts.
"""

import json
import os
import signal
import stat
import subprocess
import sys
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path

from qfr_core.sandbox_guest import read_result


@dataclass(frozen=True)
class Events:
    oom: int
    oom_kill: int
    pids_max: int


def read_events(fd: int, required: set[str]) -> dict[str, int]:
    os.lseek(fd, 0, os.SEEK_SET)
    data = os.read(fd, 4097)
    if not data or len(data) > 4096:
        raise ValueError("unobservable resource events")
    values: dict[str, int] = {}
    for line in data.decode("ascii").splitlines():
        key, text = line.split()
        if key in values or not text.isascii() or not text.isdecimal():
            raise ValueError("invalid resource events")
        value = int(text)
        if value > 2**64 - 1:
            raise ValueError("invalid resource event counter")
        values[key] = value
    if not required <= values.keys():
        raise ValueError("required resource counters unavailable")
    return values


@contextmanager
def open_events(root: Path = Path("/sys/fs/cgroup")) -> Iterator[Callable[[], Events]]:
    # Open before candidate execution and keep non-inherited read-only FDs to the
    # same kernel objects. Candidate-created paths cannot replace the observer.
    with ExitStack() as stack:

        def counter(name: str) -> int:
            fd = os.open(root / name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
            stack.callback(os.close, fd)
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise ValueError("resource event source is not a kernel counter file")
            return fd

        memory, pids = counter("memory.events"), counter("pids.events")

        def observe() -> Events:
            mem = read_events(memory, {"oom", "oom_kill"})
            tasks = read_events(pids, {"max"})
            return Events(mem["oom"], mem["oom_kill"], tasks["max"])

        yield observe


def failure(before: Events, after: Events, returncode: int) -> str | None:
    initial = (before.oom, before.oom_kill, before.pids_max)
    final = (after.oom, after.oom_kill, after.pids_max)
    if any(right < left for left, right in zip(initial, final, strict=True)):
        raise ValueError("resource counters moved backwards")
    # A combined resource failure is classified as memory first, then PID limit.
    # A plain SIGKILL does not establish OOM; successful output cannot hide events.
    if after.oom > before.oom or after.oom_kill > before.oom_kill:
        return "failed:memory"
    if after.pids_max > before.pids_max:
        return "failed:process_limit"
    if returncode == -signal.SIGXCPU:
        return "failed:cpu_limit"
    if returncode == -signal.SIGXFSZ:
        return "failed:output_limit"
    return "failed:runtime" if returncode else None


def main() -> None:
    try:
        with open_events() as observe:
            before = observe()  # Missing evidence prevents any candidate launch.
            if before != Events(0, 0, 0):
                raise ValueError("fresh job already exhausted resources before execution")
            child = subprocess.run(
                [sys.executable, "-s", "-P", "-B", "/input/guest.py"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                check=False,
            )
            code = failure(before, observe(), child.returncode)
        if code is not None:
            print(json.dumps({"code": code, "output": None}, separators=(",", ":")))
        else:
            # This is a function call in the surviving supervisor, not a new
            # Docker exec or process. Keep the existing no-follow/bounded reader.
            read_result()
    except (OSError, ValueError, UnicodeError):
        # Distinguish missing observer evidence from candidate/runtime failure.
        # Do not expose exception messages, source, paths or daemon diagnostics.
        raise SystemExit(95) from None


if __name__ == "__main__":
    main()
