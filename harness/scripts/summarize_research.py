"""Export verifiable trial accounting; keep model transcripts and market rows private."""

import argparse
import hashlib
import json
import shutil
import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import yaml

from qfh.budget import admission_open
from qfh.coding_plan import CodingPolicy, coding_detail
from qfh.evidence import canonical
from qfh.research import Research
from qfh.trial_metrics import model_metrics, resource_metrics, role_windows, work_metrics


def collect_resources(servers, started, finished):
    samples, manifests = [], []
    for server in servers.iterdir():
        manifest = json.loads((server / "manifest.json").read_text())
        file = server / "resources.jsonl"
        selected = []
        if file.exists():
            for line in file.read_text().splitlines():
                try:
                    sample = json.loads(line)
                except json.JSONDecodeError:
                    continue  # A still-running sampler may have an unfinished final line.
                if started <= datetime.fromisoformat(sample["at"]) <= finished:
                    selected.append(sample)
        stopped_file = server / "stopped.json"
        stopped = (
            datetime.fromisoformat(json.loads(stopped_file.read_text())["at"])
            if stopped_file.exists()
            else datetime.now(UTC)
        )
        overlaps = datetime.fromisoformat(manifest["started_at"]) <= finished and stopped >= started
        # A killed server has no stopped.json. Its open manifest is not evidence
        # that it served a later trial; require samples inside this trial's window.
        if overlaps and selected:
            samples.extend(selected)
            manifests.append({"path": str(server / "manifest.json"), "manifest": manifest})
    samples.sort(key=lambda sample: sample["at"])
    return samples, manifests


