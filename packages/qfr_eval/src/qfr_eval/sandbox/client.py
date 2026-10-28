"""Evaluator client with no Docker API access; native jobs use private Unix RPC."""

import base64
import json
import os
import socket
import time
from typing import Any

from qfr_core.contracts.execution import RunnerInput
from qfr_core.contracts.intake import ExecutionContract
from qfr_core.data_layer.snapshots import canonical_json

from qfr_eval.sandbox.controller import receive, send
from qfr_eval.sandbox.models import (
    DockerControllerConfiguration,
    DockerControllerRequest,
    DockerNativeProfile,
    DockerNativeReadiness,
    SandboxProfileValue,
)
from qfr_eval.sandbox.runner import (
    ExecutionResult,
    SandboxCleanupError,
    SandboxRunner,
    SandboxUnavailable,
    decode_result,
    validate_execution,
)


class DockerControllerClient(SandboxRunner):
    profile: DockerNativeProfile

    def __init__(self, profile: DockerNativeProfile, image_digest: str, socket_path: str):
        super().__init__(profile, image_digest)
        # Reuse the bounded absolute-path validator; this does not open an engine socket.
        DockerControllerConfiguration(
            schema_version="1",
            profile=profile,
            image_digest=image_digest,
            docker_socket="/var/run/docker.sock",
            control_socket=socket_path,
            max_parallel_jobs=1,
        )
        self.socket_path = socket_path

    def _rpc(self, value: DockerControllerRequest) -> dict[str, Any]:
        p = self.profile
        timeout = 2 * p.timeout_seconds + 60 * p.control_timeout_seconds
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
                stream.settimeout(p.control_timeout_seconds)
                stream.connect(self.socket_path)
                send(
                    stream, canonical_json(value.model_dump(mode="json")), p.control_timeout_seconds
                )
                data = receive(stream, p.max_output_bytes + 65536, time.monotonic() + timeout)
            result = json.loads(data)
            if not isinstance(result, dict):
                raise ValueError("invalid controller response")
            if result.get("status") == "cleanup_uncertain":
                raise SandboxCleanupError("controller cannot verify job cleanup")
            if result.get("status") not in ("readiness", "result"):
                raise SandboxUnavailable("native controller unavailable")
            return result
        except (OSError, ValueError):
            raise SandboxUnavailable("native controller transport unavailable") from None

    def readiness(self) -> DockerNativeReadiness:
        value = self._rpc(
            DockerControllerRequest(
                schema_version="1",
                operation="readiness",
                profile_sha256=self.profile.sha256,
                image_digest=self.image,
                contract=None,
                package_base64=None,
                request=None,
            )
        )
        ready = DockerNativeReadiness.model_validate(value.get("value"))
        if ready.profile_sha256 != self.profile.sha256 or ready.image_digest != self.image:
            raise SandboxUnavailable("native controller readiness identity differs")
        self._ready = ready
        return ready

    def execute(
        self, contract: ExecutionContract, package: bytes, request: RunnerInput
    ) -> ExecutionResult:
        validate_execution(self.profile, self.image, contract, package, request)
        result = self._rpc(
            DockerControllerRequest(
                schema_version="1",
                operation="execute",
                profile_sha256=self.profile.sha256,
                image_digest=self.image,
                contract=contract,
                package_base64=base64.b64encode(package).decode("ascii"),
                request=request,
            )
        )
        if set(result) != {"status", "code", "output", "output_sha256", "isolation"}:
            raise SandboxUnavailable("invalid controller result")
        checked = decode_result(
            canonical_json({"code": result["code"], "output": result["output"]}),
            self.profile.max_output_bytes,
        )
        checks = result["isolation"]
        if (
            checked.output_sha256 != result["output_sha256"]
            or not isinstance(checks, dict)
            or any(not isinstance(k, str) or type(v) is not bool for k, v in checks.items())
        ):
            raise SandboxUnavailable("controller output identity or controls differ")
        if checked.code == "ok" and (not checks or not all(checks.values())):
            raise SandboxUnavailable("controller result lacks isolation evidence")
        return ExecutionResult(checked.code, checked.output, checked.output_sha256, checks)


def configured_runner(profile: SandboxProfileValue, image: str) -> SandboxRunner:
    if isinstance(profile, DockerNativeProfile):
        path = os.environ.get("QFR_SANDBOX_CONTROLLER_SOCKET")
        if not path:
            raise SandboxUnavailable("native profile requires its evaluator-only controller socket")
        return DockerControllerClient(profile, image, path)
    return SandboxRunner(profile, image)
