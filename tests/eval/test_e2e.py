"""Phase 3 acceptance, end to end on the synthetic world, through the MCP front door.

Thirty seed factors imported with qfr.pool.import are pulled by the scheduler, screened
and evaluated on W1 by the worker, and released at the next 6-hour batch with rounded
values; qfr.report.list shows what research sees and qfr.evidence.get returns the
owner-grade evidence at full precision. The seeds become the correlation library once
their W1 records exist; a stack with no seeds records the library gate as vacuous.
"""

import json
from decimal import Decimal
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from tests.eval.stack_rig import stack
from tests.registry_rig import factor_manifest

pytestmark = pytest.mark.postgres

SEEDS = [
    ("ma_ratio_5_20", "Mean($close, 5) / Mean($close, 20) - 1", 1),
    ("reversal_5", "-Delta($close, 5) / Ref($close, 5)", 1),
    ("price_volume_corr", "Corr($close, $volume, 20)", -1),
    ("volume_surge", "Rank($volume) - Rank(Mean($volume, 20))", 1),
    ("range_20", "Max($high, 20) / Min($low, 20) - 1", -1),
    ("price_cv_20", "Std($close, 20) / Mean($close, 20)", -1),
    ("ts_rank_close_60", "TsRank($close, 60)", 1),
    ("volume_z_20", "TsZ($volume, 20)", 1),
    ("slope_10", "Slope($close, 10) / $close", 1),
    ("trend_fit_20", "Rsq($close, 20)", 1),
    ("return_skew_60", "Skew(Pct($close, 1), 60)", -1),
    ("return_kurt_60", "Kurt(Pct($close, 1), 60)", -1),
    ("days_since_high", "ArgMax($high, 20)", -1),
    ("days_since_low", "ArgMin($low, 20)", 1),
    ("intraday_return", "($close - $open) / $open", -1),
    ("daily_range", "($high - $low) / $close", -1),
    ("intraday_mean_10", "Mean(($close - $open) / $open, 10)", -1),
    ("volume_ratio_log", "Log(Mean($volume, 5) / Mean($volume, 60))", 1),
    ("rank_corr_10", "Corr(Rank($close), Rank($volume), 10)", -1),
    ("ret_vol_cov", "Cov(Pct($close, 1), Pct($volume, 1), 20)", 1),
    ("ema_return_10", "EMA(Pct($close, 1), 10)", 1),
    ("residual_20", "Resi($close, 20) / $close", -1),
    ("lagged_momentum", "Ref(Pct($close, 5), 20)", 1),
    ("volatility_20", "Std(Pct($close, 1), 20)", -1),
    ("momentum_60", "Pct($close, 60)", 1),
    ("volume_median_ratio", "Med($volume, 10) / Mean($volume, 40)", 1),
    ("volume_ts_rank", "TsRank($volume, 10)", 1),
    ("up_days_20", "Sum(Sign(Delta($close, 1)), 20)", 1),
    ("wma_gap_10", "WMA($close, 10) / $close - 1", -1),
    ("volume_change_z", "Zscore(Delta($volume, 5))", 1),
]
REPORTS = Draft202012Validator(json.loads(Path("schemas/public/released_report.json").read_text()))


def entries():
    return [
        {"name": n, "title": n.replace("_", " "), "expression": e, "expected_sign": s,
         "horizon_days": 5}
        for n, e, s in SEEDS
    ]  # fmt: skip


def multiple_of(value, step):
    return (Decimal(str(value)) / Decimal(str(step))) % 1 == 0


@pytest.fixture
def full(tmp_path, monkeypatch, small_zones):
    with stack(tmp_path, monkeypatch, small_zones) as built:
        yield built


