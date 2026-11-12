"""Export verifiable trial accounting; keep model transcripts and market rows private."""

import argparse
import hashlib
import json
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from qfh.budget import admission_open
from qfh.research import Research


def peak_rate(calls, field, weighted=False):
    points = sorted(
        (
            datetime.fromisoformat(c[field]).timestamp(),
            (sum(c["usage"].values()) if c["usage"] else 0) if weighted else 1,
        )
        for c in calls
        if c[field]
    )
    return max((sum(n for t, n in points if end - 60 < t <= end) for end, _ in points), default=0)


def summarize(config, private, trial_id):
    research = Research(config, private)
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
    total = {
        key: sum(c["usage"][key] for c in calls if c["usage"])
        for key in ("input_uncached", "input_cached", "input_cache_write", "output")
    }
    inputs = total["input_uncached"] + total["input_cached"] + total["input_cache_write"]
    started = datetime.fromisoformat(trial["at"])
    finished = max(
        (datetime.fromisoformat(c["finished"]) for c in calls if c["finished"]), default=started
    )
    samples, manifests = [], []
    for server in (private / "research/servers").iterdir():
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
        if overlaps:
            samples.extend(selected)
            manifests.append({"path": str(server / "manifest.json"), "manifest": manifest})
    samples.sort(key=lambda sample: sample["at"])
    peak_rss = max((s["process_tree_rss_bytes"] for s in samples), default=None)
    cpu_percent = [s["host_cpu_percent"] for s in samples if s.get("host_cpu_percent") is not None]
    swap = [s["host_swap"]["used"] for s in samples if s.get("host_swap")]
    memory = [s["host_memory"] for s in samples if s.get("host_memory")]
    free_disk = [s["disk_free_bytes"] for s in samples if s.get("disk_free_bytes") is not None]
    sampled_core_rates = []
    for first, second in zip(samples, samples[1:], strict=False):
        elapsed = (
            datetime.fromisoformat(second["at"]) - datetime.fromisoformat(first["at"])
        ).total_seconds()
        previous = first.get("process_cpu_seconds_by_pid", {})
        current = second.get("process_cpu_seconds_by_pid", {})
        if elapsed > 0 and previous and current:
            cpu = sum(max(0, seconds - previous.get(pid, 0)) for pid, seconds in current.items())
            sampled_core_rates.append(cpu / elapsed)
    by_role = {}
    for member in members:
        own = [c for c in calls if c["step"] == f"research:{trial_id}:{member['role']}"]
        by_role[member["role"]] = {
            "session_id": member["session_id"],
            "report_state": member["state"],
            "provider_requests": len(own),
            "conservative_cny": sum(c["charged"] or 0 for c in own) / 1_000_000,
            "tokens": {key: sum(c["usage"][key] for c in own if c["usage"]) for key in total},
        }
    with research.data.db() as db:
        data_calls = []  # DataGuard connections do not use Row factories.
        columns = [r[1] for r in db.execute("PRAGMA table_info(requests)")]
        for row in db.execute("SELECT * FROM requests ORDER BY id"):
            call = dict(zip(columns, row, strict=True))
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
    checks = {
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
        or all(admission_open(datetime.fromisoformat(c["started"])) for c in calls),
        "resource_samples_required_for_live": synthetic or bool(samples),
    }
    summary = {
        "trial_id": trial_id,
        "mode": "synthetic_model_and_data" if synthetic else "live_DeepSeek_with_BaoStock",
        "status": "pass" if all(checks.values()) else "partial_or_failed",
        "checks": checks,
        "started_utc": started.isoformat(),
        "finished_utc": finished.isoformat(),
        "wall_seconds": (finished - started).total_seconds(),
        "roles": by_role,
        "model_usage": {
            "provider": "deepseek",
            "configured_model": research.policy.roles["supervisor"].model,
            "requests": len(calls),
            "tokens": total,
            "total_tokens": sum(total.values()),
            "input_cache_hit_ratio": total["input_cached"] / inputs if inputs else None,
            "peak_rolling_60s_dispatch_rpm": peak_rate(calls, "started"),
            "peak_rolling_60s_completion_rpm": peak_rate(calls, "finished"),
            "peak_rolling_60s_dispatch_tpm": peak_rate(calls, "started", True),
            "peak_rolling_60s_completion_tpm": peak_rate(calls, "finished", True),
            "rate_definition": "Call totals attributed to dispatch/completion, "
            "not per-token arrival.",
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
        "data": {
            "query": research.policy.query.model_dump(mode="json"),
            "requests_during_trial": data_calls,
            "tool_fetches": len(data_results),
            "exact_cache_hits": sum(r.get("cache_reused") is True for r in data_results),
            "evidence_ids": sorted({r["evidence_id"] for r in data_results}),
        },
        "resources": {
            "samples": len(samples),
            "process_tree_peak_rss_bytes": peak_rss,
            "host_cpu_max_percent": max(cpu_percent, default=None),
            "process_tree_peak_sampled_cpu_cores": max(sampled_core_rates, default=None),
            "swap_peak_bytes": max(swap, default=None),
            "host_total_ram_bytes": memory[0]["total"] if memory else None,
            "host_available_ram_min_bytes": min((m["available"] for m in memory), default=None),
            "work_volume_min_free_bytes": min(free_disk, default=None),
            "measurement_errors": sorted(
                {e for s in samples for e in s.get("measurement_errors", [])}
            ),
            "scope": "Guard and DSH/data child process tree. Host readings include unrelated work. "
            "Short-lived children between samples may be missed. Not production sizing. "
            "A null metric means no measurement, never zero usage.",
        },
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
            )
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
    paths += [
        p for c in calls for p in (private / "campaign/wire" / c["id"]).glob("*") if p.is_file()
    ]
    paths += [
        private / "data/evidence" / f"{ident}.json" for ident in summary["data"]["evidence_ids"]
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
    args = parser.parse_args()
    summary, manifest = summarize(args.config.resolve(), args.private.resolve(), args.trial_id)
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
