"""P1.4 as-of properties and BND-06 against physically built datasets."""

import json
import os
import subprocess
from datetime import date, timedelta
from pathlib import Path

import polars as pl
import pytest
import yaml
from hypothesis import given
from hypothesis import strategies as st
from qfr_core.data_layer.pilot import PilotConfig, financial_availability, import_pilot
from qfr_core.data_layer.snapshots import Snapshot, slice_frame
from qfr_eval.ingest.build import build_zones

ROOT = Path(__file__).resolve().parents[2]


@given(
    st.lists(
        st.tuples(st.integers(0, 30), st.one_of(st.none(), st.integers(0, 40))),
        min_size=1,
        max_size=80,
    ),
    st.integers(0, 40),
)
def test_slice_never_returns_a_future_or_unavailable_row(values, bound):
    start = date(2020, 1, 1)
    frame = pl.DataFrame(
        {
            "date": [start + timedelta(days=a) for a, _ in values],
            "available_date": [
                start + timedelta(days=b) if b is not None else None for _, b in values
            ],
        },
        schema={"date": pl.Date, "available_date": pl.Date},
    )
    upto = start + timedelta(days=bound)
    actual = slice_frame(frame, upto, "date", "available_date")
    assert all(
        row["date"] <= upto and row["available_date"] <= upto
        for row in actual.iter_rows(named=True)
    )
    assert actual.height == sum(a <= bound and b is not None and b <= bound for a, b in values)


def pilot():
    root = os.environ.get("QFR_PILOT_ROOT")
    if not root:
        pytest.skip("Licensed pilot input required: QFR_PILOT_ROOT")
    cfg = PilotConfig.model_validate_json((ROOT / "configs/data/pilot_import.json").read_bytes())
    return import_pilot(Path(root) / "P1_English_Delivery_20261022", ROOT / "fixtures/pilot", cfg)


@pytest.mark.pilot
def test_bnd_06_built_pilot_research_snapshot_and_compose_mounts(tmp_path):
    source = pilot()
    research, full = build_zones(
        tmp_path,
        source.tables,
        cutoff=date(2022, 12, 31),
        as_of=date(2026, 10, 18),
        profile="pilot_industry_v1",
        source="uploaded packages",
        build_code_version="test",
        exposure=source.exposure,
        conventions={},
        principal="test",
        request_id="bnd-06",
    )
    assert research.manifest.snapshot_id != full.manifest.snapshot_id
    loaded = Snapshot.load(research.path)
    assert "evaluation_prices" not in loaded.slice(date.max)
    for name, frame in loaded.slice(date.max).items():
        for column, dtype in frame.schema.items():
            if dtype == pl.Date:
                assert not (frame[column] > date(2022, 12, 31)).any(), (name, column)
    assert loaded.manifest.exposure.history == "previously_seen"
    assert all(t.quality.vintage_status == "unknown" for t in loaded.manifest.tables)
    assert (
        next(
            t for t in loaded.manifest.tables if t.name == "membership"
        ).quality.membership_grade.value
        == "D"
    )
    compose = yaml.safe_load((ROOT / "infra/docker-compose.yml").read_text())
    for service, settings in compose["services"].items():
        if service.startswith("research") or service.startswith("mcp"):
            mounts = settings.get("volumes", [])
            assert all("full" not in mount and "epochs" not in mount for mount in mounts)
            assert all(mount.endswith(":ro") for mount in mounts)


def test_regulatory_availability_does_not_use_report_end_as_knowledge_date():
    cfg = PilotConfig.model_validate_json((ROOT / "configs/data/pilot_import.json").read_bytes())
    assert financial_availability(date(2024, 6, 30), cfg) == date(2024, 9, 1)
    assert financial_availability(date(2024, 12, 31), cfg) == date(2025, 5, 1)
    with pytest.raises(ValueError, match="availability unknown"):
        financial_availability(date(2024, 3, 31), cfg)


def test_qfr_data_build_cli_and_private_ground_truth(tmp_path):
    config = json.loads((ROOT / "configs/data/synthetic.json").read_text())
    config.update(days=100, instruments=40)
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    process = subprocess.run(
        [
            "qfr",
            "data",
            "build",
            "--source",
            "synthetic",
            "--world",
            "null",
            "--config",
            str(path),
            "--output",
            str(tmp_path / "snapshots"),
            "--cutoff",
            "2010-03-01",
            "--principal",
            "test",
            "--request-id",
            "cli",
            "--build-code-version",
            "test",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(process.stdout)
    research = Snapshot.load(Path(result["research"]))
    full = Snapshot.load(Path(result["full"]))
    assert "ground_truth" not in research.slice(date.max)
    assert "ground_truth" in full.slice(date.max)
    assert research.read("panel")["date"].max() <= date(2010, 3, 1)
