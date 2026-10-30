"""REL policy mechanics using synthetic private evidence, not pilot acceptance."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError
from qfr_core.configuration import load_yaml
from qfr_core.contracts.reports import (
    MetricValue,
    PublicReleasePolicyCard,
    ReleasedReport,
    ReleasedScalar,
    WithheldRelease,
)
from qfr_eval.protocols.models import FrozenProtocol
from qfr_eval.records import EvaluationRequest, Measurement, OfficialRecord
from qfr_eval.release.models import PilotReleasePolicy, StockReleasePolicy
from qfr_eval.release.pilot import project_pilot, rank_bucket
from qfr_eval.release.policy import batch_at_or_after, coarsen, eligible_at, public_card, t_bucket
from qfr_eval.release.stock import project_advancement, project_w1, project_w2

ROOT = Path(__file__).resolve().parents[2]
PRIVATE = ROOT / "packages/qfr_eval/src/qfr_eval/private_contracts"


def policy(profile="pilot"):
    model = PilotReleasePolicy if profile == "pilot" else StockReleasePolicy
    return model.model_validate_json(
        (ROOT / f"configs/evaluation/release_{profile}_v1.json").read_bytes()
    )


def metric(value, reason="insufficient_data"):
    return MetricValue(value=value, missing_reason=reason if value is None else None)


def evidence(score=0.5, *, intent="evaluated", period_count=100, diagnostics=None):
    protocol = load_yaml(
        ROOT / "configs/evaluation/pilot_p0_p1_verification_v1.yaml", FrozenProtocol
    )
    rv = json.loads((PRIVATE / "EvaluationRequest.valid.json").read_bytes())
    rv.update(
        artifact_version_id=str(uuid4()),
        protocol_id=protocol.protocol_id,
        protocol_version=protocol.version,
        protocol_hash=protocol.sha256,
        window="validation",
        cycle="weekly",
        intent=intent,
    )
    request = EvaluationRequest.model_validate(rv)
    mv = json.loads((PRIVATE / "Measurement.valid.json").read_bytes())
    mv.update(
        metrics={
            "extreme_macro_recall": metric(score).model_dump(),
            "long_short_net_per_period": metric(-0.002).model_dump(),
        },
        status="complete",
        period_count=period_count,
        diagnostics=diagnostics or {},
        hurdle={"paired_primary": "fail", "overall": "fail", "placebo": "insufficient_data"},
    )
    measured = Measurement.model_validate(mv)
    body = json.loads((PRIVATE / "OfficialRecord.valid.json").read_bytes())
    body.update(
        record_id=str(uuid4()),
        window="validation",
        cycle="weekly",
        stage="measurement",
        status="complete",
        request_hash=request.sha256,
        results_hash=measured.results_hash,
        metrics=measured.metrics,
        protocol_hash=protocol.sha256,
        identity={
            "artifact_version_id": str(request.artifact_version_id),
            "content_hash": request.content_hash,
            "protocol_version": f"{protocol.protocol_id}@{protocol.version}",
            "dataset_version_id": request.snapshot_id,
            "evaluator_version": request.runtime.evaluator_git_sha,
        },
    )
    return OfficialRecord.model_validate(body), request, measured, protocol


def project(case, *, bests=None, ordinals=None, peers=None):
    return project_pilot(
        *case,
        policy(),
        bests=bests or {},
        ordinals=ordinals or {"root": 1},
        frozen_family_scores=peers or [],
        baseline_version_id="baseline",
        cost_basis_ref="10bps",
        pit_grade_downgrade=True,
    )


def test_rel_06_pilot_ladder_keeps_raw_threshold_and_original_full_scalar_identity():
    first = evidence(0.5, period_count=100)
    report, best = project(first)
    assert report.scalar.measurement.value == 0.4945561368140035
    below = evidence(0.5112399122003182, period_count=200)
    unchanged, updates = project(below, bests=best, ordinals={"root": 2})
    assert not updates
    assert unchanged.scalar == report.scalar.model_copy(update={"attribution": "lineage_best"})
    assert unchanged.scalar.period_count == 100
    assert unchanged.scalar.origin_artifact_version_id == str(first[1].artifact_version_id)
    assert unchanged.scalar.origin_artifact_version_id != str(below[1].artifact_version_id)
    above = evidence(0.5112399122003183, period_count=200)
    changed, new_best = project(above, bests=best, ordinals={"root": 3})
    assert changed.scalar.attribution == "current_version" and new_best
    assert changed.scalar.origin_artifact_version_id == str(above[1].artifact_version_id)
    assert new_best["root"].unrounded_score == 0.5112399122003183


@pytest.mark.parametrize("score,periods", [(0.9, 200), (None, 0), (0.1, 1000)])
def test_budget_withholding_has_no_outcome_flags_or_counts(score, periods):
    case = evidence(score, period_count=periods, diagnostics={"secret": "private-marker"})
    report, updates = project(case, ordinals={"root": 4, "other": 1})
    assert isinstance(report, WithheldRelease)
    assert report.model_dump() == {"type": "withheld", "reason": "budget"}
    assert not updates


def test_diagnostics_and_withheld_intent_never_emit_measurements():
    for intent, reason in [("diagnostic", "non_selectable"), ("withheld", "budget")]:
        result, updates = project(evidence(0.9, intent=intent))
        assert result.model_dump() == {"type": "withheld", "reason": reason}
        assert not updates


def test_rel_04_05_projection_does_not_copy_diagnostics_or_secondary_numbers():
    case = evidence(
        0.5,
        diagnostics={
            "w3_metrics": {"value": 0.987654321},
            "raw_error": "private-marker",
            "daily_series": [0.987654321],
            "confirmation_start": "2099-01-01",
        },
    )
    result, _ = project(case)
    serialized = result.model_dump_json()
    assert all(
        s not in serialized
        for s in ["private-marker", "2099-01-01", ".987654321", "w3_metrics", "daily_series"]
    )
    assert result.minimum_detectable_effect == metric(None, "withheld")
    assert result.hurdle_flags.paired_primary == "fail"
    assert result.hurdle_flags.net_result == "fail"
    assert result.hurdle_flags.overall == "fail"
    assert "pit_grade_downgrade" in result.quality_flags
    with pytest.raises(ValidationError):
        WithheldRelease.model_validate(
            {"type": "withheld", "reason": "budget", "sample_count": 100}
        )


def test_missing_primary_never_creates_best_or_a_pass():
    result, bests = project(evidence(None))
    assert not bests and result.not_for_selection
    assert result.scalar.measurement.missing_reason == "insufficient_data"
    assert result.rank_bucket == "withheld"
    assert result.hurdle_flags.overall == "fail"


@pytest.mark.parametrize(
    "change",
    [
        {"window": "development"},
        {"cycle": "monthly"},
        {"protocol_hash": "f" * 64},
        {"snapshot_id": "f" * 64},
    ],
)
def test_release_identity_and_scope_mismatch_fail_closed(change):
    r, q, m, p = evidence()
    with pytest.raises(ValueError, match="frozen pilot"):
        project((r, q.model_copy(update=change), m, p))


def test_unreserved_or_incompatible_lineage_is_rejected():
    first = evidence()
    _, best = project(first)
    r, q, m, p = first
    with pytest.raises(ValueError, match="reservations"):
        project_pilot(
            r,
            q,
            m,
            p,
            policy(),
            bests={},
            ordinals={},
            frozen_family_scores=[],
            baseline_version_id="baseline",
            cost_basis_ref="10bps",
            pit_grade_downgrade=False,
        )
    bad = best["root"].model_copy(update={"scope_sha256": "f" * 64})
    with pytest.raises(ValueError, match="incompatible"):
        project(first, bests={"root": bad})


def test_family_rank_buckets_are_frozen_tie_aware_and_missing_is_not_dropped():
    assert rank_bucket(0.5, [0.5, 0.5]) == "middle"
    assert rank_bucket(0.9, [0.1, 0.5]) == "top"
    assert rank_bucket(0.1, [0.5, 0.9]) == "bottom"
    assert rank_bucket(0.9, [None, 0.1]) == "withheld"
    with pytest.raises(ValueError, match="nonfinite"):
        rank_bucket(0.5, [float("nan")])


@pytest.mark.parametrize(
    "value,step,expected",
    [
        (0.0125, 0.005, 0.015),
        (-0.0125, 0.005, -0.015),
        (0.123, 0.02, 0.12),
        (1.125, 0.25, 1.25),
        (0.529, 0.05, 0.55),
        (-0.01, 0.05, 0),
    ],
)
def test_rel_01_decimal_rounding_is_explicit_at_half_steps(value, step, expected):
    assert coarsen(metric(value), step).value == expected
    assert coarsen(metric(None, "failed"), step) == metric(None, "failed")


def test_rel_02_batches_utc_boundaries_and_advancement_delay():
    stock = policy("stock")
    at = datetime(2026, 10, 25, 23, 59, 59, 999999, tzinfo=UTC)
    monday = datetime(2026, 10, 26, tzinfo=UTC)
    assert eligible_at(stock, "w1", at) == monday
    assert eligible_at(stock, "w2", at) == monday
    assert eligible_at(stock, "w2", monday) == monday
    assert eligible_at(stock, "advancement", monday + timedelta(seconds=1)) == datetime(
        2026, 11, 9, tzinfo=UTC
    )
    assert eligible_at(policy(), "pilot", monday + timedelta(seconds=1)) == monday + timedelta(
        hours=6
    )
    with pytest.raises(ValueError):
        batch_at_or_after(datetime(2026, 1, 1))
    for source in ("W3", "confirmation", "unknown"):
        with pytest.raises(ValueError, match="mapping"):
            eligible_at(stock, source, monday)


def test_rel_01_stock_w1_allowlist_and_missing_values():
    metrics = {
        "rank_ic_mean": metric(0.0125),
        "rank_ic_ir": metric(0.123),
        "nw_t": metric(2.5),
        "ls_net_sharpe": metric(1.125),
        "positive_rank_ic_date_share": metric(0.529),
        "w3_sharpe": metric(123456),
    }
    result = project_w1(
        metrics,
        window="W1",
        policy=policy("stock"),
        yearly={"2022": metric(0.0125)},
        decay={"1": metric(0.0125), "5": metric(None)},
        library_artifact_version_id="should-not-leak",
        coverage_bucket="unavailable",
        complexity=5,
    )
    assert result.rank_ic_mean.value == 0.015 and result.rank_ic_ir.value == 0.12
    assert result.ls_net_sharpe.value == 1.25
    assert result.nw_t_bucket == "2_to_3" and result.positive_rank_ic_date_share.value == 0.55
    assert result.library_artifact_version_id is None
    assert result.yearly_rank_ic["2022"].value == 0.015
    assert result.top_turnover == metric(None)
    assert "w3_sharpe" not in result.model_dump_json() and "123456" not in result.model_dump_json()
    with pytest.raises(ValueError, match="W1"):
        project_w1(
            metrics,
            window="W3",
            policy=policy("stock"),
            yearly={},
            decay={},
            library_artifact_version_id=None,
            coverage_bucket="unavailable",
            complexity=0,
        )


def stock_scalar(value, version="synthetic-original"):
    return ReleasedScalar(
        metric="RankIC_mean",
        sampling_unit="trading_date",
        period_count=100,
        cost_basis_ref="stock-costs",
        baseline_version_id=None,
        measurement=metric(value),
        origin_artifact_version_id=version,
        attribution="current_version",
    )


def test_rel_06_stock_ladder_exact_step_and_no_child_relabelling():
    stock = policy("stock")
    first, best = project_w2(
        stock_scalar(0.02),
        window="W2",
        policy=stock,
        passed=True,
        scope_sha256="0" * 64,
        prior=None,
    )
    assert first.scalar.measurement.value == 0.02
    held, none = project_w2(
        stock_scalar(0.0249, "child"),
        window="W2",
        policy=stock,
        passed=True,
        scope_sha256="0" * 64,
        prior=best,
    )
    assert held.ladder_status == "unchanged" and held.scalar is None and none is None
    new, updated = project_w2(
        stock_scalar(0.025, "child"),
        window="W2",
        policy=stock,
        passed=True,
        scope_sha256="0" * 64,
        prior=best,
    )
    assert new.ladder_status == "improved" and new.scalar.measurement.value == 0.03
    assert updated.scalar.origin_artifact_version_id == "child"
    with pytest.raises(ValueError, match="missing"):
        project_w2(
            stock_scalar(None),
            window="W2",
            policy=stock,
            passed=True,
            scope_sha256="0" * 64,
            prior=best,
        )
    assert project_advancement(advanced=False).model_dump() == {
        "type": "advancement",
        "decision": "NOT_ADVANCED",
    }


@pytest.mark.parametrize(
    "value,expected",
    [(None, "unavailable"), (-1, "below_1"), (1, "1_to_2"), (2, "2_to_3"), (3, "above_3")],
)
def test_t_bucket_closed_edges(value, expected):
    assert t_bucket(metric(value)) == expected


def test_public_policy_card_does_not_copy_private_protocol_or_confirmation_budget():
    for name in ("pilot", "stock"):
        result = public_card(policy(name))
        PublicReleasePolicyCard.model_validate_json(result.model_dump_json())
        assert "protocol_sha256" not in result.model_dump_json()
        assert "confirmation_queries" not in result.model_dump_json()
        assert not result.confirmation_metrics_released


@given(st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False))
def test_rel_05_forbidden_private_values_never_enter_a_stock_report(secret):
    result = project_w1(
        {"W3": metric(secret), "raw_error": metric(secret)},
        window="W1",
        policy=policy("stock"),
        yearly={},
        decay={},
        library_artifact_version_id=None,
        coverage_bucket="unavailable",
        complexity=0,
    )
    reference = project_w1(
        {},
        window="W1",
        policy=policy("stock"),
        yearly={},
        decay={},
        library_artifact_version_id=None,
        coverage_bucket="unavailable",
        complexity=0,
    )
    assert result == reference


def test_new_released_flags_and_withheld_variant_validate_public_schema():
    base = json.loads((ROOT / "contracts/examples/ReleasedReport.valid.json").read_bytes())
    base["content"] = {"type": "withheld", "reason": "budget"}
    ReleasedReport.model_validate(base)
