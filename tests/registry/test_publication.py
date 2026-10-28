import base64
import hashlib
import io
import json
import stat
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from qfr_core.contracts.publication import PublicationRequest, PublicationResponse
from qfr_core.data_layer.snapshots import canonical_json
from qfr_registry.api.app import create_app
from qfr_registry.publication import Principal
from qfr_registry.validation import InvalidPublication, PublicationConflict, package_metadata


@pytest.mark.database
def test_reg02_reg04_identical_publication_and_server_identity(registry_service, publisher, draft):
    request = draft()
    first = registry_service.publish(request, publisher, uuid4())
    repeated = registry_service.publish(request, publisher, uuid4())
    different_claim = request.model_copy(
        update={"publish_key": str(uuid4()), "content_hash": "0" * 64}
    )
    other = registry_service.publish(different_claim, publisher, uuid4())
    assert first.created and not repeated.created and not other.created
    assert first.artifact == repeated.artifact == other.artifact
    manifest = first.artifact.manifest
    assert UUID(manifest.artifact_version_id).version == 7
    assert manifest.created_by == publisher.name and manifest.created_at.tzinfo is not None
    expected = hashlib.sha256(
        canonical_json(
            {
                "hash_spec": "qfr-publication/1",
                "profile": request.profile,
                "dsl_policy_hash": first.artifact.dsl_policy_hash,
                "manifest": request.manifest.model_dump(mode="json", exclude={"family_id"}),
            }
        )
    ).hexdigest()
    assert manifest.content_hash == expected != request.content_hash
    assert registry_service.store.read(first.artifact.payload_digest) == canonical_json(
        {
            "hash_spec": "qfr-publication/1",
            "profile": request.profile,
            "dsl_policy_hash": first.artifact.dsl_policy_hash,
            "manifest": request.manifest.model_dump(mode="json", exclude={"family_id"}),
        }
    )


@pytest.mark.database
def test_reg03_revision_new_hash_same_family_and_retry_conflict(registry_service, publisher, draft):
    request = draft()
    first = registry_service.publish(request, publisher, uuid4()).artifact
    body = request.model_dump(mode="json")
    body["manifest"]["title"] = "A documented revision"
    with pytest.raises(PublicationConflict, match="key reused"):
        registry_service.publish(PublicationRequest.model_validate(body), publisher, uuid4())
    body["publish_key"] = str(uuid4())
    body["manifest"]["family_id"] = first.manifest.family_id
    body["manifest"]["parent_version_ids"] = [first.manifest.artifact_version_id]
    body["manifest"]["rationale"]["change_summary"] = "Clarify the title"
    second = registry_service.publish(
        PublicationRequest.model_validate(body), publisher, uuid4()
    ).artifact
    assert second.version_no == 2 and second.published_seq > first.published_seq
    assert second.manifest.content_hash != first.manifest.content_hash
    assert second.manifest.family_id == first.manifest.family_id
    assert second.manifest.canonical_fingerprint == first.manifest.canonical_fingerprint


@pytest.mark.database
def test_concurrent_identical_definitions_get_one_id(registry_service, publisher, draft):
    request = draft()
    requests = [request.model_copy(update={"publish_key": str(uuid4())}) for _ in range(3)]
    with ThreadPoolExecutor(3) as pool:
        results = list(
            pool.map(lambda r: registry_service.publish(r, publisher, uuid4()), requests)
        )
    assert sum(r.created for r in results) == 1
    assert len({r.artifact.manifest.artifact_version_id for r in results}) == 1


@pytest.mark.database
@pytest.mark.parametrize("field,value", [("fields_used", ["volume"]), ("max_lookback_days", 2)])
def test_declared_versus_parsed_is_not_trusted(registry_service, publisher, draft, field, value):
    body = draft().model_dump(mode="json")
    body["manifest"]["payload"][field] = value
    with pytest.raises(InvalidPublication, match="differ from parsed"):
        registry_service.publish(PublicationRequest.model_validate(body), publisher, uuid4())


@pytest.mark.database
def test_publisher_cannot_cross_program_or_create_an_unlinked_revision(
    registry_service, publisher, draft
):
    request = draft()
    reader = Principal("reader", frozenset({"reader"}), publisher.programs)
    with pytest.raises(PermissionError):
        registry_service.publish(request, reader, uuid4())
    outsider = Principal("publisher", publisher.roles, frozenset({"another-program"}))
    with pytest.raises(PermissionError):
        registry_service.publish(request, outsider, uuid4())
    first = registry_service.publish(request, publisher, uuid4()).artifact
    body = request.model_dump(mode="json")
    body["publish_key"] = str(uuid4())
    body["manifest"]["title"] = "Changed without parent"
    body["manifest"]["family_id"] = first.manifest.family_id
    with pytest.raises(InvalidPublication, match="requires a parent"):
        registry_service.publish(PublicationRequest.model_validate(body), publisher, uuid4())


@pytest.mark.database
def test_http_publication_codes_hash_and_closed_mutation_surface(
    registry_service, publisher, draft
):
    from qfr_registry.api.app import unavailable_authorizer

    app = create_app(registry_service)
    app.dependency_overrides[unavailable_authorizer] = lambda: publisher
    client = TestClient(app)
    body = draft().model_dump(mode="json")
    request_id = str(uuid4())
    first = client.post("/v1/artifacts", json=body, headers={"x-request-id": request_id})
    assert first.status_code == 201 and first.headers["x-request-id"] == request_id
    PublicationResponse.model_validate(first.json())
    assert client.post("/v1/artifacts", json=body).status_code == 200
    body["manifest"]["title"] = "conflicting retry"
    assert client.post("/v1/artifacts", json=body).status_code == 409
    assert (
        TestClient(create_app(registry_service)).post("/v1/artifacts", json=body).status_code == 401
    )
    mutations = {
        (path, method)
        for path, methods in client.get("/openapi.json").json()["paths"].items()
        for method in methods
        if method not in {"get", "head", "options"}
    }
    assert mutations == {("/v1/artifacts", "post")}


