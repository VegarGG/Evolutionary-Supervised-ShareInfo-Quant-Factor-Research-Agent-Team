"""P1.7 golden calculations: five instruments, eight dates, hand-designed returns."""

import math
import statistics
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl
import pytest
from qfr_core.metrics.core import (
    MetricConfig,
    behavioral_similarity,
    correlation,
    fingerprint,
    forward_labels,
    newey_west_t,
    preprocess,
    stock_metrics,
)
from qfr_core.metrics.pilot import PilotMetricConfig, drift_weights, pilot_metrics, transition

ROOT = Path(__file__).resolve().parents[2]


def stock_config():
    settings = MetricConfig.model_validate_json(
        (ROOT / "configs/metrics/stock_daily_v1.json").read_bytes()
    )
    return settings.model_copy(
        update={
            "min_names": 5,
            "min_listed_days": 1,
            "winsor_low": 0.0,
            "winsor_high": 1.0,
            "horizons": [1, 5],
        }
    )


def golden_market():
    rows, scores = [], []
    for i in range(5):
        close = 100.0
        for t in range(8):
            if t >= 2:
                close *= 1 + (i + 1) / 100 * (1 if t % 2 == 0 else -1)
            day = date(2020, 1, 1) + timedelta(days=t)
            rows.append(
                dict(
                    instrument=str(i),
                    date=day,
                    close=close,
                    adv20=float(100 + i * 20),
                    in_csi300=True,
                    listed_days=t + 1,
                    is_suspended=False,
                )
            )
            scores.append(dict(instrument=str(i), date=day, value=float(i + 1)))
    return pl.DataFrame(rows), pl.DataFrame(scores)


def test_stock_golden_rankic_costs_quantiles_autocorrelation_coverage_library():
    panel, scores = golden_market()
    result = stock_metrics(
        panel,
        scores,
        stock_config(),
        start=date(2020, 1, 1),
        end=date(2020, 1, 8),
        library={"same": scores},
    )
    valid = result.series.filter(pl.col("rank_ic").is_not_null())
    np.testing.assert_allclose(valid["rank_ic"], [1.0, -1.0, 1.0, -1.0, 1.0, -1.0], atol=1e-12)
    np.testing.assert_allclose(
        valid["ls_gross"], [0.04, -0.04, 0.04, -0.04, 0.04, -0.04], atol=1e-12
    )
    net = [0.036, -0.04, 0.04, -0.04, 0.04, -0.04]
    np.testing.assert_allclose(valid["ls_net"], net, atol=1e-12)
    assert result.summary["RankIC_mean"].value == pytest.approx(0, abs=1e-12)
    assert result.summary["RankIC_std"].value == pytest.approx(math.sqrt(6 / 5))
    assert result.summary["RankIC_IR"].value == pytest.approx(0, abs=1e-12)
    assert result.summary["RankIC_t_NW"].value == pytest.approx(0, abs=1e-12)
    assert result.summary["hit_ratio"].value == 0.5
    assert result.summary["top_turnover"].value == pytest.approx(1 / 6)
    assert result.summary["bottom_turnover"].value == pytest.approx(1 / 6)
    assert result.summary["autocorrelation"].value == pytest.approx(1)
    assert result.summary["coverage"].value == 1
    assert result.summary["library_correlation"].value == pytest.approx(1)
    assert result.library_argmax == "same"
    expected = statistics.mean(net) / statistics.stdev(net) * math.sqrt(252)
    assert result.summary["ls_net_sharpe"].value == pytest.approx(expected)
    assert not result.official and set(result.decay) == {1, 5}


def test_label_timing_and_window_boundary():
    panel, _ = golden_market()
    labels = forward_labels(panel, 1, date(2020, 1, 2), date(2020, 1, 6))
    a = labels.filter(pl.col("instrument") == "0")["label"].to_list()
    assert a[0] is None and a[4:] == [None] * 4
    assert a[1:4] == pytest.approx([-0.01, 0.01, -0.01])


