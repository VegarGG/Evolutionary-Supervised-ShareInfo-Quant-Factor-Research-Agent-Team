"""Bounded Docker/runsc control. This module runs only in the trusted evaluator.

Candidate code is never imported by this process. All bind mounts are read-only;
the single result is copied from bounded tmpfs before the container is destroyed.
"""

import hashlib
import io
import json
import os
import re
import selectors
import signal
import subprocess
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

import polars as pl
from qfr_core import sandbox_guest
from qfr_core.contracts.execution import RunnerInput, RunnerOutput
from qfr_core.contracts.intake import ExecutionContract
from qfr_core.data_layer.snapshots import canonical_json
from qfr_core.runner_tables import unpack_table

from qfr_eval.sandbox.models import (
    SandboxCode,
    SandboxProfile,
    SandboxProfileValue,
    SandboxReadiness,
    SandboxReadinessValue,
)


class SandboxUnavailable(RuntimeError):
    """No executable acceptance without a validated backend."""


class SandboxCleanupError(RuntimeError):
    """Uncertain cleanup must never be reported as successful execution."""


class _BoundExceeded(RuntimeError):
    pass


@dataclass(frozen=True)
class ExecutionResult:
    code: SandboxCode
    output: RunnerOutput | None
    output_sha256: str | None
    isolation: dict[str, bool]


_PROBE = """
import ctypes, importlib.util, os, pathlib, resource, socket
def run(value):
    status = {x.split(":", 1)[0]: x.split(":", 1)[1].strip()
              for x in pathlib.Path("/proc/self/status").read_text().splitlines()
              if x.startswith(("CapEff:", "CapBnd:"))}
    checks = {
      "non_root": os.getuid() != 0,
      "dropped_capabilities": int(status["CapEff"],16) == int(status["CapBnd"],16) == 0,
      "no_new_privileges": ctypes.CDLL(None).prctl(39,0,0,0,0) == 1,
      "no_external_interface": [name for _,name in socket.if_nameindex()] == ["lo"],
      "no_private_packages": importlib.util.find_spec("qfr_eval") is None,
      "no_private_assets": not any(pathlib.Path(p).exists() for p in
          ("/workspace", "/eval", "/run/secrets", "/var/run/docker.sock", "/evidence")),
      "bounded_cpu": resource.getrlimit(resource.RLIMIT_CPU)[0] > 0,
      "bounded_file": resource.getrlimit(resource.RLIMIT_FSIZE)[0] > 0,
      "bounded_processes": resource.getrlimit(resource.RLIMIT_NPROC)[0] > 0,
    }
    try:
        pathlib.Path("/var/tmp/qfr-root-write-probe").write_text("probe")
        checks["read_only_root"] = False
    except OSError as e:
        checks["read_only_root"] = e.errno == 30
    with socket.socket() as s:
        s.settimeout(0.25)
        try:
            s.connect(("203.0.113.1",9))
            checks["network_denied"] = False
        except OSError:
            checks["network_denied"] = True
    return {"schema_version":"1", "kind":"data_product", "tables":{"checks":{
      "columns":["check","passed"], "dtypes":["String","Boolean"],
      "rows":[[k,v] for k,v in sorted(checks.items())]}}}
"""


def _relative_file(name: str) -> str:
    path = PurePosixPath(name)
    if (
        not name
        or path.is_absolute()
        or "\\" in name
        or any(part in (".", "..", "") for part in name.split("/"))
        or any(ord(char) < 32 for char in name)
    ):
        raise ValueError("unsafe package file")
    return path.as_posix()


def unpack_package(data: bytes, profile: SandboxProfileValue) -> dict[str, bytes]:
    if len(data) > profile.max_package_bytes:
        raise ValueError("package exceeds configured byte bound")
    result: dict[str, bytes] = {}
    total = 0
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if len(archive.infolist()) > profile.max_package_files:
            raise ValueError("package exceeds configured file bound")
        for entry in archive.infolist():
            name = _relative_file(entry.filename)
            mode = entry.external_attr >> 16
            if entry.is_dir() or (mode & 0o170000) not in (0, 0o100000) or name in result:
                raise ValueError("package requires unique regular files")
            total += entry.file_size
            if total > profile.max_package_bytes or entry.flag_bits & 1:
                raise ValueError("package expansion or encryption is unsupported")
            result[name] = archive.read(entry)
    return result


