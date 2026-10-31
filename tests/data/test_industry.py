"""Point-in-time industry classification and market adapters (PLAN 6.1 S3, P8.6)."""

from datetime import date
from pathlib import Path

import numpy as np
import polars as pl
import pytest
from qfr_core.data.industry import (
    NO_INDUSTRY,
    IndustryError,
    check_industry,
    clip,
    industry_codes,
    normalize_instrument,
    read_industry_csv,
)
from qfr_core.data.snapshot import (
    DateRange,
    SnapshotData,
    SnapshotError,
    SnapshotSource,
    check_research_snapshot,
    read_snapshot,
    write_snapshot,
)
from qfr_core.eligibility import Eligibility
from qfr_core.metrics.matrix import Market
from qfr_eval.ingest.adapters import (
    AdapterUnavailable,
    CnAdapter,
    MarketAdapter,
    UsEquitiesAdapter,
    VendorFeed,
)
from qfr_eval.ingest.cn import IngestError, attach_industry
from qfr_eval.ingest.config import CnIngestConfig, load_cn
from qfr_eval.ingest.synthetic import INDUSTRY_SCHEME

from tests.ingest.test_cn import CALENDAR, archive_of, ingest, qlib_tree, sha


@pytest.fixture
def cn_release(tmp_path):
    archive = archive_of(qlib_tree(tmp_path / "src"), tmp_path / "qlib_bin.tar.gz")
    manifest = tmp_path / "qlib_bin.manifest.json"
    manifest.write_text(
        '{"files": [{"name": "qlib_bin.tar.gz", "sha256": "' + sha(archive) + '"}]}'
    )
    return archive, manifest


def write_csv(path: Path, rows: list[str]) -> Path:
    path.write_text("instrument,start,end,industry\n" + "\n".join(rows) + "\n")
    return path


def test_instrument_ids_normalize_to_the_qlib_form():
    assert normalize_instrument("SH600000") == "SH600000"
    assert normalize_instrument(" 000001.sz ") == "SZ000001"
    assert normalize_instrument("830799.BJ") == "BJ830799"
    with pytest.raises(IndustryError):
        normalize_instrument("AAPL")


def test_the_csv_reader_closes_open_intervals_and_drops_future_ones(tmp_path):
    path = write_csv(
        tmp_path / "sw.csv",
        [
            "600000.SH,2018-01-01,2019-06-30,Banks",
            "600000.SH,2019-07-01,,Financials",
            "SZ000001,2018-01-01,,Banks",
            "SZ000002,2030-01-01,,Real Estate",
        ],
    )
    table = read_industry_csv(path, "sw2021_l1", date(2020, 12, 31))
    assert table.get_column("scheme").unique().to_list() == ["sw2021_l1"]
    rows = table.select("instrument", "end", "industry").rows()
    assert rows == [
        ("SH600000", date(2019, 6, 30), "Banks"),
        ("SH600000", date(2020, 12, 31), "Financials"),
        ("SZ000001", date(2020, 12, 31), "Banks"),
    ]


def test_overlapping_or_malformed_intervals_are_refused(tmp_path):
    overlap = write_csv(
        tmp_path / "overlap.csv",
        ["SH600000,2018-01-01,2019-06-30,Banks", "SH600000,2019-06-30,,Financials"],
    )
    with pytest.raises(IndustryError, match="overlapping"):
        read_industry_csv(overlap, "sw", date(2020, 1, 1))
    backwards = write_csv(tmp_path / "back.csv", ["SH600000,2019-01-01,2018-01-01,Banks"])
    with pytest.raises(IndustryError, match="ends before"):
        read_industry_csv(backwards, "sw", date(2020, 1, 1))
    with pytest.raises(IndustryError, match="scheme"):
        read_industry_csv(backwards, "Bad Scheme", date(2020, 1, 1))
    missing = tmp_path / "missing.csv"
    missing.write_text("instrument,start,industry\nSH600000,2018-01-01,Banks\n")
    with pytest.raises(IndustryError, match="lacks columns"):
        read_industry_csv(missing, "sw", date(2020, 1, 1))


def test_codes_follow_the_intervals_point_in_time(tmp_path):
    path = write_csv(
        tmp_path / "sw.csv",
        ["SH600000,2019-01-01,2019-01-08,Banks", "SH600000,2019-01-09,,Insurance"],
    )
    table = read_industry_csv(path, "sw", CALENDAR[-1])
    codes = industry_codes(table, CALENDAR, ["SH600000", "SZ000001"])
    assert codes.names == ["Banks", "Insurance"]
    column = codes.codes[:, 0].tolist()
    switch = CALENDAR.index(date(2019, 1, 9))
    assert column[:switch] == [0] * switch
    assert column[switch:] == [1] * (len(CALENDAR) - switch)
    assert (codes.codes[:, 1] == NO_INDUSTRY).all()
    assert codes.coverage(np.ones(codes.codes.shape, dtype=bool)) == pytest.approx(0.5)


