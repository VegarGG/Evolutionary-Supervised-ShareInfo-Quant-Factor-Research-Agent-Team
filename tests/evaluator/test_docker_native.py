"""Offline control-plane regressions. These never count as real SBX acceptance."""

import copy
import hashlib
import io
import json
import socket
import struct
import tarfile
import threading
import time
from pathlib import Path

import pytest
from pydantic import ValidationError
from qfr_core.contracts.execution import RunnerInput
from qfr_eval.sandbox.client import configured_runner
from qfr_eval.sandbox.controller import Controller, receive
from qfr_eval.sandbox.docker_api import DockerAPI, DockerBoundExceeded, DockerError
from qfr_eval.sandbox.models import (
    NATIVE_REQUIRED_CHECKS,
    DockerControllerConfiguration,
    DockerControllerRequest,
    DockerNativeProfile,
    DockerNativeReadiness,
    SandboxProfile,
)
from qfr_eval.sandbox.native import DockerNativeRunner
from qfr_eval.sandbox.native_plan import LABEL, SEAL_CHECK, container_spec, input_archive
from qfr_eval.sandbox.runner import SandboxCleanupError, SandboxRunner, SandboxUnavailable

IMAGE = "sha256:" + "0" * 64
JOB = "qfr-native-" + "0" * 32


@pytest.fixture
def native_profile():
    value = json.loads(Path("configs/evaluation/sandbox_docker_native_v1.json").read_text())
    value.update(
        scope="bounded_synthetic_acceptance",
        cpus=0.5,
        memory_bytes=134217728,
        cpu_seconds=3,
        timeout_seconds=5,
        tmpfs_bytes=2097152,
        max_input_bytes=65536,
        max_package_bytes=65536,
        max_output_bytes=65536,
        input_tmpfs_bytes=2097152,
        control_timeout_seconds=2,
    )
    return DockerNativeProfile.model_validate(value)


@pytest.fixture
def request_value():
    return RunnerInput.model_validate(
        {
            "schema_version": "1",
            "seed": 0,
            "tables": {"input": {"columns": [], "dtypes": [], "rows": []}},
        }
    )


def test_versioned_native_contract_cannot_relabel_legacy(native_profile, monkeypatch):
    with pytest.raises(ValidationError):
        SandboxProfile.model_validate(native_profile.model_dump())
    with pytest.raises(ValidationError):
        DockerNativeProfile.model_validate({**native_profile.model_dump(), "runtime": "runsc"})
    with pytest.raises(SandboxUnavailable, match="explicit native backend"):
        SandboxRunner(native_profile, IMAGE).readiness()
    monkeypatch.delenv("QFR_SANDBOX_CONTROLLER_SOCKET", raising=False)
    with pytest.raises(SandboxUnavailable, match="controller socket"):
        configured_runner(native_profile, IMAGE)


@pytest.mark.parametrize(
    "change",
    [
        {"pids_limit": 17},
        {"runtime": "runc --privileged"},
        {"user_id": 0},
        {"boundary": "gvisor"},
        {"seccomp_sha256": "0" * 64},
        {"input_tmpfs_bytes": 1},
        {"docker_socket": "/var/run/docker.sock"},
        {"process_accounting": "rlimit_nproc"},
    ],
)
def test_native_profile_rejects_unapproved_control_changes(native_profile, change):
    with pytest.raises(ValidationError):
        DockerNativeProfile.model_validate({**native_profile.model_dump(), **change})


def test_ready_cannot_be_claimed_by_an_empty_or_incomplete_check_map(native_profile):
    value = dict(
        schema_version="2",
        status="ready",
        profile_sha256=native_profile.sha256,
        image_digest=IMAGE,
        engine_os="linux",
        engine_architecture="aarch64",
        engine_version="test",
        engine_id_sha256="0" * 64,
        controller_os="darwin",
        controller_architecture="arm64",
        runtime="runc",
        boundary="docker_shared_kernel",
        checks={},
        reason_code="ok",
    )
    with pytest.raises(ValidationError):
        DockerNativeReadiness.model_validate(value)
    value["checks"] = {name: True for name in NATIVE_REQUIRED_CHECKS}
    valid = DockerNativeReadiness.model_validate(value)
    assert valid.controller_os == "darwin" and valid.engine_os == "linux"
    value["checks"]["cgroup_pids"] = False
    with pytest.raises(ValidationError):
        DockerNativeReadiness.model_validate(value)


