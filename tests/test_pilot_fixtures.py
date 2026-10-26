"""Exact source inventory checks only; no original model imports or evaluator execution."""

import json
import os
from pathlib import Path

import pytest

from scripts.extract_pilot_evidence import PACKAGE_DIRS, extract, metadata, verified_source

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures/pilot"
ASSETS = json.loads((FIXTURE / "appendix-a3-spec.json").read_text())


@pytest.fixture
def pilot_root():
    value = os.environ.get("QFR_PILOT_ROOT")
    if not value:
        pytest.skip(
            "Licensed pilot data absent: set QFR_PILOT_ROOT to the parent of original P0/P1 folders"
        )
    path = Path(value)
    assert path.is_dir(), "QFR_PILOT_ROOT is set but does not exist"
    return path


@pytest.mark.pilot
@pytest.mark.parametrize("model", ["P0", "P1"])
@pytest.mark.parametrize("asset_id", sorted(ASSETS))
def test_pilot_input_hash_rows_columns_dates(pilot_root, model, asset_id):
    expected = json.loads((FIXTURE / f"manifests/{asset_id}.json").read_text())
    spec = ASSETS[asset_id]
    package = pilot_root / PACKAGE_DIRS[model]
    assert verified_source(package, spec["path"]) == expected["sha256"]
    actual = metadata(package / spec["path"], spec)
    for key in ["sha256", "bytes", "rows", "columns", "date_column", "date_range", "date_format"]:
        assert actual[key] == expected[key], f"{model}/{asset_id}: {key} differs"
    assert actual["rows"] == spec["rows"]
    assert len(actual["columns"]) == spec["column_count"]
    if spec["date_column"]:
        assert actual["date_range"] == {"start": spec["start"], "end": spec["end"]}
    else:
        assert actual["date_range"] is None


@pytest.mark.pilot
def test_pilot_golden_evidence_exact_source_extraction(pilot_root):
    generated = extract(pilot_root)
    for filename, data in generated.items():
        assert data == json.loads((FIXTURE / filename).read_text()), filename


def test_committed_oracle_coverage_and_precision():
    golden = json.loads((FIXTURE / "golden_evidence.json").read_text())
    assert golden["exposure"] == "previously_seen"
    for model in ["P0", "P1"]:
        assert len(golden["reference_outputs"][model]) == 24
        rows = golden["aggregates"][model]["report_2026"]["selected_rows"]
        assert {row["values"]["model_cycle"] for row in rows} == {"weekly", "monthly", "quarterly"}
        for row in rows:
            cycle = row["values"]["model_cycle"]
            assert row["values"]["evaluated_periods"] == ("39" if cycle == "weekly" else "9")
            assert row["values"]["immature_periods"] == "1"
            assert row["values"]["clean_out_of_sample"] == "False"
    primary = golden["aggregates"]["P1"]["primary_window"]["selected_rows"]
    assert {row["values"]["periods"] for row in primary} == {"143", "33"}
    assert all(isinstance(row["values"]["rank_ic"], str) for row in primary)
    assert {
        row["values"]["confidence_level"]
        for row in golden["aggregates"]["P1"]["paired_intervals"]["selected_rows"]
    } == {"0.95", "0.9958333333333333"}
