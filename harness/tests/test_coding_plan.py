import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from qfh.budget import BudgetPolicy, BudgetRefused, Ledger, Usage
from qfh.coding_plan import (
    CodingLedger,
    CodingPolicy,
    coding_detail,
    parse_coding_usage,
    read_coding_credential,
)
from qfh.research import PilotExtension, Research
from qfh.trial_metrics import model_metrics

CONFIGS = Path(__file__).resolve().parents[1] / "configs"
NOW = datetime.fromisoformat("2026-11-13T11:00:00+08:00")


def policy(**changes):
    return CodingPolicy.model_validate(
        {
            **yaml.safe_load((CONFIGS / "glm-coding-2026-11-13.yaml").read_text()),
            **changes,
        }
    )


def ledger(tmp_path, **changes):
    cash = Research(CONFIGS / "research-trial.yaml", tmp_path).ledger
    return CodingLedger(cash, policy(**changes))


def test_coding_quota_is_atomic_and_preserves_cash_ledger(tmp_path):
    obj = ledger(tmp_path)
    before = obj.snapshot()

    def attempt(i):
        try:
            obj.reserve(str(i), f"probe:{i}", NOW)
            return str(i)
        except BudgetRefused:
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        accepted = [ident for ident in pool.map(attempt, range(8)) if ident is not None]
    assert len(accepted) == 1
    usage = Usage(input_uncached=100, input_cached=20, input_cache_write=0, output=10)
    obj.settle(accepted[0], usage, metadata={"cache_tokens_reported": True})
    obj.settle(accepted[0], usage, metadata={"cache_tokens_reported": True})
    after = obj.snapshot()
    cash_upper = 120 * 2 + 10 * 8
    assert after["cumulative_micro_cny"] == before["cumulative_micro_cny"] + cash_upper
    assert (
        after["remaining_unreserved_micro_cny"]
        == before["remaining_unreserved_micro_cny"] - cash_upper
    )
    detail = coding_detail(after["calls"][0])
    assert detail["quota_settled_upper_microcredits"] == 120 * 230 + 10 * 800
    assert after["calls"][0]["charged"] == cash_upper
    with pytest.raises(ValueError, match="conflicting"):
        obj.settle(accepted[0], usage.model_copy(update={"output": 11}))


def test_unknown_usage_retains_subscription_reservation_across_restart(tmp_path):
    obj = ledger(tmp_path)
    obj.reserve("first", "first", NOW)
    obj.unknown("first", "ReadTimeout")
    restarted = ledger(tmp_path)
    detail = coding_detail(restarted.snapshot()["calls"][0])
    assert detail["quota_reserved_microcredits"] == obj.coding.reservation
    assert detail["quota_settled_upper_microcredits"] is None
    assert detail["route_id"] == obj.coding.id
    with pytest.raises(BudgetRefused, match="unknown"):
        restarted.reserve("next", "next", NOW)


def test_operator_package_amendment_counts_old_calls_and_preserves_saved_policy(tmp_path):
    obj = ledger(tmp_path)
    usage = Usage(input_uncached=1048576, input_cached=0, input_cache_write=0, output=8192)
    for i in range(4):
        obj.reserve(str(i), str(i), NOW, output_tokens=8192)
        obj.settle(str(i), usage)
    before = obj.snapshot()
    with pytest.raises(BudgetRefused, match="work-package"):
        obj.reserve("blocked", "blocked", NOW, output_tokens=8192)
    amended = CodingLedger(
        obj, policy(id="bounded-package-amendment", cash_package_micro_cny=20000000)
    )
    amended.reserve("next", "next", NOW, output_tokens=8192)
    after = amended.snapshot()
    assert [c for c in after["calls"] if c["id"] != "next"] == before["calls"]
    assert obj.policy.package_micro_cny == 10000000
    assert (
        coding_detail(next(c for c in after["calls"] if c["id"] == "next"))[
            "cash_package_micro_cny"
        ]
        == 20000000
    )
    assert Ledger(obj.path, obj.policy).policy == obj.policy


def test_package_amendment_cannot_expand_original_cash_ceiling(tmp_path):
    obj = ledger(tmp_path)
    with pytest.raises(ValueError, match="original cumulative ceiling"):
        CodingLedger(obj, policy(cash_package_micro_cny=200000001))
    cash_policy = BudgetPolicy.model_validate(
        {**obj.policy.model_dump(), "carry_micro_cny": 198000000}
    )
    cash = Ledger(tmp_path / "near-original-limit.sqlite3", cash_policy)
    amended = CodingLedger(cash, policy(cash_package_micro_cny=20000000))
    with pytest.raises(BudgetRefused, match="original cumulative budget"):
        amended.reserve("blocked", "blocked", NOW, output_tokens=8192)
    assert not amended.snapshot()["calls"]


