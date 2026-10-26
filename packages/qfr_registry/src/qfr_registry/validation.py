"""Validate publication data without executing source or trusting client hashes."""

import base64
import binascii
import hashlib
import io
import re
import stat
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath
from uuid import UUID

from qfr_core.contracts.artifacts import (
    CompositeImplementation,
    DocumentImplementation,
    DSLImplementation,
    FactorPayload,
    ModelPayload,
    PackageImplementation,
    PythonImplementation,
    ResearchNotePayload,
)
from qfr_core.contracts.publication import PublicationRequest, RunnerPackage
from qfr_core.data_layer.snapshots import canonical_json
from qfr_core.dsl.language import DSLConfig, analyze, canonical_hash, parse

from qfr_registry.policy import RegistryPolicy


class InvalidPublication(ValueError):
    """Safe, fixed validation message; never contains uploaded source text."""


class PublicationConflict(ValueError):
    pass


def digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def safe_member(name: str) -> str:
    path = PurePosixPath(name)
    if (
        not name
        or path.is_absolute()
        or ".." in path.parts
        or "\\" in name
        or ":" in name
        or any(ord(c) < 32 for c in name)
        or str(path) != name.rstrip("/")
        or len(path.parts) > 16
    ):
        raise InvalidPublication("unsafe payload path")
    return str(path)


def package_metadata(data: bytes, policy: RegistryPolicy) -> RunnerPackage:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            if len(infos) > policy.max_archive_members:
                raise InvalidPublication("archive member limit")
            names: set[str] = set()
            expanded = 0
            for info in infos:
                name = safe_member(info.filename)
                mode = info.external_attr >> 16
                if name in names or stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR):
                    raise InvalidPublication("archive duplicate or special member")
                names.add(name)
                expanded += info.file_size
                if (
                    info.flag_bits & 1
                    or info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                    or info.file_size > policy.max_file_bytes
                    or expanded > policy.max_archive_expanded_bytes
                    or info.file_size > max(info.compress_size, 1) * policy.max_compression_ratio
                ):
                    raise InvalidPublication("archive expansion or encryption limit")
            if "runner.json" not in names:
                raise InvalidPublication("package runner metadata missing")
            metadata = RunnerPackage.model_validate_json(archive.read("runner.json"))
            entry = metadata.entrypoint.split(":", 1)
            if safe_member(entry[0]) not in names or not entry[0].endswith(".py"):
                raise InvalidPublication("declared runner source missing")
            if len(entry) == 2 and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", entry[1]):
                raise InvalidPublication("invalid runner function")
            for name in metadata.weight_files:
                if safe_member(name) not in names or not name.endswith(".json"):
                    raise InvalidPublication("unsupported or missing frozen weight file")
            return metadata
    except InvalidPublication:
        raise
    except (ValueError, KeyError, OSError, zipfile.BadZipFile, RecursionError):
        raise InvalidPublication("invalid declared runner package") from None


@dataclass(frozen=True)
class ValidatedPublication:
    content_hash: str
    implementation_hash: str
    canonical_hash: str | None
    dsl_policy_hash: str | None
    request_digest: str
    bundle: bytes
    files: dict[str, bytes]


