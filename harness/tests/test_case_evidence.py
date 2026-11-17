import copy
import json

import pytest
from test_case_factor import panel, spec
from test_case_research import host

from qfh.case_evidence import comparisons
from qfh.case_factor import inspect_factor
from qfh.case_usage import summarize_calls


@pytest.mark.parametrize(
    "text, rejected",
    [
        ("Return is now divided by the trailing daily-return standard deviation.", True),
        ("Return is divided by trailing daily return SD.", True),
        ("Return is now divided by the trailing daily-return SD times sqrt(lookback).", False),
        ("Volatility scaling motivates an unproven research hypothesis.", False),
        ("Return is not divided by the trailing daily-return standard deviation.", False),
    ],
)
def test_explicit_normalization_description_cannot_omit_the_lookback_scale(
    tmp_path, text, rejected
):
    obj = typed_host(tmp_path)
    task, payload, _ = designed_payload(obj)
    payload["hypothesis"]["text"] = text
    result = obj.submit(task["child_id"], "revise", json.dumps(payload))
    assert (result["status"] == "rejected") is rejected
    if rejected:
        assert "sqrt(lookback)" in result["error"]


@pytest.mark.parametrize(
    "text, rejected",
    [
        (
            "A window equal to the lookback was inspected, motivated by the dispersion evidence.",
            False,
        ),
        (
            "A window equal to the lookback was inspected, "
            "because recorded return dispersion differs.",
            False,
        ),
        ("The recorded measures do not establish improved cross-symbol comparability.", False),
        ("The recorded measures cannot establish equal comparability.", False),
        ("Normalization might reduce the SD spread.", False),
        ("The spread of score SDs did not compress.", True),
        ("The dispersion remains as wide.", True),
        ("The ratio of maximum to minimum SD is lower.", True),
        ("Normalization improves comparability.", True),
    ],
)
def test_comparison_guard_distinguishes_parameters_and_evidence_limits(text, rejected):
    from types import SimpleNamespace as N

    from qfh.case_evidence import comparison_issues

    issues = comparison_issues(
        N(hypothesis=N(text=""), rationale=N(text=text), decisions=[], issue_resolutions=[])
    )
    assert bool(issues) is rejected
    if rejected:
        assert "rationale.text" in issues[0]
        assert text.rstrip(".").lower() in issues[0]


def test_changed_row_count_agrees_across_float_and_decimal_engines():
    from qfh.case_audit import changed_rows, decimal_scores

    rows = [
        {"symbol": "600000.XSHG", "date": f"2026-01-{i:02}", "close": 10 + i * 0.1 + (i % 3) * 0.2}
        for i in range(1, 26)
    ]
    baseline, alternative = spec(lookback=5), spec(lookback=3)
    actual = inspect_factor(rows, alternative, baseline, tolerant_changes=True)
    independent = changed_rows(
        decimal_scores(rows, alternative.model_dump()),
        decimal_scores(rows, baseline.model_dump()),
        tolerant=True,
    )
    assert actual["summary"]["changed_score_or_eligibility_rows_from_initial"] == independent == 8


def test_actual_ledger_snapshot_can_feed_usage_without_json_reparsing(tmp_path):
    from datetime import UTC, datetime

    from qfh.budget import Usage
    from qfh.coding_plan import CodingLedger

    obj = typed_host(tmp_path)
    ledger = obj.research.ledger
    ledger.grant_step("case:test:supervisor", "test", 1, 1, "Offline accounting regression")
    coding = CodingLedger(ledger, obj.route)
    request_id = "offline-snapshot-test"
    coding.reserve(request_id, "case:test:supervisor", datetime(2026, 11, 17, 4, tzinfo=UTC))
    coding.settle(
        request_id, Usage(input_cached=20, input_uncached=10, input_cache_write=0, output=5)
    )
    summary = summarize_calls(ledger.snapshot()["calls"], "test")
    assert summary["team"]["requests"] == 1 and summary["team"]["total_tokens"] == 35


def typed_host(tmp_path):
    return host(
        tmp_path,
        protocol="structured-v3",
        reference_mode="task_bound",
        evidence_contract="typed-v1",
    )


def finding(obj, statement="Observed prices vary.", refs=None):
    task = obj.begin("root", "analyze", "Inspect source", [])
    body = {
        "candidate_id": "assigned",
        "topic": "coverage",
        "status": "supported",
        "statement": statement,
        "fact_refs": refs or ["600000.XSHG.warmup_exclusions"],
        "citations": [{"evidence_id": "prices", "quote": "Observed prices vary."}],
        "contradicts": [],
    }
    return task, body


@pytest.mark.parametrize(
    "statement", ["62 - 6 = 57", "62 observations minus 6 leaves 57", "Warmup exclusions are 6."]
)
def test_analyst_arithmetic_and_numeric_copies_rejected_at_source(tmp_path, statement):
    obj = typed_host(tmp_path)
    task, body = finding(obj, statement)
    result = obj.submit(task["child_id"], "findings", json.dumps({"findings": [body]}))
    assert result["status"] == "rejected"
    assert not obj.scope("root")["findings"]
    body["statement"] = "Required closes per signal and warmup exclusions are distinct."
    assert (
        obj.submit(task["child_id"], "findings", json.dumps({"findings": [body]}))["status"]
        == "accepted"
    )


