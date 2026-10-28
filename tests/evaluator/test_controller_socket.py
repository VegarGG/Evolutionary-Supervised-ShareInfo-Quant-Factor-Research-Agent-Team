"""Controller-only permission diagnosis; never modifies a real Docker socket."""

import os
import socket
import stat
from types import SimpleNamespace

import pytest
from qfr_eval.sandbox import socket_check


@pytest.mark.parametrize("groups,permitted", [([20], False), ([0], True)])
def test_container_mount_gid_not_mac_host_gid_controls_access(monkeypatch, groups, permitted):
    observation = SimpleNamespace(st_uid=0, st_gid=0, st_mode=stat.S_IFSOCK | 0o660)
    monkeypatch.setattr(socket_check.Path, "stat", lambda _: observation)
    monkeypatch.setattr(socket_check.os, "geteuid", lambda: 65532)
    monkeypatch.setattr(socket_check.os, "getegid", lambda: 65532)
    monkeypatch.setattr(socket_check.os, "getgroups", lambda: groups)
    calls = []

    def allowed(path, mode, **kwargs):
        calls.append((path, mode, kwargs))
        return permitted

    monkeypatch.setattr(socket_check.os, "access", allowed)
    monkeypatch.setattr(socket_check.os, "supports_effective_ids", {allowed})
    observed = socket_check.socket_access("/var/run/docker.sock")
    assert observed["socket_gid"] == 0 and observed["effective_uid"] == 65532
    assert observed["supplementary_groups"] == groups
    assert observed["connect_permission"] is permitted
    assert calls == [("/var/run/docker.sock", os.W_OK, {"effective_ids": True})]
    if permitted:
        socket_check.require_socket_access("/var/run/docker.sock")
    else:
        with pytest.raises(ValueError, match="inside this container"):
            socket_check.require_socket_access("/var/run/docker.sock")


def test_socket_diagnostic_does_not_connect_or_change_permissions(tmp_path, monkeypatch):
    # Short path is independently important on macOS; this is a synthetic socket.
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory(prefix="qfr-perm-", dir="/tmp") as directory:
        path = Path(directory) / "s"
        with socket.socket(socket.AF_UNIX) as server:
            server.bind(str(path))
            before = path.stat()
            monkeypatch.setattr(socket_check.os, "chmod", lambda *a: pytest.fail("no chmod"))
            monkeypatch.setattr(socket_check.os, "chown", lambda *a: pytest.fail("no chown"))
            observed = socket_check.socket_access(str(path))
            socket_check.require_socket_access(str(path))
            after = path.stat()
            assert observed["socket"] and observed["connect_permission"]
            assert (before.st_uid, before.st_gid, before.st_mode) == (
                after.st_uid,
                after.st_gid,
                after.st_mode,
            )
    file = tmp_path / "regular-file"
    file.write_text("synthetic non-socket")
    with pytest.raises(ValueError, match="access denied"):
        socket_check.require_socket_access(str(file))
    with pytest.raises(ValueError, match="missing or unreadable"):
        socket_check.require_socket_access(str(tmp_path / "absent"))


def test_platform_without_effective_access_requires_equal_real_and_effective_ids(
    tmp_path, monkeypatch
):
    path = tmp_path / "fixture"
    path.touch()
    monkeypatch.setattr(socket_check.os, "supports_effective_ids", set())
    monkeypatch.setattr(socket_check.os, "getuid", lambda: 501)
    monkeypatch.setattr(socket_check.os, "geteuid", lambda: 65532)
    with pytest.raises(ValueError, match="cannot be observed"):
        socket_check.socket_access(str(path))
    monkeypatch.setattr(socket_check.os, "geteuid", lambda: 501)
    monkeypatch.setattr(socket_check.os, "getgid", lambda: 20)
    monkeypatch.setattr(socket_check.os, "getegid", lambda: 20)
    assert socket_check.socket_access(str(path))["connect_permission"]
