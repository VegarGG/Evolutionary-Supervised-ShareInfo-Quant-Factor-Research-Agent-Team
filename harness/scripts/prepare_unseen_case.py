"""Freeze the open-case protocol, fetch one BaoStock chunk, or prepare paired packages."""

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import yaml

from qfh.case_factor import FactorSpec, definition, inspect_factor, panel_quality, price_profile
from qfh.case_research import CaseEpisode, CasePolicy
from qfh.coding_plan import CodingLedger, CodingPolicy
from qfh.data_gateway import DataPolicy, dispatch
from qfh.evidence import EvidenceStore, Query
from qfh.research import Research
from qfh.shared_state import atomic_new, digest


def prepare(config, private, action, index=None):
    root = Path(__file__).resolve().parents[1]
    study = yaml.safe_load(config.read_text())
    folder = private / "case-studies" / study["id"]
    folder.mkdir(parents=True, exist_ok=True)
    data_config = root / "configs" / study.get("data_config", "data-unseen-2026-11-16.yaml")
    policy = DataPolicy.model_validate(yaml.safe_load(data_config.read_text()))
    research = Research(root / "configs/research-trial.yaml", private)
    route = CodingPolicy.model_validate(
        yaml.safe_load(
            (
                root / "configs" / study.get("route_config", "glm-coding-unseen-2026-11-16.yaml")
            ).read_text()
        )
    )
    queries = [Query(symbols=[s], **r) for s in study["symbols"] for r in study["ranges"]]
    baseline = FactorSpec.model_validate(study["initial_spec"])
    if action == "initialize":
        before = research.ledger.snapshot()
        for call in before["calls"]:
            if call["state"] == "unknown":
                CodingLedger(research.ledger, route).verify_reserved_timeout(call)
            elif call["state"] not in ("settled", "rejected_reserved"):
                raise ValueError("unsettled usage requires inspection")
        with research.data.db() as db:
            used = db.execute(
                "SELECT provider,kind,COUNT(*),SUM(estimated_cells) FROM requests "
                "GROUP BY provider,kind"
            ).fetchall()
        atomic_new(
            folder / "FROZEN_PLAN.json",
            {
                "at": datetime.now(UTC).isoformat(),
                "study": study,
                "study_sha256": digest(study),
                "data_policy": policy.model_dump(mode="json"),
                "data_policy_sha256": digest(policy.model_dump(mode="json")),
                "route": route.model_dump(mode="json"),
                "queries": [q.model_dump(mode="json") for q in queries],
                "data_usage_before": used,
                "budget_before": {k: v for k, v in before.items() if k != "calls"},
                "covered_call_ids_sha256": digest(sorted(c["id"] for c in before["calls"])),
                "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"]).decode().strip(),
                "protocol_file_sha256": hashlib.sha256(
                    (
                        root.parent
                        / "docs/harness"
                        / study.get("protocol_file", "UNSEEN_CASE_2026-11-16.md")
                    ).read_bytes()
                ).hexdigest(),
                "protocol_text": (
                    root.parent
                    / "docs/harness"
                    / study.get("protocol_file", "UNSEEN_CASE_2026-11-16.md")
                ).read_text(),
                "source_sha256": {
                    str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in [
                        Path(__file__),
                        root / "src/qfh/case_factor.py",
                        root / "src/qfh/baostock_source.py",
                        root / "src/qfh/data_gateway.py",
                    ]
                },
            },
        )
        return {"status": "frozen_before_data", "queries": len(queries), "model_requests": 0}
    frozen = json.loads((folder / "FROZEN_PLAN.json").read_bytes())
    if frozen["study_sha256"] != digest(study) or frozen["data_policy_sha256"] != digest(
        policy.model_dump(mode="json")
    ):
        raise ValueError("frozen protocol changed")
    if action == "fetch":
        if index is None or not 0 <= index < len(queries):
            raise ValueError("choose one planned query index")
        dest = folder / f"fetch-{index:02}.json"
        if dest.exists():
            raise ValueError("fetch attempt already recorded; no replay")
        for i in range(index):
            prior = json.loads((folder / f"fetch-{i:02}.json").read_bytes())
            if prior["status"] != "success":
                raise ValueError("prior data stage did not pass")
        started = datetime.now(UTC).isoformat()
        try:
            result = dispatch(
                {
                    "provider": "baostock",
                    "kind": "bars",
                    "run_id": study["id"],
                    "query": queries[index].model_dump(mode="json"),
                    "credentials": {},
                },
                policy,
                private / "data",
            )
            evidence = EvidenceStore(private / "data/evidence").get(result["evidence_id"])
            quality = panel_quality(
                evidence["content"],
                queries[index].symbols,
                queries[index].start.isoformat(),
                queries[index].end.isoformat(),
            )
            if not quality["rows"]:
                raise ValueError("empty planned data chunk")
            record = {
                "status": "success",
                "started": started,
                "finished": datetime.now(UTC).isoformat(),
                "query": queries[index].model_dump(mode="json"),
                "result": result,
                "quality": quality,
            }
        except Exception as error:
            record = {
                "status": "failed",
                "started": started,
                "finished": datetime.now(UTC).isoformat(),
                "query": queries[index].model_dump(mode="json"),
                "error_type": type(error).__name__,
                "error": str(error),
            }
            atomic_new(dest, record)
            raise
        atomic_new(dest, record)
        return {
            "status": record["status"],
            "index": index,
            "rows": quality["rows"],
            "cache_reused": result["cache_reused"],
            "model_requests": 0,
        }
    chunks = [json.loads((folder / f"fetch-{i:02}.json").read_bytes()) for i in range(len(queries))]
    if any(c["status"] != "success" for c in chunks):
        raise ValueError("not all planned data chunks succeeded")
    evidence = [
        EvidenceStore(private / "data/evidence").get(c["result"]["evidence_id"]) for c in chunks
    ]
    rows = sorted(
        [r for e in evidence for r in e["content"]], key=lambda r: (r["symbol"], r["date"])
    )
    start, end = study["ranges"][0]["start"], study["ranges"][-1]["end"]
    quality = panel_quality(rows, study["symbols"], start, end)
    if (
        min(quality["rows_by_symbol"].values()) < study["minimum_rows_per_symbol"]
        or quality["common_dates"] < study["minimum_common_dates"]
    ):
        raise ValueError("predeclared data-coverage minimum failed")
    sources = {
        "source_contract": "BaoStock historical unadjusted daily close, CNY/share. "
        "Current download, "
        "not a vintage archive. No volume, corporate actions, delisted universe, point-in-time "
        "membership, bid/ask, transaction costs, official calendar or forward return labels. "
        "Source retrieval occurs after this research window. These are exploratory development "
        "observations, never a holdout. Close-only jumps cannot identify corporate actions. "
        "All signal calculations use observations at/before t; execution no earlier than the "
        "next observed close. Sample SD divides by n-1. Normalization divides the trailing return "
        "by trailing daily-return SD times sqrt(lookback); this does not make an annual Sharpe "
        "ratio or remove systematic risk. Small convenience sample; no alpha or superiority proof.",
        "data_quality": json.dumps(quality, ensure_ascii=False, indent=2),
        "price_profile": json.dumps(price_profile(rows), ensure_ascii=False, indent=2),
        "initial_inspection": json.dumps(
            inspect_factor(rows, baseline, baseline)["summary"], ensure_ascii=False, indent=2
        ),
    }
    if study.get("research_contract"):
        sources["research_contract"] = study["research_contract"]
    for symbol in study["symbols"]:
        sources["prices_" + symbol.replace(".", "_")] = (
            "symbol,date,unadjusted_close_CNY_per_share\n"
            + "\n".join(
                f"{r['symbol']},{r['date']},{r['close']}" for r in rows if r["symbol"] == symbol
            )
        )
    bundle = {
        "study_sha256": digest(study),
        "rows": rows,
        "rows_sha256": digest(rows),
        "quality": quality,
        "sources": sources,
        "source_ids": [c["result"]["evidence_id"] for c in chunks],
        "retrieved_at": [e["retrieved_at"] for e in evidence],
    }
    atomic_new(folder / "BUNDLE.json", bundle)
    if frozen.get("route") != route.model_dump(mode="json"):
        raise ValueError("frozen model authority changed")
    research.activate_model_route(
        route,
        expected_previous_id=study.get("previous_route_id", "glm-coding-review-low-2026-11-13"),
    )
    packages = private / "case-packages"
    packages.mkdir(exist_ok=True)
    for n, variant in enumerate(study["planned_order"], 1):
        ident = f"{study.get('package_prefix', 'unseen')}-{variant}-{n:02}"
        episode = CaseEpisode(
            episode_id=ident,
            actors={
                "supervisor": "supervisor",
                **{
                    f"{role}-{i}": role
                    for i in range(1, study["max_tasks"] + 1)
                    for role in ("author", "reviewer")
                },
            },
            sources=sources,
            initial=definition(
                baseline,
                study["symbols"],
                "A short-horizon momentum hypothesis; usefulness and direction are unproven.",
            ),
            policy=study["board"],
            initial_spec=baseline,
            symbols=study["symbols"],
            rows=rows,
            data_snapshot_sha256=digest(rows),
            start=start,
            end=end,
        )
        package = CasePolicy(
            package_id=ident,
            study_id=study["id"],
            variant=variant,
            authority=study["authority"],
            question=study["question"],
            route_id=route.id,
            model=route.model,
            episode=episode,
            protocol=study.get("protocol", "legacy"),
            max_tool_bytes=study.get("max_tool_bytes", 24000),
            page_chars=study.get("page_chars", 2500),
            **{
                k: study[k]
                for k in (
                    "max_tasks",
                    "supervisor_requests",
                    "worker_requests",
                    "total_requests",
                    "max_output_tokens",
                    "max_inspections",
                )
            },
        )
        atomic_new(packages / f"{ident}.json", package.model_dump())
    return {
        "status": "paired_packages_frozen",
        "rows": len(rows),
        "data_snapshot_sha256": digest(rows),
        "order": study["planned_order"],
        "model_requests": 0,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--private", type=Path, required=True)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "configs/unseen-baostock-2026-11-16.yaml",
    )
    parser.add_argument("action", choices=["initialize", "fetch", "packages"])
    parser.add_argument("--index", type=int)
    args = parser.parse_args()
    print(
        json.dumps(prepare(args.config.resolve(), args.private.resolve(), args.action, args.index))
    )
