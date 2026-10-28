"""MCP's only data access: explicitly scoped HTTP clients plus public verification."""

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, TypeVar
from urllib.parse import urlencode
from uuid import UUID

from pydantic import BaseModel
from qfr_core.access import ServicePrincipal
from qfr_core.contracts.artifacts import ArtifactDefinition
from qfr_core.contracts.delivery import DeliveryReceipt
from qfr_core.contracts.feedback import ReportPage
from qfr_core.contracts.mcp import MCPBackendBinding, MCPPolicy, MCPReply, ResourceDocumentPage
from qfr_core.contracts.publication import ArtifactPage, PublishedArtifact
from qfr_core.contracts.reports import ReleasedReport
from qfr_core.contracts.research import (
    DeliveryExportReference,
    JobPage,
    JobStatus,
    ResearchApiPolicy,
)
from qfr_core.contracts.transfers import AssetPage
from qfr_core.data_layer.snapshots import canonical_json
from qfr_core.delivery_rules import content_sha256
from qfr_core.exports import read_archive, verify_export
from qfr_core.registry_client import RegistryClient
from qfr_core.service_client import PublicServiceClient
from qfr_core.signatures import EvidenceVerifier, SignatureRejected

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class Backend:
    roles: frozenset[str]
    research: PublicServiceClient
    registry: RegistryClient
    feedback: PublicServiceClient
    intake: PublicServiceClient


