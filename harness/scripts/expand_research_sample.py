"""Prepare one additional bounded BaoStock chunk per invocation, without LLM calls."""

import argparse
import hashlib
import json
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psutil
import yaml

from qfh.data_gateway import DataPolicy, dispatch
from qfh.evidence import canonical
from qfh.research import Research
from qfh.research_samples import ExpansionPlan, SampleActivation, compose_sample, support_profile
from qfh.research_specification import ContrastSpec


def write_new(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--private", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "configs/research-trial.yaml",
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--initialize", action="store_true")
    action.add_argument("--next-data", action="store_true")
    action.add_argument("--activate", action="store_true")
    args = parser.parse_args()
    research = Research(args.config.resolve(), args.private.resolve())
    plan = ExpansionPlan.model_validate(yaml.safe_load(args.plan.read_text()))
    plan_hash = hashlib.sha256(canonical(plan.model_dump(mode="json"))).hexdigest()
    folder = research.root / "sample-expansions" / plan.id
    folder.mkdir(parents=True, exist_ok=True)
    frozen_path = folder / "FROZEN_PLAN.json"
    policy_path = args.plan.resolve().parent / plan.data_config
    data_policy = DataPolicy.model_validate(yaml.safe_load(policy_path.read_text()))
    old, new = research.data_policy.model_dump(), data_policy.model_dump()
    old["provider_allowances"].pop("baostock", None)
    new["provider_allowances"].pop("baostock", None)
    if old != new:
        raise ValueError("only the BaoStock allowance may change; preserve cutoff and paid sources")
    protocol_hash = hashlib.sha256(
        canonical(research.statistics.model_dump(mode="json"))
    ).hexdigest()
    policy_hash = hashlib.sha256(canonical(data_policy.model_dump(mode="json"))).hexdigest()
    snapshot = research.ledger.snapshot()
    if any(c["state"] != "settled" for c in snapshot["calls"]):
        raise ValueError("unsettled model usage requires inspection before sample expansion")

    if args.initialize:
        with research.db() as db:
            row = db.execute(
                "SELECT draft FROM trials WHERE id=?", (plan.reference_trial_id,)
            ).fetchone()
            active = research.active_sample(db)
        if not row or not row[0]:
            raise ValueError("the referenced prior draft must exist")
        draft = json.loads(row[0])
        prior = draft["specification"]
        if prior["specification_id"] != plan.reference_specification_id:
            raise ValueError("reference specification differs")
        base = research.store.get(plan.base_evidence_id)
        if base["query"] != research.policy.query.model_dump(mode="json"):
            raise ValueError("base evidence differs from the prior research sample")
        previous_start = research.policy.query.start
        for query in plan.steps:
            if (
                query.symbols != research.policy.query.symbols
                or query.end + timedelta(days=1) != previous_start
            ):
                raise ValueError(
                    "each planned chunk must extend the same stock backward without gaps"
                )
            previous_start = query.start
        frozen = {
            "at": datetime.now(UTC).isoformat(),
            "plan": plan.model_dump(mode="json"),
            "plan_sha256": plan_hash,
            "definition": prior["definition"],
            "statistical_protocol": research.statistics.model_dump(mode="json"),
            "statistical_protocol_sha256": protocol_hash,
            "data_policy_sha256": policy_hash,
            "previous_active_sample_id": active["id"] if active else None,
            "budget_before": {k: v for k, v in snapshot.items() if k != "calls"},
            "covered_model_call_ids_sha256": hashlib.sha256(
                canonical(sorted(c["id"] for c in snapshot["calls"]))
            ).hexdigest(),
            "selection_rule": "First planned stage meeting quality and predeclared "
            "case/bucket/block targets; no effect, interval or significance "
            "inspection for stopping.",
            "analysis_status": "Existing exploratory candidate frozen before new downloads; "
            "not preregistered or held-out confirmatory research.",
            "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"]).decode().strip(),
            "dirty_diff_sha256": hashlib.sha256(
                subprocess.check_output(["git", "diff", "--binary", "HEAD"])
            ).hexdigest(),
            "source_sha256": {
                name: hashlib.sha256(
                    (args.config.resolve().parent.parent / name).read_bytes()
                ).hexdigest()
                for name in (
                    "scripts/expand_research_sample.py",
                    "src/qfh/research_samples.py",
                    "src/qfh/data_gateway.py",
                    "src/qfh/baostock_source.py",
                )
            },
        }
        write_new(frozen_path, frozen)
        print(
            json.dumps(
                {
                    "status": "plan_frozen",
                    "plan_sha256": plan_hash,
                    "maximum_new_queries": len(plan.steps),
                    "model_requests": 0,
                }
            )
        )
        return

    frozen = json.loads(frozen_path.read_text())
    if (
        frozen["plan_sha256"] != plan_hash
        or frozen["statistical_protocol_sha256"] != protocol_hash
        or frozen["data_policy_sha256"] != policy_hash
    ):
        raise ValueError("plan, data policy or statistical protocol changed after freezing")
    spec = ContrastSpec.model_validate(frozen["definition"])
    stages = [json.loads(p.read_text()) for p in sorted(folder.glob("stage-*.json"))]
    if any(s["status"] != "success" for s in stages):
        raise ValueError("failed or uncertain stage requires inspection; no automatic replay")
    parent_ids = [plan.base_evidence_id] + [s["new_source_evidence_id"] for s in stages]
    ready = bool(stages and stages[-1]["quality"]["support_ready"])

    if args.activate:
        if not ready:
            raise ValueError("sample does not yet meet the frozen support targets")
        record = research.store.get(stages[-1]["composed_evidence_id"])
        amendment = SampleActivation(
            id=plan.id,
            authority=plan.authority,
            expected_previous_id=frozen["previous_active_sample_id"],
            evidence_id=stages[-1]["composed_evidence_id"],
            query=record["query"],
            plan_id=plan.id,
            plan_sha256=plan_hash,
            fixed_definition=spec,
            statistical_protocol_sha256=protocol_hash,
            preview_rows=plan.preview_rows,
            alignment_preview_rows=plan.alignment_preview_rows,
        )
        activated = research.activate_sample(amendment)
        if not (folder / "ACTIVATED.json").exists():
            write_new(folder / "ACTIVATED.json", activated)
        print(
            json.dumps(
                {
                    "status": "sample_activated",
                    "evidence_id": amendment.evidence_id,
                    "query": record["query"],
                    "quality": stages[-1]["quality"],
                    "model_requests": 0,
                }
            )
        )
        return

    if ready:
        raise ValueError(
            "support target reached; activate this frozen sample, do not expand further"
        )
    index = len(stages)
    if index >= len(plan.steps):
        raise ValueError("planned expansion exhausted without sufficient support")
    query = plan.steps[index]
    attempt = folder / f"attempt-{index + 1:02}.json"
    write_new(
        attempt,
        {
            "at": datetime.now(UTC).isoformat(),
            "query": query.model_dump(mode="json"),
            "plan_sha256": plan_hash,
            "data_policy_sha256": policy_hash,
            "model_requests": 0,
        },
    )
    started = time.monotonic()
    process = psutil.Process()
    cpu_before = process.cpu_times()
    rss_before = process.memory_info().rss
    try:
        result = dispatch(
            {
                "provider": "baostock",
                "kind": "bars",
                "run_id": plan.id,
                "query": query.model_dump(mode="json"),
                "credentials": {},
            },
            data_policy,
            research.data_root,
        )
        parent_ids.append(result["evidence_id"])
        composed_id, composed = compose_sample(
            research.store, parent_ids, data_policy.research_cutoff, plan.id, plan_hash, index + 1
        )
        quality = support_profile(composed["content"], spec, research.statistics, plan)
        if quality["weekend_observations"] or quality["large_unadjusted_return_warnings"]:
            raise ValueError("quality warning requires inspection before more data or inference")
        record = {
            "status": "success",
            "stage": index + 1,
            "query": query.model_dump(mode="json"),
            "new_source_evidence_id": result["evidence_id"],
            "cache_reused": result["cache_reused"],
            "new_source_rows": result["row_count"],
            "composed_evidence_id": composed_id,
            "source_evidence_ids": parent_ids,
            "quality": quality,
        }
    except Exception as exc:
        record = {
            "status": "failed_or_unknown",
            "stage": index + 1,
            "error": str(exc),
            "action": "stop; inspect retained data request and wire before any retry",
        }
    cpu_after = process.cpu_times()
    record.update(
        finished_at=datetime.now(UTC).isoformat(),
        elapsed_seconds=time.monotonic() - started,
        process_cpu_seconds=(cpu_after.user + cpu_after.system)
        - (cpu_before.user + cpu_before.system),
        process_rss_before_bytes=rss_before,
        process_rss_after_bytes=process.memory_info().rss,
        resource_scope="This preparation process only; before/after RSS is not a sampled peak.",
        model_requests=0,
        plan_sha256=plan_hash,
    )
    write_new(folder / f"stage-{index + 1:02}.json", record)
    print(json.dumps(record))
    if record["status"] != "success":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