@pytest.mark.database
def test_http_body_cap_and_validation_do_not_echo_uploaded_values(registry_service, publisher):
    from qfr_registry.api.app import unavailable_authorizer

    registry_service.policy = registry_service.policy.model_copy(update={"max_request_bytes": 1024})
    app = create_app(registry_service)
    app.dependency_overrides[unavailable_authorizer] = lambda: publisher
    client = TestClient(app)
    assert client.post("/v1/artifacts", content=b"x" * 1025).status_code == 413
    response = client.post("/v1/artifacts", json={"manifest": "PRIVATE-UPLOADED-TEXT"})
    assert response.status_code == 400 and "PRIVATE-UPLOADED-TEXT" not in response.text


def zip_bytes(entries):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, data in entries:
            archive.writestr(name, data)
    return output.getvalue()


@pytest.mark.parametrize("name", ["../runner.py", "/runner.py", "x\\runner.py", "x/../runner.py"])
def test_package_paths_rejected_before_source_read(registry_policy, name):
    with pytest.raises(InvalidPublication, match="unsafe payload path"):
        package_metadata(
            zip_bytes([(name, b"raise RuntimeError('must never execute')")]), registry_policy
        )


def test_package_symlinks_expansion_and_unknown_metadata_fail(registry_policy):
    symlink = zipfile.ZipInfo("runner.py")
    symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
    with pytest.raises(InvalidPublication, match="special member"):
        package_metadata(zip_bytes([(symlink, b"/etc/passwd")]), registry_policy)
    policy = registry_policy.model_copy(update={"max_archive_expanded_bytes": 1})
    with pytest.raises(InvalidPublication, match="expansion"):
        package_metadata(zip_bytes([("runner.py", b"abc")]), policy)
    with pytest.raises(InvalidPublication, match="metadata missing"):
        package_metadata(zip_bytes([("runner.py", b"abc")]), registry_policy)


@pytest.mark.database
def test_declared_package_metadata_and_opaque_source(registry_service, publisher, draft):
    metadata = {
        "format": "qfr-json-runner/1",
        "kind": "factor",
        "entrypoint": "runner.py:run",
        "input_schema_ref": "inputs/1",
        "output_schema_ref": "outputs/1",
        "dependency_lock_sha256": "0" * 64,
        "fields_used": ["close"],
        "max_lookback_days": 1,
        "weight_files": [],
    }
    package = zip_bytes(
        [
            ("runner.json", json.dumps(metadata)),
            ("runner.py", "raise RuntimeError('publication must not execute me')"),
        ]
    )
    body = draft().model_dump(mode="json")
    contract = json.loads(Path("contracts/examples/ExecutionContract.valid.json").read_text())
    contract.update(
        {
            "runner": "qfr-json-runner/1",
            "interface": "function",
            "function": "runner.py:run",
            "command": None,
        }
    )
    body["manifest"]["implementation"] = {
        "type": "declared_package_runner",
        "package_asset_id": "package",
        "execution_contract": contract,
    }
    body["manifest"]["output_schema_ref"] = "outputs/1"
    body["manifest"]["payload_files"] = [
        {
            "asset_id": "package",
            "sha256": hashlib.sha256(package).hexdigest(),
            "media_type": "application/zip",
        }
    ]
    body["files"] = [{"asset_id": "package", "data_base64": base64.b64encode(package).decode()}]
    result = registry_service.publish(PublicationRequest.model_validate(body), publisher, uuid4())
    assert result.created and result.artifact.manifest.canonical_fingerprint is None
    assert registry_service.store.read(hashlib.sha256(package).hexdigest()) == package
    body["publish_key"] = str(uuid4())
    body["manifest"]["implementation"]["execution_contract"]["function"] = "runner.py:wrong"
    with pytest.raises(InvalidPublication, match="function differs"):
        registry_service.publish(PublicationRequest.model_validate(body), publisher, uuid4())


@pytest.mark.database
def test_payload_write_failure_cannot_commit_publication_or_audit(
    registry_service, registry_connect, publisher, draft, monkeypatch
):
    request = draft()
    request_id = uuid4()

    def fail(data):
        raise OSError("controlled storage failure")

    monkeypatch.setattr(registry_service.store, "put", fail)
    with pytest.raises(OSError, match="controlled storage failure"):
        registry_service.publish(request, publisher, request_id)
    with registry_connect() as conn:
        for table in (
            "artifact_families",
            "artifact_versions",
            "registry_events",
            "publication_requests",
        ):
            assert conn.execute(
                f"SELECT count(*) FROM registry.{table} WHERE request_id=%s", [request_id]
            ).fetchone() == (0,)


def test_payload_store_rejects_symlink_and_detects_corruption(tmp_path):
    from qfr_registry.storage.objects import PayloadStore

    store = PayloadStore(tmp_path / "store")
    original = b"immutable synthetic bytes"
    identity = store.put(original)
    assert store.put(original) == identity
    path = store.root / identity
    path.chmod(0o600)
    path.write_bytes(b"deliberately corrupted fixture")
    with pytest.raises(ValueError, match="checksum mismatch"):
        store.read(identity)
    path.unlink()
    target = tmp_path / "outside"
    target.write_bytes(original)
    path.symlink_to(target)
    with pytest.raises(OSError):
        store.read(identity)
    with pytest.raises(OSError):
        store.put(original)
    assert target.read_bytes() == original