def test_staging_archive_has_only_declared_files_no_host_mounts_and_fixed_modes(
    native_profile,
    request_value,
):
    data = input_archive(
        native_profile,
        {"nested/main.py": b"# never executed"},
        request_value,
        {"interface": "function", "function": "nested/main.py:run"},
    )
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        members = archive.getmembers()
        assert all(m.uid == m.gid == 65532 for m in members)
        assert all(m.mode == (0o555 if m.isdir() else 0o444) for m in members)
        assert all(m.isdir() or m.isreg() for m in members)
        assert {m.name for m in members if m.isreg()} == {
            "package/nested/main.py",
            "guest.py",
            "request.json",
            "options.json",
            "seal.json",
        }
        seal = json.load(archive.extractfile("seal.json"))
        for name, digest in seal.items():
            assert hashlib.sha256(archive.extractfile(name).read()).hexdigest() == digest
    spec = container_spec(native_profile, IMAGE, JOB, 0, helper=False)
    host = spec["HostConfig"]
    assert host["Binds"] == [] and host["Devices"] == []
    assert host["Mounts"] == [
        {
            "Type": "volume",
            "Source": JOB + "-input",
            "Target": "/input",
            "ReadOnly": True,
            "VolumeOptions": {"NoCopy": True},
        }
    ]
    assert not any(x["Name"] == "nproc" for x in host["Ulimits"])
    assert host["PidsLimit"] == 16


@pytest.mark.parametrize("name", ["../escape.py", "/private/file", "a/../b", "a\\b", "x\0y"])
def test_archive_rejects_host_path_and_traversal(native_profile, request_value, name):
    with pytest.raises(ValueError):
        input_archive(native_profile, {name: b"opaque"}, request_value, {})


class FakeEngine:
    """Records a lifecycle with realistic inspect fields, not a security proof."""

    def __init__(self, *, mutate=None, fail=None):
        self.objects = {}
        self.volume = None
        self.events = []
        self.mutate = mutate
        self.fail = fail

    def json(self, method, path, *, timeout, value=None):
        self.events.append((method, path))
        if path == "/volumes/create":
            self.volume = {**value, "Options": value["DriverOpts"]}
            if self.fail == "volume_timeout":
                raise TimeoutError()
            return self.volume
        if path.startswith("/volumes/"):
            if self.volume is None:
                raise DockerError(404)
            return self.volume
        if path.startswith("/containers/create?"):
            name = path.split("name=", 1)[1]
            actual = {
                "Config": {k: v for k, v in value.items() if k != "HostConfig"},
                "HostConfig": copy.deepcopy(value["HostConfig"]),
                "Image": value["Image"],
                "State": {"OOMKilled": False},
            }
            mount = value["HostConfig"]["Mounts"][0]
            actual["Mounts"] = [
                {
                    "Type": "volume",
                    "Name": mount["Source"],
                    "Destination": mount["Target"],
                    "RW": not mount["ReadOnly"],
                }
            ]
            self.objects[name] = actual
            if self.mutate:
                self.mutate(actual)
            return {"Id": "1" * 64}
        if path.startswith("/containers/"):
            name = path.split("/")[2]
            if name not in self.objects:
                raise DockerError(404)
            return self.objects[name]
        raise AssertionError(path)

    def request(self, method, path, *, timeout, body=None, **kwargs):
        self.events.append((method, path))
        if method == "DELETE":
            if self.fail == "cleanup":
                raise DockerError(500)
            if path.startswith("/containers/"):
                self.objects.pop(path.split("/")[2].split("?", 1)[0], None)
            else:
                self.volume = None
        return b""

    def exec(self, name, command, *, timeout, limit):
        self.events.append(("exec", name, command))
        if command[-1] == SEAL_CHECK:
            if self.fail == "seal":
                raise ValueError("seal mismatch")
            if not name.endswith("-stager"):
                assert name + "-stager" not in self.objects
            return b""
        if command[-1] == "--read":
            return json.dumps(
                {
                    "code": "ok",
                    "output": {
                        "schema_version": "1",
                        "kind": "data_product",
                        "tables": {
                            "result": {"columns": ["x"], "dtypes": ["Int64"], "rows": [[1]]}
                        },
                    },
                }
            ).encode()
        assert name + "-stager" not in self.objects
        return b""


