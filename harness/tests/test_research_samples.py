import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError
from test_research import report
from test_research_specification import specification
from test_research_v4 import new_draft

from qfh.data_gateway import DataPolicy, dispatch
from qfh.evidence import Query, canonical
from qfh.research import Operation, Research
from qfh.research_samples import (
    ExpansionPlan,
    SampleActivation,
    SampleRange,
    compose_sample,
    support_profile,
)


@pytest.fixture
def sample(tmp_path, monkeypatch):
    monkeypatch.setattr("qfh.research.admission_open", lambda _: True)
    (tmp_path / "OFFLINE_ONLY").touch()
    config = Path(__file__).resolve().parents[1] / "configs/research-trial.yaml"
    research = Research(config, tmp_path)
    research.admit("historical-root")
    plan = ExpansionPlan.model_validate(
        yaml.safe_load((config.parent / "sample-expansion-2026-11-13.yaml").read_text())
    )
    policy = DataPolicy.model_validate(
        yaml.safe_load((config.parent / plan.data_config).read_text())
    )

    def fetch(query, *_):
        rows = []
        current = query.start
        while current <= query.end:
            if current.weekday() < 5:
                rows.append(
                    {
                        "symbol": query.symbols[0],
                        "date": current.isoformat(),
                        "close": 100 + current.toordinal() % 2,
                    }
                )
            current += timedelta(days=1)
        return rows, {"synthetic": True, "external_requests": 0}

    parent_ids = []
    for query in [research.policy.query, *plan.steps[:4]]:
        item = dispatch(
            {
                "provider": "baostock",
                "kind": "bars",
                "run_id": "test-preparation",
                "query": query.model_dump(mode="json"),
                "credentials": {},
            },
            policy,
            research.data_root,
            baostock_fetch=fetch,
        )
        parent_ids.append(item["evidence_id"])
    plan_hash = hashlib.sha256(canonical(plan.model_dump(mode="json"))).hexdigest()
    ident, record = compose_sample(
        research.store, parent_ids, policy.research_cutoff, plan.id, plan_hash, 4, synthetic=True
    )
    amendment = SampleActivation(
        id=plan.id,
        authority=plan.authority,
        expected_previous_id=None,
        evidence_id=ident,
        query=record["query"],
        plan_id=plan.id,
        plan_sha256=plan_hash,
        fixed_definition=specification(),
        statistical_protocol_sha256=hashlib.sha256(
            canonical(research.statistics.model_dump(mode="json"))
        ).hexdigest(),
        preview_rows=20,
        alignment_preview_rows=2,
    )
    return research, plan, parent_ids, record, amendment


def test_staged_composition_preserves_lineage_and_only_checks_support(sample):
    research, plan, parents, record, _ = sample
    assert len(record["content"]) > 100
    assert record["source_evidence_ids"] == sorted(parents)
    profile = support_profile(record["content"], specification(), research.statistics, plan)
    assert (
        profile["support_ready"] and min(profile["signal_bucket"], profile["control_bucket"]) >= 40
    )
    assert profile["inference_computed"] is False
    assert "effect" not in profile and "interval" not in profile
    _, earlier = compose_sample(
        research.store,
        parents[:2],
        research.data_policy.research_cutoff,
        plan.id,
        "0" * 64,
        1,
        synthetic=True,
    )
    assert not support_profile(earlier["content"], specification(), research.statistics, plan)[
        "support_ready"
    ]
    with pytest.raises(ValidationError):
        Query.model_validate(record["query"])
    assert SampleRange.model_validate(record["query"]).start == date(2026, 5, 1)


@pytest.mark.parametrize("change", ["overlap", "gap", "duplicate", "provider", "null", "mode"])
def test_composition_rejects_bad_parents(sample, change):
    research, plan, parents, _, _ = sample
    bad = research.store.get(parents[1])
    if change in ("overlap", "gap"):
        bad["query"]["end"] = "2026-10-19" if change == "overlap" else "2026-10-17"
    elif change == "duplicate":
        bad["content"].append(bad["content"][0])
    elif change == "provider":
        bad["provider"] = "ifind"
    elif change == "null":
        bad["content"][0]["close"] = None
    else:
        bad["transport"]["synthetic"] = False
    bad_ids = [parents[0], research.store.put(bad)]
    with pytest.raises((ValueError, ArithmeticError)):
        compose_sample(
            research.store,
            bad_ids,
            research.data_policy.research_cutoff,
            plan.id,
            "0" * 64,
            1,
            synthetic=True,
        )


def test_append_only_activation_preserves_old_scopes_and_budget(sample):
    research, _, _, _, amendment = sample
    before = research.ledger.snapshot()
    original = research.policy.model_dump_json()
    result = research.activate_sample(amendment)
    assert research.activate_sample(amendment) == result
    assert research.ledger.snapshot() == before and research.policy.model_dump_json() == original
    assert research.scope("historical-root")["sample"] is None
    research.admit("expanded-root")
    scope = research.scope("expanded-root")
    assert scope["sample"]["evidence_id"] == amendment.evidence_id
    assert scope["query"] == amendment.query.model_dump(mode="json")
    with research.db() as db:
        assert (
            db.execute("SELECT COUNT(*) FROM events WHERE kind='sample_activated'").fetchone()[0]
            == 1
        )
    with pytest.raises(ValueError, match="immutable"):
        research.activate_sample(
            amendment.model_copy(update={"authority": "Owner changed authority " * 3})
        )


