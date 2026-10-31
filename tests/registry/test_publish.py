"""P2.2 and P2.3 against the real registry_db: REG-02, REG-03, REG-04 and AUD-01."""

import hashlib
import json

import pytest
from qfr_core.composite import strategy_canonical_hash
from qfr_core.config import canonical_json
from qfr_core.contracts import FactorManifest, StrategyImplementation
from qfr_core.dsl import apply_diff, canonicalize, parse, to_string
from qfr_core.ids import uuid7
from sqlalchemy import text

from tests.registry_rig import (
    factor_manifest,
    headers,
    research_ids,
    seed_manifest,
    strategy_manifest,
)

pytestmark = pytest.mark.postgres


def expected_hash(manifest):
    normalized = FactorManifest.model_validate(manifest).model_dump(mode="json")
    return hashlib.sha256(canonical_json(normalized).encode()).hexdigest()


def test_reg_02_republishing_identical_content_returns_the_same_version(rig):
    manifest = factor_manifest()
    first = rig.publish(manifest)
    assert first.status_code == 201, first.text
    again = rig.publish(manifest)
    assert again.status_code == 200, again.text
    assert again.json()["created"] is False
    assert again.json()["version"]["version_id"] == first.json()["version"]["version_id"]
    assert "artifact_publish_idempotent" in rig.log_lines()
    count = rig.db.conn.execute(text("SELECT count(*) FROM artifact_versions")).scalar()
    assert count == 1


def test_reg_03_any_manifest_change_creates_a_new_version(rig):
    ids = research_ids()
    first = rig.publish(factor_manifest(ids=ids)).json()["version"]
    family = first["family_id"]
    seen = {first["content_hash"]}
    changes = [
        factor_manifest(ids=ids, family_id=family, sign=-1),  # sign flip
        factor_manifest(
            expression="Mean($close, 10) / Mean($close, 60) - 1",  # window change
            ids=ids,
            family_id=family,
            parents=[first["version_id"]],
        ),
        factor_manifest(ids=ids, family_id=family, title="Retitled"),  # any other edit
    ]
    numbers = []
    for manifest in changes:
        response = rig.publish(manifest)
        assert response.status_code == 201, response.text
        version = response.json()["version"]
        assert version["family_id"] == family
        assert version["content_hash"] not in seen
        seen.add(version["content_hash"])
        numbers.append(version["version_no"])
    assert numbers == [2, 3, 4]
    family_view = rig.client.get(f"/v1/families/{family}", headers=headers("reader")).json()
    assert [v["version_no"] for v in family_view["versions"]] == [1, 2, 3, 4]


def test_reg_04_server_computes_hashes_and_ignores_client_values(rig):
    manifest = factor_manifest()
    forged = "f" * 64
    body = {
        "publish_key": "forged-hash",
        "content_hash": forged,
        "canonical_hash": forged,
        "version_no": 99,
        "manifest": manifest | {"content_hash": forged, "version_id": str(uuid7())},
    }
    response = rig.client.post("/v1/artifacts", json=body, headers=headers("publisher"))
    assert response.status_code == 201, response.text
    version = response.json()["version"]
    assert version["content_hash"] == expected_hash(manifest) != forged
    assert (
        version["canonical_hash"]
        == hashlib.sha256(b"((Mean($close,20)/Mean($close,60))-1)").hexdigest()
    )
    assert version["version_no"] == 1
    assert "client_server_fields_ignored" in rig.log_lines()


def test_declared_fields_and_lookback_must_match_the_parsed_expression(rig):
    manifest = factor_manifest()
    manifest["declared"]["fields_used"] = ["close", "volume"]
    response = rig.publish(manifest)
    assert response.status_code == 400
    assert response.json()["error"] == "DECLARATION_MISMATCH"
    manifest = factor_manifest()
    manifest["declared"]["max_lookback_days"] = 20
    assert rig.publish(manifest).json()["error"] == "DECLARATION_MISMATCH"


def test_invalid_expressions_and_schemas_are_400_with_fields(rig):
    manifest = factor_manifest()
    manifest["implementation"]["expression"] = "Mean($close, 20"
    response = rig.publish(manifest)
    assert response.status_code == 400
    assert response.json()["error"] == "PARSE_ERROR"
    manifest = factor_manifest()
    manifest["implementation"]["expression"] = "Mean($close, 7)"  # window outside the set
    assert rig.publish(manifest).json()["error"] == "FORBIDDEN_CONSTRUCT"
    manifest = factor_manifest()
    del manifest["rationale"]
    response = rig.publish(manifest)
    assert response.status_code == 400
    assert response.json()["error"] == "SCHEMA_INVALID"
    assert any("rationale" in d["field"] for d in response.json()["details"])
    nothing = rig.db.conn.execute(text("SELECT count(*) FROM artifact_versions")).scalar()
    assert nothing == 0