def test_preprocessing_rank_ties_newey_west_and_missing_metrics():
    config = stock_config().model_copy(update={"winsor_low": 0.25, "winsor_high": 0.75})
    actual = preprocess(np.asarray([0.0, 1.0, 2.0, 100.0, np.nan]), config)
    clipped = [0.75, 1.0, 2.0, 26.5]
    expected = [(x - statistics.mean(clipped)) / statistics.stdev(clipped) for x in clipped]
    np.testing.assert_allclose(actual[:4], expected)
    assert np.isnan(actual[-1])
    assert correlation([1.0, 1.0, 2.0], [1.0, 2.0, 3.0], ranked=True) == pytest.approx(
        math.sqrt(3) / 2
    )
    assert newey_west_t([1.0, 2.0, 3.0, 4.0, 5.0, 6.0], 1) == pytest.approx(
        3.5 / math.sqrt(179 / 216)
    )
    panel, scores = golden_market()
    unavailable = stock_metrics(
        panel,
        scores.with_columns(pl.lit(None, dtype=pl.Float64).alias("value")),
        stock_config(),
        start=date(2020, 1, 1),
        end=date(2020, 1, 8),
    )
    assert unavailable.summary["RankIC_mean"].value is None
    assert unavailable.summary["RankIC_mean"].missing_reason == "insufficient_data"
    assert unavailable.summary["coverage"].value == 0


def test_behavioral_fingerprint_requires_seed_and_never_samples_future():
    _, scores = golden_market()
    with pytest.raises(ValueError, match="seed"):
        fingerprint(scores, cutoff=date(2020, 1, 5), seed=None, dates=3)
    a = fingerprint(scores, cutoff=date(2020, 1, 5), seed=1234, dates=3)
    b = fingerprint(
        scores.with_columns(-pl.col("value")), cutoff=date(2020, 1, 5), seed=1234, dates=3
    )
    assert a["date"].max() <= date(2020, 1, 5) and a["date"].n_unique() == 3
    assert behavioral_similarity(a, b).value == pytest.approx(1)


def test_library_correlation_excludes_ineligible_names():
    panel, scores = golden_market()
    excluded_panel = panel.with_columns(
        (pl.col("instrument") + "_excluded").alias("instrument"),
        pl.lit(False).alias("in_csi300"),
    )
    excluded_scores = scores.with_columns(
        (pl.col("instrument") + "_excluded").alias("instrument"),
        (pl.col("value") * 100).alias("value"),
    )
    combined = pl.concat([scores, excluded_scores])
    library = pl.concat([scores, excluded_scores.with_columns(-pl.col("value"))])
    result = stock_metrics(
        pl.concat([panel, excluded_panel]),
        combined,
        stock_config(),
        start=date(2020, 1, 1),
        end=date(2020, 1, 8),
        library={"eligible_twin": library},
    )
    assert result.summary["library_correlation"].value == pytest.approx(1)
    assert result.library_argmax == "eligible_twin"


def test_pilot_golden_recalls_classes_direction_returns_costs_and_drift():
    config = PilotMetricConfig.model_validate_json(
        (ROOT / "configs/metrics/pilot_industry_v1.json").read_bytes()
    )
    config = config.model_copy(update={"industry_count": 5})
    predictions = pl.DataFrame(
        {
            "code": list("abcde"),
            "industry": list("ABCDE"),
            "factor_score": [5.0, 4.0, 3.0, 2.0, 1.0],
            "original": [5.0, 4.0, 3.0, 2.0, 1.0],
            "rank": [1, 2, 3, 4, 5],
            "selected": [True, False, False, False, False],
        }
    )
    realized = pl.DataFrame(
        {"code": list("abcde"), "industry": list("ABCDE"), "return": [0.05, 0.04, 0.03, 0.02, 0.01]}
    )
    result = pilot_metrics(predictions, realized, benchmark_return=0.03, config=config)
    for name in [
        "top_precision",
        "bottom_precision",
        "top_recall",
        "bottom_recall",
        "extreme_macro_recall",
        "three_class_accuracy",
        "three_class_balanced_accuracy",
        "directional_accuracy_vs_csi500",
        "rank_ic",
        "action_rank_ic",
        "top_traded_notional",
        "top_one_way_turnover",
    ]:
        assert result.metrics[name].value == pytest.approx(1), name
    assert result.metrics["top_net_return_10bps"].value == pytest.approx(0.99895 - 0.95)
    assert result.metrics["top_excess_equal31_net_10bps"].value == pytest.approx(0.01895)
    assert result.next_weights == {"top": {"a": 1.0}, "bottom": {"e": 1.0}}
    drifted = drift_weights({"a": 0.5, "b": 0.5}, {"a": 0.2, "b": 0.0})
    assert drifted == pytest.approx({"a": 6 / 11, "b": 5 / 11})
    movement = transition({"a": 0.5, "b": 0.5}, drifted, 1e-9)
    assert movement["traded_notional"] == pytest.approx(1 / 11)
    assert transition({"c": 1.0}, {"a": 1.0}, 1e-9)["traded_notional"] == 2
