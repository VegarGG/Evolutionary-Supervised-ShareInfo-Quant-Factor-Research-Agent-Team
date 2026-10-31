"""SET-01 and SET-02 through the MCP front door, against real registry_db and control_db."""

import csv
import io
from uuid import UUID

import pytest
from qfr_core.pool_import import NO_DEFAULTS_NOTICE

from tests.mcp.setup_rig import setup_rig

pytestmark = pytest.mark.postgres

ZERO = {"seed": 0, "approved": 0, "retired": 0, "total": 0}
ROWS = [
    (
        "ma_cross_20_60",
        "20/60 moving-average crossover",
        "Mean($close, 20) / Mean($close, 60) - 1",
        1,
        5,
        "momentum;trend",
        "from the owner's 2024 notebook",
    ),
    ("reversal_5", "Five-day reversal", "-Delta($close, 5) / Ref($close, 5)", 1, 5, "reversal", ""),
    ("price_volume_corr", "Price-volume correlation", "Corr($close, $volume, 20)", -1, 10, "", ""),
    ("volume_surge", "Volume surge", "Rank($volume) - Rank(Mean($volume, 20))", 1, 5, "", ""),
    ("range_20", "Twenty-day range", "Max($high, 20) / Min($low, 20) - 1", -1, 20, "risk", ""),
]


def csv_file(rows):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        ["name", "title", "expression", "expected_sign", "horizon_days", "tags", "notes"]
    )
    writer.writerows(rows)
    return buffer.getvalue()


@pytest.fixture
def rig(tmp_path, monkeypatch):
    with setup_rig(tmp_path, monkeypatch) as built:
        yield built


def test_set_01_a_fresh_stack_is_empty_and_says_so(rig):
    status = rig.ok("qfr.status")["data"]
    assert status["phase"] == 4
    assert status["services"]["registry-api"]["status"] == "ok"
    assert status["services"]["control_db"] == {"healthy": True}
    assert status["pool_counts"] == {"factor": ZERO, "strategy": ZERO}
    assert status["registry_counts"] == {
        "factor_versions": 0,
        "strategy_versions": 0,
        "families": 0,
    }
    assert status["notice"] == NO_DEFAULTS_NOTICE
    assert status["setup_complete"] is False and status["setup"] == {}

    setup = rig.ok("qfr.setup.status")["data"]
    assert setup["steps"]["pool"]["status"] == "not_started"
    assert setup["steps"]["providers"]["status"] == "not_configured"
    assert setup["steps"]["data"]["status"] == "not_configured"
    assert setup["steps"]["token"]["status"] == "ok"
    assert setup["notice"] == NO_DEFAULTS_NOTICE and setup["setup_complete"] is False
    for pool in ("factor", "strategy"):
        assert rig.ok("qfr.pool.list", pool=pool)["data"]["items"] == []

    declined = rig.ok("qfr.pool.import", no_pool=True)
    assert declined["status"] == "ok"
    assert declined["data"]["notice"] == NO_DEFAULTS_NOTICE
    assert declined["data"]["setup_ref"] is None and declined["data"]["entries"] == []

    state = rig.store.latest_setup_states()["pool"]
    assert state.status == "empty" and state.principal == "owner"
    assert state.details["notice"] == NO_DEFAULTS_NOTICE
    assert state.request_id == declined["request_id"]
    assert rig.audit.calls[-1].request_id == declined["request_id"]
    assert declined["request_id"] in rig.audit.calls[-1].downstream_request_ids
    assert rig.events("qfr-mcp", "setup_pool_declined")[-1]["request_id"] == declined["request_id"]
    summary_lines = [
        line
        for line in rig.events("registry-api", "api_request_completed")
        if line["payload"]["path"] == "/v1/summary"
    ]
    assert summary_lines[-1]["request_id"] == declined["request_id"]

    after = rig.ok("qfr.status")["data"]
    assert after["setup"]["pool"]["status"] == "empty"
    assert after["notice"] == NO_DEFAULTS_NOTICE
    assert rig.trace_counts() == {}


