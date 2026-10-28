"""Private frozen artifact bytes and execution policy; no remote references."""

import base64
import binascii
import hashlib
from typing import Literal, Self

from pydantic import model_validator
from qfr_core.contracts.artifacts import PackageImplementation, PythonImplementation
from qfr_core.contracts.base import Contract, Text
from qfr_core.contracts.publication import PublishedArtifact
from qfr_core.dsl.language import DSLConfig

from qfr_eval.sandbox.models import SandboxProfileValue, SandboxReadinessValue
from qfr_eval.scheduler.dedup import verify_publication
from qfr_eval.screening.models import KindAdapterProfile, ScreeningExecutionPolicy


class ArtifactExecutionBundle(Contract):
    schema_version: Literal["1"]
    artifact: PublishedArtifact
    payloads_base64: dict[Text, str]
    execution_policy: ScreeningExecutionPolicy
    adapter_profile: KindAdapterProfile
    dsl_config: DSLConfig | None
    sandbox_profile: SandboxProfileValue | None
    screening_backend: SandboxReadinessValue | None

    def assets(self) -> dict[str, bytes]:
        try:
            values = {
                name: base64.b64decode(value, validate=True)
                for name, value in self.payloads_base64.items()
            }
        except (ValueError, binascii.Error) as exc:
            raise ValueError("invalid frozen payload encoding") from exc
        manifest = self.artifact.manifest
        if set(values) != {p.asset_id for p in manifest.payload_files} or any(
            hashlib.sha256(values[p.asset_id]).hexdigest() != p.sha256
            for p in manifest.payload_files
        ):
            raise ValueError("frozen payload checksum differs from publication")
        return values

    @model_validator(mode="after")
    def pinned_execution(self) -> Self:
        verify_publication(
            self.artifact,
            {self.artifact.profile: self.dsl_config} if self.dsl_config else {},
        )
        self.assets()
        implementation = self.artifact.manifest.implementation
        if isinstance(implementation, (PackageImplementation, PythonImplementation)):
            profile, backend = self.sandbox_profile, self.screening_backend
            contract = implementation.execution_contract
            if (
                profile is None
                or backend is None
                or backend.status != "ready"
                or backend.image_digest != contract.image_digest
                or backend.profile_sha256 != profile.sha256
                or contract.approved_sandbox_profile_ref != profile.profile_id
                or contract.dependency_lock_sha256 != profile.dependency_lock_sha256
                or contract.limits.cpu_seconds != profile.cpu_seconds
                or contract.limits.memory_bytes != profile.memory_bytes
                or contract.limits.timeout_seconds != profile.timeout_seconds
                or contract.limits.max_output_bytes != profile.max_output_bytes
            ):
                raise ValueError("frozen runner lacks matching validated execution controls")
        elif self.sandbox_profile is not None or self.screening_backend is not None:
            raise ValueError("non-sandbox artifact cannot claim backend evidence")
        return self