def decode_result(data: bytes, limit: int) -> ExecutionResult:
    if len(data) > limit:
        return ExecutionResult("failed:output_limit", None, None, {})
    try:
        envelope = json.loads(data)
        if not isinstance(envelope, dict) or set(envelope) != {"code", "output"}:
            raise ValueError("invalid envelope")
        code = envelope["code"]
        if code != "ok":
            allowed: tuple[SandboxCode, ...] = (
                "failed:network",
                "failed:filesystem",
                "failed:process_limit",
                "failed:memory",
                "failed:cpu_limit",
                "failed:timeout",
                "failed:output_limit",
                "failed:runtime",
            )
            if code not in allowed or envelope["output"] is not None:
                raise ValueError("invalid failure envelope")
            return ExecutionResult(code, None, None, {})
        output = RunnerOutput.model_validate(envelope["output"])
        for table in output.tables.values():
            unpack_table(table)  # Actual scalar dtypes, finite floats and dates.
        digest = hashlib.sha256(canonical_json(output.model_dump(mode="json"))).hexdigest()
        return ExecutionResult("ok", output, digest, {})
    except (ValueError, TypeError, OverflowError, RecursionError, pl.exceptions.PolarsError):
        return ExecutionResult("failed:invalid_output", None, None, {})


class SandboxRunner:
    def __init__(
        self,
        profile: SandboxProfileValue,
        image_digest: str,
        *,
        docker_host: str = "unix:///var/run/docker.sock",
        docker_binary: str = "docker",
    ) -> None:
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_digest):
            raise ValueError("sandbox requires an immutable local image digest")
        if not docker_host.startswith("unix:///"):
            raise ValueError("sandbox control requires an explicit local Unix socket")
        self.profile, self.image = profile, image_digest
        self.prefix = [docker_binary, "--host=" + docker_host]
        self._ready: SandboxReadinessValue | None = None

    def _command(self, args: list[str], *, timeout: float, limit: int = 65536) -> bytes:
        # No shell, inherited stdin, candidate output logs or unbounded capture.
        child = subprocess.Popen(
            self.prefix + args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        assert child.stdout is not None
        result = bytearray()
        deadline = time.monotonic() + timeout
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(child.stdout, selectors.EVENT_READ)
                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise subprocess.TimeoutExpired(args[0], timeout)
                    for key, _ in selector.select(min(remaining, 0.2)):
                        chunk = os.read(key.fd, 65536)
                        if not chunk:
                            selector.unregister(key.fd)
                            continue
                        result.extend(chunk)
                        if len(result) > limit:
                            raise _BoundExceeded("bounded control output")
                code = child.wait(timeout=max(0.001, deadline - time.monotonic()))
                if code:
                    raise subprocess.CalledProcessError(code, args[0])
                return bytes(result)
        finally:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGKILL)
            child.wait()
            child.stdout.close()

    def _inspect_controls(self, value: dict[str, Any]) -> dict[str, bool]:
        host, config = value["HostConfig"], value["Config"]
        p = self.profile
        return {
            "runtime": host["Runtime"] == "runsc",
            "network": host["NetworkMode"] == "none",
            "read_only_root_config": host["ReadonlyRootfs"] is True,
            "user": config["User"] == f"{p.user_id}:{p.user_id}",
            "caps": host["CapDrop"] == ["ALL"] and not host.get("CapAdd"),
            "no_new_privileges_config": "no-new-privileges:true" in host["SecurityOpt"],
            "memory_limit": host["Memory"] == host["MemorySwap"] == p.memory_bytes,
            "cpu_quota": host["NanoCpus"] == int(p.cpus * 1_000_000_000),
            "pid_limit": host["PidsLimit"] == p.pids_limit,
            "unprivileged": not host["Privileged"] and not host.get("Devices"),
            "bounded_tmpfs": host["Tmpfs"]
            == {"/tmp": f"rw,noexec,nosuid,nodev,size={p.tmpfs_bytes},mode=1777"},
            "only_readonly_input_mount": len(value["Mounts"]) == 1
            and all(m["Destination"] == "/input" and not m["RW"] for m in value["Mounts"]),
            "immutable_image": value["Image"] == self.image,
            "no_logs": host["LogConfig"]["Type"] == "none",
        }

    def _execute(
        self,
        files: dict[str, bytes],
        request: RunnerInput,
        options: dict[str, Any],
    ) -> ExecutionResult:
        p = self.profile
        if not isinstance(p, SandboxProfile):
            raise SandboxUnavailable("native profiles require the explicit native backend")
        name = "qfr-sbx-" + uuid4().hex
        control = p.control_timeout_seconds
        created = False
        isolation: dict[str, bool] = {}
        result = ExecutionResult("failed:runtime", None, None, isolation)
        with tempfile.TemporaryDirectory(prefix="qfr-sandbox-") as folder:
            # Parent remains 0700. Only this one sanitized child is mounted.
            root = Path(folder) / "input"
            root.mkdir(mode=0o755)
            root.chmod(0o755)
            package = root / "package"
            package.mkdir(mode=0o755)
            package.chmod(0o755)
            for name_in_package, content in files.items():
                target = package / _relative_file(name_in_package)
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
                # Managed executors may use umask 077. Only these newly created
                # sanitized mount directories become traversable; the enclosing
                # host directory remains 0700 and original inputs are untouched.
                parent = target.parent
                while parent != package:
                    parent.chmod(0o755)
                    parent = parent.parent
                target.write_bytes(content)
                target.chmod(0o444)
            data = canonical_json(request.model_dump(mode="json"))
            if len(data) > p.max_input_bytes:
                raise ValueError("input exceeds configured byte bound")
            for filename, payload in {
                "request.json": data,
                "options.json": canonical_json(
                    {
                        **options,
                        "process_limit": p.process_limit,
                        "max_output_bytes": p.max_output_bytes,
                    }
                ),
                "guest.py": Path(sandbox_guest.__file__).read_bytes(),
            }.items():
                (root / filename).write_bytes(payload)
                (root / filename).chmod(0o444)
            args = [
                "create",
                "--name",
                name,
                "--pull",
                "never",
                "--runtime",
                p.runtime,
                "--network",
                "none",
                "--read-only",
                "--user",
                f"{p.user_id}:{p.user_id}",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges:true",
                "--memory",
                str(p.memory_bytes),
                "--memory-swap",
                str(p.memory_bytes),
                "--cpus",
                str(p.cpus),
                "--pids-limit",
                str(p.pids_limit),
                "--ulimit",
                f"cpu={p.cpu_seconds}:{p.cpu_seconds + 1}",
                "--ulimit",
                f"fsize={p.max_output_bytes}:{p.max_output_bytes}",
                "--ulimit",
                f"nofile={p.file_descriptors}:{p.file_descriptors}",
                "--tmpfs",
                f"/tmp:rw,noexec,nosuid,nodev,size={p.tmpfs_bytes},mode=1777",
                "--mount",
                f"type=bind,src={root},dst=/input,readonly",
                "--log-driver",
                "none",
                "--restart",
                "no",
            ]
            for key, value in {
                "PYTHONHASHSEED": str(request.seed),
                "PYTHONPATH": "",
                "PYTHONHOME": "",
                "OMP_NUM_THREADS": "1",
                "OPENBLAS_NUM_THREADS": "1",
                "POLARS_MAX_THREADS": "1",
                "TZ": "UTC",
                "HTTP_PROXY": "",
                "HTTPS_PROXY": "",
                "ALL_PROXY": "",
                "NO_PROXY": "",
                "http_proxy": "",
                "https_proxy": "",
                "all_proxy": "",
                "no_proxy": "",
            }.items():
                args += ["--env", key + "=" + value]
            args += [
                self.image,
                "python",
                "-I",
                "-B",
                "-c",
                "import time; time.sleep(" + str(p.timeout_seconds + 2 * control) + ")",
            ]
            try:
                # A timed-out create has an uncertain outcome; always attempt
                # name-scoped cleanup, even before receiving its container ID.
                created = True
                self._command(args, timeout=control)
                inspected = json.loads(self._command(["inspect", name], timeout=control))[0]
                isolation = self._inspect_controls(inspected)
                if not all(isolation.values()):
                    return ExecutionResult("failed:backend_unavailable", None, None, isolation)
                self._command(["start", name], timeout=control)
                self._command(
                    ["exec", name, "python", "-s", "-P", "-B", "/input/guest.py"],
                    timeout=p.timeout_seconds,
                )
                output = self._command(
                    ["exec", name, "python", "-I", "-B", "/input/guest.py", "--read"],
                    timeout=control,
                    limit=p.max_output_bytes,
                )
                result = decode_result(output, p.max_output_bytes)
            except subprocess.TimeoutExpired:
                result = ExecutionResult("failed:timeout", None, None, isolation)
            except _BoundExceeded:
                result = ExecutionResult("failed:output_limit", None, None, isolation)
            except subprocess.CalledProcessError as exc:
                # Docker reports a cgroup OOM separately from guest exceptions.
                try:
                    state = json.loads(self._command(["inspect", name], timeout=control))[0][
                        "State"
                    ]
                    code: SandboxCode = "failed:runtime"
                    if state["OOMKilled"]:
                        code = "failed:memory"
                    elif exc.returncode == 94:
                        code = "failed:invalid_output"
                    elif exc.returncode == 128 + signal.SIGXCPU:
                        code = "failed:cpu_limit"
                except (subprocess.SubprocessError, ValueError, KeyError):
                    code = "failed:backend_unavailable"
                result = ExecutionResult(code, None, None, isolation)
            finally:
                if created:
                    try:
                        try:
                            self._command(["rm", "--force", name], timeout=control)
                        except subprocess.CalledProcessError:
                            # A failed create can leave no container at all;
                            # verify that outcome rather than inventing an orphan.
                            pass
                        remaining = self._command(
                            ["ps", "-aq", "--filter", "name=^/" + name + "$"], timeout=control
                        )
                        if remaining.strip():
                            raise SandboxCleanupError("sandbox container remains after removal")
                    except (subprocess.SubprocessError, _BoundExceeded) as exc:
                        raise SandboxCleanupError("sandbox cleanup could not be verified") from exc
        return ExecutionResult(result.code, result.output, result.output_sha256, isolation)

    def readiness(self) -> SandboxReadinessValue:
        p = self.profile
        if not isinstance(p, SandboxProfile):
            raise SandboxUnavailable("native profiles require the explicit native backend")
        host_os = architecture = "unknown"
        checks: dict[str, bool] = {}
        try:
            info = json.loads(
                self._command(["info", "--format", "{{json .}}"], timeout=p.control_timeout_seconds)
            )
            host_os, architecture = info["OSType"], info["Architecture"]
            checks = {
                "linux": host_os == "linux",
                "runtime_registered": "runsc" in info["Runtimes"],
            }
            if all(checks.values()):
                request = RunnerInput.model_validate(
                    {
                        "schema_version": "1",
                        "seed": 0,
                        "tables": {"probe": {"columns": [], "dtypes": [], "rows": []}},
                    }
                )
                probe = self._execute(
                    {"probe.py": _PROBE.encode()},
                    request,
                    {"interface": "function", "function": "probe.py:run"},
                )
                checks.update(probe.isolation)
                checks["probe_completed"] = probe.code == "ok" and probe.output is not None
                if probe.output is not None:
                    checks.update(
                        {str(row[0]): row[1] is True for row in probe.output.tables["checks"].rows}
                    )
        except (
            OSError,
            subprocess.SubprocessError,
            ValueError,
            KeyError,
            _BoundExceeded,
            SandboxUnavailable,
        ):
            checks["probe_completed"] = False
        ready = bool(checks) and all(checks.values())
        self._ready = SandboxReadiness(
            schema_version="1",
            status="ready" if ready else "unavailable",
            profile_sha256=p.sha256,
            image_digest=self.image,
            host_os=host_os,
            architecture=architecture,
            runtime="runsc",
            checks=checks,
            reason_code="ok" if ready else "failed:backend_unavailable",
        )
        return self._ready

    def execute(
        self, contract: ExecutionContract, package: bytes, request: RunnerInput
    ) -> ExecutionResult:
        files = validate_execution(self.profile, self.image, contract, package, request)
        if self._ready is None:
            self.readiness()
        if self._ready is None or self._ready.status != "ready":
            raise SandboxUnavailable("executable kind requires validated frozen-backend readiness")
        return self._execute(
            files,
            request,
            {
                "interface": contract.interface,
                "function": contract.function,
                "command": contract.command,
            },
        )