def test_complexity_caps_are_recorded_for_screening_not_enforced(rig):
    long = " + ".join(f"Mean($close, {w})" for w in (1, 2, 3, 5, 10, 20, 40, 60))
    response = rig.publish(factor_manifest("wide", long))
    assert response.status_code == 201, response.text
    errors = response.json()["version"]["analysis"]["static_limit_errors"]
    assert errors and errors[0]["code"] == "COMPLEXITY_LIMIT"


def test_family_rules(rig):
    ids = research_ids()
    first = rig.publish(factor_manifest(ids=ids)).json()["version"]
    clash = rig.publish(factor_manifest(ids=ids, expression="Mean($close, 5)"))
    assert clash.status_code == 409 and clash.json()["error"] == "NAME_CONFLICT"
    renamed = factor_manifest("other_name", ids=ids, family_id=first["family_id"])
    assert rig.publish(renamed).json()["error"] == "NAME_MISMATCH"
    elsewhere = factor_manifest(family_id=first["family_id"])
    assert rig.publish(elsewhere).json()["error"] == "PROGRAM_MISMATCH"
    unknown = rig.publish(factor_manifest(family_id=str(uuid7())))
    assert unknown.status_code == 400 and unknown.json()["error"] == "FAMILY_UNKNOWN"
    # The same name in another program is another family.
    assert rig.publish(factor_manifest(expression="Mean($close, 3)")).status_code == 201


def test_lineage_records_parents_with_ast_diffs_that_rebuild_the_child(rig):
    ids = research_ids()
    root = rig.publish(factor_manifest(ids=ids)).json()["version"]
    child_expression = "Rank(Mean($close, 10) / Mean($close, 60) - 1)"
    child = rig.publish(
        factor_manifest(
            "child",
            child_expression,
            ids=ids,
            parents=[root["version_id"]],
            operator="llm_mutation",
        )
    ).json()["version"]
    grandchild = rig.publish(
        factor_manifest(
            "grandchild",
            "Rank(Mean($close, 10) / Mean($close, 120) - 1)",
            ids=ids,
            parents=[child["version_id"]],
            operator="syntactic_mutation",
        )
    ).json()["version"]
    view = rig.client.get(
        f"/v1/artifacts/{child['version_id']}/lineage?depth=1", headers=headers("evaluator")
    ).json()
    assert {n["version_id"]: n["distance"] for n in view["nodes"]} == {
        root["version_id"]: -1,
        child["version_id"]: 0,
        grandchild["version_id"]: 1,
    }
    edge = next(e for e in view["edges"] if e["version_id"] == child["version_id"])
    assert edge["relation"] == "parent" and edge["ast_diff"]
    rebuilt = apply_diff(
        canonicalize(parse(root["manifest"]["implementation"]["expression"])), edge["ast_diff"]
    )
    assert to_string(rebuilt) == child["analysis"]["canonical"]
    deep = rig.client.get(
        f"/v1/artifacts/{root['version_id']}/lineage?depth=5", headers=headers("reader")
    ).json()
    assert [n["distance"] for n in deep["nodes"]] == [0, 1, 2]
    missing = rig.client.get(
        f"/v1/artifacts/{root['version_id']}/lineage", headers=headers("reader")
    )
    assert missing.status_code == 200
    unknown_parent = factor_manifest("orphan", ids=ids, parents=[str(uuid7())])
    assert rig.publish(unknown_parent).json()["error"] == "PARENT_UNKNOWN"


def test_strategies_reference_published_factors_and_hash_normalized_weights(rig):
    ids = research_ids()
    a = rig.publish(factor_manifest("a_factor", ids=ids)).json()["version"]
    b = rig.publish(factor_manifest("b_factor", "Mean($volume, 20)", ids=ids)).json()["version"]
    manifest = strategy_manifest([(a["version_id"], 1, 1.0), (b["version_id"], -1, 3.0)], ids=ids)
    response = rig.publish(manifest)
    assert response.status_code == 201, response.text
    version = response.json()["version"]
    weights = [w["weight"] for w in version["analysis"]["normalized_weights"]]
    assert weights == [0.25, 0.75]
    implementation = StrategyImplementation.model_validate(manifest["implementation"])
    assert version["canonical_hash"] == strategy_canonical_hash(implementation)
    lineage = rig.client.get(
        f"/v1/artifacts/{version['version_id']}/lineage", headers=headers("reader")
    ).json()
    assert {e["relation"] for e in lineage["edges"]} == {"component"}
    # A revised strategy records a component-level diff to its parent strategy.
    revised = strategy_manifest(
        [(a["version_id"], 1, 1.0), (b["version_id"], -1, 1.0)],
        ids=ids,
        family_id=version["family_id"],
        extra_parents=[version["version_id"]],
        top_k=60,
    )
    second = rig.publish(revised).json()["version"]
    assert second["version_no"] == 2
    edges = rig.client.get(
        f"/v1/artifacts/{second['version_id']}/lineage", headers=headers("reader")
    ).json()["edges"]
    parent_edge = next(e for e in edges if e["relation"] == "parent")
    assert {d["op"] for d in parent_edge["ast_diff"]} == {"component_changed", "portfolio_changed"}
    # Components must be published factor versions.
    bad = strategy_manifest([(str(uuid7()), 1, 1.0)], "bad_blend", ids=ids)
    assert rig.publish(bad).json()["error"] == "COMPONENT_INVALID"
    nested = strategy_manifest([(version["version_id"], 1, 1.0)], "nested", ids=ids)
    assert rig.publish(nested).json()["error"] == "COMPONENT_INVALID"


