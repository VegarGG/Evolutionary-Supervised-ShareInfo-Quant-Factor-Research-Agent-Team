import math
import statistics

import pytest

from qfh.case_factor import FactorSpec, inspect_factor, panel_quality, scores


def spec(**changes):
    return FactorSpec.model_validate(
        {
            "lookback": 2,
            "direction": 1,
            "normalization": "none",
            "volatility_window": None,
            "max_absolute_daily_return": None,
            **changes,
        }
    )


def panel(prices=(100, 102, 101, 104, 100, 105, 106)):
    return [
        {"symbol": "600000.XSHG", "date": f"2026-01-{i + 1:02}", "close": p}
        for i, p in enumerate(prices)
    ]


def test_raw_and_volatility_scores_match_independent_calculation():
    rows = panel()
    raw = scores(rows, spec())
    assert raw[2]["score"] == pytest.approx(101 / 100 - 1)
    assert raw[2]["execution_date"] == "2026-01-04"
    normalized = scores(rows, spec(normalization="realized_volatility", volatility_window=5))
    rs = [102 / 100 - 1, 101 / 102 - 1, 104 / 101 - 1, 100 / 104 - 1, 105 / 100 - 1]
    expected = (105 / 104 - 1) / (statistics.stdev(rs) * math.sqrt(2))
    assert normalized[5]["score"] == pytest.approx(expected)
    assert normalized[4]["excluded_reason"] == "insufficient_past_observations"


def test_future_prices_cannot_change_earlier_signals():
    rows = panel()
    changed = [*rows[:5], {**rows[5], "close": 99999}, {**rows[6], "close": 1}]
    for configured in [spec(), spec(normalization="realized_volatility", volatility_window=5)]:
        assert scores(rows, configured)[:5] == scores(changed, configured)[:5]


def test_eligibility_bound_uses_past_fraction_and_zero_volatility_is_missing():
    rows = panel()
    bounded = scores(rows, spec(max_absolute_daily_return=0.02))
    assert bounded[3]["excluded_reason"] == "past_return_bound"
    flat = scores(panel([100] * 7), spec(normalization="realized_volatility", volatility_window=5))
    assert flat[5]["score"] is None and flat[5]["excluded_reason"] == "zero_trailing_volatility"
    assert flat[-1]["execution_date"] is None


def test_inspection_detects_real_changes_and_preserves_baseline_identity():
    rows = panel()
    initial = inspect_factor(rows, spec(), spec())
    assert initial["summary"]["changed_score_or_eligibility_rows_from_initial"] == 0
    child = inspect_factor(rows, spec(lookback=3), spec())
    assert child["summary"]["changed_score_or_eligibility_rows_from_initial"] > 0
    assert initial["summary"]["by_symbol"]["600000.XSHG"]["signals_with_next_observed_close"] == 4


@pytest.mark.parametrize(
    "changes",
    [
        {"normalization": "none", "volatility_window": 5},
        {"normalization": "realized_volatility"},
        {"lookback": 1},
        {"lookback": 2.5},
        {"max_absolute_daily_return": float("nan")},
    ],
)
def test_unexecutable_or_ambiguous_specs_rejected(changes):
    with pytest.raises(ValueError):
        spec(**changes)


@pytest.mark.parametrize("bad", ["duplicate", "negative", "future", "extra"])
def test_panel_quality_rejects_untrustworthy_rows(bad):
    rows = panel()
    if bad == "duplicate":
        rows.append(rows[0])
    if bad == "negative":
        rows[0]["close"] = -1
    if bad == "future":
        rows[0]["date"] = "2027-01-01"
    if bad == "extra":
        rows[0]["volume"] = 1
    with pytest.raises(ValueError):
        panel_quality(rows, ["600000.XSHG"], "2026-01-01", "2026-01-31")