def test_set_02_a_five_row_file_yields_five_human_seed_versions_and_entries(rig):
    (rig.imports / "raw_pool.csv").write_text(csv_file(ROWS))
    report = rig.ok("qfr.pool.import", file="raw_pool.csv")
    data = report["data"]
    assert report["status"] == "ok"
    assert data["counts"] == {
        "entries": 5,
        "published": 5,
        "unchanged": 0,
        "invalid": 0,
        "failed": 0,
    }
    assert data["pool_counts"]["factor"] == {"seed": 5, "approved": 0, "retired": 0, "total": 5}
    assert data["pool_counts"]["strategy"] == ZERO
    assert data["notice"] is None
    assert data["source"]["kind"] == "file" and data["source"]["file"] == "raw_pool.csv"
    setup_ref = data["setup_ref"]

    for outcome, row in zip(data["entries"], ROWS, strict=True):
        assert outcome["outcome"] == "published" and outcome["name"] == row[0]
        assert outcome["version_no"] == 1
        version = rig.ok("qfr.artifact.get", version_id=outcome["version_id"])["data"]
        provenance = version["manifest"]["provenance"]
        assert provenance["operator"] == "human_seed" and provenance["job_id"] is None
        assert provenance["research_snapshot_id"] is None
        assert version["manifest"]["implementation"]["expression"] == row[2]
        assert version["content_hash"] == outcome["content_hash"]
        assert version["publisher"] == "control"

    page = rig.ok("qfr.pool.list", pool="factor")["data"]
    assert len(page["items"]) == 5
    assert {item["status"] for item in page["items"]} == {"seed"}
    assert {item["setup_ref"] for item in page["items"]} == {setup_ref}
    tags = {item["title"]: sorted(item["tags"]) for item in page["items"]}
    assert tags["20/60 moving-average crossover"] == ["momentum", "trend"]
    assert page["items"][0]["evidence_tier"] is None

    entry_id = data["entries"][0]["entry_id"]
    detail = rig.ok("qfr.pool.get", pool="factor", entry_id=entry_id)["data"]
    assert [e["action"] for e in detail["events"]] == ["ADDED"]
    assert detail["events"][0]["to_status"] == "seed"
    assert detail["version"]["name"] == "ma_cross_20_60"
    assert detail["version"]["manifest"]["rationale"]["mechanism"] == ROWS[0][6]

    assert rig.trace_counts() == {"DSL_VALIDATED": 5, "SEEDS_PUBLISHED": 5}
    state = rig.store.latest_setup_states()["pool"]
    assert state.status == "imported" and state.details["setup_ref"] == setup_ref
    started = "SELECT count(*) FROM setup_state WHERE state_id = :s AND status = 'importing'"
    assert rig.control_db.count(started, s=UUID(setup_ref)) == 1
    audit = next(c for c in rig.audit.calls if c.request_id == report["request_id"])
    assert audit.tool == "qfr.pool.import" and audit.outcome == "ok"
    assert audit.downstream_request_ids == [report["request_id"]]
    registry_lines = rig.events("registry-api", "api_request_completed")
    assert sum(line["request_id"] == report["request_id"] for line in registry_lines) >= 10
    published = rig.events("qfr-mcp", "pool_import_entry_published")
    assert len(published) == 5 and all(line["candidate_id"] for line in published)

    status = rig.ok("qfr.status")["data"]
    assert status["notice"] is None
    assert status["registry_counts"]["factor_versions"] == 5