def test_publication_roles_and_publish_keys(rig):
    explore = factor_manifest()
    denied = rig.publish(explore, role="control")
    assert denied.status_code == 403 and denied.json()["error"] == "CONTROL_SEEDS_ONLY"
    pretend = rig.publish(seed_manifest(), role="publisher")
    assert pretend.status_code == 403 and pretend.json()["error"] == "SETUP_IMPORT_CONTROL_ONLY"
    assert rig.publish(seed_manifest(), role="control").status_code == 201
    for role in ("reader", "evaluator"):
        assert rig.publish(explore, role=role).status_code == 403
    anonymous = rig.client.post("/v1/artifacts", json={"publish_key": "x", "manifest": explore})
    assert anonymous.status_code == 401 and anonymous.json()["error"] == "UNAUTHORIZED"
    assert rig.publish(explore, key="retry-key").status_code == 201
    other = factor_manifest("another")
    reused = rig.publish(other, key="retry-key")
    assert reused.status_code == 409 and reused.json()["error"] == "PUBLISH_KEY_REUSED"


def test_since_seq_listing_is_ordered_and_role_restricted(rig):
    ids = research_ids()
    published = [
        rig.publish(factor_manifest(f"f{i}", f"Mean($close, {w})", ids=ids)).json()["version"]
        for i, w in enumerate((5, 10, 20))
    ]
    first = rig.client.get("/v1/artifacts?since_seq=0&limit=2", headers=headers("evaluator"))
    page = first.json()
    assert [v["version_id"] for v in page["items"]] == [p["version_id"] for p in published[:2]]
    rest = rig.client.get(
        f"/v1/artifacts?since_seq={page['next_since_seq']}", headers=headers("control")
    ).json()
    assert [v["version_id"] for v in rest["items"]] == [published[2]["version_id"]]
    assert rig.client.get("/v1/artifacts", headers=headers("publisher")).status_code == 403
    one = rig.client.get(
        f"/v1/artifacts/{published[0]['version_id']}", headers=headers("publisher")
    )
    assert one.status_code == 200 and one.json()["manifest"]["name"] == "f0"
    assert rig.client.get(f"/v1/artifacts/{uuid7()}", headers=headers("reader")).status_code == 404
    too_many = rig.client.get("/v1/artifacts?limit=2001", headers=headers("reader"))
    assert too_many.status_code == 400


def test_aud_01_every_write_has_an_audit_row_with_principal_and_request_id(rig):
    response = rig.client.post(
        "/v1/artifacts",
        json={"publish_key": "audit", "manifest": factor_manifest()},
        headers=headers("publisher", **{"X-Request-Id": "req-audit-1"}),
    )
    assert response.headers["X-Request-Id"] == "req-audit-1"
    version_id = response.json()["version"]["version_id"]
    row = (
        rig.db.conn.execute(
            text("SELECT principal, action, request_id, version_id, payload FROM registry_events")
        )
        .mappings()
        .one()
    )
    assert row["principal"] == "publisher" and row["action"] == "VERSION_PUBLISHED"
    assert row["request_id"] == "req-audit-1" and str(row["version_id"]) == version_id
    stored = rig.db.conn.execute(
        text("SELECT request_id FROM artifact_versions WHERE version_id = :v"), {"v": version_id}
    ).scalar()
    assert stored == "req-audit-1"
    lines = [json.loads(line) for line in rig.log_lines().splitlines()]
    published = next(line for line in lines if line["event"] == "artifact_published")
    assert published["request_id"] == "req-audit-1" and published["version_id"] == version_id
    assert published["principal"] == "publisher" and published["family_id"]
    request_line = next(line for line in lines if line["event"] == "api_request_completed")
    assert request_line["payload"]["status"] == 201 and request_line["principal"] == "publisher"
    assert "test-publisher-token" not in rig.log_lines()
