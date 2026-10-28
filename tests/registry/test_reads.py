import base64
import hashlib
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from qfr_core.contracts.publication import ArtifactLineage, ArtifactPage, PublicationRequest
from qfr_registry.api.app import create_app, unavailable_authorizer
from qfr_registry.policy import RegistryReadPolicy
from qfr_registry.publication import Principal
from qfr_registry.reads import RegistryNotFound, RegistryReader
from qfr_registry.validation import InvalidPublication


@pytest.fixture
def reader(registry_service):
    return RegistryReader(
        registry_service.connect,
        registry_service.store,
        RegistryReadPolicy.model_validate_json(Path("configs/registry/read_v1.json").read_bytes()),
    )


@pytest.fixture
def read_principal(publisher):
    return Principal("fixture-reader", frozenset({"reader"}), publisher.programs)


def child(registry, publisher, draft, parents, *, family=None):
    body = draft().model_dump(mode="json")
    body["manifest"]["family_id"] = family
    body["manifest"]["parent_version_ids"] = [p.manifest.artifact_version_id for p in parents]
    body["manifest"]["provenance"]["operator"] = "crossover" if len(parents) > 1 else "explore"
    body["manifest"]["rationale"]["change_summary"] = "Synthetic revision for lineage testing"
    return registry.publish(PublicationRequest.model_validate(body), publisher, uuid4()).artifact


@pytest.mark.database
def test_reads_return_verified_committed_publications_and_hide_other_programs(
    registry_service, publisher, draft, reader, read_principal
):
    record = registry_service.publish(draft(), publisher, uuid4()).artifact
    identity = UUID(record.manifest.artifact_version_id)
    assert reader.get(identity, read_principal) == record
    for requested_id, principal in (
        (uuid4(), read_principal),
        (identity, Principal("outside", frozenset({"reader"}), frozenset({"other-program"}))),
    ):
        with pytest.raises(RegistryNotFound):
            reader.get(requested_id, principal)
    for principal in (
        Principal("", frozenset({"reader"}), publisher.programs),
        Principal("no-role", frozenset(), publisher.programs),
        Principal("no-program", frozenset({"reader"}), frozenset()),
    ):
        with pytest.raises(PermissionError):
            reader.get(UUID(record.manifest.artifact_version_id), principal)


@pytest.mark.database
def test_cursor_pages_no_omissions_and_empty_poll_preserves_cursor(
    registry_service, publisher, draft, reader, read_principal
):
    records = [registry_service.publish(draft(), publisher, uuid4()).artifact for _ in range(3)]
    first = reader.page(read_principal, since_seq=0, limit=2)
    assert first.items == records[:2] and first.has_more
    last = reader.page(read_principal, since_seq=first.next_cursor, limit=2)
    assert last.items == records[2:] and not last.has_more
    empty = reader.page(read_principal, since_seq=last.next_cursor, limit=2)
    assert not empty.items and not empty.has_more and empty.next_cursor == last.next_cursor
    added = registry_service.publish(draft(), publisher, uuid4()).artifact
    assert reader.page(read_principal, since_seq=empty.next_cursor, limit=2).items == [added]
    with pytest.raises(PermissionError):
        reader.page(publisher, since_seq=0, limit=2)


@pytest.mark.database
def test_page_size_and_bytes_bounds_are_explicit_without_cursor_loss(
    registry_service, registry_connect, publisher, draft, reader, read_principal
):
    records = [registry_service.publish(draft(), publisher, uuid4()).artifact for _ in range(3)]
    with registry_connect() as conn:
        largest = conn.execute(
            "SELECT max(octet_length(payload::text)) FROM registry.artifact_versions "
            "WHERE program_id=ANY(%s)",
            [list(publisher.programs)],
        ).fetchone()[0]
    reader.policy = reader.policy.model_copy(update={"max_page_bytes": largest + 1024})
    page = reader.page(read_principal, since_seq=0, limit=3)
    assert page.items == records[:1] and page.has_more
    page2 = reader.page(read_principal, since_seq=page.next_cursor, limit=3)
    assert page2.items == records[1:2] and page2.has_more
    for cursor, limit in ((-1, 1), (0, 0), (0, 101)):
        with pytest.raises(InvalidPublication, match="page bounds"):
            reader.page(read_principal, since_seq=cursor, limit=limit)
    reader.policy = reader.policy.model_copy(update={"max_page_bytes": 1})
    with pytest.raises(InvalidPublication, match="byte bound"):
        reader.page(read_principal, since_seq=0, limit=1)