def run_fake(native_profile, request_value, engine):
    runner = DockerNativeRunner(native_profile, IMAGE)
    runner.api = engine
    return runner._execute(
        {"main.py": b"# opaque"},
        request_value,
        {"interface": "function", "function": "main.py:run"},
    )


def test_lifecycle_keeps_mount_alive_then_removes_writer_before_execution(
    native_profile,
    request_value,
):
    engine = FakeEngine()
    result = run_fake(native_profile, request_value, engine)
    assert result.code == "ok" and result.isolation["input_sealed"]
    assert not engine.objects and engine.volume is None
    starts = [i for i, e in enumerate(engine.events) if e[0] == "POST" and e[1].endswith("/start")]
    deletes = [i for i, e in enumerate(engine.events) if e[0] == "DELETE"]
    assert len(starts) == 2 and starts[-1] < deletes[0]


@pytest.mark.parametrize(
    "key,value",
    [
        ("Runtime", "runsc"),
        ("Runtime", "sysbox-runc"),
        ("NetworkMode", "bridge"),
        ("Privileged", True),
        ("PidsLimit", 0),
        ("MemorySwap", -1),
        ("SecurityOpt", ["seccomp=unconfined"]),
        ("PidMode", "host"),
        ("CgroupnsMode", "host"),
        ("CapAdd", ["SYS_ADMIN"]),
    ],
)
def test_actual_control_mismatch_prevents_execution(native_profile, request_value, key, value):
    engine = FakeEngine(mutate=lambda item: item["HostConfig"].update({key: value}))
    result = run_fake(native_profile, request_value, engine)
    assert result.code == "failed:backend_unavailable"
    assert not any(e[0] == "exec" for e in engine.events)
    assert not engine.objects and engine.volume is None


@pytest.mark.parametrize("failure", ["volume_timeout", "seal", "cleanup"])
def test_partial_creation_and_uncertain_cleanup_never_return_success(
    native_profile,
    request_value,
    failure,
):
    engine = FakeEngine(fail=failure)
    if failure == "cleanup":
        with pytest.raises(SandboxCleanupError):
            run_fake(native_profile, request_value, engine)
    else:
        assert run_fake(native_profile, request_value, engine).code != "ok"
        assert not engine.objects and engine.volume is None


def test_controller_does_not_accept_arbitrary_docker_parameters(native_profile, monkeypatch):
    config = DockerControllerConfiguration(
        schema_version="1",
        profile=native_profile,
        image_digest=IMAGE,
        docker_socket="/tmp/fake.sock",
        control_socket="/tmp/control.sock",
        max_parallel_jobs=1,
    )
    controller = Controller(config)
    monkeypatch.setattr(controller.runner, "readiness", lambda: pytest.fail("no Docker operation"))
    request = DockerControllerRequest(
        schema_version="1",
        operation="readiness",
        profile_sha256=native_profile.sha256,
        image_digest=IMAGE,
        contract=None,
        request=None,
        package_base64=None,
    ).model_dump(mode="json")
    for change in (
        {"mounts": ["/private"]},
        {"image_digest": "sha256:" + "f" * 64},
        {"profile_sha256": "0" * 64},
        {"operation": "remove"},
    ):
        assert controller.dispatch(json.dumps({**request, **change}).encode()) == {
            "status": "unavailable"
        }


