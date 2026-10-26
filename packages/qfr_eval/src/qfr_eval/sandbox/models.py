"""Versioned operational limits, separate from financial admission rules."""

import hashlib
from typing import Literal, Self

from pydantic import Field, PositiveInt, model_validator
from qfr_core.contracts.base import Contract, Sha256, Text
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
