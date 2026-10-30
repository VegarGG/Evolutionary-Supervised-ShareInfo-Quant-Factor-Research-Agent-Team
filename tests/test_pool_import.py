"""Raw factor pool parsing, validation and seed manifests (PLAN Section 13.6)."""

import csv
import io
import json
import re
from uuid import UUID

import pytest
from qfr_core.contracts import FactorManifest, ReasonCode, StrategyManifest
from qfr_core.ids import uuid7
from qfr_core.pool_import import (
    NO_DEFAULTS_NOTICE,
    ImportFileError,
    InvalidEntry,
    SeedIds,
    ValidEntry,
    entry_digest,
    factor_seed_manifest,
    parse_import_file,
    qfr_core_version,
    strategy_seed_manifest,
    validate_entries,
)

from tests.registry_rig import LIMITS

FACTOR = {
    "name": "ma_cross_20_60",
    "title": "20/60 moving-average crossover",
    "expression": "Mean($close, 20) / Mean($close, 60) - 1",
    "expected_sign": 1,
    "horizon_days": 5,
    "tags": ["momentum", "trend"],
    "notes": "from the owner's 2024 notebook",
}
REVERSAL = {
    "name": "reversal_5",
    "title": "Five-day reversal",
    "expression": "-Delta($close, 5) / Ref($close, 5)",
    "expected_sign": 1,
    "horizon_days": 5,
}
STRATEGY = {
    "name": "trend_and_reversal",
    "title": "Trend plus reversal",
    "expected_sign": 1,
    "horizon_days": 5,
    "strategy": {
        "components": [
            {"name": "ma_cross_20_60", "sign": 1, "weight": 0.6},
            {"name": "reversal_5", "sign": 1, "weight": 0.4},
        ],
        "combination": "zscore_weighted_sum",
        "portfolio": {
            "type": "topk_dropout",
            "top_k": 50,
            "dropout": 5,
            "rebalance": "daily",
            "long_only": True,
        },
    },
}


def ids() -> SeedIds:
    return SeedIds(candidate_id=uuid7(), hypothesis_id=uuid7(), validation_id=uuid7())


def test_the_no_defaults_notice_is_the_plan_text():
    assert NO_DEFAULTS_NOTICE == (
        "No default factors. No default strategies. Research will start from exploration "
        "only. Library-correlation and novelty checks are vacuous until the pool has entries."
    )


def test_json_yaml_and_csv_carry_the_same_entries():
    as_json = parse_import_file(
        "pool.json", json.dumps({"schema_version": "pool_import/1", "entries": [FACTOR]}).encode()
    )
    as_yaml = parse_import_file(
        "pool.yaml",
        (
            b"entries:\n"
            b"  - name: ma_cross_20_60\n"
            b"    title: 20/60 moving-average crossover\n"
            b'    expression: "Mean($close, 20) / Mean($close, 60) - 1"\n'
            b"    expected_sign: 1\n"
            b"    horizon_days: 5\n"
            b"    tags: [momentum, trend]\n"
            b"    notes: from the owner's 2024 notebook\n"
        ),
    )
    as_csv = parse_import_file(
        "pool.csv",
        (
            "name,title,expression,expected_sign,horizon_days,tags,notes\n"
            "ma_cross_20_60,20/60 moving-average crossover,"
            '"Mean($close, 20) / Mean($close, 60) - 1",1,5,momentum;trend,'
            "from the owner's 2024 notebook\n"
        ).encode("utf-8-sig"),
    )
    assert as_json == as_yaml == as_csv == [FACTOR]


def test_csv_strategy_cells_are_json():
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["name", "title", "expected_sign", "horizon_days", "strategy"])
    writer.writerow(["s1", "Strategy", 1, 5, json.dumps(STRATEGY["strategy"])])
    rows = parse_import_file("pool.csv", buffer.getvalue().encode())
    assert rows[0]["strategy"] == STRATEGY["strategy"]


@pytest.mark.parametrize(
    ("name", "data", "message"),
    [
        ("pool.txt", b"entries: []", "unsupported file type"),
        ("pool.json", b"[1, 2]", "mapping"),
        ("pool.json", b"{not json", "not valid JSON"),
        ("pool.yaml", b"entries: {a: 1}", "entries must be a list"),
        ("pool.yaml", b"schema_version: pool_import/2\nentries: []", "pool_import/1"),
        ("pool.yaml", b"entries: []\nextra: 1", "unknown top-level keys"),
        ("pool.csv", b"name,title,colour\n", "unknown ['colour']"),
        ("pool.csv", b"name,title\n", "missing ['expected_sign', 'horizon_days']"),
        ("pool.csv", b"name,title,expected_sign,horizon_days\na,b,1,5,extra\n", "more cells"),
        ("pool.json", b"\xff\xfe", "not UTF-8"),
    ],
)
def test_unreadable_files_are_refused_as_a_whole(name, data, message):
    with pytest.raises(ImportFileError, match=re.escape(message)):
        parse_import_file(name, data)


