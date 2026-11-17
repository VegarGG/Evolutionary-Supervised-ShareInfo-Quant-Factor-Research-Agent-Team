from datetime import date, timedelta
from decimal import Decimal, localcontext

import pytest

from qfh.research_metrics import ArithmeticProtocol, calculate_observations

PROTOCOL = ArithmeticProtocol(
    protocol="test", decimal_precision=28, execution_lag=1, label_horizon=1
)


def rows(prices):
    return [
        {
            "symbol": "000001.XSHE",
            "date": (date(2026, 1, 1) + timedelta(days=i)).isoformat(),
            "close": p,
        }
        for i, p in enumerate(prices)
    ]


def test_geometric_series_lags_and_alignment_do_not_count_one_extra_observation():
    data = rows([2**i for i in range(10)])
    result = calculate_observations("a" * 64, data, [1, 5, 10], PROTOCOL)
    facts = result["facts"]
    assert facts["returns.mean"] == {"value": "1", "unit": "return_fraction"}
    assert facts["returns.sample_stdev"]["value"] == "0"
    assert facts["lag.5.latest_return"]["value"] == "31"
    assert facts["lag.5.signal_count"]["value"] == "5"
    assert facts["lag.5.aligned_case_count"]["value"] == "3"
    assert facts["lag.5.first_signal_date"]["value"] == "2026-01-06"
    assert facts["lag.10.signal_count"]["value"] == "0"
    assert result["alignment"]["5"][0] == {
        "signal_date": "2026-01-06",
        "lookback_start_date": "2026-01-01",
        "execution_date": "2026-01-07",
        "label_end_date": "2026-01-08",
        "label_available": True,
    }
    assert result["alignment"]["5"][-1]["execution_date"] is None
    assert result == calculate_observations("a" * 64, list(reversed(data)), [10, 5, 1], PROTOCOL)
    with localcontext() as context:
        context.prec = 6
        assert result == calculate_observations("a" * 64, data, [1, 5, 10], PROTOCOL)


def test_nonconstant_returns_moments_and_units_have_independent_expected_values():
    facts = calculate_observations("a" * 64, rows([100, 80, 120, 90]), [1], PROTOCOL)["facts"]
    assert facts["daily_return.2026-01-02"]["value"] == "-0.2"
    assert facts["returns.median"]["value"] == "-0.2"
    assert Decimal(facts["returns.mean"]["value"]) == Decimal(1) / 60
    assert float(facts["returns.sample_stdev"]["value"]) == pytest.approx(0.4193248541803041)
    assert facts["returns.positive_count"]["value"] == "1"
    assert facts["returns.negative_count"]["value"] == "2"
    small = calculate_observations("a" * 64, rows([100, 90]), [1, 5], PROTOCOL)["facts"]
    assert "returns.sample_stdev" not in small
    assert small["lag.1.aligned_case_count"]["value"] == "0"


@pytest.mark.parametrize("prices", [[1, 0], [1, -1], [1, "NaN"], [1, "Infinity"]])
def test_invalid_prices_are_not_silently_used(prices):
    with pytest.raises(ValueError, match="positive"):
        calculate_observations("a" * 64, rows(prices), [1], PROTOCOL)


def test_duplicate_dates_and_mixed_symbols_are_rejected():
    data = rows([10, 11])
    with pytest.raises(ValueError, match="distinct"):
        calculate_observations("a" * 64, [data[0], data[0]], [1], PROTOCOL)
    data[1]["symbol"] = "600000.XSHG"
    with pytest.raises(ValueError, match="single symbol"):
        calculate_observations("a" * 64, data, [1], PROTOCOL)
