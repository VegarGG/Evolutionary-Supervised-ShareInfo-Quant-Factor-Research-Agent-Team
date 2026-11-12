import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pytest

from qfh.budget import BudgetPolicy, BudgetRefused, Ledger, Usage, admission_open


def policy(**changes):
    return BudgetPolicy(
        **{
            "total_micro_cny": 200_000_000,
            "carry_micro_cny": 56_256_735,
            "carry_requests": 884,
            "carry_source_sha256": "a" * 64,
            "package_micro_cny": 10_000_000,
            "input_micro_cny_per_token": 2,
            "output_micro_cny_per_token": 8,
            "provider_context_tokens": 1_048_576,
            "provider_max_output_tokens": 393_216,
            "concurrency": 1,
            "max_requests_per_step": 1,
            **changes,
        }
    )


NOW = datetime.fromisoformat("2026-11-12T12:01:00+08:00")


def test_concurrent_admission_never_overspends(tmp_path):
    ledger = Ledger(tmp_path / "spend.db", policy(concurrency=500))

    def attempt(i):
        try:
            ledger.reserve(str(i), str(i), NOW)
            return True
        except BudgetRefused:
            return False

    with ThreadPoolExecutor(max_workers=24) as pool:
        assert sum(pool.map(attempt, range(100))) == 1
    assert ledger.snapshot()["unresolved_micro_cny"] == policy().reservation


def test_unknown_charge_survives_restart_and_blocks_retry(tmp_path):
    path = tmp_path / "spend.db"
    ledger = Ledger(path, policy())
    ledger.reserve("one", "step", NOW)
    ledger.unknown("one", "connection lost after dispatch")
    resumed = Ledger(path, policy())
    with pytest.raises(BudgetRefused):
        resumed.reserve("two", "step", NOW)
    with pytest.raises(BudgetRefused):
        resumed.reserve("three", "another-step", NOW)
    assert resumed.snapshot()["unresolved_micro_cny"] == policy().reservation


def test_settlement_counts_cache_as_input_and_is_idempotent(tmp_path):
    ledger = Ledger(tmp_path / "spend.db", policy())
    ledger.reserve("one", "step", NOW)
    usage = Usage(input_uncached=10, input_cached=100, input_cache_write=5, output=30)
    ledger.settle("one", usage)
    ledger.settle("one", usage)
    assert ledger.snapshot()["new_settled_micro_cny"] == 470
    assert ledger.snapshot()["cumulative_micro_cny"] == 56_257_205
    with pytest.raises(ValueError, match="conflicting"):
        ledger.settle("one", usage.model_copy(update={"output": 31}))
    with pytest.raises(BudgetRefused):
        ledger.reserve("one", "other", NOW)


def test_global_total_and_policy_cannot_be_reset(tmp_path):
    p = policy(total_micro_cny=57_000_000)
    ledger = Ledger(tmp_path / "spend.db", p)
    with pytest.raises(BudgetRefused, match="original"):
        ledger.reserve("one", "step", NOW)
    with pytest.raises(ValueError, match="policy changed"):
        Ledger(tmp_path / "spend.db", policy())


@pytest.mark.parametrize(
    "hour,expected", [(11, False), (12, True), (13, True), (14, False), (17, False), (18, True)]
)
def test_admission_windows(hour, expected):
    assert admission_open(NOW.replace(hour=hour)) is expected


def test_explicit_conversation_grant_keeps_old_limits_and_shared_cap(tmp_path):
    ledger = Ledger(tmp_path / "spend.db", policy())
    ledger.grant_step("root", "trial", 3, 3, "owner-approved integration trial")
    ledger.grant_step("worker", "trial", 2, 3, "owner-approved integration trial")
    for i, step in enumerate(["root", "worker", "root"]):
        ledger.reserve(str(i), step, NOW)
        ledger.settle(
            str(i), Usage(input_uncached=1, input_cached=0, input_cache_write=0, output=1)
        )
    with pytest.raises(BudgetRefused, match="trial request"):
        ledger.reserve("extra", "worker", NOW)
    with pytest.raises(ValueError, match="immutable"):
        ledger.grant_step("worker", "trial", 3, 3, "changed")
    ledger.reserve("old", "diagnostic", NOW)
    ledger.settle("old", Usage(input_uncached=1, input_cached=0, input_cache_write=0, output=1))
    with pytest.raises(ValueError, match="already used"):
        ledger.grant_step("diagnostic", "new", 2, 2, "attempted replay")
    with pytest.raises(BudgetRefused, match="step request"):
        ledger.reserve("replay", "diagnostic", NOW)


def test_billing_reconciliation_preserves_calls_and_charges_new_calls(tmp_path):
    ledger = Ledger(tmp_path / "spend.db", policy())
    ledger.reserve("old", "old", NOW)
    usage = Usage(input_uncached=10, input_cached=0, input_cache_write=0, output=10)
    with pytest.raises(ValueError, match="unknown charges"):
        ledger.reconcile_official_total(20_350_000, "wrong", "owner invoice")
    ledger.settle("old", usage)
    digest = hashlib.sha256(json.dumps(["old"], separators=(",", ":")).encode()).hexdigest()
    with pytest.raises(ValueError, match="history changed"):
        ledger.reconcile_official_total(20_350_000, "wrong", "owner invoice")
    ledger.reconcile_official_total(20_350_000, digest, "owner invoice")
    resumed = Ledger(ledger.path, policy())
    s = resumed.snapshot()
    assert s["cumulative_micro_cny"] == 20_350_000
    assert s["remaining_unreserved_micro_cny"] == 179_650_000
    assert s["calls"][0]["charged"] == 100
    resumed.reserve("new", "new", NOW)
    assert (
        resumed.snapshot()["remaining_unreserved_micro_cny"] == 179_650_000 - policy().reservation
    )
    resumed.settle("new", usage)
    assert resumed.snapshot()["cumulative_micro_cny"] == 20_350_100


def test_reconciled_actual_total_is_still_capped(tmp_path):
    ledger = Ledger(tmp_path / "spend.db", policy())
    digest = hashlib.sha256(b"[]").hexdigest()
    ledger.reconcile_official_total(199_000_000, digest, "owner invoice")
    with pytest.raises(BudgetRefused, match="original cumulative"):
        ledger.reserve("new", "new", NOW)
    ledger.grant_step("root", "trial", 2, 2, "owner-approved test")
    with ledger.transaction() as db:
        for statement in (
            "UPDATE billing_baselines SET actual=0",
            "DELETE FROM billing_baselines",
            "UPDATE step_grants SET max_requests=1000",
            "DELETE FROM step_grants",
        ):
            with pytest.raises(sqlite3.IntegrityError, match="append only"):
                db.execute(statement)