class Gateway:
    def __init__(
        self,
        bindings: Mapping[tuple[str, UUID], Backend],
        policy: MCPPolicy,
        export_policy: ResearchApiPolicy,
        verifier: EvidenceVerifier,
    ):
        self.bindings, self.policy = dict(bindings), policy
        self.export_policy, self.verifier = export_policy, verifier

    @classmethod
    def configured(
        cls,
        bindings: Sequence[MCPBackendBinding],
        environment: Mapping[str, str],
        policy: MCPPolicy,
        export_policy: ResearchApiPolicy,
        verifier: EvidenceVerifier,
    ) -> "Gateway":
        clients = {}
        for entry in bindings:
            key = entry.principal, entry.program_id
            if key in clients or len(set(entry.roles)) != len(entry.roles):
                raise ValueError("duplicate MCP backend binding or role")
            clients[key] = Backend(
                frozenset(entry.roles),
                PublicServiceClient.from_environment(entry.research, environment),
                RegistryClient.from_environment(entry.registry, environment),
                PublicServiceClient.from_environment(entry.feedback, environment),
                PublicServiceClient.from_environment(entry.intake, environment),
            )
        return cls(clients, policy, export_policy, verifier)

    def backend(
        self, caller: ServicePrincipal, program: UUID, *, role: str | None = None
    ) -> Backend:
        value = self.bindings.get((caller.name, program))
        if (
            caller.audience != "mcp"
            or str(program) not in caller.programs
            or value is None
            or caller.roles != value.roles
            or (role is not None and role not in caller.roles)
        ):
            raise PermissionError("MCP program or role is not authorized")
        return value

    def research(
        self,
        caller: ServicePrincipal,
        program: UUID,
        model: type[T],
        method: Literal["GET", "POST"],
        path: str,
        value: BaseModel | None = None,
        *,
        role: str | None = None,
    ) -> T:
        backend = self.backend(caller, program, role=role)
        _, data = backend.research.request(
            method, path, body=value.model_dump_json().encode() if value else None
        )
        result = model.model_validate_json(data)
        if isinstance(result, JobStatus):
            self.verify_job(caller, program, result)
        if isinstance(result, JobPage):
            for item in result.items:
                self.verify_job(caller, program, item)
        # Program-scoped path parameters are built by handlers, never arbitrary client URLs.
        return result

    def intake(
        self,
        caller: ServicePrincipal,
        program: UUID,
        model: type[T],
        method: Literal["GET", "POST"],
        path: str,
        value: BaseModel | None = None,
        *,
        write: bool = False,
    ) -> T:
        backend = self.backend(caller, program, role="research_lead" if write else None)
        _, data = backend.intake.request(
            method, path, body=value.model_dump_json().encode() if value else None
        )
        result = model.model_validate_json(data)
        if hasattr(result, "program_id") and str(result.program_id) != str(program):
            raise ValueError("intake response program differs")
        if isinstance(result, AssetPage) and any(
            item.program_id != program for item in result.items
        ):
            raise ValueError("intake page program differs")
        return result

    def verify_job(self, caller: ServicePrincipal, program: UUID, value: JobStatus) -> None:
        job = value.job
        if job.project_id != str(program):
            raise PermissionError("job program differs")
        if job.receipt is None:
            return
        receipt = self.receipt(caller, program, UUID(job.receipt.receipt_id))
        configs = {r.reference_id: r.sha256 for r in receipt.config_refs}
        if (
            receipt.job_id != job.job_id
            or receipt.result != job.receipt.result
            or content_sha256(receipt.model_dump(mode="json")) != job.receipt.receipt_sha256
            or receipt.gate_spec_hash != job.exit_gate.spec_hash
            or configs.get("admission:" + job.job_id) != job.payload_hash
            or configs.get("job-config:" + job.job_id) != job.config_hash
            or receipt.independent_checker not in self.export_policy.trusted_delivery_checkers
            or configs.get(receipt.independent_checker)
            != self.export_policy.trusted_delivery_checkers[receipt.independent_checker]
        ):
            raise SignatureRejected("job receipt binding differs")

    def receipt(self, caller: ServicePrincipal, program: UUID, identity: UUID) -> DeliveryReceipt:
        backend = self.backend(caller, program)
        _, raw = backend.feedback.request("GET", f"v1/delivery-receipts/{identity}")
        result = self.verifier.delivery(raw)
        if result.receipt_id != str(identity) or result.created_at > datetime.now(UTC):
            raise SignatureRejected("delivery identity or release time differs")
        return result

    def report(self, caller: ServicePrincipal, program: UUID, identity: UUID) -> ReleasedReport:
        _, raw = self.backend(caller, program).feedback.request("GET", f"v1/reports/{identity}")
        result = self.verifier.report(raw)
        if (
            result.report_id != str(identity)
            or result.program_id != str(program)
            or result.released_at > datetime.now(UTC)
        ):
            raise SignatureRejected("released report scope differs")
        return result

    def report_page(
        self, caller: ServicePrincipal, program: UUID, *, after: UUID | None, limit: int
    ) -> ReportPage:
        self.page_size(limit)
        query: dict[str, str | int] = {"limit": limit}
        if after:
            query["after_id"] = str(after)
        _, raw = self.backend(caller, program).feedback.request(
            "GET", "v1/reports?" + urlencode(query)
        )
        result = ReportPage.model_validate_json(raw)
        if len(result.items) > limit:
            raise ValueError("released page exceeds requested bound")
        for report in result.items:
            self.verifier.report(report)
            if report.program_id != str(program) or report.released_at > datetime.now(UTC):
                raise SignatureRejected("released page scope differs")
        return result

    @staticmethod
    def verify_artifact(program: UUID, artifact: PublishedArtifact) -> None:
        raw = artifact.manifest.model_dump(mode="json")
        definition = {
            k: v
            for k, v in raw.items()
            if k in ArtifactDefinition.model_fields and k != "family_id"
        }
        digest = content_sha256(
            dict(
                hash_spec="qfr-publication/1",
                profile=artifact.profile,
                dsl_policy_hash=artifact.dsl_policy_hash,
                manifest=definition,
            )
        )
        if (
            artifact.manifest.provenance.program_id != str(program)
            or artifact.payload_digest != digest
            or artifact.manifest.content_hash != digest
        ):
            raise ValueError("Registry artifact scope or hash differs")

    def artifact(
        self, caller: ServicePrincipal, program: UUID, identity: UUID
    ) -> PublishedArtifact:
        value = self.backend(caller, program).registry.get(identity)
        self.verify_artifact(program, value)
        return value

    def artifact_page(
        self, caller: ServicePrincipal, program: UUID, *, since_seq: int, limit: int
    ) -> ArtifactPage:
        self.page_size(limit)
        result = self.backend(caller, program).registry.page(since_seq=since_seq, limit=limit)
        for artifact in result.items:
            self.verify_artifact(program, artifact)
        return result

    def download(
        self,
        caller: ServicePrincipal,
        program: UUID,
        job: UUID,
        identity: UUID,
        expected: DeliveryExportReference | None = None,
    ) -> bytes:
        backend = self.backend(caller, program)
        # Check the job program even if a backend token is misconfigured too broadly.
        status = self.research(caller, program, JobStatus, "GET", f"v1/jobs/{job}")
        _, raw = backend.research.request("GET", f"v1/jobs/{job}/exports/{identity}")
        manifest, receipt = verify_export(
            raw,
            self.verifier,
            self.export_policy,
            expected_manifest_sha256=expected.manifest_sha256 if expected else None,
        )
        files = read_archive(raw, self.export_policy)
        if (
            manifest.export_id != str(identity)
            or manifest.job_id != str(job)
            or json.loads(files["brief.json"])["project_id"] != str(program)
            or status.job.receipt is None
            or status.job.receipt.receipt_id != receipt.receipt_id
        ):
            raise SignatureRejected("delivery export belongs to different accepted context")
        if expected and (
            expected.export_id != identity
            or expected.job_id != job
            or len(raw) != expected.archive_bytes
            or hashlib.sha256(raw).hexdigest() != expected.archive_sha256
        ):
            raise SignatureRejected("delivery export differs from reference")
        return raw

    def reply(
        self, value: BaseModel, summary: str, *, uri: str | None = None, official: bool = False
    ) -> MCPReply:
        data = value.model_dump(mode="json")
        raw = canonical_json(data)
        if len(raw) > self.policy.max_inline_result_bytes:
            if uri is None:
                raise ValueError("result requires a smaller page")
            data = {"read_resource": uri, "bytes": len(raw)}
        return MCPReply(
            summary=summary,
            data=data,
            resource_uri=uri,
            document_sha256=hashlib.sha256(raw).hexdigest(),
            official_signature_verified=official,
        )

    def document_page(
        self, value: BaseModel, uri: str, page: int, *, official: bool = False
    ) -> ResourceDocumentPage:
        raw = canonical_json(value.model_dump(mode="json"))
        text = raw.decode("utf-8")
        width = self.policy.resource_page_characters
        count = max(1, (len(text) + width - 1) // width)
        if not 0 <= page < count:
            raise ValueError("resource page is outside document")
        return ResourceDocumentPage(
            uri=uri,
            page=page,
            pages=count,
            document_sha256=hashlib.sha256(raw).hexdigest(),
            text=text[page * width : (page + 1) * width],
            official_signature_verified=official,
        )

    def page_size(self, limit: int) -> None:
        if not 1 <= limit <= self.policy.max_page_size:
            raise ValueError("page size exceeds MCP policy")