def test_each_entry_is_validated_like_an_agent_draft():
    raw = [
        FACTOR,
        REVERSAL,
        STRATEGY,
        FACTOR | {"title": "duplicate"},
        {**REVERSAL, "name": "bad_field", "expression": "Mean($foo, 5)"},
        {**REVERSAL, "name": "bad_parse", "expression": "Ref($close, -1)"},
        {**REVERSAL, "name": "bad_window", "expression": "Mean($close, 5000)"},
        {**REVERSAL, "name": "Not A Slug"},
        {"name": "neither", "title": "t", "expected_sign": 1, "horizon_days": 5},
        STRATEGY
        | {
            "name": "dangling",
            "strategy": STRATEGY["strategy"]
            | {"components": [{"name": "bad_field", "sign": 1, "weight": 1.0}]},
        },
        "not a mapping",
    ]
    results = validate_entries(raw, LIMITS)
    assert [type(r).__name__ for r in results] == ["ValidEntry"] * 3 + ["InvalidEntry"] * 8
    invalid = {r.index: r for r in results if isinstance(r, InvalidEntry)}
    codes = {i: [e.reason_code for e in r.errors] for i, r in invalid.items()}
    assert (
        codes[3] == [ReasonCode.SCHEMA_INVALID] and "duplicate name" in invalid[3].errors[0].message
    )
    assert codes[4] == [ReasonCode.FORBIDDEN_CONSTRUCT]
    assert codes[5] == [ReasonCode.PARSE_ERROR]
    assert codes[6] == [ReasonCode.FORBIDDEN_CONSTRUCT]
    assert set(codes[7]) == {ReasonCode.SCHEMA_INVALID} and invalid[7].errors[0].field == "name"
    assert codes[8] == [ReasonCode.SCHEMA_INVALID]
    assert codes[9] == [ReasonCode.COMPONENT_INVALID]
    assert invalid[9].kind == "strategy" and invalid[4].kind == "factor"
    assert invalid[10].name is None and invalid[10].kind is None
    valid = [r for r in results if isinstance(r, ValidEntry)]
    assert valid[0].analysis is not None and valid[2].analysis is None


def test_the_digest_ignores_tags_but_not_the_definition():
    entry = validate_entries([FACTOR], LIMITS)[0]
    retagged = validate_entries([FACTOR | {"tags": ["other"]}], LIMITS)[0]
    changed = validate_entries([FACTOR | {"expression": "Mean($close, 10) - 1"}], LIMITS)[0]
    assert isinstance(entry, ValidEntry) and isinstance(retagged, ValidEntry)
    assert isinstance(changed, ValidEntry)
    assert entry_digest(entry.entry) == entry_digest(retagged.entry)
    assert entry_digest(entry.entry) != entry_digest(changed.entry)


def test_strategy_digest_depends_on_component_versions():
    results = validate_entries([FACTOR, REVERSAL, STRATEGY], LIMITS)
    strategy = results[2]
    assert isinstance(strategy, ValidEntry)
    first = {"ma_cross_20_60": uuid7(), "reversal_5": uuid7()}
    second = first | {"reversal_5": uuid7()}
    assert entry_digest(strategy.entry, first) != entry_digest(strategy.entry, second)


def test_factor_seed_manifest_is_a_human_seed_setup_import():
    result = validate_entries([FACTOR], LIMITS)[0]
    assert isinstance(result, ValidEntry) and result.analysis is not None
    seed_ids = ids()
    manifest = factor_seed_manifest(
        result.entry, result.analysis, seed_ids, None, None, qfr_core_version()
    )
    FactorManifest.model_validate(manifest.model_dump(mode="json"))
    provenance = manifest.provenance
    assert provenance.operator == "human_seed" and provenance.job_id is None
    assert provenance.program_id is None and provenance.research_snapshot_id is None
    assert provenance.parent_version_ids == [] and provenance.trace_ref == seed_ids.candidate_id
    assert manifest.rationale.mechanism == FACTOR["notes"]
    assert manifest.rationale.hypothesis_id == seed_ids.hypothesis_id
    assert manifest.review.verdict_id == seed_ids.validation_id and manifest.review.rounds == 0
    assert manifest.declared.fields_used == ["close"]
    assert manifest.declared.max_lookback_days == result.analysis.max_lookback_days
    assert manifest.rationale.change_summary is None
    family, previous = uuid7(), uuid7()
    follow_up = factor_seed_manifest(
        result.entry, result.analysis, ids(), family, previous, qfr_core_version()
    )
    assert follow_up.family_id == family and follow_up.provenance.parent_version_ids == [previous]
    assert follow_up.rationale.change_summary


def test_strategy_seed_manifest_references_its_component_versions():
    results = validate_entries([FACTOR, REVERSAL, STRATEGY], LIMITS)
    strategy = results[2]
    assert isinstance(strategy, ValidEntry)
    components = {"ma_cross_20_60": uuid7(), "reversal_5": uuid7()}
    manifest = strategy_seed_manifest(
        strategy.entry, components, ids(), None, None, qfr_core_version()
    )
    StrategyManifest.model_validate(manifest.model_dump(mode="json"))
    parts = manifest.implementation.components
    assert [p.version_id for p in parts] == list(components.values())
    assert manifest.provenance.parent_version_ids == list(components.values())
    assert manifest.provenance.operator == "human_seed"
    assert "weight 0.6" in manifest.rationale.composition_rationale
    assert isinstance(manifest.provenance.trace_ref, UUID)