def test_set_02_invalid_rows_are_rejected_with_reason_codes_and_logged(rig):
    (rig.imports / "mixed.yaml").write_text(
        "schema_version: pool_import/1\n"
        "entries:\n"
        "  - name: ma_cross_20_60\n"
        "    title: 20/60 moving-average crossover\n"
        '    expression: "Mean($close, 20) / Mean($close, 60) - 1"\n'
        "    expected_sign: 1\n"
        "    horizon_days: 5\n"
        "  - name: unknown_field\n"
        "    title: Uses a field that does not exist\n"
        '    expression: "Mean($foo, 5)"\n'
        "    expected_sign: 1\n"
        "    horizon_days: 5\n"
        "  - name: reversal_5\n"
        "    title: Five-day reversal\n"
        '    expression: "-Delta($close, 5) / Ref($close, 5)"\n'
        "    expected_sign: 1\n"
        "    horizon_days: 5\n"
        "  - name: no_horizon\n"
        "    title: Missing horizon\n"
        '    expression: "Mean($close, 5)"\n'
        "    expected_sign: 1\n"
        "  - name: trend_and_reversal\n"
        "    title: Trend plus reversal\n"
        "    expected_sign: 1\n"
        "    horizon_days: 5\n"
        "    strategy:\n"
        "      components:\n"
        "        - {name: ma_cross_20_60, sign: 1, weight: 0.6}\n"
        "        - {name: reversal_5, sign: 1, weight: 0.4}\n"
        "      combination: zscore_weighted_sum\n"
        "      portfolio: {type: topk_dropout, top_k: 50, dropout: 5, rebalance: daily,"
        " long_only: true}\n"
    )
    report = rig.ok("qfr.pool.import", file="mixed.yaml")
    data = report["data"]
    assert report["status"] == "partial"
    assert data["counts"] == {
        "entries": 5,
        "published": 3,
        "unchanged": 0,
        "invalid": 2,
        "failed": 0,
    }
    by_name = {o["name"]: o for o in data["entries"]}
    assert by_name["unknown_field"]["outcome"] == "invalid"
    assert by_name["unknown_field"]["reasons"][0]["reason_code"] == "FORBIDDEN_CONSTRUCT"
    assert by_name["unknown_field"]["version_id"] is None
    assert by_name["no_horizon"]["reasons"][0]["reason_code"] == "SCHEMA_INVALID"
    assert by_name["no_horizon"]["reasons"][0]["field"] == "horizon_days"
    rejected = rig.events("qfr-mcp", "pool_import_entry_rejected")
    assert {line["payload"]["name"] for line in rejected} == {"unknown_field", "no_horizon"}
    assert {line["error_code"] for line in rejected} == {"FORBIDDEN_CONSTRUCT", "SCHEMA_INVALID"}
    assert all(line["request_id"] == report["request_id"] for line in rejected)

    strategy = by_name["trend_and_reversal"]
    assert strategy["outcome"] == "published" and strategy["kind"] == "strategy"
    assert data["pool_counts"]["strategy"]["seed"] == 1
    version = rig.ok("qfr.artifact.get", version_id=strategy["version_id"])["data"]
    components = version["manifest"]["implementation"]["components"]
    assert [c["version_id"] for c in components] == [
        by_name["ma_cross_20_60"]["version_id"],
        by_name["reversal_5"]["version_id"],
    ]
    assert version["manifest"]["provenance"]["operator"] == "human_seed"