def test_finding_reference_is_bound_to_real_current_counts(tmp_path):
    obj = typed_host(tmp_path)
    task, body = finding(obj, refs=["invented.count"])
    result = obj.submit(task["child_id"], "findings", json.dumps({"findings": [body]}))
    assert result["status"] == "rejected" and "fact reference" in result["error"]
    counts = obj.scope(task["child_id"])["current_count_facts"]["600000.XSHG"]
    assert counts["closes_required_per_signal"] == spec().lookback + 1
    assert counts["warmup_exclusions"] == spec().lookback
    assert (
        counts["eligible_signals"]
        == counts["observed_closes"] - counts["warmup_exclusions"] - counts["additional_exclusions"]
    )


def designed_payload(obj):
    task, body = finding(obj)
    assert (
        obj.submit(task["child_id"], "findings", json.dumps({"findings": [body]}))["status"]
        == "accepted"
    )
    obj.finish("root", task["child_id"], {"stopReason": "completed"})
    task = obj.begin("root", "design", "Inspect alternative", ["finding:1"])
    receipt = obj.inspect(task["child_id"], spec(lookback=3).model_dump_json())
    payload = {
        "parent_id": "assigned",
        "inspection_id": receipt["inspection_ref"],
        "facts_sha256": "inspection",
        "comparison_refs": receipt["comparison_refs"],
        "hypothesis": {"text": "Persistence is an unproven hypothesis.", "fact_refs": ["spec"]},
        "rationale": {"text": "Explore a trailing horizon.", "fact_refs": ["scope"]},
        "decisions": [
            {"finding_id": "finding:1", "disposition": "adopt", "reason": "Motivates exploration."}
        ],
        "citations": body["citations"],
        "basis_review_id": None,
        "issue_resolutions": [],
    }
    return task, payload, receipt


@pytest.mark.parametrize(
    "bad",
    [
        "The cross-symbol spread of score SDs did not compress.",
        "The ratio of maximum to minimum SD is lower.",
    ],
)
def test_comparative_claims_use_computed_records_even_when_measure_is_named(tmp_path, bad):
    obj = typed_host(tmp_path)
    task, payload, receipt = designed_payload(obj)
    payload["rationale"]["text"] = bad
    assert obj.submit(task["child_id"], "revise", json.dumps(payload))["status"] == "rejected"
    payload["rationale"]["text"] = "The recorded comparisons inform an exploratory choice."
    assert obj.submit(task["child_id"], "revise", json.dumps(payload))["status"] == "accepted"
    report = obj.scope("root")["structured_report"]
    assert len(report["body"]["comparisons"]) == 4
    assert all(
        c["right_inspection_id"] == receipt["inspection_id"] for c in report["body"]["comparisons"]
    )


@pytest.mark.parametrize(
    "ref",
    ["inspection:6/paired_eligible_symbol_dates.score_sd_max_over_min", "inspection:1/unknown"],
)
def test_comparison_cannot_forge_inspection_or_measure(tmp_path, ref):
    obj = typed_host(tmp_path)
    task, payload, _ = designed_payload(obj)
    payload["comparison_refs"] = [ref]
    result = obj.submit(task["child_id"], "revise", json.dumps(payload))
    assert result["status"] == "rejected"


def test_comparison_cohorts_and_undefined_ratios_are_explicit():
    rows = panel()
    left = inspect_factor(rows, spec(), spec())
    right = inspect_factor(rows, spec(lookback=3), spec())
    result = comparisons(left, right)
    paired = result["paired_eligible_symbol_dates.score_sd_max_over_min"]
    separate = result["each_spec_eligible_symbol_dates.score_sd_max_over_min"]
    assert paired["same_observations"] and not separate["same_observations"]
    assert (
        paired["left_by_symbol"]["600000.XSHG"]["count"]
        == paired["right_by_symbol"]["600000.XSHG"]["count"]
    )
    assert paired["left_value"] == paired["right_value"] == 1
    flat = copy.deepcopy(left)
    for row in flat["rows"]:
        if row["score"] is not None:
            row["score"] = 0
    result = comparisons(flat, flat)["paired_eligible_symbol_dates.score_sd_max_over_min"]
    assert result["left_value"] is None and result["direction_right_vs_left"] == "undefined"


def call(ident, actor, state="settled"):
    return {
        "id": ident,
        "step": "case:test:" + actor,
        "state": state,
        "finished": "2026-11-17T00:00:00Z",
        "charged": 100,
        "usage": {"input_cached": 20, "input_uncached": 10, "input_cache_write": 0, "output": 5},
        "detail": json.dumps({"funding": "coding_plan", "quota_settled_upper_microcredits": 500}),
    }


def test_usage_uses_settled_team_not_prior_snapshot_or_root_footer():
    calls = [call(str(i), "supervisor") for i in range(9)] + [
        call("worker", "author-2"),
        call("ack", "author-2:ack"),
    ]
    calls.append({**call("other", "supervisor"), "step": "case:other:supervisor"})
    result = summarize_calls(calls, "test")
    assert result["agents"]["supervisor"]["work_requests"] == 9
    assert result["agents"]["supervisor"]["acknowledgement_requests"] == 0
    assert result["team"]["requests"] == 11 and result["team"]["total_tokens"] == 385
    assert result["team"]["conservative_exposure_micro_cny"] == 1100


@pytest.mark.parametrize("state", ["pending", "unknown", "rejected_reserved"])
def test_usage_never_claims_completion_with_unsettled_request(state):
    with pytest.raises(ValueError, match="known settled"):
        summarize_calls([call("bad", "supervisor", state)], "test")