def validate_execution(
    profile: SandboxProfileValue,
    image: str,
    contract: ExecutionContract,
    package: bytes,
    request: RunnerInput,
) -> dict[str, bytes]:
    p = profile
    if request.seed > 2**32 - 1:
        raise ValueError("runner seed exceeds supported deterministic range")
    if (
        contract.image_digest != image
        or contract.approved_sandbox_profile_ref != p.profile_id
        or contract.dependency_lock_sha256 != p.dependency_lock_sha256
        or contract.runner != "qfr-json-runner/1"
        or contract.input_schema_ref != "RunnerInput/1"
        or contract.output_schema_ref != "RunnerOutput/1"
        or request.seed not in contract.seeds
    ):
        raise ValueError("runner contract does not bind the approved execution profile")
    limits = contract.limits
    if (
        limits.cpu_seconds != p.cpu_seconds
        or limits.memory_bytes != p.memory_bytes
        or limits.timeout_seconds != p.timeout_seconds
        or limits.max_output_bytes != p.max_output_bytes
    ):
        raise ValueError("runner limits differ from frozen profile")
    files = unpack_package(package, p)
    if contract.interface == "function":
        function = contract.function or ""
        if not re.fullmatch(r"[A-Za-z0-9_/.-]+\.py:[A-Za-z_][A-Za-z0-9_]*", function):
            raise ValueError("unsupported function interface")
        source = _relative_file(function.split(":")[0])
    else:
        command = contract.command or []
        if len(command) != 2 or command[0] != "python":
            raise ValueError("command interface requires python and one declared script")
        source = _relative_file(command[1])
    if source not in files or not source.endswith(".py"):
        raise ValueError("declared entry point is absent")
    return files