def validate(
    request: PublicationRequest, policy: RegistryPolicy, dsl_configs: dict[str, DSLConfig]
) -> ValidatedPublication:
    manifest = request.manifest
    if len(request.files) > policy.max_payload_files:
        raise InvalidPublication("payload count limit")
    if len(set(manifest.parent_version_ids)) != len(manifest.parent_version_ids):
        raise InvalidPublication("duplicate lineage parent")
    try:
        for parent in manifest.parent_version_ids:
            UUID(parent)
        if manifest.family_id is not None:
            UUID(manifest.family_id)
    except ValueError:
        raise InvalidPublication("invalid family or parent identifier") from None
    files: dict[str, bytes] = {}
    declarations = {f.asset_id: f for f in manifest.payload_files}
    if len(declarations) != len(manifest.payload_files):
        raise InvalidPublication("duplicate payload declaration")
    total = 0
    for uploaded in request.files:
        if uploaded.asset_id not in declarations or uploaded.asset_id in files:
            raise InvalidPublication("undeclared or duplicate payload")
        if len(uploaded.data_base64) > 4 * ((policy.max_file_bytes + 2) // 3):
            raise InvalidPublication("payload size limit")
        try:
            data = base64.b64decode(uploaded.data_base64, validate=True)
        except (ValueError, binascii.Error):
            raise InvalidPublication("invalid payload encoding") from None
        total += len(data)
        if len(data) > policy.max_file_bytes or total > policy.max_total_payload_bytes:
            raise InvalidPublication("payload size limit")
        if hashlib.sha256(data).hexdigest() != declarations[uploaded.asset_id].sha256:
            raise InvalidPublication("payload checksum mismatch")
        files[uploaded.asset_id] = data
    if files.keys() != declarations.keys():
        raise InvalidPublication("declared payload missing")
    implementation = manifest.implementation
    canonical = policy_hash = None
    if isinstance(implementation, DSLImplementation):
        config = dsl_configs.get(request.profile)
        if config is None or not isinstance(manifest.payload, FactorPayload):
            raise InvalidPublication("DSL profile unsupported")
        try:
            parsed = parse(implementation.expression, config)
            analysis = analyze(parsed, config)
        except (ValueError, RecursionError):
            raise InvalidPublication("invalid DSL implementation") from None
        if (
            set(manifest.payload.fields_used) != analysis.fields
            or len(manifest.payload.fields_used) != len(set(manifest.payload.fields_used))
            or manifest.payload.max_lookback_days != analysis.lookback
            or manifest.complexity != analysis.complexity
        ):
            raise InvalidPublication(
                "declared fields, lookback or complexity differ from parsed DSL"
            )
        canonical = canonical_hash(implementation.expression, config)
        policy_hash = digest(config.model_dump(mode="json"))
    elif isinstance(implementation, PackageImplementation):
        if implementation.package_asset_id not in files:
            raise InvalidPublication("package payload missing")
        metadata = package_metadata(files[implementation.package_asset_id], policy)
        contract = implementation.execution_contract
        if (
            contract.runner not in policy.allowed_runners
            or metadata.kind != manifest.kind
            or metadata.input_schema_ref != contract.input_schema_ref
            or metadata.output_schema_ref != contract.output_schema_ref
            or contract.output_schema_ref != manifest.output_schema_ref
            or metadata.dependency_lock_sha256 != contract.dependency_lock_sha256
        ):
            raise InvalidPublication("declared execution contract differs from package metadata")
        if contract.interface == "function":
            if contract.function != metadata.entrypoint or ":" not in metadata.entrypoint:
                raise InvalidPublication("declared runner function differs")
        elif contract.command != ["python", metadata.entrypoint] or ":" in metadata.entrypoint:
            raise InvalidPublication("unsupported declared runner command")
        if isinstance(manifest.payload, FactorPayload) and (
            sorted(manifest.payload.fields_used) != sorted(metadata.fields_used)
            or manifest.payload.max_lookback_days != metadata.max_lookback_days
        ):
            raise InvalidPublication("declared factor fields differ from package metadata")
    elif isinstance(implementation, PythonImplementation):
        contract = implementation.execution_contract
        if (
            implementation.source_asset_id not in files
            or contract.runner not in policy.allowed_runners
            or contract.interface != "function"
            or contract.function != implementation.entrypoint
        ):
            raise InvalidPublication("unsupported constrained runner declaration")
        # Source AST inspection and all code execution occur only in the approved sandbox.
    elif isinstance(implementation, DocumentImplementation):
        if implementation.asset_id not in files:
            raise InvalidPublication("document payload missing")
    elif isinstance(implementation, CompositeImplementation):
        if len({c.artifact.artifact_version_id for c in implementation.components}) != len(
            implementation.components
        ):
            raise InvalidPublication("duplicate composite component")
    else:
        raise InvalidPublication("unsupported implementation")
    if (
        isinstance(manifest.payload, ModelPayload)
        and not set(manifest.payload.weight_asset_ids) <= files.keys()
    ):
        raise InvalidPublication("frozen model weights missing")
    if (
        isinstance(manifest.payload, ResearchNotePayload)
        and manifest.payload.document_asset_id not in files
    ):
        raise InvalidPublication("research note missing")
    definition = manifest.model_dump(mode="json", exclude={"family_id"})
    bundle = canonical_json(
        {
            "hash_spec": "qfr-publication/1",
            "profile": request.profile,
            "dsl_policy_hash": policy_hash,
            "manifest": definition,
        }
    )
    return ValidatedPublication(
        hashlib.sha256(bundle).hexdigest(),
        digest(
            {
                "implementation": implementation.model_dump(mode="json"),
                "payloads": [f.model_dump(mode="json") for f in manifest.payload_files],
            }
        ),
        canonical,
        policy_hash,
        digest(request.model_dump(mode="json", exclude={"content_hash", "files", "publish_key"})),
        bundle,
        files,
    )