def test_frame_bound_precedes_body_read():
    left, right = socket.socketpair()
    try:
        left.sendall(struct.pack(">Q", 10**12))
        with pytest.raises(ValueError, match="exceeds bound"):
            receive(right, 100, time.monotonic() + 1)
    finally:
        left.close()
        right.close()


def test_cleanup_refuses_a_resource_with_another_owner(native_profile):
    runner = DockerNativeRunner(native_profile, IMAGE)
    engine = FakeEngine()
    engine.objects[JOB] = {"Config": {"Labels": {LABEL: "another-job"}}}
    runner.api = engine
    with pytest.raises(SandboxCleanupError, match="unowned"):
        runner._remove_container(JOB)
    assert not any(event[0] == "DELETE" for event in engine.events)


def test_restart_with_orphans_refuses_new_work_without_deletion(native_profile, monkeypatch):
    config = DockerControllerConfiguration(
        schema_version="1",
        profile=native_profile,
        image_digest=IMAGE,
        docker_socket="/tmp/fake.sock",
        control_socket="/tmp/control.sock",
        max_parallel_jobs=1,
    )
    controller = Controller(config)
    calls = []

    def response(method, path, **kwargs):
        calls.append(method)
        return [{"Id": "previous-job"}] if path.startswith("/containers/") else {"Volumes": []}

    monkeypatch.setattr(controller.runner.api, "json", response)
    with pytest.raises(SandboxUnavailable, match="predecessor cleanup"):
        controller.require_quiescent_start()
    assert calls == ["GET", "GET"]


def test_controller_poisoned_after_unverifiable_cleanup(native_profile, monkeypatch):
    config = DockerControllerConfiguration(
        schema_version="1",
        profile=native_profile,
        image_digest=IMAGE,
        docker_socket="/tmp/fake.sock",
        control_socket="/tmp/control.sock",
        max_parallel_jobs=1,
    )
    controller = Controller(config)
    calls = []

    def fail():
        calls.append("probe")
        raise SandboxCleanupError("synthetic cleanup failure")

    monkeypatch.setattr(controller.runner, "readiness", fail)
    request = (
        DockerControllerRequest(
            schema_version="1",
            operation="readiness",
            profile_sha256=native_profile.sha256,
            image_digest=IMAGE,
            contract=None,
            request=None,
            package_base64=None,
        )
        .model_dump_json()
        .encode()
    )
    assert controller.dispatch(request) == {"status": "cleanup_uncertain"}
    assert controller.dispatch(request) == {"status": "unavailable"}
    assert calls == ["probe"]


@pytest.mark.parametrize("kind", ["oversize", "slow", "stderr", "truncated"])
def test_docker_transport_limits_truncated_or_slow_streams(tmp_path, kind):
    path = str(tmp_path / "engine.sock")
    server = socket.socket(socket.AF_UNIX)
    server.bind(path)
    server.listen(1)

    def worker():
        conn, _ = server.accept()
        with conn:
            conn.recv(4096)
            try:
                conn.sendall(b"HTTP/1.0 200 OK\r\nContent-Type: application/octet-stream\r\n\r\n")
                if kind == "slow":
                    for _ in range(20):
                        conn.sendall(b"x")
                        time.sleep(0.03)
                elif kind == "oversize":
                    conn.sendall(b"x" * 100)
                elif kind == "stderr":
                    conn.sendall(b"\2\0\0\0" + struct.pack(">I", 1) + b"x")
                else:
                    conn.sendall(b"\1\0\0\0" + struct.pack(">I", 5) + b"x")
            except OSError:
                pass

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    start = time.monotonic()
    try:
        expected = {
            "slow": TimeoutError,
            "oversize": DockerBoundExceeded,
            "stderr": ValueError,
            "truncated": ValueError,
        }[kind]
        with pytest.raises(expected):
            DockerAPI(path).request(
                "GET", "/test", timeout=0.2, limit=50, raw_stream=kind in ("stderr", "truncated")
            )
        assert time.monotonic() - start < 1
    finally:
        thread.join(timeout=2)
        server.close()
        assert not thread.is_alive()
