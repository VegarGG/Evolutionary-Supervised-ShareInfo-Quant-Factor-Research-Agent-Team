"""P1.1 data identity and dense-calendar acceptance."""

import json
from datetime import date

import polars as pl
import pytest
from qfr_core.contracts.data import ExposureAndQuality, QualityLabels
from qfr_core.data_layer.snapshots import (
    Snapshot,
    TableInput,
    dense_panel,
    file_hash,
    logical_hash,
    write_snapshot,
)


def quality():
    return QualityLabels(
        timing_grade="A",
        timing_basis="Synthetic observation dates",
        vintage_status="verified",
        vintage_notes="Generated once",
        membership_grade="A",
        membership_status="point_in_time",
        membership_notes="Synthetic",
    )


def exposure():
    return ExposureAndQuality(
        history="previously_seen",
        inspected_periods=[],
        training_tuning_history="Software test fixture",
        provider_knowledge_exposure="unknown",
        quality=quality(),
        licence_constraints=["Synthetic"],
        unknowns=[],
    )


def input_table():
    return TableInput(
        "panel",
        pl.DataFrame(
            {
                "date": [date(2020, 1, 2), date(2021, 1, 4)],
                "instrument": ["中文代码", "中文代码"],
                "close": [10.0, None],
            }
        ),
        ("instrument", "date"),
        quality(),
        "Synthetic",
    )


def write(root, tables=None, **overrides):
    options = dict(
        profile="stock_daily_v1",
        zone="full",
        cutoff=None,
        as_of=date(2021, 1, 4),
        source="synthetic",
        build_code_version="fixture/1",
        exposure=exposure(),
        conventions={"missing": "null"},
        principal="test",
        request_id="request-1",
    )
    return write_snapshot(root, tables or [input_table()], **(options | overrides))


def test_snapshot_roundtrip_content_address_and_no_rewrite(tmp_path):
    snapshot = write(tmp_path)
    before = (snapshot.path / "manifest.json").stat().st_mtime_ns
    assert (
        Snapshot.load(snapshot.path)
        .read("panel")
        .equals(input_table().frame.select(sorted(input_table().frame.columns)))
    )
    assert len(snapshot.manifest.tables[0].files) == 2
    assert write(tmp_path).manifest.snapshot_id == snapshot.manifest.snapshot_id
    assert (snapshot.path / "manifest.json").stat().st_mtime_ns == before
    assert (
        write(tmp_path, build_code_version="fixture/2").manifest.snapshot_id
        != snapshot.manifest.snapshot_id
    )
    events = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]
    assert len(events) == 3 and all(e["principal"] == "test" and e["request_id"] for e in events)


def test_physical_and_logical_hashes_have_distinct_meanings(tmp_path):
    frame = input_table().frame
    assert logical_hash(frame, ["instrument", "date"]) == logical_hash(
        frame.reverse(), ["instrument", "date"]
    )
    frame.write_parquet(tmp_path / "a", compression="uncompressed")
    frame.write_parquet(tmp_path / "b", compression="zstd")
    assert file_hash(tmp_path / "a") != file_hash(tmp_path / "b")
    assert logical_hash(pl.read_parquet(tmp_path / "a"), ["instrument", "date"]) == logical_hash(
        pl.read_parquet(tmp_path / "b"), ["instrument", "date"]
    )
    assert logical_hash(frame, ["instrument", "date"]) != logical_hash(
        frame.with_columns(pl.lit(0.0).alias("close")), ["instrument", "date"]
    )


def test_snapshot_rejects_tamper_and_future_research_data(tmp_path):
    snapshot = write(tmp_path)
    path = snapshot.path / snapshot.manifest.tables[0].files[0].path
    path.write_bytes(path.read_bytes() + b"tamper")
    with pytest.raises(ValueError, match="physical hash"):
        Snapshot.load(snapshot.path)
    with pytest.raises(ValueError, match="cutoff"):
        write(tmp_path, zone="research", cutoff=date(2020, 1, 2), as_of=date(2020, 1, 2))


def test_duplicate_keys_and_nonfinite_values_fail():
    frame = input_table().frame
    with pytest.raises(ValueError, match="duplicate"):
        logical_hash(pl.concat([frame, frame]), ["date", "instrument"])
    with pytest.raises(ValueError, match="infinite"):
        logical_hash(
            frame.with_columns(pl.lit(float("inf")).alias("close")), ["date", "instrument"]
        )
    null = frame.with_columns(pl.lit(None, dtype=pl.Float64).alias("close"))
    nan = frame.with_columns(pl.lit(float("nan")).alias("close"))
    assert logical_hash(null, ["date", "instrument"]) == logical_hash(nan, ["date", "instrument"])


def test_dense_calendar_preserves_missing_prices_and_instrument_lifetimes():
    dates = [date(2020, 1, day) for day in [2, 3, 6]]
    data = pl.DataFrame(
        {
            "date": [dates[0], dates[2], dates[1]],
            "instrument": ["A", "A", "B"],
            "close": [10.0, 12.0, 5.0],
            "open": [10.0, 12.0, 5.0],
            "high": [11.0, 13.0, 6.0],
            "low": [9.0, 11.0, 4.0],
            "volume": [1.0, 2.0, 0.0],
            "amount": [10.0, 24.0, 0.0],
            "factor": [2.0, 2.0, 1.0],
        }
    )
    dense = dense_panel(data, pl.DataFrame({"date": dates}))
    a = dense.filter(pl.col("instrument") == "A")
    assert a["close"].to_list() == [10.0, None, 12.0]
    assert a["close_raw"].to_list() == [5.0, None, 6.0]
    assert a["ret_1d"].null_count() == 3  # No return across an unobserved price.
    assert a["listed_days"].to_list() == [1, 2, 3]
    assert a["is_suspended"].to_list() == [False, True, False]
    assert dense.filter(pl.col("instrument") == "B").height == 1
