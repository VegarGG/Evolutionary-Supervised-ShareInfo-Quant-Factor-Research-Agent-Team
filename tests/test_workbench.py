"""The research workbench facade (PLAN P1.11): W0 only, research snapshot only, and the
same numbers as the evaluator's code on the full snapshot restricted to W0."""

import json
from pathlib import Path

import numpy as np
import pytest
from qfr_core.backtest import BacktestSettings, run_backtest
from qfr_core.composite import CompositePart, composite
from qfr_core.data.snapshot import SnapshotError
from qfr_core.dsl import compile_expression
from qfr_core.metrics.factor import evaluate_factor
from qfr_core.metrics.fingerprint import behavioral_similarity, fingerprint
from qfr_core.metrics.matrix import Market
from qfr_core.operators import evaluate
from qfr_core.workbench import ComponentInput, Workbench

from tests.dsl_strategies import LIMITS
from tests.synthetic_fixtures import ELIGIBILITY, PROTOCOL, SETTINGS

CARD = json.loads(Path("configs/public_cards.json").read_text())
A1 = "-Pct($close,5)"
A2 = "Clip(Sign($ret)*($volume/Mean($volume,20)-1),-3,3)"


@pytest.fixture(scope="module")
def bench(small_zones):
    return Workbench(small_zones.research.path, Path("configs/public_cards.json"))


@pytest.fixture(scope="module")
def evaluator(small_zones):
    full = small_zones.full
    panel = full.panel()
    return panel, Market.from_panel(panel, ELIGIBILITY, full.calendar())


def same_numbers(actual, expected):
    """Equal up to float summation order: the research market has fewer columns."""
    a, e = actual.model_dump(mode="json"), expected.model_dump(mode="json")
    assert a.keys() == e.keys()
    for key in a:
        if isinstance(e[key], (int, float, list)) or (
            isinstance(e[key], dict)
            and all(isinstance(v, (int, float, type(None))) for v in e[key].values())
        ):
            assert a[key] == pytest.approx(e[key], rel=1e-12, abs=1e-15), key
        else:
            assert a[key] == e[key], key


def evaluator_values(evaluator, expression):
    panel, market = evaluator
    return market.matrix(evaluate(panel, compile_expression(expression, LIMITS).tree, ELIGIBILITY))


def test_the_public_card_carries_what_the_workbench_needs():
    protocol = CARD["protocol"]
    assert protocol["fingerprint"] == PROTOCOL["fingerprint"]
    assert "epoch_ref" not in protocol and "acceptance" not in protocol["gates"]


def test_factor_metrics_equal_the_evaluator_on_w0(bench, evaluator, small_zones):
    report = bench.factor(A1, 1)
    assert report.visibility == "research_non_official" and report.window == "W0"
    assert report.snapshot_id == small_zones.research.snapshot_id
    _, market = evaluator
    window = small_zones.research.manifest.research_window
    official = evaluate_factor(
        evaluator_values(evaluator, A1), market, window.start, window.end, 1, SETTINGS
    )
    same_numbers(report.metrics, official.metrics)
    assert report.metrics.rankic_mean is not None and report.metrics.rankic_mean > 0.02
    settings = BacktestSettings.from_protocol(PROTOCOL)
    reference = run_backtest(
        evaluator_values(evaluator, A1), market, window.start, window.end, settings
    )
    same_numbers(report.reference_strategy, reference.metrics)


def test_composite_metrics_equal_the_evaluator_on_w0(bench, evaluator, small_zones):
    components = [ComponentInput(A1, 1, 2.0), ComponentInput(A2, 1, 1.0)]
    report = bench.composite(components, top_k=20, dropout=2)
    _, market = evaluator
    window = small_zones.research.manifest.research_window
    parts = [
        CompositePart("c1", 1, 2.0, evaluator_values(evaluator, A1)),
        CompositePart("c2", 1, 1.0, evaluator_values(evaluator, A2)),
    ]
    scores = composite(parts, market, SETTINGS)
    official = evaluate_factor(scores, market, window.start, window.end, 1, SETTINGS)
    same_numbers(report.metrics, official.metrics)
    assert [row.component for row in report.contributions] == ["c1", "c2"]
    settings = BacktestSettings.from_protocol(PROTOCOL, 20, 2)
    assert (
        report.reference_strategy
        == run_backtest(scores, market, window.start, window.end, settings).metrics
    )


def test_fingerprints_match_across_zones(bench, evaluator):
    _, market = evaluator
    dates = bench.fingerprint_dates()
    assert len(dates) == 40 and max(dates) <= bench.window.end
    research = bench.fingerprint(A1)
    official = fingerprint(evaluator_values(evaluator, A1), market, dates)
    assert behavioral_similarity(research, official) == pytest.approx(1.0)
    np.testing.assert_allclose(
        research.aligned(official.instruments), official.ranks, equal_nan=True
    )


def test_the_workbench_refuses_the_full_snapshot(small_zones):
    with pytest.raises(SnapshotError, match="BND-06"):
        Workbench(small_zones.full.path, CARD)


def test_invalid_expressions_are_rejected_with_reason_codes(bench):
    from qfr_core.dsl import DslError

    with pytest.raises(DslError) as error:
        bench.factor("Ref($close,-1)", 1)
    assert error.value.code.value == "PARSE_ERROR"
