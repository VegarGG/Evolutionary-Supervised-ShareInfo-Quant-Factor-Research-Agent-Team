from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from qfh.trial_metrics import model_metrics, offpeak_cost, peak_rate, resource_metrics, role_windows

START = datetime.fromisoformat("2026-11-12T10:00:00+00:00")
PRICING = yaml.safe_load(
    (
        Path(__file__).resolve().parents[1] / "configs/deepseek-flash-pricing-2026-11-12.yaml"
    ).read_text()
)


def at(seconds):
    return (START + timedelta(seconds=seconds)).isoformat()


def call(seconds, uncached=10, cached=90, output=20):
    return {
        "started": at(seconds),
        "finished": at(seconds + 5),
        "state": "settled",
        "usage": {
            "input_uncached": uncached,
            "input_cached": cached,
            "input_cache_write": 0,
            "output": output,
        },
        "charged": 2 * (uncached + cached) + 8 * output,
        "reserved": 5_242_880,
    }


def test_cache_ratio_is_token_weighted_and_tariff_separate_from_budget_debit():
    calls = [call(0, 1, 9), call(20, 900, 100)]
    metrics = model_metrics(calls, PRICING)
    assert metrics["input_cache_hit_ratio"] == pytest.approx(109 / 1010)
    assert metrics["published_price_estimate_cny"] == pytest.approx(0.00106318)
    assert metrics["conservative_settled_cny"] == pytest.approx(0.00234)
    assert metrics["cost_invoice_verified"] is False
    assert model_metrics(calls, PRICING, synthetic=True)["published_price_estimate_cny"] is None


def test_rolling_rates_use_exact_60_second_boundary_and_do_not_invent_unknown_tokens():
    calls = [call(0), call(59), call(60)]
    assert peak_rate(calls, "started") == 2
    assert peak_rate(calls, "started", True) == 240
    unknown = {**call(61), "state": "unknown", "usage": None, "charged": None}
    metrics = model_metrics([*calls, unknown], PRICING)
    assert metrics["peak_rolling_60s_dispatch_rpm"] == 3
    assert metrics["peak_rolling_60s_dispatch_tpm"] == 240
    assert metrics["requests_with_known_usage"] == 3
    assert metrics["unresolved_reserved_cny"] == 5.24288
    assert metrics["published_price_estimate_cny"] is None
    assert metrics["unpriced_requests"] == 1
    assert metrics["all_usage_settled"] is False


def test_tariff_refuses_boundary_crossing_or_unpriced_cache_creation():
    known = call(0)
    assert offpeak_cost(known, PRICING) == Decimal("0.0000918")
    boundary = {
        **known,
        "started": "2026-11-12T13:59:59+08:00",
        "finished": "2026-11-12T14:00:00+08:00",
    }
    assert offpeak_cost(boundary, PRICING) is None
    cache_write = {**known, "usage": {**known["usage"], "input_cache_write": 1}}
    assert offpeak_cost(cache_write, PRICING) is None


def test_role_activity_excludes_supervisor_waits_and_cross_boundary_cpu():
    members = [
        {"role": "supervisor", "session_id": "root"},
        {"role": "researcher", "session_id": "first"},
        {"role": "reviewer", "session_id": "second"},
    ]
    events = [
        {"kind": kind, "at": at(second), "body": {"child_id": child}}
        for child, kind, second in (
            ("first", "worker_started", 20),
            ("first", "worker_finished", 50),
            ("second", "worker_started", 60),
            ("second", "worker_finished", 90),
        )
    ]
    windows = role_windows(members, events, START, START + timedelta(seconds=120))
    samples = []
    for second, cpu in zip(
        range(5, 120, 10), [0, 1, 101, 102, 103, 203, 303, 304, 305, 405, 406, 407], strict=True
    ):
        samples.append(
            {
                "at": at(second),
                "process_cpu_seconds_by_pid": {"123": cpu},
                "process_tree_rss_bytes": 1000 + second,
            }
        )
    supervisor = resource_metrics(samples, windows["supervisor"])
    assert supervisor["activity_wall_seconds"] == 60
    assert supervisor["samples"] == 6
    assert supervisor["cpu_sample_coverage_seconds"] == 30
    assert supervisor["process_tree_peak_sampled_cpu_cores"] == pytest.approx(0.1)
    researcher = resource_metrics(samples, windows["researcher"])
    assert researcher["activity_wall_seconds"] == 30
    assert researcher["samples"] == 3
    assert researcher["process_tree_peak_rss_bytes"] == 1045
    assert researcher["cpu_sample_coverage_seconds"] == 20
    total = resource_metrics(samples, [(START, START + timedelta(seconds=120))])
    assert total["process_tree_peak_sampled_cpu_cores"] == 10


def test_missing_resource_samples_are_not_zero_usage():
    metrics = resource_metrics([], [(START, START + timedelta(seconds=10))])
    assert metrics["samples"] == 0
    assert metrics["process_tree_peak_rss_bytes"] is None
    assert metrics["process_tree_mean_sampled_cpu_cores"] is None
    assert metrics["host_total_ram_bytes"] is None