def test_activation_reconstructs_composite_from_verified_sources(sample):
    research, _, _, record, amendment = sample
    record["content"][0]["close"] = 42
    tampered_id = research.store.put(record)
    with pytest.raises(ValueError, match="reproduce"):
        research.activate_sample(amendment.model_copy(update={"evidence_id": tampered_id}))
    assert research.trial_sample("historical-root") is None


def test_expanded_two_worker_round_uses_full_data_but_bounded_views(sample, monkeypatch):
    research, _, _, record, amendment = sample
    research.activate_sample(amendment)
    research.admit("expanded-root")
    monkeypatch.setattr(
        "qfh.research.dispatch", lambda *_args, **_kwargs: pytest.fail("no vendor access")
    )
    specs = []
    for role in ("researcher", "reviewer"):
        child = research.begin_worker(
            "expanded-root", role, "Execute the frozen definition independently."
        )["child_id"]
        bars = research.operate(
            Operation(op="data", session_id=child, args={"kind": "bars", "query": record["query"]})
        )
        assert bars["cache_reused"] and bars["content_is_preview"]
        assert len(bars["content"]) == 20 < bars["row_count"]
        metrics = research.operate(
            Operation(op="metrics", session_id=child, args={"evidence_id": amendment.evidence_id})
        )
        assert int(metrics["facts"]["sample.observations"]["value"]) == len(record["content"])
        assert not any(k.startswith("daily_return.") for k in metrics["facts"])
        full = research.calculations.get(metrics["calculation_artifact_id"])["result"]
        assert len(full["alignment"]["1"]) > 100 and len(metrics["alignment"]["1"]) == 4
        assert full["measurement_id"] == metrics["measurement_id"]
        assessed = research.operate(
            Operation(
                op="specification",
                session_id=child,
                args={
                    "evidence_id": amendment.evidence_id,
                    "specification_json": amendment.fixed_definition.model_dump_json(),
                },
            )
        )
        assert assessed["inference"]["interval"] is not None
        assert assessed["inference"]["bootstrap_replicates_run"] == 2000
        assert len(assessed["alignment"]) == 4 and assessed["alignment_total_rows"] > 100
        assert len(json.dumps(assessed)) < research.policy.max_tool_result_chars
        specs.append(assessed)
        with pytest.raises(ValueError, match="frozen definition"):
            research.specification(
                child, amendment.evidence_id, specification(threshold="0.1").model_dump_json()
            )
        output = {
            **report(amendment.evidence_id),
            "specification_id": assessed["specification_id"],
            "measurement_refs": [
                {
                    "measurement_id": metrics["measurement_id"],
                    "keys": ["sample.observations", "returns.mean"],
                }
            ],
        }
        assert research.submit_report(child, json.dumps(output))["status"] == "accepted"
        finished = research.finish_worker(
            "expanded-root",
            child,
            {"stopReason": "completed", "output": [{"type": "text", "text": "Submitted."}]},
        )
        assert len(json.dumps(finished)) < research.policy.max_tool_result_chars
    assert specs[0] == specs[1]
    result = research.operate(
        Operation(
            op="draft",
            session_id="expanded-root",
            args=new_draft(amendment.evidence_id, specs[0]["specification_id"]),
        )
    )
    assert result["draft"]["execution_time"] == "next_observation_close"
    assert len(json.dumps(result)) < research.policy.max_tool_result_chars


def test_composed_scope_rejects_other_queries_and_hidden_measurement_keys(sample):
    research, _, _, record, amendment = sample
    research.activate_sample(amendment)
    research.admit("expanded-root")
    child = research.begin_worker(
        "expanded-root", "researcher", "Inspect the complete permitted sample."
    )["child_id"]
    with pytest.raises(ValueError, match="single permitted"):
        research.operate(
            Operation(
                op="data",
                session_id=child,
                args={"kind": "bars", "query": research.policy.query.model_dump(mode="json")},
            )
        )
    research.operate(
        Operation(op="data", session_id=child, args={"kind": "bars", "query": record["query"]})
    )
    metrics = research.operate(
        Operation(op="metrics", session_id=child, args={"evidence_id": amendment.evidence_id})
    )
    from qfh.research import WorkerReport

    hidden = "daily_return." + record["content"][1]["date"]
    body = WorkerReport.model_validate(
        {
            **report(amendment.evidence_id),
            "measurement_refs": [{"measurement_id": metrics["measurement_id"], "keys": [hidden]}],
        }
    )
    with pytest.raises(ValueError, match="unknown or duplicate"):
        research.resolve_measurements(child, body)