def test_reviewed_auth_rejection_keeps_both_reservations_and_request_count(tmp_path):
    obj = ledger(tmp_path, max_requests=2)
    obj.reserve("first", "probe:1", NOW)
    obj.unknown("first", "ValueError")
    wire = tmp_path / "wire/first"
    wire.mkdir(parents=True)
    request = b'{"model":"glm-5.3-flash"}'
    (wire / "request.json").write_bytes(request)
    (wire / "response.sse").write_text('{"error":{"type":"401","message":"Rejected"}}')
    http = {
        "status": 500,
        "endpoint": obj.coding.endpoint,
        "step": "probe:1",
        "request_sha256": hashlib.sha256(request).hexdigest(),
    }
    (wire / "http.json").write_text(json.dumps(http))
    authority = "Owner replaced the key; operator reviewed a complete authentication rejection."
    with pytest.raises(ValueError, match="complete recorded"):
        obj.review_auth_rejection(wire, authority=authority)
    before = obj.snapshot()
    http["status"] = 401
    (wire / "http.json").write_text(json.dumps(http))
    obj.review_auth_rejection(wire, authority=authority)
    after = obj.snapshot()
    assert after["unresolved_micro_cny"] == before["unresolved_micro_cny"]
    assert after["remaining_unreserved_micro_cny"] == before["remaining_unreserved_micro_cny"]
    call = after["calls"][0]
    assert call["state"] == "rejected_reserved" and call["charged"] is None
    assert coding_detail(call)["quota_settled_upper_microcredits"] is None
    assert coding_detail(call)["quota_reserved_microcredits"] == obj.coding.reservation
    research = Research(CONFIGS / "research-trial.yaml", tmp_path)
    research.extend_allowance(
        PilotExtension(
            amendment_id="reviewed-rejection-repair",
            expected_limit=3,
            new_limit=4,
            authority="Owner authorized a bounded repair and a pilot allowance extension.",
            reason="Permit a new trial while retaining both reviewed rejection reservations.",
        )
    )
    assert research.ledger.snapshot() == after
    assert research.allowance()["effective_limit"] == 4
    with pytest.raises(ValueError, match="matching unknown"):
        obj.review_auth_rejection(wire, authority=authority)
    restarted = ledger(tmp_path, max_requests=2)
    restarted.reserve("repair", "repair:1", NOW, output_tokens=128)
    assert restarted.snapshot()["unresolved_micro_cny"] == (
        obj.policy.reservation + obj.coding.maximum_input_tokens * 2 + 128 * 8
    )
    restarted.settle(
        "repair", Usage(input_uncached=1, input_cached=0, input_cache_write=0, output=1)
    )
    with pytest.raises(BudgetRefused, match="request allowance"):
        restarted.reserve("extra", "extra", NOW)


def test_coding_caps_expiry_and_no_fallback(tmp_path):
    obj = ledger(tmp_path, max_requests=1)
    obj.reserve("first", "first", NOW)
    obj.settle("first", Usage(input_uncached=1, input_cached=0, input_cache_write=0, output=1))
    with pytest.raises(BudgetRefused, match="request allowance"):
        obj.reserve("next", "next", NOW)
    with pytest.raises(BudgetRefused, match="window"):
        obj.reserve("late", "late", datetime.fromisoformat("2026-11-13T18:00:00+08:00"))
    with pytest.raises(BudgetRefused, match="already used"):
        obj.reserve("first", "different", NOW)
    for changes in (
        {"endpoint": "https://open.bigmodel.cn/api/paas/v4/chat/completions"},
        {"model": "glm-5.3"},
        {"platform": "untrusted-host"},
    ):
        with pytest.raises(ValidationError):
            policy(**changes)


def test_quota_reservation_accounts_for_previously_settled_usage(tmp_path):
    obj = ledger(tmp_path, max_microcredits=policy().reservation)
    obj.reserve("first", "first", NOW)
    obj.settle("first", Usage(input_uncached=1, input_cached=0, input_cache_write=0, output=1))
    with pytest.raises(BudgetRefused, match="quota allowance"):
        obj.reserve("second", "second", NOW)


