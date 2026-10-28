"""Bounded trusted fixtures: no candidate execution or real OOM/fork stress here."""

import json
import os
import signal
import subprocess
from contextlib import contextmanager

import pytest
from qfr_core import sandbox_native as supervisor


@pytest.mark.parametrize(
    "after,status,expected",
    [
        (supervisor.Events(0, 0, 0), 0, None),
        (supervisor.Events(1, 1, 0), -signal.SIGKILL, "failed:memory"),
        (supervisor.Events(1, 0, 0), 0, "failed:memory"),
        (supervisor.Events(0, 0, 1), 0, "failed:process_limit"),
        (supervisor.Events(0, 0, 1), 137, "failed:process_limit"),
        (supervisor.Events(1, 1, 1), 0, "failed:memory"),
        (supervisor.Events(0, 0, 0), -signal.SIGKILL, "failed:runtime"),
        (supervisor.Events(0, 0, 0), 137, "failed:runtime"),
        (supervisor.Events(0, 0, 0), 152, "failed:runtime"),
        (supervisor.Events(0, 0, 0), -signal.SIGXCPU, "failed:cpu_limit"),
        (supervisor.Events(0, 0, 0), -signal.SIGXFSZ, "failed:output_limit"),
    ],
)
def test_only_kernel_events_establish_oom_or_pid_exhaustion(after, status, expected):
    assert supervisor.failure(supervisor.Events(0, 0, 0), after, status) == expected


@pytest.mark.parametrize("after", [(0, 1, 1), (1, 0, 1), (1, 1, 0)])
def test_backward_counters_are_not_accepted(after):
    with pytest.raises(ValueError, match="backwards"):
        supervisor.failure(supervisor.Events(1, 1, 1), supervisor.Events(*after), 0)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "oom 0\n",
        "oom 0\noom 1\noom_kill 0\n",
        "oom -1\noom_kill 0\n",
        "oom nope\noom_kill 0\n",
        "oom 18446744073709551616\noom_kill 0\n",
        "oom 0 ignored\noom_kill 0\n",
        "x" * 4097,
    ],
)
def test_missing_ambiguous_or_invalid_counters_fail(tmp_path, text):
    source = tmp_path / "events"
    source.write_text(text)
    with source.open("rb") as stream, pytest.raises(ValueError):
        supervisor.read_events(stream.fileno(), {"oom", "oom_kill"})


def test_counter_handles_are_fixed_readonly_and_not_inherited(tmp_path, monkeypatch):
    memory = tmp_path / "memory.events"
    memory.write_text("low 0\nmax 12\noom 0\noom_kill 0\n")
    (tmp_path / "pids.events").write_text("max 0\n")
    opened = []
    original = os.open

    def track(path, flags):
        assert flags & os.O_NOFOLLOW and flags & os.O_CLOEXEC
        assert flags & os.O_ACCMODE == os.O_RDONLY
        fd = original(path, flags)
        assert not os.get_inheritable(fd)
        opened.append(fd)
        return fd

    monkeypatch.setattr(supervisor.os, "open", track)
    with supervisor.open_events(tmp_path) as observe:
        assert observe() == supervisor.Events(0, 0, 0)
        memory.rename(tmp_path / "original.events")
        memory.write_text("oom 500\noom_kill 500\n")
        # A replaced path cannot spoof the already-open observation.
        assert observe() == supervisor.Events(0, 0, 0)
    for fd in opened:
        with pytest.raises(OSError):
            os.fstat(fd)


def test_observer_refuses_symlinks(tmp_path):
    (tmp_path / "target").write_text("oom 0\noom_kill 0\n")
    (tmp_path / "memory.events").symlink_to(tmp_path / "target")
    with pytest.raises(OSError), supervisor.open_events(tmp_path):
        pytest.fail("symlink was accepted")


def test_counter_fifo_is_rejected_without_blocking(tmp_path):
    os.mkfifo(tmp_path / "memory.events")
    with pytest.raises(ValueError, match="counter file"), supervisor.open_events(tmp_path):
        pytest.fail("FIFO was accepted")


@pytest.mark.parametrize("mode", ["ok", "oom", "pids", "killed", "unreadable", "dirty"])
def test_supervisor_collects_without_spawning_a_result_reader(monkeypatch, capsys, mode):
    state = [supervisor.Events(0, 0, 0)]
    calls = []

    @contextmanager
    def monitor():
        def read():
            if mode == "unreadable":
                raise OSError("private diagnostic never exported")
            if mode == "dirty":
                return supervisor.Events(1, 0, 0)
            return state[0]

        yield read

    def execute(command, **kwargs):
        calls.append(command)
        assert command == [supervisor.sys.executable, "-s", "-P", "-B", "/input/guest.py"]
        assert kwargs == {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "close_fds": True,
            "check": False,
        }
        if mode == "oom":
            state[0] = supervisor.Events(1, 1, 0)
        if mode == "pids":
            state[0] = supervisor.Events(0, 0, 2)
        return subprocess.CompletedProcess(command, -signal.SIGKILL if mode == "killed" else 0)

    monkeypatch.setattr(supervisor, "open_events", monitor)
    monkeypatch.setattr(supervisor.subprocess, "run", execute)
    monkeypatch.setattr(supervisor, "read_result", lambda: calls.append("bounded reader"))
    if mode in {"unreadable", "dirty"}:
        with pytest.raises(SystemExit) as error:
            supervisor.main()
        assert error.value.code == 95
        assert not calls
    else:
        supervisor.main()
        assert len(calls) == (2 if mode == "ok" else 1)
    output = capsys.readouterr()
    assert not output.err
    if mode in {"oom", "pids", "killed"}:
        code = {"oom": "memory", "pids": "process_limit", "killed": "runtime"}[mode]
        assert json.loads(output.out) == {"code": "failed:" + code, "output": None}
    else:
        assert not output.out