@pytest.mark.database
def test_family_and_bidirectional_lineage_have_stable_bounded_depth(
    registry_service, publisher, draft, reader, read_principal
):
    root = registry_service.publish(draft(), publisher, uuid4()).artifact
    family = root.manifest.family_id
    left = child(registry_service, publisher, draft, [root], family=family)
    right = child(registry_service, publisher, draft, [root], family=family)
    joined = child(registry_service, publisher, draft, [left, right])
    root_id = UUID(root.manifest.artifact_version_id)
    family_page = reader.family(UUID(family), publisher, since_seq=0, limit=2)
    assert family_page.versions.items == [root, left] and family_page.versions.has_more
    assert reader.family(
        UUID(family), publisher, since_seq=family_page.versions.next_cursor, limit=2
    ).versions.items == [right]
    zero = reader.lineage(root_id, read_principal, depth=0)
    assert len(zero.nodes) == 1 and not zero.edges and zero.truncated_at_depth
    one = reader.lineage(root_id, read_principal, depth=1)
    assert len(one.nodes) == 3 and len(one.edges) == 2 and one.truncated_at_depth
    complete = reader.lineage(root_id, read_principal, depth=2)
    assert len(complete.nodes) == 4 and len(complete.edges) == 4 and not complete.truncated_at_depth
    assert {n.artifact_version_id for n in complete.nodes} == {
        r.manifest.artifact_version_id for r in [root, left, right, joined]
    }
    reverse = reader.lineage(UUID(joined.manifest.artifact_version_id), read_principal, depth=2)
    assert reverse.nodes == complete.nodes and reverse.edges == complete.edges
    with pytest.raises(RegistryNotFound):
        reader.family(uuid4(), read_principal, since_seq=0, limit=2)
    for depth in (-1, 17):
        with pytest.raises(InvalidPublication, match="lineage depth"):
            reader.lineage(root_id, read_principal, depth=depth)
    reader.policy = reader.policy.model_copy(update={"max_lineage_nodes": 1})
    with pytest.raises(InvalidPublication, match="resource bound"):
        reader.lineage(root_id, read_principal, depth=1)
    reader.policy = reader.policy.model_copy(update={"max_lineage_edges": 1})
    with pytest.raises(InvalidPublication, match="edge bound"):
        reader.lineage(root_id, read_principal, depth=1)


@pytest.mark.database
def test_payload_is_authorized_hash_verified_and_never_resolved_from_user_path(
    registry_service, publisher, draft, reader, read_principal
):
    data = b"synthetic immutable attachment"
    digest = hashlib.sha256(data).hexdigest()
    body = draft().model_dump(mode="json")
    body["manifest"]["payload_files"] = [
        {"asset_id": "attachment", "sha256": digest, "media_type": "application/octet-stream"}
    ]
    body["files"] = [{"asset_id": "attachment", "data_base64": base64.b64encode(data).decode()}]
    record = registry_service.publish(
        PublicationRequest.model_validate(body), publisher, uuid4()
    ).artifact
    identity = UUID(record.manifest.artifact_version_id)
    assert reader.payload(identity, "attachment", read_principal) == (
        data,
        "application/octet-stream",
        digest,
    )
    app = create_app(registry_service, read_policy=reader.policy)
    app.dependency_overrides[unavailable_authorizer] = lambda: read_principal
    response = TestClient(app).get(f"/v1/artifacts/{identity}/payload?asset_id=attachment")
    assert response.status_code == 200 and response.content == data
    assert response.headers["etag"] == f'"{digest}"'
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-disposition"] == "attachment"
    for asset in ("missing", "../../etc/passwd", digest):
        with pytest.raises(RegistryNotFound):
            reader.payload(identity, asset, read_principal)
    path = reader.store.root / record.payload_digest
    path.chmod(0o600)
    path.write_bytes(b"controlled corruption of a test object")
    with pytest.raises(ValueError, match="checksum mismatch"):
        reader.get(identity, read_principal)


@pytest.mark.database
def test_http_reads_roles_bounds_schema_and_default_denial(
    registry_service, publisher, draft, reader, read_principal
):
    record = registry_service.publish(draft(), publisher, uuid4()).artifact
    app = create_app(registry_service, read_policy=reader.policy)
    app.dependency_overrides[unavailable_authorizer] = lambda: read_principal
    client = TestClient(app)
    identity = record.manifest.artifact_version_id
    urls = [
        "/v1/artifacts?since_seq=0&limit=2",
        f"/v1/artifacts/{identity}",
        f"/v1/families/{record.manifest.family_id}?since_seq=0&limit=2",
        f"/v1/artifacts/{identity}/lineage?depth=1",
    ]
    closed = TestClient(create_app(registry_service, read_policy=reader.policy))
    for url in urls:
        assert client.get(url).status_code == 200
        assert closed.get(url).status_code == 401
    assert client.get(f"/v1/families/{record.manifest.family_id}").status_code == 200
    assert client.get(f"/v1/artifacts/{uuid4()}").status_code == 404
    for query in ("since_seq=-1&limit=1", "since_seq=0&limit=101", "limit=1"):
        assert client.get("/v1/artifacts?" + query).status_code == 400
    assert client.get(f"/v1/artifacts/{identity}/lineage?depth=17").status_code == 400
    outsider = Principal("outside", frozenset({"reader"}), frozenset({"other-program"}))
    app.dependency_overrides[unavailable_authorizer] = lambda: outsider
    assert not client.get(urls[0]).json()["items"]
    for url in urls[1:]:
        assert client.get(url).status_code == 404
    missing_policy = create_app(registry_service)
    missing_policy.dependency_overrides[unavailable_authorizer] = lambda: read_principal
    assert TestClient(missing_policy).get(urls[0]).status_code == 503


def test_page_and_lineage_contracts_reject_inconsistent_references():
    with pytest.raises(ValueError, match="empty page"):
        ArtifactPage(items=[], next_cursor=0, has_more=True)
    with pytest.raises(ValueError, match="include its root"):
        ArtifactLineage(
            root_version_id="absent", depth=0, nodes=[], edges=[], truncated_at_depth=False
        )
