"""P2.4 pool routes and P2.1 database protections: POOL-01, REG-01 and AUD-01."""

import os

import pytest
from qfr_core.ids import uuid7
from sqlalchemy import create_engine, text

from tests.registry_rig import (
    database_url,
    factor_manifest,
    headers,
    research_ids,
    seed_manifest,
    strategy_manifest,
)

pytestmark = pytest.mark.postgres


def approval(version_id, decision="approve", pool="factor", tier="w1_pass", entry_ids=()):
    return {
        "approval_id": str(uuid7()),
        "decision": decision,
        "scope": {
            "job_id": None,
            "deliverable_id": None,
            "version_ids": [version_id] if version_id else [],
            "pool": pool,
            "tier": tier,
            "case_id": None,
            "entry_ids": list(entry_ids),
        },
    }


def add(rig, body, role="control", pool="factor"):
    return rig.client.post(f"/v1/pools/{pool}/entries", json=body, headers=headers(role))


def seed_body(version_id, setup_ref=None, tags=("momentum",)):
    return {
        "version_id": version_id,
        "title": "Seed",
        "status": "seed",
        "setup_ref": setup_ref or str(uuid7()),
        "tags": list(tags),
    }


def test_pool_01_seed_imports_need_a_setup_reference_and_only_control_writes(rig):
    seed = rig.publish(seed_manifest(), role="control").json()["version"]
    setup_ref = str(uuid7())
    for role in ("publisher", "reader", "evaluator"):
        denied = add(rig, seed_body(seed["version_id"], setup_ref), role=role)
        assert denied.status_code == 403 and denied.json()["error"] == "FORBIDDEN_ROLE"
    no_reference = seed_body(seed["version_id"]) | {"setup_ref": None}
    assert add(rig, no_reference).status_code == 400
    created = add(rig, seed_body(seed["version_id"], setup_ref))
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["entry"]["status"] == "seed" and body["entry"]["setup_ref"] == setup_ref
    assert body["event"]["action"] == "ADDED" and body["event"]["to_status"] == "seed"
    again = add(rig, seed_body(seed["version_id"], str(uuid7())))
    assert again.status_code == 200 and again.json()["created"] is False
    assert again.json()["entry"]["entry_id"] == body["entry"]["entry_id"]
    # A research version is never a seed.
    research = rig.publish(factor_manifest()).json()["version"]
    refused = add(rig, seed_body(research["version_id"]))
    assert refused.status_code == 409 and refused.json()["error"] == "NOT_A_SETUP_IMPORT"
    audit = (
        rig.db.conn.execute(
            text("SELECT principal, action, payload FROM registry_events WHERE action LIKE 'POOL%'")
        )
        .mappings()
        .all()
    )
    assert len(audit) == 1 and audit[0]["principal"] == "control"
    assert audit[0]["payload"]["setup_ref"] == setup_ref


def test_pool_01_approved_entries_require_an_approval_covering_the_version(rig):
    version = rig.publish(factor_manifest()).json()["version"]["version_id"]
    other = rig.publish(factor_manifest("other", "Mean($close, 5)")).json()["version"]["version_id"]
    base = {"version_id": version, "title": "Approved", "status": "approved"}
    missing = add(rig, base | {"approved_tier": "w1_pass"})
    assert missing.status_code == 400 and missing.json()["error"] == "SCHEMA_INVALID"
    for wrong in (
        approval(other),  # another version
        approval(version, decision="retire"),  # another decision
        approval(version, pool="strategy"),  # another pool
        approval(version, tier="w2_pass"),  # another tier
    ):
        response = add(rig, base | {"approved_tier": "w1_pass", "approval": wrong})
        assert response.status_code == 403, response.text
        assert response.json()["error"] == "APPROVAL_SCOPE_MISMATCH"
    for role in ("publisher", "reader", "evaluator"):
        denied = add(rig, base | {"approved_tier": "w1_pass", "approval": approval(version)}, role)
        assert denied.status_code == 403
    good = approval(version)
    created = add(rig, base | {"approved_tier": "w1_pass", "approval": good})
    assert created.status_code == 201, created.text
    entry = created.json()["entry"]
    assert entry["status"] == "approved" and entry["approval_id"] == good["approval_id"]
    duplicate = add(rig, base | {"approved_tier": "w1_pass", "approval": approval(version)})
    assert duplicate.status_code == 409 and duplicate.json()["error"] == "ENTRY_EXISTS"
    row = rig.db.conn.execute(
        text("SELECT payload FROM registry_events WHERE action = 'POOL_ENTRY_ADDED'")
    ).scalar_one()
    assert row["approval_id"] == good["approval_id"]
    assert row["approval_scope"]["version_ids"] == [version]


