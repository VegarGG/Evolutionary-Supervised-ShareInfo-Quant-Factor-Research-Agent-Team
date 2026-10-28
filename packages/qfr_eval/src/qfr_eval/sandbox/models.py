"""Versioned operational limits, separate from financial admission rules."""

import hashlib
from pathlib import PurePosixPath
from typing import Literal, Self

from pydantic import Field, PositiveInt, model_validator
from qfr_core.contracts.base import Contract, Sha256, Text
from qfr_core.contracts.execution import RunnerInput
from qfr_core.contracts.intake import ExecutionContract
from qfr_core.data_layer.snapshots import canonical_json

SandboxCode = Literal[
    "ok",
    "failed:backend_unavailable",
    "failed:network",
    "failed:filesystem",
    "failed:process_limit",
    "failed:memory",
    "failed:cpu_limit",
    "failed:timeout",
    "failed:output_limit",
    "failed:invalid_output",
    "failed:runtime",
]


class SandboxProfile(Contract):
    schema_version: Literal["1"]
    profile_id: Text
    revision: PositiveInt
    scope: Literal["P0_P1_verification_only", "bounded_synthetic_acceptance"]
    runtime: Literal["runsc"]
    user_id: PositiveInt
    cpus: float = Field(gt=0, le=2)
    memory_bytes: PositiveInt
    pids_limit: PositiveInt = Field(ge=32, le=128)
    process_limit: PositiveInt = Field(ge=4, le=32)
    cpu_seconds: PositiveInt
    timeout_seconds: PositiveInt
    tmpfs_bytes: PositiveInt
    max_input_bytes: PositiveInt
    max_package_bytes: PositiveInt
    max_package_files: PositiveInt
    max_output_bytes: PositiveInt
    control_timeout_seconds: PositiveInt
    file_descriptors: PositiveInt
    dependency_lock_sha256: Sha256

    @model_validator(mode="after")
    def bounded(self) -> Self:
        # A command runner's temporary stdout and the single exported envelope
        # coexist briefly. Neither can spill from tmpfs onto the host filesystem.
        if self.tmpfs_bytes < 2 * self.max_output_bytes + 4096:
            raise ValueError("tmpfs must hold the bounded output envelope and command buffer")
        if self.process_limit >= self.pids_limit:
            raise ValueError("guest processes need headroom below runtime task limit")
        return self

    @property
    def sha256(self) -> str:
        return hashlib.sha256(canonical_json(self.model_dump(mode="json"))).hexdigest()


class SandboxReadiness(Contract):
    schema_version: Literal["1"]
    status: Literal["ready", "unavailable"]
    profile_sha256: Sha256
    image_digest: Text
    host_os: Text
    architecture: Text
    runtime: Literal["runsc"]
    checks: dict[Text, bool]
    reason_code: Literal["ok", "failed:backend_unavailable"]

    @model_validator(mode="after")
    def actual_readiness(self) -> Self:
        if self.status == "ready" and (
            self.reason_code != "ok" or not self.checks or not all(self.checks.values())
        ):
            raise ValueError("readiness requires every actual isolation check")
        return self


class DockerNativeProfile(Contract):
    """New shared-kernel contract. Never reinterpret a historical runsc profile."""

    schema_version: Literal["2"]
    profile_id: Text
    revision: PositiveInt
    scope: Literal["P0_P1_verification_only", "bounded_synthetic_acceptance"]
    runtime: Literal["runc"]
    boundary: Literal["docker_shared_kernel"]
    approval_ref: Literal["owner-approved-2026-10-28-docker-native-v1"]
    user_id: PositiveInt
    cpus: float = Field(gt=0, le=2)
    memory_bytes: PositiveInt
    pids_limit: PositiveInt = Field(ge=4, le=16)
    process_accounting: Literal["cgroup_total_tasks"]
    cpu_seconds: PositiveInt
    timeout_seconds: PositiveInt
    tmpfs_bytes: PositiveInt
    input_tmpfs_bytes: PositiveInt
    max_input_bytes: PositiveInt
    max_package_bytes: PositiveInt
    max_package_files: PositiveInt
    max_output_bytes: PositiveInt
    control_timeout_seconds: PositiveInt
    file_descriptors: PositiveInt
    dependency_lock_sha256: Sha256
    seccomp_sha256: Literal["514c38e72edc5363e87287ea87212211172c6c3251a974ca21ebfd05a56c7f5d"]

    @model_validator(mode="after")
    def bounded(self) -> Self:
        if self.tmpfs_bytes < 2 * self.max_output_bytes + 4096:
            raise ValueError("tmpfs must hold bounded output and command buffer")
        if self.input_tmpfs_bytes < self.max_input_bytes + self.max_package_bytes + 1048576:
            raise ValueError("input tmpfs must bound package, request and trusted metadata")
        if self.user_id != 65532:
            raise ValueError("native execution uses the isolated non-root image user")
        return self

    @property
    def sha256(self) -> str:
        return hashlib.sha256(canonical_json(self.model_dump(mode="json"))).hexdigest()


