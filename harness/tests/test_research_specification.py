import json
from datetime import date, timedelta
from decimal import Decimal, localcontext
from pathlib import Path

import pytest
import yaml

from qfh.research_specification import (
    ContrastSpec,
    StatisticalProtocol,
    assess_specification,
    infer_contrast,
    interval_outcome,
)


@pytest.fixture
def protocol():
    return StatisticalProtocol.model_validate(
        yaml.safe_load(
            (Path(__file__).resolve().parents[1] / "configs/research-statistics.yaml").read_text()
        )
    )


def specification(**changes):
    return ContrastSpec.model_validate(
        {
            "family": "close_return_contrast",
            "lookback": 1,
            "comparison": "lt",
            "threshold": "0",
            "tie_policy": "control",
            "label_horizon": 1,
            "expected_direction": "higher",
            "effect_margin": "0.001",
            **changes,
        }
    )


def rows(values):
    return [
        {
            "symbol": "TEST",
            "date": (date(2020, 1, 1) + timedelta(days=i)).isoformat(),
            "close": str(v),
        }
        for i, v in enumerate(values)
    ]


def test_one_step_labels_touch_but_do_not_overlap_and_ties_are_explicit(protocol, monkeypatch):
    monkeypatch.setattr(
        "qfh.research_specification.random.Random",
        lambda *_: pytest.fail("undersized data must not run inference"),
    )
    result = assess_specification("a" * 64, rows([100] * 10), specification(), protocol)
    assert result["support"] == {
        "signal_candidates": 9,
        "aligned_cases": 7,
        "dropped_tail_cases": 2,
        "signal_bucket": 0,
        "control_bucket": 7,
        "ties_assigned_to_control": 7,
    }
    assert result["label_geometry"] == {
        "adjacent_pairs": 6,
        "positive_overlap_pairs": 0,
        "touching_endpoint_pairs": 6,
        "serial_independence": "not_established",
    }
    assert result["inference"]["outcome"] == "insufficient_data"
    assert result["inference"]["interval"] is None
    assert result["inference"]["bootstrap_replicates_run"] == 0


def test_longer_horizon_overlap_and_tail_counts(protocol):
    result = assess_specification(
        "a" * 64, rows([100] * 10), specification(label_horizon=2), protocol
    )
    assert result["support"]["aligned_cases"] == 6
    assert result["support"]["dropped_tail_cases"] == 3
    assert result["label_geometry"]["positive_overlap_pairs"] == 5
    assert result["label_geometry"]["touching_endpoint_pairs"] == 0


@pytest.mark.parametrize(
    "lower,upper,margin,expected",
    [
        ("0.02", "0.04", "0.01", "interval_above_margin"),
        ("-0.02", "0.00", "0.01", "interval_below_margin"),
        ("-0.02", "0.04", "0.01", "inconclusive"),
        ("0.01", "0.04", "0.01", "inconclusive"),
        ("-0.02", "0.01", "0.01", "inconclusive"),
    ],
)
def test_interval_outcomes_include_inconclusive_boundaries(lower, upper, margin, expected):
    assert interval_outcome(Decimal(lower), Decimal(upper), Decimal(margin)) == expected


def test_executable_joint_block_protocol_reproduces_known_contrast(protocol):
    pairs = [(i % 2 == 0, Decimal("0.02") if i % 2 == 0 else Decimal(0)) for i in range(80)]
    with localcontext() as ctx:
        ctx.prec = protocol.decimal_precision
        first = infer_contrast(pairs, specification(effect_margin="0.01"), protocol, 5)
        second = infer_contrast(pairs, specification(effect_margin="0.01"), protocol, 5)
    assert first == second
    assert first["outcome"] == "interval_above_margin"
    assert Decimal(first["effect"]) == Decimal("0.02")
    assert Decimal(first["interval"]["lower"]) == Decimal("0.02")
    assert Decimal(first["interval"]["upper"]) == Decimal("0.02")
    assert first["interval"]["unit"] == "return_fraction"
    assert first["bootstrap_replicates_run"] == protocol.bootstrap_replicates
    assert (
        infer_contrast(pairs, specification(expected_direction="lower"), protocol, 5)["outcome"]
        == "interval_below_margin"
    )


def test_empty_bootstrap_bucket_is_unavailable_not_silently_resampled(protocol, monkeypatch):
    class Fixed:
        def __init__(self, *_):
            pass

        def randrange(self, *_):
            return 0

    monkeypatch.setattr("qfh.research_specification.random.Random", Fixed)
    p = StatisticalProtocol.model_validate({**protocol.model_dump(), "minimum_blocks": 2})
    pairs = [(i < 20, Decimal(i) / 1000) for i in range(40)]
    result = infer_contrast(pairs, specification(), p, 20)
    assert result["outcome"] == "resampling_unavailable"
    assert result["interval"] is None and result["bootstrap_replicates_run"] == 1


@pytest.mark.parametrize(
    "change",
    [
        {"threshold": "theta"},
        {"lookback": True},
        {"lookback": "1"},
        {"label_horizon": None},
        {"threshold": "NaN"},
        {"effect_margin": "Infinity"},
        {"method": "Welch or permutation"},
        {"tie_policy": "unspecified"},
        {"expected_direction": "either"},
    ],
)
def test_unresolved_or_nonfinite_specifications_are_rejected(change):
    with pytest.raises(ValueError):
        specification(**change)


def test_missing_parameter_policy_overrun_and_duplicate_dates_fail(protocol):
    body = specification().model_dump(mode="json")
    del body["effect_margin"]
    with pytest.raises(ValueError):
        ContrastSpec.model_validate_json(json.dumps(body))
    for spec in [
        specification(lookback=100),
        specification(label_horizon=100),
        specification(threshold="2"),
    ]:
        with pytest.raises(ValueError, match="policy"):
            assess_specification("a" * 64, rows([100] * 10), spec, protocol)
    with pytest.raises(ValueError, match="distinct"):
        assess_specification("a" * 64, rows([100]) * 10, specification(), protocol)


def test_normalized_identity_and_formula_have_no_unresolved_choices(protocol):
    data = rows([100, 90, 99, 90, 99, 90, 99, 90, 99, 90])
    first = assess_specification("a" * 64, data, specification(threshold="0.00"), protocol)
    second = assess_specification(
        "a" * 64, list(reversed(data)), specification(threshold="0"), protocol
    )
    assert first == second
    assert "theta" not in first["canonical_formula"] and "EITHER" not in first["canonical_formula"]
    assert "2000" in first["canonical_formula"] and "20261112" in first["canonical_formula"]
    assert first["inference"]["outcome"] == "insufficient_data"


def test_global_decimal_context_does_not_change_specification_identity(protocol):
    data = rows([100, 90, 99, 90, 99, 90, 99, 90, 99, 90])
    spec = specification(threshold="0.123456789012")
    baseline = assess_specification("a" * 64, data, spec, protocol)
    with localcontext() as ctx:
        ctx.prec = 6
        assert assess_specification("a" * 64, data, spec, protocol) == baseline
        with pytest.raises(ValueError, match="policy"):
            assess_specification(
                "a" * 64, data, specification(threshold="1.000000000001"), protocol
            )
