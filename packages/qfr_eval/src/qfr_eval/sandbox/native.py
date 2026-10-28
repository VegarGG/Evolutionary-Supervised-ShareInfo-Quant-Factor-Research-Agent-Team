"""Ordinary Docker isolation with verified controls and no backend fallback."""

import hashlib
import platform
from typing import Any
from uuid import uuid4

from qfr_core.contracts.execution import RunnerInput

from qfr_eval.sandbox.docker_api import DockerAPI, DockerBoundExceeded, DockerError, DockerExecError
from qfr_eval.sandbox.models import DockerNativeProfile, DockerNativeReadiness, SandboxCode
from qfr_eval.sandbox.native_plan import (
    LABEL,
    SEAL_CHECK,
    container_spec,
    input_archive,
    volume_spec,
)
from qfr_eval.sandbox.runner import (
    _PROBE,
    ExecutionResult,
    SandboxCleanupError,
    SandboxRunner,
    decode_result,
)


class DockerNativeRunner(SandboxRunner):
    profile: DockerNativeProfile

    def __init__(
        self,
        profile: DockerNativeProfile,
        image_digest: str,
        *,
        socket_path: str = "/var/run/docker.sock",
    ) -> None:
        super().__init__(profile, image_digest)
        self.api = DockerAPI(socket_path)

    def _inspect_native(self, value: dict[str, Any], job: str, *, helper: bool) -> dict[str, bool]:
        p = self.profile
        expected = container_spec(p, self.image, job, 0, helper=helper)["HostConfig"]
        host, config = value["HostConfig"], value["Config"]
        mounts = value["Mounts"]
        return {
            "runtime": host["Runtime"] == "runc",
            "network": host["NetworkMode"] == "none" and not host.get("PortBindings"),
            "read_only_root_config": host["ReadonlyRootfs"] is True,
            "user": config["User"] == f"{p.user_id}:{p.user_id}",
            "caps": host["CapDrop"] == ["ALL"] and not host.get("CapAdd"),
            "no_new_privileges_config": "no-new-privileges:true" in host["SecurityOpt"],
            "memory_limit": host["Memory"] == host["MemorySwap"] == p.memory_bytes,
            "cpu_quota": host["NanoCpus"] == expected["NanoCpus"],
            "pid_limit": host["PidsLimit"] == p.pids_limit,
            "unprivileged": not host["Privileged"]
            and not host.get("Devices")
            and not host.get("DeviceRequests")
            and not host.get("Binds")
            and not host.get("VolumesFrom")
            and not host.get("GroupAdd"),
            "bounded_tmpfs": host["Tmpfs"] == expected["Tmpfs"],
            "only_readonly_input_mount": len(mounts) == 1
            and mounts[0]["Type"] == "volume"
            and mounts[0]["Name"] == job + "-input"
            and mounts[0]["Destination"] == "/input"
            and mounts[0]["RW"] is helper,
            "immutable_image": value["Image"] == self.image,
            "no_logs": host["LogConfig"]["Type"] == "none",
            "seccomp_config": sorted(host["SecurityOpt"]) == sorted(expected["SecurityOpt"]),
            "private_namespaces": host["IpcMode"] == "private"
            and host["PidMode"] == ""
            and host["CgroupnsMode"] == "private"
            and host.get("UTSMode", "") == "",
            "bounded_shm": host["ShmSize"] == 1048576,
            "ulimits": sorted(host["Ulimits"], key=lambda v: v["Name"])
            == sorted(expected["Ulimits"], key=lambda v: v["Name"]),
            "owned_job": config["Labels"].get(LABEL) == job,
            "trusted_entrypoint": config["Entrypoint"] == ["python"],
        }

    def _remove_container(self, name: str) -> None:
        timeout = self.profile.control_timeout_seconds
        job = name.removesuffix("-stager")
        try:
            actual = self.api.json("GET", f"/containers/{name}/json", timeout=timeout)
        except DockerError as error:
            if error.status == 404:
                return
            raise
        if actual["Config"]["Labels"].get(LABEL) != job:
            raise SandboxCleanupError("refusing to remove an unowned container")
        try:
            self.api.request("DELETE", f"/containers/{name}?force=true&v=true", timeout=timeout)
        except DockerError as error:
            if error.status != 404:
                raise
        try:
            self.api.json("GET", f"/containers/{name}/json", timeout=timeout)
        except DockerError as error:
            if error.status == 404:
                return
            raise
        raise SandboxCleanupError("native container removal not confirmed")

    def _cleanup(self, job: str, *, containers: list[str], volume: bool) -> None:
        errors = []
        for name in reversed(containers):
            try:
                self._remove_container(name)
            except (OSError, RuntimeError, ValueError, KeyError, TypeError) as error:
                errors.append(type(error).__name__)
        if volume:
            try:
                actual = None
                try:
                    actual = self.api.json(
                        "GET", f"/volumes/{job}-input", timeout=self.profile.control_timeout_seconds
                    )
                except DockerError as error:
                    if error.status != 404:
                        raise
                if actual is not None and actual["Labels"].get(LABEL) != job:
                    raise SandboxCleanupError("refusing to remove an unowned input volume")
                try:
                    self.api.request(
                        "DELETE",
                        f"/volumes/{job}-input",
                        timeout=self.profile.control_timeout_seconds,
                    )
                except DockerError as error:
                    if error.status != 404:
                        raise
                try:
                    self.api.json(
                        "GET", f"/volumes/{job}-input", timeout=self.profile.control_timeout_seconds
                    )
                except DockerError as error:
                    if error.status != 404:
                        raise
                else:
                    raise SandboxCleanupError("native input removal not confirmed")
            except (OSError, RuntimeError, ValueError, KeyError, TypeError) as error:
                errors.append(type(error).__name__)
        if errors:
            raise SandboxCleanupError("native cleanup could not be verified")

    def _execute(
        self, files: dict[str, bytes], request: RunnerInput, options: dict[str, Any]
    ) -> ExecutionResult:
        p, job = self.profile, "qfr-native-" + uuid4().hex
        control = p.control_timeout_seconds
        archive = input_archive(p, files, request, options)
        isolation: dict[str, bool] = {}
        containers: list[str] = []
        volume = False
        result = ExecutionResult("failed:backend_unavailable", None, None, isolation)
        try:
            # Detect collisions before creating anything. Never remove an existing
            # resource just because a name matches. Random names are controller-owned.
            for path in (
                f"/volumes/{job}-input",
                f"/containers/{job}/json",
                f"/containers/{job}-stager/json",
            ):
                try:
                    self.api.json("GET", path, timeout=control)
                except DockerError as error:
                    if error.status != 404:
                        raise
                else:
                    raise ValueError("native job identity already exists")
            spec = volume_spec(p, job)
            volume = True  # timeout may mean creation completed; cleanup must verify
            self.api.json("POST", "/volumes/create", timeout=control, value=spec)
            actual = self.api.json("GET", f"/volumes/{job}-input", timeout=control)
            if (
                actual["Driver"] != "local"
                or actual["Options"] != spec["DriverOpts"]
                or actual["Labels"] != spec["Labels"]
            ):
                raise ValueError("native input volume differs from frozen controls")
            for helper in (True, False):
                name = job + "-stager" if helper else job
                containers.append(name)
                self.api.json(
                    "POST",
                    f"/containers/create?name={name}",
                    timeout=control,
                    value=container_spec(p, self.image, job, request.seed, helper=helper),
                )
                observed = self.api.json("GET", f"/containers/{name}/json", timeout=control)
                checks = self._inspect_native(observed, job, helper=helper)
                if not all(checks.values()):
                    isolation.update(checks)
                    return result
                self.api.request("POST", f"/containers/{name}/start", timeout=control)
                if helper:
                    self.api.request(
                        "PUT",
                        f"/containers/{name}/archive?path=/input",
                        timeout=control,
                        body=archive,
                    )
                    self.api.exec(
                        name, ["python", "-I", "-B", "-c", SEAL_CHECK], timeout=control, limit=1024
                    )
                else:
                    isolation.update(checks)
            # Keep one mount alive throughout the tmpfs handoff. No writer may
            # remain when the first candidate instruction executes.
            self._remove_container(job + "-stager")
            self.api.exec(
                job, ["python", "-I", "-B", "-c", SEAL_CHECK], timeout=control, limit=1024
            )
            isolation["input_sealed"] = True
            output = self.api.exec(
                job,
                ["python", "-I", "-B", "-m", "qfr_core.sandbox_native"],
                timeout=p.timeout_seconds,
                limit=p.max_output_bytes,
            )
            result = decode_result(output, p.max_output_bytes)
        except TimeoutError:
            result = ExecutionResult("failed:timeout", None, None, isolation)
        except DockerBoundExceeded:
            result = ExecutionResult("failed:output_limit", None, None, isolation)
        except DockerExecError as error:
            # Candidate exits are classified by the surviving supervisor. An
            # unexplained supervisor/control-process exit has no trustworthy
            # resource observation; never guess that exit 137 means OOM.
            code: SandboxCode = "failed:backend_unavailable"
            if error.code == 94:
                code = "failed:invalid_output"
            elif error.code == 95:
                code = "failed:backend_unavailable"
            elif error.code == 152:
                code = "failed:cpu_limit"
            try:
                state = self.api.json("GET", f"/containers/{job}/json", timeout=control)["State"]
                if type(state["OOMKilled"]) is not bool:
                    code = "failed:backend_unavailable"
                elif state["OOMKilled"]:
                    code = "failed:memory"
            except (OSError, DockerError, ValueError, KeyError):
                code = "failed:backend_unavailable"
            result = ExecutionResult(code, None, None, isolation)
        except (OSError, DockerError, ValueError, KeyError, TypeError):
            result = ExecutionResult("failed:backend_unavailable", None, None, isolation)
        finally:
            self._cleanup(job, containers=containers, volume=volume)
        return ExecutionResult(result.code, result.output, result.output_sha256, isolation)

    def readiness(self) -> DockerNativeReadiness:
        p = self.profile
        info: dict[str, Any] = {}
        checks: dict[str, bool] = {}
        try:
            info = self.api.json("GET", "/info", timeout=p.control_timeout_seconds)
            checks = {
                "linux_engine": info["OSType"] == "linux",
                "cgroup_v2": info["CgroupVersion"] == "2",
                "seccomp_available": any("name=seccomp" in x for x in info["SecurityOptions"]),
                "runtime_registered": "runc" in info["Runtimes"],
            }
            if all(checks.values()):
                probe = native_probe_source(p)
                result = self._execute(
                    {"probe.py": probe.encode()},
                    RunnerInput.model_validate(
                        {
                            "schema_version": "1",
                            "seed": 0,
                            "tables": {"probe": {"columns": [], "dtypes": [], "rows": []}},
                        }
                    ),
                    {"interface": "function", "function": "probe.py:run"},
                )
                checks.update(result.isolation)
                checks["probe_completed"] = result.code == "ok" and result.output is not None
                if result.output is not None:
                    checks.update(
                        {str(row[0]): row[1] is True for row in result.output.tables["checks"].rows}
                    )
        except (OSError, DockerError, ValueError, KeyError, TypeError, DockerBoundExceeded):
            checks["probe_completed"] = False
        ready = bool(checks) and all(checks.values()) and checks.get("probe_completed", False)
        value = DockerNativeReadiness(
            schema_version="2",
            status="ready" if ready else "unavailable",
            profile_sha256=p.sha256,
            image_digest=self.image,
            engine_os=info.get("OSType", "unknown"),
            engine_architecture=info.get("Architecture", "unknown"),
            engine_version=info.get("ServerVersion", "unknown"),
            engine_id_sha256=hashlib.sha256(info["ID"].encode()).hexdigest()
            if info.get("ID")
            else None,
            controller_os=platform.system().lower(),
            controller_architecture=platform.machine(),
            runtime="runc",
            boundary="docker_shared_kernel",
            checks=checks,
            reason_code="ok" if ready else "failed:backend_unavailable",
        )
        self._ready = value
        return value


