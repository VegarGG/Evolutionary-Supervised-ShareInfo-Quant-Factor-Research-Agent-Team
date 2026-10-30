"""Bounded offline verification of public delivery bundles; never executes payloads."""

import hashlib
import io
import json
import stat
import struct
import zipfile
from pathlib import PurePosixPath
from typing import Any

from qfr_core.contracts.artifacts import ArtifactDefinition
from qfr_core.contracts.data import ResearchDatasetRegistration
from qfr_core.contracts.delivery import DeliveryProposal, DeliveryReceipt, ExportManifest
from qfr_core.contracts.intake import InputBundle
from qfr_core.contracts.jobs import ResearchBrief
from qfr_core.contracts.publication import PublishedArtifact
from qfr_core.contracts.reports import PublicProtocolCard
from qfr_core.contracts.research import ResearchApiPolicy
from qfr_core.data_layer.catalog import registration_hash
from qfr_core.data_layer.snapshots import canonical_json
from qfr_core.delivery_rules import (
    admission_hash,
    content_sha256,
    gate_hash,
    job_config_hash,
    pilot_checker_matches_gate,
    validate_pilot_assessment,
    validate_pilot_delivery_gate,
)
from qfr_core.signatures import EvidenceVerifier


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate export JSON key")
        result[key] = value
    return result


def _json(raw: bytes, maximum: int) -> Any:
    if len(raw) > maximum:
        raise ValueError("export metadata exceeds limit")
    value = json.loads(raw, object_pairs_hook=_unique)
    canonical_json(value)  # Refuse nonfinite values as well.
    return value


def read_archive(raw: bytes, policy: ResearchApiPolicy) -> dict[str, bytes]:
    if len(raw) > policy.max_export_bytes:
        raise ValueError("export archive exceeds limit")
    # Bound central-directory allocation before ZipFile creates its member list.
    position = raw.rfind(b"PK\x05\x06", max(0, len(raw) - 65557))
    if position < 0 or len(raw) - position < 22:
        raise ValueError("export ZIP end record unavailable")
    _, disk, start_disk, disk_count, count, size, offset, comment = struct.unpack_from(
        "<4s4H2LH", raw, position
    )
    if (
        disk
        or start_disk
        or disk_count != count
        or count > policy.max_export_files + 1
        or size > policy.max_export_metadata_bytes
        or offset + size != position
        or position + 22 + comment != len(raw)
    ):
        raise ValueError("unsupported or excessive export ZIP directory")
    result: dict[str, bytes] = {}
    total = 0
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        if len(entries) != count:
            raise ValueError("export ZIP directory count differs")
        for info in entries:
            path = PurePosixPath(info.filename)
            if (
                info.orig_filename != info.filename
                or path.is_absolute()
                or any(p in {"", ".", ".."} for p in info.filename.split("/"))
                or "\\" in info.filename
                or ":" in info.filename
                or "\x00" in info.filename
                or path.as_posix() != info.filename
                or info.filename in result
                or stat.S_IFMT(info.external_attr >> 16) not in {0, stat.S_IFREG}
                or info.flag_bits & 1
                or info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
            ):
                raise ValueError("unsafe export ZIP member")
            total += info.file_size
            if total > policy.max_export_bytes:
                raise ValueError("export expansion exceeds limit")
            with archive.open(info) as stream:
                data = stream.read(info.file_size + 1)
            if len(data) != info.file_size:
                raise ValueError("export member size differs")
            result[info.filename] = data
    return result