def test_pool_01_status_events_need_approval_and_annotations_do_not(rig):
    seed = rig.publish(seed_manifest(), role="control").json()["version"]["version_id"]
    entry = add(rig, seed_body(seed, tags=("value",))).json()["entry"]
    url = f"/v1/pools/factor/entries/{entry['entry_id']}/events"
    retire = {"action": "STATUS_CHANGED", "to_status": "retired"}
    assert rig.client.post(url, json=retire, headers=headers("control")).status_code == 400
    for role in ("publisher", "reader", "evaluator"):
        body = retire | {"approval": approval(seed, decision="retire", tier=None)}
        assert rig.client.post(url, json=body, headers=headers(role)).status_code == 403
    wrong = retire | {"approval": approval(seed, decision="approve", tier=None)}
    assert rig.client.post(url, json=wrong, headers=headers("control")).status_code == 403
    by_entry = approval(None, decision="retire", tier=None, entry_ids=[entry["entry_id"]])
    response = rig.client.post(
        url, json=retire | {"approval": by_entry}, headers=headers("control")
    )
    assert response.status_code == 201, response.text
    event = response.json()
    assert (event["from_status"], event["to_status"]) == ("seed", "retired")
    again = rig.client.post(
        url,
        json=retire | {"approval": approval(seed, decision="retire", tier=None)},
        headers=headers("control"),
    )
    assert again.status_code == 409 and again.json()["error"] == "STATUS_UNCHANGED"
    reapprove = {
        "action": "STATUS_CHANGED",
        "to_status": "approved",
        "approved_tier": "w2_pass",
        "approval": approval(seed, tier="w2_pass"),
    }
    assert rig.client.post(url, json=reapprove, headers=headers("control")).status_code == 201
    note = {"action": "ANNOTATED", "tags": ["quality"], "note": "Owner's remark."}
    annotated = rig.client.post(url, json=note, headers=headers("control"))
    assert annotated.status_code == 201 and annotated.json()["to_status"] is None
    with_approval = note | {"approval": approval(seed)}
    assert rig.client.post(url, json=with_approval, headers=headers("control")).status_code == 400
    current = rig.client.get(
        f"/v1/pools/factor/entries/{entry['entry_id']}", headers=headers("reader")
    )
    detail = current.json()
    assert detail["entry"]["status"] == "approved"
    assert detail["entry"]["approved_tier"] == "w2_pass"
    assert detail["entry"]["tags"] == ["quality", "value"]
    assert [e["action"] for e in detail["events"]] == [
        "ADDED",
        "STATUS_CHANGED",
        "STATUS_CHANGED",
        "ANNOTATED",
    ]
    actions = (
        rig.db.conn.execute(
            text("SELECT action FROM registry_events WHERE entry_id = :e ORDER BY at"),
            {"e": entry["entry_id"]},
        )
        .scalars()
        .all()
    )
    assert actions == ["POOL_ENTRY_ADDED"] + ["POOL_EVENT_APPENDED"] * 3


def test_kind_must_match_the_pool(rig):
    ids = research_ids()
    factor = rig.publish(factor_manifest(ids=ids)).json()["version"]["version_id"]
    strategy = rig.publish(strategy_manifest([(factor, 1, 1.0)], ids=ids)).json()["version"]
    body = {
        "version_id": factor,
        "title": "Wrong pool",
        "status": "approved",
        "approved_tier": "w1_pass",
        "approval": approval(factor, pool="strategy"),
    }
    conflict = add(rig, body, pool="strategy")
    assert conflict.status_code == 409 and conflict.json()["error"] == "KIND_POOL_CONFLICT"
    body = body | {
        "version_id": strategy["version_id"],
        "approval": approval(strategy["version_id"], pool="strategy"),
    }
    assert add(rig, body, pool="strategy").status_code == 201
    unknown = add(rig, body | {"version_id": str(uuid7())}, pool="strategy")
    assert unknown.status_code == 400 and unknown.json()["error"] == "VERSION_UNKNOWN"
    assert rig.client.get("/v1/pools/bonds", headers=headers("reader")).status_code == 400