NATIVE_REQUIRED_CHECKS = frozenset(
    {
        "linux_engine",
        "cgroup_v2",
        "seccomp_available",
        "runtime_registered",
        "runtime",
        "network",
        "read_only_root_config",
        "user",
        "caps",
        "no_new_privileges_config",
        "memory_limit",
        "cpu_quota",
        "pid_limit",
        "unprivileged",
        "bounded_tmpfs",
        "only_readonly_input_mount",
        "immutable_image",
        "no_logs",
        "seccomp_config",
        "private_namespaces",
        "bounded_shm",
        "input_sealed",
        "probe_completed",
        "non_root",
        "dropped_capabilities",
        "no_new_privileges",
        "seccomp_filter",
        "no_external_interface",
        "no_private_packages",
        "no_private_assets",
        "read_only_root",
        "network_denied",
        "cgroup_memory",
        "cgroup_swap",
        "cgroup_cpu",
        "cgroup_pids",
        "read_only_input",
        "bounded_cpu",
        "bounded_file",
    }
)


class DockerNativeReadiness(Contract):
    schema_version: Literal["2"]
    status: Literal["ready", "unavailable"]
    profile_sha256: Sha256
    image_digest: Text
    engine_os: Text
    engine_architecture: Text
    engine_version: Text
    engine_id_sha256: Sha256 | None
    controller_os: Text
    controller_architecture: Text
    runtime: Literal["runc"]
    boundary: Literal["docker_shared_kernel"]
    checks: dict[Text, bool]
    reason_code: Literal["ok", "failed:backend_unavailable"]

    @model_validator(mode="after")
    def actual_readiness(self) -> Self:
        if self.status == "ready" and (
            self.reason_code != "ok"
            or not NATIVE_REQUIRED_CHECKS.issubset(self.checks)
            or not all(self.checks.values())
            or self.engine_os != "linux"
            or self.engine_id_sha256 is None
        ):
            raise ValueError("native readiness requires actual engine and guest evidence")
        return self


SandboxProfileValue = SandboxProfile | DockerNativeProfile
SandboxReadinessValue = SandboxReadiness | DockerNativeReadiness


class DockerControllerConfiguration(Contract):
    schema_version: Literal["1"]
    profile: DockerNativeProfile
    image_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    docker_socket: Text
    control_socket: Text
    max_parallel_jobs: Literal[1]

    @model_validator(mode="after")
    def private_unix_paths(self) -> Self:
        for name in (self.docker_socket, self.control_socket):
            if (
                not PurePosixPath(name).is_absolute()
                or ".." in PurePosixPath(name).parts
                or len(name.encode()) > 100
                or any(c in name for c in "\r\n\0?%:")
            ):
                raise ValueError("controller paths must be bounded absolute Unix socket paths")
        if self.docker_socket == self.control_socket:
            raise ValueError("controller must not overwrite the engine socket")
        return self


class DockerControllerRequest(Contract):
    schema_version: Literal["1"]
    operation: Literal["readiness", "execute"]
    profile_sha256: Sha256
    image_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    contract: ExecutionContract | None
    package_base64: str | None
    request: RunnerInput | None

    @model_validator(mode="after")
    def exact_operation(self) -> Self:
        values = (self.contract, self.package_base64, self.request)
        if self.operation == "readiness" and any(x is not None for x in values):
            raise ValueError("readiness takes no candidate input")
        if self.operation == "execute" and any(x is None for x in values):
            raise ValueError("execution requires frozen contract, bytes and input")
        return self