def test_set_02_reimport_is_idempotent_and_a_changed_row_is_a_new_version(rig):
    (rig.imports / "raw_pool.csv").write_text(csv_file(ROWS))
    first = rig.ok("qfr.pool.import", file="raw_pool.csv")["data"]
    again = rig.ok("qfr.pool.import", file="raw_pool.csv")["data"]
    assert again["counts"]["unchanged"] == 5 and again["counts"]["published"] == 0
    assert [o["version_id"] for o in again["entries"]] == [
        o["version_id"] for o in first["entries"]
    ]
    assert [o["entry_id"] for o in again["entries"]] == [o["entry_id"] for o in first["entries"]]
    assert again["pool_counts"]["factor"]["total"] == 5
    assert rig.trace_counts() == {"DSL_VALIDATED": 5, "SEEDS_PUBLISHED": 5}

    changed = list(ROWS)
    changed[0] = (*ROWS[0][:2], "Mean($close, 10) / Mean($close, 60) - 1", *ROWS[0][3:])
    changed[1] = (*ROWS[1][:5], "reversal;short_term", ROWS[1][6])
    (rig.imports / "raw_pool_v2.csv").write_text(csv_file(changed))
    second = rig.ok("qfr.pool.import", file="raw_pool_v2.csv")["data"]
    outcomes = {o["name"]: o for o in second["entries"]}
    assert outcomes["ma_cross_20_60"]["outcome"] == "published"
    assert outcomes["ma_cross_20_60"]["version_no"] == 2
    assert outcomes["ma_cross_20_60"]["family_id"] == first["entries"][0]["family_id"]
    assert outcomes["reversal_5"]["outcome"] == "unchanged"
    assert second["counts"]["published"] == 1 and second["counts"]["unchanged"] == 4
    lineage = rig.registry.client.get(
        f"/v1/artifacts/{outcomes['ma_cross_20_60']['version_id']}/lineage",
        headers={"Authorization": "Bearer test-reader-token"},
    ).json()
    assert [e["parent_version_id"] for e in lineage["edges"]] == [first["entries"][0]["version_id"]]
    retagged = rig.ok("qfr.pool.get", pool="factor", entry_id=outcomes["reversal_5"]["entry_id"])
    assert sorted(retagged["data"]["entry"]["tags"]) == ["reversal", "short_term"]
    assert [e["action"] for e in retagged["data"]["events"]] == ["ADDED", "ANNOTATED"]

    back = rig.ok("qfr.pool.import", file="raw_pool.csv")["data"]
    assert back["counts"]["unchanged"] == 5
    assert back["pool_counts"]["factor"]["total"] == 6
    assert rig.ok("qfr.status")["data"]["registry_counts"]["factor_versions"] == 6
    assert rig.trace_counts() == {"DSL_VALIDATED": 6, "SEEDS_PUBLISHED": 6}


def test_inline_entries_import_like_a_file(rig):
    entry = {
        "name": "inline_momentum",
        "title": "Inline momentum",
        "expression": "Mean($close, 5) / Mean($close, 20) - 1",
        "expected_sign": 1,
        "horizon_days": 5,
    }
    data = rig.ok("qfr.pool.import", entries=[entry])["data"]
    assert data["source"] == {"kind": "inline", "entries": 1}
    assert data["counts"]["published"] == 1


@pytest.mark.parametrize(
    ("arguments", "code"),
    [
        ({"file": "../outside.csv"}, "PATH_OUTSIDE_IMPORTS"),
        ({"file": "/etc/passwd"}, "PATH_OUTSIDE_IMPORTS"),
        ({"file": "missing.csv"}, "FILE_NOT_FOUND"),
        ({"file": "broken.json"}, "IMPORT_FILE_INVALID"),
        ({"file": "empty.yaml"}, "EMPTY_IMPORT"),
        ({}, "ARGUMENTS_INVALID"),
        ({"file": "broken.json", "no_pool": True}, "ARGUMENTS_INVALID"),
    ],
)
def test_refused_imports_change_nothing_and_are_audited_as_failures(rig, arguments, code):
    (rig.imports / "broken.json").write_text("{not json")
    (rig.imports / "empty.yaml").write_text("entries: []\n")
    (rig.imports.parent / "outside.csv").write_text(csv_file(ROWS))
    message = rig.error("qfr.pool.import", **arguments)
    assert code in message
    assert rig.audit.calls[-1].outcome == "failed"
    assert rig.store.latest_setup_states() == {}
    assert rig.trace_counts() == {}
    assert rig.events("qfr-mcp", "pool_import_rejected")[-1]["error_code"] == code
