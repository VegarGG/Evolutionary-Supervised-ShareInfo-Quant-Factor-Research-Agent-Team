from datetime import date
from pathlib import Path

import polars as pl
import pytest
from qfr_core.contracts.data import DateRange
from qfr_core.data_layer.snapshots import TableInput
from qfr_core.dsl.language import DSLConfig
from qfr_core.metrics.core import stock_metrics
from qfr_core.metrics.pilot import PilotMetricConfig
from qfr_core.workbench import Workbench

from tests.data_layer.test_snapshots import quality, write
from tests.metrics.test_metrics import golden_market, stock_config


def fixture(tmp_path, *, zone="research"):
    panel, _ = golden_market()
    table = TableInput("panel", panel, ("instrument", "date"), quality(), "Synthetic")
    return write(
        tmp_path,
        [table],
        zone=zone,
        cutoff=date(2020, 1, 8) if zone == "research" else None,
        as_of=date(2020, 1, 8),
    )


def test_workbench_w0_uses_shared_definitions_and_labels_nonofficial(tmp_path):
    snapshot = fixture(tmp_path)
    window = DateRange(start=date(2020, 1, 2), end=date(2020, 1, 6))
    bench = Workbench(snapshot.path, window)
    dsl = DSLConfig.model_validate_json(Path("configs/dsl/stock_daily_v1.json").read_bytes())
    config = stock_config().model_copy(update={"fingerprint_dates": 3})
    result = bench.stock(
        "$adv20", dsl, config, fingerprint_seed=20261026, library={"self": "$adv20"}
    )
    direct = stock_metrics(
        bench.tables["panel"],
        bench.tables["panel"].select("instrument", "date", pl.col("adv20").alias("value")),
        config,
        start=window.start,
        end=window.end,
        library={"self": result.scores},
    )
    assert result.metrics.series.equals(direct.series)
    assert result.metrics.summary == direct.summary
    assert result.snapshot_id == snapshot.manifest.snapshot_id
    assert not result.official and result.warning == "in_sample_optimistic"
    assert result.fingerprint["date"].max() <= window.end
    assert result.scores["date"].min() >= window.start
    assert result.scores["date"].max() == window.end
    bench.prefix_check("Mean($close,3)", dsl, cuts=[date(2020, 1, 4)], atol=1e-12, rtol=1e-12)
    assert bench.profile()["panel"]["rows"] == 30


def test_workbench_rejects_full_snapshot_and_future_windows(tmp_path):
    full = fixture(tmp_path, zone="full")
    with pytest.raises(ValueError, match="research-zone"):
        Workbench(full.path, DateRange(start=date(2020, 1, 1), end=date(2020, 1, 6)))
    research = fixture(tmp_path)
    with pytest.raises(ValueError, match="cutoff"):
        Workbench(research.path, DateRange(start=date(2020, 1, 1), end=date(2020, 1, 9)))


def test_workbench_does_not_read_mutated_future_rows(tmp_path):
    snapshot = fixture(tmp_path)
    window = DateRange(start=date(2020, 1, 1), end=date(2020, 1, 6))
    original = Workbench(snapshot.path, window)
    panel, _ = golden_market()
    changed = panel.with_columns(
        pl.when(pl.col("date") > window.end).then(999.0).otherwise(pl.col("close")).alias("close")
    )
    other = write(
        tmp_path,
        [TableInput("panel", changed, ("instrument", "date"), quality(), "Synthetic")],
        zone="research",
        cutoff=date(2020, 1, 8),
        as_of=date(2020, 1, 8),
    )
    modified = Workbench(other.path, window)
    assert original.tables["panel"].equals(modified.tables["panel"])


def test_pilot_workbench_mature_interval_uses_research_prices_only(tmp_path):
    days = [date(2020, 1, 1), date(2020, 1, 2), date(2020, 1, 3)]
    codes = list("abcde") + ["benchmark"]
    prices = pl.DataFrame(
        [
            {
                "date": day,
                "code": code,
                "close": 100.0 * (1 + (5 - i) / 100) if day == days[2] else 100.0,
            }
            for day in days
            for i, code in enumerate(codes)
        ]
    )
    universe = pl.DataFrame({"code": list("abcde"), "industry": list("ABCDE")})
    tables = [
        TableInput("prices_daily", prices, ("date", "code"), quality(), "Synthetic"),
        TableInput("universe", universe, ("code",), quality(), "Synthetic", None, None),
    ]
    snapshot = write(
        tmp_path,
        tables,
        profile="pilot_industry_v1",
        zone="research",
        cutoff=days[-1],
        as_of=days[-1],
    )
    bench = Workbench(snapshot.path, DateRange(start=days[0], end=days[-1]))
    predictions = universe.with_columns(
        pl.Series("factor_score", [5.0, 4.0, 3.0, 2.0, 1.0]),
        pl.Series("original", [5.0, 4.0, 3.0, 2.0, 1.0]),
        pl.Series("rank", [1, 2, 3, 4, 5]),
        pl.Series("selected", [True, False, False, False, False]),
    )
    config = PilotMetricConfig.model_validate_json(
        Path("configs/metrics/pilot_industry_v1.json").read_bytes()
    ).model_copy(update={"industry_count": 5})
    result = bench.pilot_period(
        predictions,
        decision=days[0],
        entry=days[1],
        exit=days[2],
        benchmark_code="benchmark",
        config=config,
    )
    assert not result.official and result.warning == "in_sample_optimistic"
    assert result.metrics.metrics["top_return"].value == pytest.approx(0.05)
    with pytest.raises(ValueError, match="inside W0"):
        bench.pilot_period(
            predictions,
            decision=days[0],
            entry=days[1],
            exit=date(2020, 1, 4),
            benchmark_code="benchmark",
            config=config,
        )