def test_thirty_seeds_flow_from_import_to_released_reports_and_owner_evidence(full):
    imported = full.mcp.ok("qfr.pool.import", entries=entries())["data"]
    assert imported["counts"]["published"] == 30
    versions = [e["version_id"] for e in imported["entries"]]

    full.settle()
    states = full.eval.state_counts()
    assert sum(states.values()) == 30, states
    evaluated = states.get("W1Evaluated", 0) + states.get("W1GateFailed", 0)
    assert evaluated + states.get("ScreenFailed", 0) == 30, states
    assert evaluated >= 25, states

    # Nothing is visible before the batch time (REL-02).
    assert full.mcp.ok("qfr.report.list")["data"]["items"] == []
    pending = full.mcp.ok("qfr.pool.list", pool="factor")["data"]["items"]
    assert {i["released_state"] for i in pending} == {None}

    full.eval.clock.advance(hours=6)  # 01:00 -> 07:00, past the 06:00 batch
    full.eval.release.tick()
    reports = full.mcp.ok("qfr.report.list", limit=2000)["data"]["items"]
    by_type = {}
    for report in reports:
        by_type.setdefault(report["content"]["type"], []).append(report)
        REPORTS.validate(report)  # REL-04
        for key in ("version_id", "content_hash", "protocol_id", "protocol_version",
                    "data_snapshot_id", "evaluator_code_version"):  # fmt: skip
            assert report[key], key  # EVL-02
    assert len(by_type["intake"]) == 30 and len(by_type["screening"]) == 30
    assert len(by_type["w1"]) == evaluated

    policy = full.eval.db.scalar("SELECT config FROM eval.release_policies WHERE status = 'active'")
    rounding = policy["rounding"]
    for report in by_type["w1"]:  # REL-01
        content = report["content"]
        assert multiple_of(content["rankic_mean"], rounding["rankic"])
        assert multiple_of(content["rankic_ir"], rounding["ir"])
        assert multiple_of(content["ls_net_sharpe"], rounding["sharpe"])
        assert multiple_of(content["top_turnover"], rounding["shares"])
        assert all(multiple_of(v, rounding["rankic"]) for v in content["decay_profile"].values())
        assert report["released_at"].startswith("2026-01-05T07:00")

    # Owner-grade evidence at full precision through the front door.
    w1_version = by_type["w1"][0]["version_id"]
    evidence = full.mcp.ok("qfr.evidence.get", version_id=w1_version)["data"]
    assert evidence["visibility"] == "owner_only"
    assert evidence["evaluation"]["state"] in ("W1Evaluated", "W1GateFailed")
    record = next(r for r in evidence["official_records"] if r["stage"] == "w1")
    released = by_type["w1"][0]["content"]
    assert record["metrics"]["rankic_mean"] != released["rankic_mean"]  # not rounded
    assert {g["name"] for g in evidence["gate_values"]} == {
        "sign_consistency", "rankic_mean", "rankic_ir", "rankic_t_nw", "top_turnover",
        "library_correlation", "coverage",
    }  # fmt: skip
    assert {s["kind"] for s in evidence["series"]} == {"rankic", "ls_returns", "nav"}
    # The first seed evaluated sees no library yet. Reports in one batch share a due time,
    # so the release order is not the evaluation order: take the first W1 record.
    first = full.eval.db.scalar(
        "SELECT version_id FROM eval.official_records WHERE stage = 'w1' ORDER BY record_id LIMIT 1"
    )
    earliest = full.mcp.ok("qfr.evidence.get", version_id=str(first))["data"]
    assert earliest["library_correlation"]["vacuous"] is True

    # The pool listing now carries evidence tiers and released state.
    listed = full.mcp.ok("qfr.pool.list", pool="factor")["data"]["items"]
    assert {i["evidence_tier"] for i in listed} <= {"w1_pass", "w1_fail", "screening_fail"}
    assert all(i["released_state"] for i in listed)

    # The seeds with W1 records are the correlation library now.
    library = full.admin.get("/v1/library").json()["items"]
    effective = [m for m in library if m["effective_from"] is not None]
    assert len(effective) == evaluated
    assert set(versions) >= {m["version_id"] for m in library}

    status = full.mcp.ok("qfr.status")["data"]
    assert status["services"]["eval-admin-api"]["status"] == "ok"
    assert status["services"]["feedback-api"]["status"] == "ok"
    assert {m["window"] for m in status["burn_meters"]} == {"W1", "W2", "W3"}
    w1_burn = next(m for m in status["burn_meters"] if m["window"] == "W1")
    assert w1_burn["trials"] == evaluated
    assert status["data_freshness"]["latest_full_snapshot_id"] == full.eval.db.scalar(
        "SELECT snapshot_id FROM eval.epochs WHERE status = 'active'"
    )
    setup = full.mcp.ok("qfr.setup.status")["data"]
    assert setup["steps"]["data"]["status"] == "ok"
    assert setup["snapshot_ids"]["epoch"] == status["data_freshness"]["latest_full_snapshot_id"]


def test_a_later_factor_is_measured_against_the_seed_library(full):
    full.mcp.ok("qfr.pool.import", entries=entries()[:3])
    full.settle()
    later = full.eval.registry.publish(
        factor_manifest("later_momentum", "Mean($close, 10) / Mean($close, 60) - 1")
    ).json()["version"]["version_id"]
    full.settle()
    evidence = full.mcp.ok("qfr.evidence.get", version_id=later)["data"]
    library = evidence["library_correlation"]
    assert library["vacuous"] is False
    assert library["size"] >= 1
    assert library["max_abs_correlation"] is not None
    assert {m["version_id"] for m in library["members"]} <= {
        e["version_id"] for e in full.mcp.ok("qfr.pool.list", pool="factor")["data"]["items"]
    }


def test_a_stack_with_no_seeds_records_the_library_gate_as_vacuous(full):
    full.mcp.ok("qfr.pool.import", no_pool=True)
    version = full.eval.registry.publish(factor_manifest("first", "Pct($close, 20)")).json()
    full.settle()
    version_id = version["version"]["version_id"]
    evidence = full.mcp.ok("qfr.evidence.get", version_id=version_id)["data"]
    library_gate = next(g for g in evidence["gate_values"] if g["name"] == "library_correlation")
    assert library_gate["passed"] is True and library_gate["value"] is None
    assert "vacuous" in library_gate["skipped_reason"]
    library = evidence["library_correlation"]
    assert library["vacuous"] is True and library["size"] == 0 and library["members"] == []