def test_pool_listing_and_events_since_seq(rig):
    entries = []
    for i, window in enumerate((5, 10, 20)):
        seed = rig.publish(
            seed_manifest(f"seed_{i}", f"Mean($close, {window})"), role="control"
        ).json()["version"]["version_id"]
        entries.append(add(rig, seed_body(seed)).json()["entry"])
    page = rig.client.get("/v1/pools/factor?limit=2", headers=headers("publisher")).json()
    assert [e["entry_id"] for e in page["items"]] == [e["entry_id"] for e in entries[:2]]
    rest = rig.client.get(
        f"/v1/pools/factor?cursor={page['next_cursor']}", headers=headers("reader")
    ).json()
    assert [e["entry_id"] for e in rest["items"]] == [entries[2]["entry_id"]]
    assert rest["next_cursor"] is None
    seeds = rig.client.get("/v1/pools/factor?status=seed", headers=headers("reader")).json()
    assert len(seeds["items"]) == 3
    assert rig.client.get("/v1/pools/strategy", headers=headers("reader")).json()["items"] == []
    events = rig.client.get(
        "/v1/pools/factor/events?since_seq=0&limit=2", headers=headers("evaluator")
    ).json()
    assert [e["entry_id"] for e in events["items"]] == [e["entry_id"] for e in entries[:2]]
    tail = rig.client.get(
        f"/v1/pools/factor/events?since_seq={events['next_since_seq']}",
        headers=headers("evaluator"),
    ).json()
    assert [e["entry_id"] for e in tail["items"]] == [entries[2]["entry_id"]]
    assert (
        rig.client.get("/v1/pools/factor/events", headers=headers("publisher")).status_code == 403
    )


def _seed_rows(conn):
    """Insert one row in every protected table, as the connection's role."""
    family, version, entry, now = uuid7(), uuid7(), uuid7(), "2026-10-30T00:00:00Z"
    conn.execute(
        text("""INSERT INTO artifact_families VALUES
                (:f, 'factor', NULL, NULL, 'reg01', :now, 'test', 'r')"""),
        {"f": family, "now": now},
    )
    conn.execute(
        text("""INSERT INTO artifact_versions (version_id, family_id, version_no, kind,
                manifest, payload_text, content_hash, canonical_hash, published_at, publisher,
                publish_key, analysis, request_id)
                VALUES (:v, :f, 1, 'factor', '{}', 'x', :h, :h, :now, 'test', 'k', '{}', 'r')"""),
        {"v": version, "f": family, "h": "b" * 64, "now": now},
    )
    conn.execute(
        text("""INSERT INTO pool_entries VALUES (:e, 'factor', :v, 't', :now, 'test', NULL,
                :s, 'r')"""),
        {"e": entry, "v": version, "s": uuid7(), "now": now},
    )
    conn.execute(
        text("""INSERT INTO pool_events (event_id, entry_id, at, principal, action, to_status,
                setup_ref, request_id) VALUES (:id, :e, :now, 'test', 'ADDED', 'seed', :s, 'r')"""),
        {"id": uuid7(), "e": entry, "s": uuid7(), "now": now},
    )


STATEMENTS = [
    f"{verb} {table}"
    for table in ("artifact_versions", "pool_entries", "pool_events")
    for verb in ("UPDATE", "DELETE FROM", "TRUNCATE")
]


def _sql(statement):
    verb, table = statement.rsplit(" ", 1)
    if verb == "UPDATE":
        column = {"artifact_versions": "publisher", "pool_entries": "title", "pool_events": "note"}
        return f"UPDATE {table} SET {column[table]} = 'altered'"
    if verb == "TRUNCATE":
        # CASCADE gets past the foreign-key check so the TRUNCATE trigger is what refuses.
        return f"TRUNCATE {table} CASCADE"
    return statement


@pytest.mark.parametrize("statement", STATEMENTS)
def test_reg_01_updates_and_deletes_raise_even_as_registry_app(statement):
    engine = create_engine(database_url("REGISTRY"))
    with engine.connect() as conn:
        outer = conn.begin()
        _seed_rows(conn)
        with pytest.raises(Exception, match="permission denied"), conn.begin_nested():
            conn.execute(text(_sql(statement)))
        outer.rollback()
    engine.dispose()


@pytest.mark.parametrize("statement", STATEMENTS)
def test_reg_01_triggers_block_mutation_for_the_table_owner(statement):
    url = os.environ.get("QFR_TEST_REGISTRY_MIGRATION_URL")
    if not url:
        if os.environ.get("QFR_REQUIRE_DB_TESTS") == "1":
            pytest.fail("the registry migration URL is required")
        pytest.skip("registry migration credentials not configured")
    engine = create_engine(url)
    with engine.connect() as conn:
        outer = conn.begin()
        _seed_rows(conn)
        with pytest.raises(Exception, match="append-only"), conn.begin_nested():
            conn.execute(text(_sql(statement)))
        outer.rollback()
    engine.dispose()


def test_registry_role_has_no_ddl_and_the_view_is_read_only():
    engine = create_engine(database_url("REGISTRY"))
    with engine.connect() as conn:
        privileges = conn.execute(
            text("""SELECT has_table_privilege(current_user, 'pool_current_v', 'INSERT'),
                           has_schema_privilege(current_user, 'public', 'CREATE'),
                           has_table_privilege(current_user, 'registry_events', 'UPDATE')""")
        ).one()
    assert tuple(privileges) == (False, False, False)
    engine.dispose()