def test_snapshots_carry_the_table_and_the_research_copy_is_clipped(small_zones):
    full, research = small_zones.full, small_zones.research
    assert "industry.parquet" in full.manifest.files
    table = full.industry()
    assert table is not None and check_industry(table) == INDUSTRY_SCHEME
    assert table.equals(small_zones.world.industry.sort("instrument", "start"))
    assert full.manifest.row_counts["industry"] == table.height
    cutoff = check_research_snapshot(research)
    clipped = research.industry()
    assert clipped is not None and clipped.get_column("end").max() <= cutoff
    assert clipped.equals(clip(table, cutoff))


def test_the_market_lays_out_each_names_sector(small_zones):
    snapshot = read_snapshot(small_zones.full.path)
    eligibility = Eligibility(
        universe="csi300", listed_days_min=0, exclude_suspended=False, cross_section_min=10
    )
    market = Market.from_panel(
        snapshot.panel(), eligibility, snapshot.calendar(), snapshot.industry()
    )
    assert market.industry is not None and market.industry.scheme == INDUSTRY_SCHEME
    codes = market.industry.codes
    # Every name keeps one sector over its listed life and has none outside it.
    for j in range(len(market.instruments)):
        listed = codes[:, j][codes[:, j] != NO_INDUSTRY]
        assert listed.size and np.unique(listed).size == 1
    assert market.industry.coverage(market.eligible) == 1.0


def test_a_research_snapshot_with_later_industry_rows_fails_bnd06(small_zones, tmp_path):
    world = small_zones.world
    cutoff = small_zones.research.manifest.research_cutoff
    assert cutoff is not None
    data = SnapshotData(
        world.panel.filter(pl.col("date") <= cutoff),
        world.membership.filter(pl.col("start") <= cutoff).with_columns(
            pl.min_horizontal(pl.col("end"), pl.lit(cutoff)).alias("end")
        ),
        world.calendar.filter(pl.col("date") <= cutoff),
        industry=world.industry,  # not clipped
    )
    window = small_zones.research.manifest.research_window
    forged = write_snapshot(
        tmp_path / "research",
        "research",
        data,
        SnapshotSource("synthetic", None, None, {}, {}, {}),
        research_window=DateRange(start=window.start, end=cutoff) if window else None,
    )
    with pytest.raises(SnapshotError, match="industry"):
        check_research_snapshot(forged)


def test_cn_ingest_attaches_the_owner_file_and_checks_coverage(tmp_path, cn_release):
    data, source = ingest(tmp_path, *cn_release)
    good = write_csv(
        tmp_path / "good.csv",
        ["600000.SH,2018-01-01,,Banks", "000001.SZ,2018-01-01,,Banks", "300001.SZ,2018-01-01,,IT"],
    )
    attached, details = attach_industry(data, source, good, "sw2021_l1", 0.9)
    assert attached.industry is not None and attached.industry.height == 3
    assert details.checks["industry_coverage_csi300"] == 1.0
    assert details.checks["industry_scheme"] == "sw2021_l1"
    assert "sw2021_l1" in str(details.conventions["industry"])
    thin = write_csv(tmp_path / "thin.csv", ["300001.SZ,2018-01-01,,IT"])
    with pytest.raises(IngestError, match="classifies no instrument|0.0%"):
        attach_industry(data, source, thin, "sw2021_l1", 0.9)
    with pytest.raises(IngestError, match="missing"):
        attach_industry(data, source, tmp_path / "absent.csv", "sw2021_l1", 0.9)


def test_cn_config_sets_the_industry_file_and_scheme_together():
    base = load_cn(Path("configs")).model_dump()
    with pytest.raises(ValueError, match="together"):
        CnIngestConfig.model_validate(base | {"industry_file": "industry/sw.csv"})
    with pytest.raises(ValueError, match="inside the raw data folder"):
        CnIngestConfig.model_validate(
            base | {"industry_file": "../sw.csv", "industry_scheme": "sw"}
        )


def test_the_cn_adapter_fits_the_interface_and_the_us_adapter_needs_a_vendor(tmp_path):
    cn = CnAdapter(load_cn(Path("configs")))
    assert isinstance(cn, MarketAdapter) and cn.conventions.lot_size == 100
    us = UsEquitiesAdapter()
    assert isinstance(us, MarketAdapter) and us.conventions.lot_size == 1
    with pytest.raises(AdapterUnavailable, match="point-in-time vendor"):
        us.build(tmp_path)

    class Vendor:
        name = "example"

        def calendar(self):
            return []

        def constituents(self, universe):
            return pl.DataFrame()

        def bars(self, instruments):
            return pl.DataFrame()

        def identifiers(self):
            return pl.DataFrame()

        def industry(self, scheme):
            return pl.DataFrame()

    vendor = Vendor()
    assert isinstance(vendor, VendorFeed)
    with pytest.raises(AdapterUnavailable, match="A-share specific"):
        UsEquitiesAdapter(vendor).build(tmp_path)