def verify_export(
    raw: bytes,
    verifier: EvidenceVerifier,
    policy: ResearchApiPolicy,
    *,
    expected_manifest_sha256: str | None = None,
) -> tuple[ExportManifest, DeliveryReceipt]:
    files = read_archive(raw, policy)
    manifest_raw = files.get("manifest.json")
    if manifest_raw is None:
        raise ValueError("export manifest absent")
    if (
        expected_manifest_sha256 is not None
        and hashlib.sha256(manifest_raw).hexdigest() != expected_manifest_sha256
    ):
        raise ValueError("export differs from admitted download reference")
    manifest = ExportManifest.model_validate(_json(manifest_raw, policy.max_export_metadata_bytes))
    if set(files) != {"manifest.json", *(e.path for e in manifest.files)}:
        raise ValueError("export member set differs")
    references: dict[tuple[str, str], bytes] = {}
    for entry in manifest.files:
        data = files[entry.path]
        if len(data) != entry.bytes or hashlib.sha256(data).hexdigest() != entry.sha256:
            raise ValueError("export member hash differs")
        key = (entry.kind, entry.reference_id)
        if key in references:
            raise ValueError("duplicate export semantic reference")
        references[key] = data

    used: set[tuple[str, str]] = set()

    def get(kind: str, identity: str, *, path: str | None = None) -> bytes:
        if (kind, identity) not in references:
            raise ValueError("required export reference absent")
        if path is not None and not any(
            e.kind == kind and e.reference_id == identity and e.path == path for e in manifest.files
        ):
            raise ValueError("export metadata path differs")
        used.add((kind, identity))
        return references[(kind, identity)]

    receipt = verifier.delivery(get("delivery_receipt", manifest.receipt.reference_id))
    if (
        receipt.result != "pass"
        or receipt.receipt_id != manifest.receipt.reference_id
        or receipt.job_id != manifest.job_id
        or receipt.artifact_refs != manifest.artifact_refs
    ):
        raise ValueError("export lacks its exact passing receipt")
    configs = {r.reference_id: r.sha256 for r in receipt.config_refs}
    if (
        receipt.independent_checker not in policy.trusted_delivery_checkers
        or len(configs) != len(receipt.config_refs)
        or configs.get(receipt.independent_checker)
        != policy.trusted_delivery_checkers[receipt.independent_checker]
    ):
        raise ValueError("export checker is not trusted")

    def metadata(path: str) -> Any:
        if path not in files:
            raise ValueError("export intent document absent")
        return _json(files[path], policy.max_export_metadata_bytes)

    bundle = InputBundle.model_validate(metadata("input_bundle.json"))
    brief = ResearchBrief.model_validate(metadata("brief.json"))
    proposal = DeliveryProposal.model_validate(metadata("proposal.json"))
    get("provenance", "input-bundle:" + bundle.bundle_id, path="input_bundle.json")
    get("provenance", "brief:" + brief.brief_id, path="brief.json")
    get("provenance", "proposal:" + proposal.proposal_id, path="proposal.json")
    get("configuration_reference", "job-config:" + receipt.job_id, path="job_config.json")
    get("source_manifest", "sources:" + bundle.bundle_id, path="source_manifest.json")
    validate_pilot_delivery_gate(brief.exit_gate)
    validate_pilot_assessment(brief)
    if (
        configs.get("input-bundle:" + bundle.bundle_id)
        != content_sha256(bundle.model_dump(mode="json"))
        or configs.get("brief:" + brief.brief_id) != content_sha256(brief.model_dump(mode="json"))
        or configs.get("proposal:" + proposal.proposal_id)
        != content_sha256(proposal.model_dump(mode="json"))
        or configs.get("admission:" + receipt.job_id) != admission_hash(bundle, brief)
        or configs.get("job-config:" + receipt.job_id) != job_config_hash(bundle)
        or manifest.source_config_hash != job_config_hash(bundle)
        or metadata("job_config.json") != bundle.job_config.model_dump(mode="json")
        or brief.input_bundle_id != bundle.bundle_id
        or brief.exit_gate.spec_hash != receipt.gate_spec_hash
        or gate_hash(brief.exit_gate) != receipt.gate_spec_hash
        or proposal.job_id != receipt.job_id
        or proposal.artifact_refs != receipt.artifact_refs
        or proposal.released_report_refs != receipt.released_report_refs
        or receipt.allowed_conclusions != brief.exit_gate.allowed_conclusions
        or receipt.conclusion != proposal.conclusion
        or not pilot_checker_matches_gate(brief.exit_gate, receipt.independent_checker)
        or sorted(c.check_id for c in receipt.checks) != sorted(brief.exit_gate.required_checks)
        or (brief.exit_gate.human_signoff_required and not receipt.human_signoff_ref)
        or set(configs)
        != {
            "input-bundle:" + bundle.bundle_id,
            "brief:" + brief.brief_id,
            "proposal:" + proposal.proposal_id,
            "admission:" + receipt.job_id,
            "job-config:" + receipt.job_id,
            receipt.independent_checker,
        }
    ):
        raise ValueError("export intent differs from signed admission")
    if metadata("source_manifest.json") != [
        a.model_dump(mode="json") for a in bundle.source_assets
    ]:
        raise ValueError("export source manifest differs from signed input")
    # The shortlist is a view over the same receipt; it cannot omit required evidence.
    if "shortlist.json" in files:
        get("provenance", "shortlist:" + proposal.proposal_id, path="shortlist.json")
        if metadata("shortlist.json") != [r.model_dump(mode="json") for r in proposal.shortlist]:
            raise ValueError("export shortlist differs from signed proposal")
    for artifact_ref in receipt.artifact_refs:
        artifact = PublishedArtifact.model_validate(
            _json(
                get("artifact_manifest", artifact_ref.artifact_version_id),
                policy.max_export_metadata_bytes,
            )
        )
        definition = {
            k: v
            for k, v in artifact.manifest.model_dump(mode="json").items()
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
            artifact.manifest.artifact_version_id != artifact_ref.artifact_version_id
            or artifact.manifest.content_hash != artifact_ref.content_hash
            or artifact.payload_digest != digest
            or digest != artifact_ref.content_hash
            or artifact.manifest.provenance.program_id != brief.project_id
        ):
            raise ValueError("export artifact identity differs")
        for payload in artifact.manifest.payload_files:
            data = get(
                "artifact_payload", artifact_ref.artifact_version_id + ":" + payload.asset_id
            )
            if hashlib.sha256(data).hexdigest() != payload.sha256:
                raise ValueError("export payload differs from signed artifact")
    reports = []
    for ref in receipt.released_report_refs:
        data = get("released_report", ref.reference_id)
        report = verifier.report(data)
        if (
            hashlib.sha256(data).hexdigest() != ref.sha256
            or report.report_id != ref.reference_id
            or report.program_id != brief.project_id
        ):
            raise ValueError("export report binding differs")
        reports.append(report)
    if (
        not reports
        or {r.identity.protocol_version for r in reports} != set(brief.exit_gate.protocol_refs)
        or {r.identity.dataset_version_id for r in reports}
        != {r.reference_id for r in receipt.dataset_refs}
        or {r.protocol_card_ref for r in reports} != {r.reference_id for r in receipt.protocol_refs}
        or not {r.reference_id for r in receipt.dataset_refs} <= set(bundle.data_refs)
    ):
        raise ValueError("export released evidence scope differs")
    for ref in receipt.protocol_refs:
        data = get("public_protocol_card", ref.reference_id)
        card = PublicProtocolCard.model_validate(_json(data, policy.max_export_metadata_bytes))
        if (
            hashlib.sha256(data).hexdigest() != ref.sha256
            or (card.card_ref or card.protocol_version) != ref.reference_id
        ):
            raise ValueError("export public protocol binding differs")
    for ref in receipt.dataset_refs:
        registration = ResearchDatasetRegistration.model_validate(
            _json(get("dataset_manifest", ref.reference_id), policy.max_export_metadata_bytes)
        )
        if (
            registration.dataset_version_id != ref.reference_id
            or ref.sha256 != ref.reference_id
            or registration.program_id != brief.project_id
            or registration_hash(registration) != registration.registration_id
            or content_sha256(registration.research_manifest.model_dump(mode="json"))
            != registration.research_manifest_sha256
        ):
            raise ValueError("export research dataset binding differs")
    if used != set(references):
        raise ValueError("export contains unbound additional material")
    return manifest, receipt
