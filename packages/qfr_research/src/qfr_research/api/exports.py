"""Durable exports assembled exclusively from scoped public evidence.

Original source packages and private evaluation data are never read here. Dataset
entries describe authorized research slices; they are not copies of licensed data.
"""

import hashlib
import io
import stat
import zipfile
from typing import Any
from uuid import UUID

from qfr_core.access import ServicePrincipal
from qfr_core.contracts.data import ResearchDatasetRegistration
from qfr_core.contracts.delivery import (
    DeliveryReceipt,
    ExportEntry,
    ExportManifest,
    VersionReference,
)
from qfr_core.contracts.enums import JobState
from qfr_core.contracts.research import DeliveryExportReference, DeliveryExportRequest
from qfr_core.data_layer.catalog import read_registration
from qfr_core.data_layer.snapshots import canonical_json
from qfr_core.delivery_rules import content_sha256
from qfr_core.exports import verify_export
from qfr_core.identifiers import uuid7

from qfr_research.api.deliveries import Deliveries
from qfr_research.api.errors import InvalidResearchRequest, ResearchConflict, ResearchNotFound
from qfr_research.api.storage import scope
from qfr_research.db import attributed


class Exports(Deliveries):
    def export(
        self,
        principal: ServicePrincipal,
        job_id: UUID,
        request: DeliveryExportRequest,
        request_id: UUID,
    ) -> DeliveryExportReference:
        with self.storage.connection() as conn, attributed(conn, principal.name, request_id):
            context, _, _ = self._context(conn, principal, job_id, lock=True)
            job, program = context.job, UUID(context.job.project_id)
            scope(principal, program, "research_lead")
            body = request.model_dump(mode="json")
            action = "export:" + str(job_id)
            old = self.storage.operation(conn, program, action, request.operation_key, body)
            if old is not None:
                return DeliveryExportReference.model_validate(old)
            if (
                job.state != JobState.COMPLETED
                or job.receipt is None
                or job.receipt.result != "pass"
            ):
                raise ResearchConflict("only independently accepted delivery can be exported")
            row = conn.execute(
                "SELECT d.payload,j.active_delivery_proposal_id FROM research.research_jobs j "
                "JOIN research.delivery_refs d ON d.id=j.delivery_ref_id "
                "WHERE j.id=%s AND j.program_id=%s",
                [job_id, program],
            ).fetchone()
            if row is None or row[1] is None:
                raise ResearchConflict("accepted delivery evidence unavailable")
            receipt = self.evidence.verifier.delivery(DeliveryReceipt.model_validate(row[0]))
            if (
                receipt.receipt_id != job.receipt.receipt_id
                or content_sha256(receipt.model_dump(mode="json")) != job.receipt.receipt_sha256
            ):
                raise InvalidResearchRequest("accepted receipt binding differs")
            # Re-resolve immutable references, without asking evaluation to run anything.
            candidate = self.delivery_candidate(principal, job_id, row[1])
            self.verify_delivery_binding(candidate, receipt)
            proposal = candidate.proposal
            entries: list[ExportEntry] = []
            files: dict[str, bytes] = {}
            total = 0

            def add(
                path: str, kind: Any, identity: str, value: Any, *, binary: bool = False
            ) -> None:
                nonlocal total
                data: bytes = value if binary else canonical_json(value)
                if path in files:
                    raise InvalidResearchRequest("duplicate export path")
                total += len(data)
                if (
                    total > self.policy.max_export_bytes
                    or len(files) >= self.policy.max_export_files
                    or (not binary and len(data) > self.policy.max_export_metadata_bytes)
                ):
                    raise InvalidResearchRequest("export exceeds configured bound")
                files[path] = data
                entries.append(
                    ExportEntry(
                        path=path,
                        kind=kind,
                        reference_id=identity,
                        sha256=hashlib.sha256(data).hexdigest(),
                        bytes=len(data),
                    )
                )

            add(
                "input_bundle.json",
                "provenance",
                "input-bundle:" + context.input_bundle.bundle_id,
                context.input_bundle.model_dump(mode="json"),
            )
            add(
                "brief.json",
                "provenance",
                "brief:" + context.brief.brief_id,
                context.brief.model_dump(mode="json"),
            )
            add(
                "proposal.json",
                "provenance",
                "proposal:" + proposal.proposal_id,
                proposal.model_dump(mode="json"),
            )
            add(
                "job_config.json",
                "configuration_reference",
                "job-config:" + job.job_id,
                context.input_bundle.job_config.model_dump(mode="json"),
            )
            add(
                "source_manifest.json",
                "source_manifest",
                "sources:" + context.input_bundle.bundle_id,
                [a.model_dump(mode="json") for a in context.input_bundle.source_assets],
            )
            add(
                "receipt.json",
                "delivery_receipt",
                receipt.receipt_id,
                receipt.model_dump(mode="json"),
            )
            if request.shortlist_only:
                add(
                    "shortlist.json",
                    "provenance",
                    "shortlist:" + proposal.proposal_id,
                    [r.model_dump(mode="json") for r in proposal.shortlist],
                )
            for artifact_ref in receipt.artifact_refs:
                artifact = self.evidence.artifact(program, artifact_ref)
                artifact_id = str(UUID(artifact_ref.artifact_version_id))
                add(
                    f"artifacts/{artifact_id}/manifest.json",
                    "artifact_manifest",
                    artifact_ref.artifact_version_id,
                    artifact.model_dump(mode="json"),
                )
                for payload in artifact.manifest.payload_files:
                    data = self.evidence.payload(program, artifact, payload.asset_id)
                    if hashlib.sha256(data).hexdigest() != payload.sha256:
                        raise InvalidResearchRequest("export payload hash differs")
                    name = hashlib.sha256(payload.asset_id.encode()).hexdigest()
                    add(
                        f"artifacts/{artifact_id}/payload/{name}",
                        "artifact_payload",
                        artifact_ref.artifact_version_id + ":" + payload.asset_id,
                        data,
                        binary=True,
                    )
            for ref in receipt.released_report_refs:
                report = self.evidence.report(program, UUID(ref.reference_id))
                add(
                    f"reports/{UUID(ref.reference_id)}.json",
                    "released_report",
                    ref.reference_id,
                    report.model_dump(mode="json"),
                )
            for ref in receipt.protocol_refs:
                card = self.evidence.protocol_card(program, ref.reference_id)
                name = hashlib.sha256(ref.reference_id.encode()).hexdigest()
                add(
                    f"cards/{name}.json",
                    "public_protocol_card",
                    ref.reference_id,
                    card.model_dump(mode="json"),
                )
            for ref in receipt.dataset_refs:
                row = conn.execute(
                    "SELECT payload FROM research.dataset_registrations "
                    "WHERE program_id=%s AND dataset_version_id=%s",
                    [program, ref.reference_id],
                ).fetchone()
                if row is None:
                    raise ResearchNotFound("registered research dataset unavailable")
                registration = ResearchDatasetRegistration.model_validate(row[0])
                if (
                    read_registration(
                        self.research_root, registration.registration_id, str(program)
                    )
                    != registration
                ):
                    raise InvalidResearchRequest("trusted research catalog differs")
                add(
                    f"datasets/{registration.dataset_version_id}.json",
                    "dataset_manifest",
                    ref.reference_id,
                    registration.model_dump(mode="json"),
                )
            identity = uuid7()
            manifest = ExportManifest(
                schema_version="1",
                export_id=str(identity),
                job_id=job.job_id,
                receipt=VersionReference(
                    reference_id=receipt.receipt_id, sha256=job.receipt.receipt_sha256
                ),
                artifact_refs=receipt.artifact_refs,
                files=entries,
                created_at=self.storage.now(conn),
                source_config_hash=job.config_hash,
            )
            files["manifest.json"] = canonical_json(manifest.model_dump(mode="json"))
            if len(files["manifest.json"]) > self.policy.max_export_metadata_bytes:
                raise InvalidResearchRequest("export manifest exceeds bound")
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, "w", allowZip64=False) as archive:
                for name, data in sorted(files.items()):
                    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                    info.create_system = 3
                    info.external_attr = (stat.S_IFREG | 0o600) << 16
                    archive.writestr(info, data, compress_type=zipfile.ZIP_STORED)
            raw = stream.getvalue()
            verify_export(raw, self.evidence.verifier, self.policy)
            result = DeliveryExportReference(
                export_id=identity,
                job_id=job_id,
                manifest_sha256=hashlib.sha256(files["manifest.json"]).hexdigest(),
                archive_sha256=hashlib.sha256(raw).hexdigest(),
                archive_bytes=len(raw),
                download_path=f"/v1/jobs/{job_id}/exports/{identity}",
            )
            self.storage.insert(
                conn,
                "export_records",
                result.model_dump(mode="json"),
                principal.name,
                request_id,
                program,
                identity=identity,
                research_job_id=job_id,
                archive=raw,
                archive_sha256=result.archive_sha256,
            )
            self.storage.remember(
                conn,
                program,
                action,
                request.operation_key,
                body,
                result.model_dump(mode="json"),
                principal.name,
                request_id,
            )
            return result

    def download(
        self, principal: ServicePrincipal, job_id: UUID, export_id: UUID
    ) -> tuple[DeliveryExportReference, bytes]:
        with self.storage.connection() as conn:
            context, _, _ = self._context(conn, principal, job_id)
            row = conn.execute(
                "SELECT payload,archive,archive_sha256 FROM research.export_records "
                "WHERE id=%s AND research_job_id=%s AND program_id=%s",
                [export_id, job_id, UUID(context.job.project_id)],
            ).fetchone()
        if row is None:
            raise ResearchNotFound("delivery export unavailable")
        ref, raw = DeliveryExportReference.model_validate(row[0]), bytes(row[1])
        if (
            ref.export_id != export_id
            or ref.job_id != job_id
            or len(raw) != ref.archive_bytes
            or row[2] != ref.archive_sha256
            or hashlib.sha256(raw).hexdigest() != ref.archive_sha256
        ):
            raise InvalidResearchRequest("persisted export integrity differs")
        verify_export(
            raw, self.evidence.verifier, self.policy, expected_manifest_sha256=ref.manifest_sha256
        )
        return ref, raw