def test_glm_missing_cache_counters_are_reported_unknown_not_zero(tmp_path):
    events = [
        {"type": "message_start", "message": {"usage": {"input_tokens": 20}}},
        {"type": "message_delta", "usage": {"output_tokens": 5}},
        {"type": "message_stop"},
    ]
    usage, metadata = parse_coding_usage(events)
    assert metadata["cache_tokens_reported"] is False
    obj = ledger(tmp_path)
    obj.reserve("one", "one", NOW)
    obj.settle("one", usage, metadata=metadata)
    measured = model_metrics(obj.snapshot()["calls"], policy().model_dump(mode="json"))
    assert measured["total_tokens"] == 25
    assert measured["input_cache_hit_ratio"] is None
    assert measured["published_price_estimate_cny"] is None
    assert measured["subscription_credits_settled_upper_bound"] == 0.0086
    for malformed in (events[:-1], [events[0], events[-1]]):
        with pytest.raises(ValueError, match="incomplete"):
            parse_coding_usage(malformed)


def test_new_route_freezes_per_trial_without_rewriting_old_trials(tmp_path, monkeypatch):
    monkeypatch.setattr("qfh.research.admission_open", lambda _: True)
    monkeypatch.setattr(CodingPolicy, "admission_open", lambda *_: True)
    research = Research(CONFIGS / "research-trial.yaml", tmp_path)
    research.admit("old", expected_route_id="deepseek")
    old_scope = research.scope("old")
    old_policy = research.policy.model_dump_json()
    route = policy()
    research.activate_model_route(route)
    research.activate_model_route(route)
    assert research.policy.model_dump_json() == old_policy
    assert research.scope("old") == old_scope
    with pytest.raises(BudgetRefused, match="route differs"):
        research.admit("old", expected_route_id=route.id)
    research.admit("new", expected_route_id=route.id)
    assert research.trial_model_route("new")["model"] == "glm-5.3-flash"
    worker = research.begin_worker("new", "researcher", "Inspect the scoped data independently")
    assert worker["route"]["provider"] == "glm_coding"
    assert worker["route"]["model"] == "glm-5.3-flash"
    research.admit(worker["child_id"], expected_route_id=route.id)
    with pytest.raises(ValueError, match="immutable"):
        research.activate_model_route(policy(max_requests=25))
    with research.db() as db:
        rows = list(db.execute("SELECT body FROM events WHERE kind='model_route_activated'"))
    assert len(rows) == 1
    assert json.loads(rows[0][0])["route"]["subscription_tier"] == "Pro"


def test_route_activation_refuses_unresolved_cash_usage(tmp_path, monkeypatch):
    monkeypatch.setattr("qfh.budget.admission_open", lambda _: True)
    research = Research(CONFIGS / "research-trial.yaml", tmp_path)
    research.ledger.reserve("pending", "pending", NOW)
    with pytest.raises(ValueError, match="pending/unknown"):
        research.activate_model_route(policy())


def test_glm_subscription_does_not_bypass_original_cash_ceiling(tmp_path):
    original = ledger(tmp_path)
    tight = original.policy.model_copy(
        update={
            "total_micro_cny": original.policy.carry_micro_cny + original.policy.reservation - 1,
        }
    )
    obj = CodingLedger(Ledger(tmp_path / "tight.sqlite3", tight), policy())
    with pytest.raises(BudgetRefused, match="original cumulative"):
        obj.reserve("one", "one", NOW)
    assert obj.snapshot()["calls"] == []


def test_native_credential_reference_is_owner_only_and_errors_hide_values(tmp_path):
    home = tmp_path / "research-ui-home"
    home.mkdir()
    path = home / ".credentials.yaml"
    key = "dummy-secret-only-for-this-test"
    value = {
        "api_key": key,
        "platform": "bigmodel-cn",
        "plan": "coding",
        "model": "glm-5.3-flash",
        "tier": "Pro",
    }
    path.write_text(
        yaml.safe_dump({"version": 1, "refs": {"QFH_GLM_CODING_CREDENTIAL": json.dumps(value)}})
    )
    path.chmod(0o600)
    assert read_coding_credential(tmp_path) == key
    path.chmod(0o644)
    with pytest.raises(ValueError) as exc:
        read_coding_credential(tmp_path)
    assert key not in str(exc.value)
    path.chmod(0o600)
    path.write_text("invalid: [" + key)
    with pytest.raises(ValueError) as exc:
        read_coding_credential(tmp_path)
    assert key not in str(exc.value)