def summarize(config, private, trial_id, pricing_path=None, balance_paths=()):
    research = Research(config, private)
    route = research.trial_model_route(trial_id)
    coding = CodingPolicy.model_validate(route) if route else None
    pricing_path = pricing_path or config.parent / "deepseek-flash-pricing-2026-11-12.yaml"
    pricing = route if coding else yaml.safe_load(pricing_path.read_text())
    if any(r["model"] != pricing["model"] for r in research.resolved_roles(route).values()):
        raise ValueError("reporting tariff does not match the configured model")
    budget = research.ledger.snapshot()
    synthetic = (private / "OFFLINE_ONLY").exists()
    calls = [c for c in budget["calls"] if c["step"].startswith(f"research:{trial_id}:")]
    with research.db() as db:
        trial = dict(db.execute("SELECT * FROM trials WHERE id=?", (trial_id,)).fetchone())
        members = [
            dict(r) for r in db.execute("SELECT * FROM members WHERE trial_id=?", (trial_id,))
        ]
        ids = {m["session_id"] for m in members}
        events = [
            {**dict(r), "body": json.loads(r["body"])}
            for r in db.execute("SELECT * FROM events")
            if r["principal"] in ids
        ]
    draft = json.loads(trial["draft"]) if trial["draft"] else None
    usage = model_metrics(calls, pricing, synthetic=synthetic)
    started = datetime.fromisoformat(trial["at"])
    finished = max(
        [started]
        + [datetime.fromisoformat(c["finished"]) for c in calls if c["finished"]]
        + [datetime.fromisoformat(e["at"]) for e in events]
    )
    samples, manifests = collect_resources(private / "research/servers", started, finished)
    windows = role_windows(members, events, started, finished)
    by_role = {}
    for member in members:
        own = [c for c in calls if c["step"] == f"research:{trial_id}:{member['role']}"]
        by_role[member["role"]] = {
            "session_id": member["session_id"],
            "report_state": member["state"]
            if member["role"] != "supervisor"
            else "draft_recorded"
            if draft is not None
            else "no_draft",
            "admission_state": member["state"],
            "provider_requests": len(own),
            "conservative_cny": sum(c["charged"] or 0 for c in own) / 1_000_000,
            **model_metrics(own, pricing, synthetic=synthetic),
            "work": work_metrics(member, events, draft),
            "shared_resources_during_activity": resource_metrics(samples, windows[member["role"]]),
        }
    with research.data.db() as db:
        data_calls = []  # DataGuard connections do not use Row factories.
        data_history = []
        columns = [r[1] for r in db.execute("PRAGMA table_info(requests)")]
        for row in db.execute("SELECT * FROM requests ORDER BY id"):
            call = dict(zip(columns, row, strict=True))
            data_history.append(call)
            if started <= datetime.fromisoformat(call["at"]) <= finished:
                data_calls.append(call)
    data_results = [
        e["body"]["result"]
        for e in events
        if e["kind"] == "tool_result"
        and e["body"]["op"] == "data"
        and e["body"]["args"].get("kind") == "bars"
    ]
    failures = [e for e in events if e["kind"] == "tool_failure"]
    evidence_ids = sorted({r["evidence_id"] for r in data_results})
    sample = research.trial_sample(trial_id)
    source_evidence_ids = sorted(
        set(evidence_ids)
        | {
            source
            for ident in evidence_ids
            for source in research.store.get(ident).get("source_evidence_ids", [])
        }
    )
    data_wire_keys = {
        c["cache_key"]
        for c in data_history
        if c["provider"] == "baostock"
        and c["kind"] == "bars"
        and (c in data_calls or c["result_id"] in source_evidence_ids)
    }
    mode_verified = bool(manifests) and all(
        m["manifest"]["mode"] == ("synthetic_model_and_data" if synthetic else "live")
        for m in manifests
    )
    checks = {
        "execution_mode_matches_manifests": mode_verified,
        "exactly_three_roles": set(by_role) == {"supervisor", "researcher", "reviewer"},
        "both_workers_valid": all(
            m["state"] == "completed" for m in members if m["role"] != "supervisor"
        )
        and len(members) == 3,
        "draft_recorded": draft is not None,
        "all_model_usage_settled": bool(calls) and all(c["state"] == "settled" for c in calls),
        "both_workers_fetched_evidence": all(
            any(
                e["principal"] == m["session_id"]
                and e["kind"] == "tool_result"
                and e["body"]["op"] == "data"
                for e in events
            )
            for m in members
            if m["role"] != "supervisor"
        )
        and len(members) == 3,
        "no_tool_failures": not failures,
        "source_baostock_only": trial["provider"] == "baostock"
        and all(c["provider"] == "baostock" for c in data_calls),
        "within_original_budget": budget["remaining_unreserved_micro_cny"] >= 0,
        "authorized_dispatch_windows": synthetic
        or all(
            (coding.admission_open if coding else admission_open)(
                datetime.fromisoformat(c["started"])
            )
            for c in calls
        ),
        "configured_route_matches_ledger": all(
            coding_detail(c).get("route_id") == coding.id if coding else not coding_detail(c)
            for c in calls
        ),
        "resource_samples_required_for_live": synthetic or bool(samples),
        "raw_data_transport_required_for_live": synthetic
        or (
            bool(evidence_ids)
            and bool(data_wire_keys)
            and all(
                (private / "data/baostock-wire" / f"{key}.{suffix}").exists()
                for key in data_wire_keys
                for suffix in ("json", "bin")
            )
        ),
    }
    summary = {
        "trial_id": trial_id,
        "mode": (
            "synthetic_model_and_data"
            if synthetic
            else "live_GLM_Coding_Plan_with_BaoStock"
            if coding
            else "live_DeepSeek_with_BaoStock"
        )
        if mode_verified
        else "unverified_execution_mode",
        "status": "pass" if all(checks.values()) else "partial_or_failed",
        "checks": checks,
        "started_utc": started.isoformat(),
        "finished_utc": finished.isoformat(),
        "wall_seconds": (finished - started).total_seconds(),
        "roles": by_role,
        "model_usage": {
            "provider": coding.provider if coding else "deepseek",
            "configured_model": coding.model
            if coding
            else research.policy.roles["supervisor"].model,
            **usage,
            "pricing": pricing,
            "pricing_sha256": hashlib.sha256(
                canonical(pricing) if coding else pricing_path.read_bytes()
            ).hexdigest(),
        },
        "accounting": {
            "trial_conservative_cny": sum(c["charged"] or 0 for c in calls) / 1_000_000,
            "campaign": {k: v for k, v in budget.items() if k != "calls"},
            "basis": "Owner-reported official baseline + subsequent conservative charges. "
            "Original ceiling unchanged."
            if budget["billing_baseline"]
            else "Historical conservative carry plus subsequent conservative charges."
            + (" Synthetic accounting only; no actual spend." if synthetic else ""),
        },
        "pilot_allowance_at_export": research.allowance(),
        "data": {
            "query": sample["query"] if sample else research.policy.query.model_dump(mode="json"),
            "sample": sample,
            "requests_during_trial": data_calls,
            "tool_fetches": len(data_results),
            "exact_cache_hits": sum(r.get("cache_reused") is True for r in data_results),
            "evidence_ids": evidence_ids,
            "source_evidence_ids": source_evidence_ids,
        },
        "resources": resource_metrics(samples, [(started, finished)]),
        "draft": None
        if draft is None
        else {
            k: draft[k]
            for k in (
                "title",
                "formula",
                "signal_time",
                "execution_time",
                "evidence_ids",
                "decisions",
                "limitations",
                "next_steps",
                "measured_facts",
                "proposal_phase",
                "specification",
                "statistical_outcome",
                "scientific_acceptance",
                "selected_specification_id",
            )
            if k in draft
        },
        "tool_failures": [
            {
                "seq": e["seq"],
                "principal": e["principal"],
                "op": e["body"]["op"],
                "reason": e["body"]["reason"],
            }
            for e in failures
        ],
        "manifests": manifests,
        "limits": [
            "No independent evaluation, publication or gate passed.",
            "Single stock and short historical sample; no alpha claim.",
            "DSH session footer counts the selected session; this report includes all three roles.",
        ],
    }
    paths = [research.path, research.ledger.path, research.data.path]
    if balance_paths:
        observations = [
            [json.loads(line) for line in path.read_text().splitlines()] for path in balance_paths
        ]
        result = {
            "read_requests": len(observations),
            "statuses": [rows[-1]["status"] for rows in observations],
            "inference_requests": 0,
            "account_balance_decrease_by_currency": None,
            "scope": "Account-level observation across the trial, not an invoice or "
            "per-agent charge. Other account activity, credits or delayed billing can affect it. "
            "Absolute balances remain in private snapshots; the ledger is unchanged.",
        }
        if len(observations) == 2 and result["statuses"] == ["success", "success"]:
            balances = [
                {
                    row["currency"]: Decimal(row["total_balance"])
                    for row in rows[-1]["account"]["balance_infos"]
                }
                for rows in observations
            ]
            result["account_balance_decrease_by_currency"] = {
                currency: str(balances[0][currency] - balances[1][currency])
                for currency in sorted(balances[0].keys() & balances[1].keys())
            }
        summary["accounting"]["balance_observations"] = result
        paths += list(balance_paths)
    paths += [
        p for c in calls for p in (private / "campaign/wire" / c["id"]).glob("*") if p.is_file()
    ]
    paths += [private / "data/evidence" / f"{ident}.json" for ident in source_evidence_ids]
    calculation_ids = {
        e["body"]["result"]["calculation_artifact_id"]
        for e in events
        if e["kind"] == "tool_result" and e["body"]["result"].get("calculation_artifact_id")
    }
    paths += [private / "research/calculations" / f"{ident}.json" for ident in calculation_ids]
    if sample:
        preparation = private / "research/sample-expansions" / sample["plan_id"]
        paths += list(preparation.glob("*.json"))
        summary["data"]["preparation"] = [
            json.loads(p.read_text()) for p in sorted(preparation.glob("stage-*.json"))
        ]
        summary["calculation_artifact_ids"] = sorted(calculation_ids)
    paths += [
        path
        for key in data_wire_keys
        for suffix in ("json", "bin")
        if (path := private / "data/baostock-wire" / f"{key}.{suffix}").exists()
    ]
    for m in manifests:
        paths += list(Path(m["path"]).parent.glob("*.json*"))
    for home_name in ("research-ui-home", "ui-home"):
        for p in (private / home_name / "sessions").rglob("session*.jsonl*"):
            if p.parent.name in ids:
                paths.append(p)
    frozen = (
        private
        / "research/exports"
        / (trial_id + "-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ"))
    )
    frozen.mkdir(parents=True, exist_ok=False)
    raw_manifest = []
    for source in sorted(set(paths)):
        target = frozen / source.relative_to(private)
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.suffix == ".sqlite3":
            with (
                sqlite3.connect(f"file:{source}?mode=ro", uri=True) as original,
                sqlite3.connect(target) as snapshot,
            ):
                original.backup(snapshot)
        else:
            shutil.copyfile(source, target)
        raw_manifest.append(
            {
                "source_path": str(source),
                "snapshot_path": str(target),
                "size_bytes": target.stat().st_size,
                "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            }
        )
    summary["private_snapshot"] = str(frozen)
    summary["snapshot_at"] = datetime.now(UTC).isoformat()
    summary["resources"]["frozen_evidence_bytes"] = sum(r["size_bytes"] for r in raw_manifest)
    summary["resources"]["trial_wire_bytes"] = sum(
        r["size_bytes"] for r in raw_manifest if "/campaign/wire/" in r["source_path"]
    )
    summary["resources"]["native_session_archive_bytes"] = sum(
        r["size_bytes"] for r in raw_manifest if "/sessions/" in r["source_path"]
    )
    summary["resources"]["disk_footprint_scope"] = (
        "File lengths, not allocated filesystem blocks. Frozen evidence includes shared ledger "
        "snapshots and overlapping server logs; wire and session archives are trial-specific."
    )
    for role, values in by_role.items():
        call_ids = {c["id"] for c in calls if c["step"] == f"research:{trial_id}:{role}"}
        values["wire_bytes"] = sum(
            r["size_bytes"] for r in raw_manifest if Path(r["source_path"]).parent.name in call_ids
        )
        values["native_session_archive_bytes"] = sum(
            r["size_bytes"]
            for r in raw_manifest
            if "/sessions/" in r["source_path"]
            and Path(r["source_path"]).parent.name == values["session_id"]
        )
    return summary, raw_manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "configs/research-trial.yaml",
    )
    parser.add_argument("--private", type=Path, required=True)
    parser.add_argument("--trial-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pricing", type=Path)
    parser.add_argument("--balance-before", type=Path)
    parser.add_argument("--balance-after", type=Path)
    args = parser.parse_args()
    if bool(args.balance_before) != bool(args.balance_after):
        parser.error("supply both balance observations, including failed attempts, or neither")
    summary, manifest = summarize(
        args.config.resolve(),
        args.private.resolve(),
        args.trial_id,
        args.pricing.resolve() if args.pricing else None,
        (args.balance_before.resolve(), args.balance_after.resolve())
        if args.balance_before
        else (),
    )
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "RESULTS.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n"
    )
    (args.output / "RAW_MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(
        json.dumps(
            {
                "status": summary["status"],
                "requests": summary["model_usage"]["requests"],
                "trial_cny": summary["accounting"]["trial_conservative_cny"],
            }
        )
    )


if __name__ == "__main__":
    main()
