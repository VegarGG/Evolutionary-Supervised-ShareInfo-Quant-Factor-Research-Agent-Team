"""Offline integrity and private-material boundaries for synthetic signed exports."""

import hashlib
import io
import json
import stat
import zipfile
from uuid import UUID, uuid4

import pytest
from qfr_core.access import ServicePrincipal
from qfr_core.contracts.research import DeliveryExportRequest
from qfr_core.data_layer.snapshots import canonical_json
from qfr_core.exports import read_archive, verify_export
from qfr_research.api.errors import ResearchConflict, ResearchNotFound
from qfr_research.api.exports import Exports
from test_delivery_acceptance import accept, delivery_setup, seal_receipt
from test_research_jobs import changed

pytestmark = pytest.mark.database


def setup_export(connect, root):
    case = delivery_setup(connect, root, service_class=Exports)
    seal_receipt(case)
    accept(case)
    request = DeliveryExportRequest(operation_key="export", shortlist_only=False)
    ref = case.service.export(case.principal, UUID(case.status.job.job_id), request, uuid4())
    _, raw = case.service.download(case.principal, ref.job_id, ref.export_id)
    return case, request, ref, raw


def pack(files):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for path, value in files.items():
            archive.writestr(path, value)
    return stream.getvalue()


def repack(files):
    manifest = json.loads(files["manifest.json"])
    for entry in manifest["files"]:
        data = files[entry["path"]]
        entry.update(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
    files["manifest.json"] = canonical_json(manifest)
    return pack(files)


def test_export_is_durable_scoped_and_independently_verifiable(research_connect, tmp_path):
    case, request, ref, raw = setup_export(research_connect, tmp_path)
    manifest, receipt = verify_export(
        raw,
        case.evidence.verifier,
        case.service.policy,
        expected_manifest_sha256=ref.manifest_sha256,
    )
    assert receipt == case.evidence.receipt_value and manifest.export_id == str(ref.export_id)
    assert ref.archive_sha256 == hashlib.sha256(raw).hexdigest()
    assert case.service.export(case.principal, ref.job_id, request, uuid4()) == ref
    recreated = Exports(case.service.storage, case.evidence, case.service.research_root)
    assert recreated.download(case.principal, ref.job_id, ref.export_id) == (ref, raw)
    outsider = ServicePrincipal(
        "other", "research", frozenset({"reader"}), frozenset({str(uuid4())})
    )
    with pytest.raises((ResearchNotFound, PermissionError)):
        recreated.download(outsider, ref.job_id, ref.export_id)
    files = read_archive(raw, case.service.policy)
    assert not any(name.endswith((".csv", ".parquet", ".pem", ".env")) for name in files)
    assert "source_manifest.json" in files and "input_bundle.json" in files
    shortlist = case.service.export(
        case.principal,
        ref.job_id,
        changed(request, operation_key="shortlist", shortlist_only=True),
        uuid4(),
    )
    _, smaller = case.service.download(case.principal, ref.job_id, shortlist.export_id)
    view = read_archive(smaller, case.service.policy)
    assert json.loads(view["shortlist.json"]) == []  # Supported negative is a valid delivery.
    assert set(files) <= set(view)  # A shortlist never strips mandatory evidence.


def test_export_waits_for_independent_acceptance(research_connect, tmp_path):
    case = delivery_setup(research_connect, tmp_path, service_class=Exports)
    with pytest.raises(ResearchConflict, match="accepted"):
        case.service.export(
            case.principal,
            UUID(case.status.job.job_id),
            DeliveryExportRequest(operation_key="early", shortlist_only=False),
            uuid4(),
        )


@pytest.mark.parametrize(
    "issue", ["input", "brief", "payload", "extra_private", "unsigned", "missing", "source"]
)
def test_self_consistent_manifest_cannot_replace_signed_evidence(research_connect, tmp_path, issue):
    case, _, _, raw = setup_export(research_connect, tmp_path)
    files = read_archive(raw, case.service.policy)
    if issue in {"input", "brief", "source"}:
        name = {
            "input": "input_bundle.json",
            "brief": "brief.json",
            "source": "source_manifest.json",
        }[issue]
        body = json.loads(files[name])
        if issue == "source":
            body = [{"private_raw": True}]
        else:
            body["objective"] = "changed intent"
        files[name] = canonical_json(body)
    elif issue == "payload":
        name = next(n for n in files if "/payload/" in n)
        files[name] += b"changed"
    elif issue == "extra_private":
        files["private.csv"] = b"synthetic-private-marker"
        manifest = json.loads(files["manifest.json"])
        manifest["files"].append(
            dict(
                path="private.csv",
                kind="artifact_payload",
                reference_id="unbound",
                bytes=0,
                sha256="0" * 64,
            )
        )
        files["manifest.json"] = canonical_json(manifest)
    elif issue == "unsigned":
        body = json.loads(files["receipt.json"])
        body.pop("signature")
        files["receipt.json"] = canonical_json(body)
        with pytest.raises(ValueError):
            verify_export(pack(files), case.evidence.verifier, case.service.policy)
        return
    else:
        files.pop("brief.json")
        with pytest.raises(ValueError):
            verify_export(pack(files), case.evidence.verifier, case.service.policy)
        return
    with pytest.raises(ValueError):
        verify_export(repack(files), case.evidence.verifier, case.service.policy)


def test_archive_paths_symlinks_and_expansion_refused_before_use(research_connect, tmp_path):
    case, _, _, raw = setup_export(research_connect, tmp_path)
    policy = case.service.policy
    for path in ["../escape", "/absolute", "a/../escape", "a\\escape", "C:drive", "a//b"]:
        with pytest.raises(ValueError, match="unsafe"):
            read_archive(pack({path: b"x"}), policy)
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        info = zipfile.ZipInfo("link")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, b"../../outside")
    with pytest.raises(ValueError, match="unsafe"):
        read_archive(stream.getvalue(), policy)
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("compressed", b"0" * 10000)
    with pytest.raises(ValueError, match="expansion"):
        read_archive(stream.getvalue(), changed(policy, max_export_bytes=2000))
    with pytest.raises(ValueError, match="directory"):
        read_archive(raw, changed(policy, max_export_files=1))