def native_probe_source(p: DockerNativeProfile) -> str:
    """Retain non-network controls; use complete state-based native network proof."""
    probe = _PROBE.replace(
        "resource.getrlimit(resource.RLIMIT_NPROC)[0] > 0",
        'int(pathlib.Path("/sys/fs/cgroup/pids.max").read_text()) == ' + str(p.pids_limit),
    ).replace(
        '    return {"schema_version"',
        '''
    cgroup = pathlib.Path('/sys/fs/cgroup')
    status_all = pathlib.Path('/proc/self/status').read_text().splitlines()
    checks['seccomp_filter'] = any(x.split() == ['Seccomp:', '2'] for x in status_all)
    checks['cgroup_memory'] = (cgroup/'memory.max').read_text().strip() == MEMORY
    checks['cgroup_swap'] = (cgroup/'memory.swap.max').read_text().strip() == '0'
    checks['cgroup_pids'] = (cgroup/'pids.max').read_text().strip() == PIDS
    quota, period = (cgroup/'cpu.max').read_text().split()
    checks['cgroup_cpu'] = quota != 'max' and int(quota)/int(period) == CPUS
    try:
        pathlib.Path('/input/native-write-probe').write_text('probe')
        checks['read_only_input'] = False
    except OSError as e:
        checks['read_only_input'] = e.errno == 30
    return {"schema_version"''',
    )
    probe = f"MEMORY={str(p.memory_bytes)!r}\nPIDS={str(p.pids_limit)!r}\nCPUS={p.cpus!r}\n" + probe
    start = probe.index("    with socket.socket() as s:\n")
    end = probe.index("    cgroup = pathlib.Path", start)
    probe = probe[:start] + "    checks.update(audit_network())\n" + probe[end:]
    probe = probe.replace('[name for _,name in socket.if_nameindex()] == ["lo"]', "False")
    return "from qfr_core.sandbox_network import audit_network\n" + probe
