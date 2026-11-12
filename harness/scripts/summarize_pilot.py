"""Export auditable diagnostic measurements without keys or DSH home files."""

import argparse
import hashlib
import json
import platform
import sqlite3
import statistics
from datetime import datetime
from pathlib import Path

import psutil


def rolling_peak(calls, field, tokens=False):
    entries = [(datetime.fromisoformat(c[field]), c) for c in calls if c[field]]
    entries.sort(key=lambda item: item[0])

    def value(call):
        return sum(call["usage"].values()) if tokens else 1

    return max(
        (
            sum(value(c) for at, c in entries if 0 <= (edge - at).total_seconds() < 60)
            for edge, _ in entries
        ),
        default=0,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--private", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root, out = args.private.resolve(), args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(root / "spend.sqlite3") as db:
        db.row_factory = sqlite3.Row
        policy = json.loads(db.execute("SELECT body FROM config WHERE id=1").fetchone()[0])
        calls = [dict(row) for row in db.execute("SELECT * FROM calls ORDER BY started")]
    for call in calls:
        call["usage"] = json.loads(call["usage"]) if call["usage"] else None
    rows, artifacts = [], []
    for run in sorted((root / "runs").iterdir()):
        if not (run / "result.json").exists():
            continue
        result = json.loads((run / "result.json").read_text())
        manifest = json.loads((run / "manifest.json").read_text())
        group = [c for c in calls if c["step"].startswith(run.name + ":")]
        usage = {
            k: sum(c["usage"][k] for c in group if c["usage"])
            for k in ("input_uncached", "input_cached", "input_cache_write", "output")
        }
        input_total = usage["input_uncached"] + usage["input_cached"] + usage["input_cache_write"]
        samples = [json.loads(line) for line in (run / "resources.jsonl").read_text().splitlines()]
        start = min(datetime.fromisoformat(c["started"]) for c in group)
        end = max(datetime.fromisoformat(c["finished"]) for c in group)
        elapsed = (end - start).total_seconds()
        final = result["final"]
        steps = [json.loads(path.read_text()) for path in sorted(run.glob("step-[0-9].json"))]
        row = {
            "run_id": run.name,
            "variant": manifest["variant"],
            "synthetic_evidence": True,
            "started_utc": start.isoformat(),
            "finished_utc": end.isoformat(),
            "provider_span_seconds": elapsed,
            "actual_requests": len(group),
            "usage": usage,
            "cache_hit_rate": usage["input_cached"] / input_total if input_total else None,
            "conservative_cny": sum(c["charged"] or 0 for c in group) / 1e6,
            "offpeak_tariff_estimate_cny": (
                usage["input_uncached"]
                + usage["input_cache_write"]
                + usage["input_cached"] * 0.02
                + usage["output"] * 4
            )
            / 1e6,
            "span_normalized_rpm": len(group) * 60 / elapsed,
            "span_normalized_tpm": sum(usage.values()) * 60 / elapsed,
            "peak_trailing_60s_dispatch_rpm": rolling_peak(group, "started"),
            "peak_trailing_60s_dispatch_attributed_tpm": rolling_peak(group, "started", True),
            "peak_trailing_60s_completion_attributed_tpm": rolling_peak(group, "finished", True),
            "resource_samples": len(samples),
            "sampled_process_tree_peak_rss_bytes": max(
                s["process_tree_rss_bytes"] for s in samples
            ),
            "observed_process_tree_cpu_seconds": max(
                s["process_tree_cpu_seconds"] for s in samples
            ),
            "host_cpu_percent_median": statistics.median(s["host_cpu_percent"] for s in samples),
            "host_cpu_percent_max": max(s["host_cpu_percent"] for s in samples),
            "host_swap_used_peak_bytes": max(s["host_swap"]["used"] for s in samples),
            "disk_free_min_bytes": min(s["disk_free_bytes"] for s in samples),
            "known_answer_checks": {
                "signal_date": final["first_signal_date"] == "2024-04-30",
                "execution_date": final["first_execution_date"] == "2024-05-06",
                "unit_correct_ratio": abs(final["computed_ratio"] - 0.02) < 1e-12,
                "source_ids_covered": {"S1", "S2", "S3"}
                <= {source for claim in final["claims"] for source in claim["evidence_ids"]},
            },
            "manifest": manifest,
            "steps": steps,
        }
        rows.append(row)
        for p in sorted(run.iterdir()):
            if p.is_file():
                artifacts.append(
                    {
                        "path": str(p.relative_to(root)),
                        "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                        "bytes": p.stat().st_size,
                    }
                )
    for p in sorted((root / "wire").glob("*/*")):
        if p.is_file():
            artifacts.append(
                {
                    "path": str(p.relative_to(root)),
                    "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                    "bytes": p.stat().st_size,
                }
            )
    settled = sum(c["charged"] or 0 for c in calls)
    unresolved = sum(c["reserved"] for c in calls if c["charged"] is None)
    total_usage = {
        k: sum(c["usage"][k] for c in calls if c["usage"])
        for k in ("input_uncached", "input_cached", "input_cache_write", "output")
    }
    input_total = sum(total_usage[k] for k in total_usage if k != "output")
    report = {
        "status": "bounded_known_answer_pilot_complete",
        "run_count": len(rows),
        "actual_requests": len(calls),
        "usage": total_usage,
        "cache_hit_rate": total_usage["input_cached"] / input_total,
        "new_conservative_cny": settled / 1e6,
        "carry_conservative_cny": policy["carry_micro_cny"] / 1e6,
        "cumulative_conservative_cny": (policy["carry_micro_cny"] + settled) / 1e6,
        "unresolved_reserved_cny": unresolved / 1e6,
        "remaining_unreserved_cny": (
            policy["total_micro_cny"] - policy["carry_micro_cny"] - settled - unresolved
        )
        / 1e6,
        "invoice_verified": False,
        "peak_trailing_60s_dispatch_rpm": rolling_peak(calls, "started"),
        "peak_trailing_60s_dispatch_attributed_tpm": rolling_peak(calls, "started", True),
        "peak_trailing_60s_completion_attributed_tpm": rolling_peak(calls, "finished", True),
        "machine": {
            "system": platform.system(),
            "release": platform.release(),
            "architecture": platform.machine(),
            "logical_cpus": psutil.cpu_count(),
            "physical_cpus": psutil.cpu_count(logical=False),
            "ram_bytes": psutil.virtual_memory().total,
        },
        "runs": rows,
        "limitations": [
            "One easy synthetic case; no collaboration advantage, market alpha or "
            "production acceptance established.",
            "All treatments share evidence and requested aggregate output cap; single has "
            "one call, others three. Actual compute differs.",
            "Sequential treatments are not randomized; later requests may benefit from warm "
            "shared provider cache.",
            "Two-second process-tree RSS is summed RSS, not unique physical memory; short "
            "peaks may be missed.",
            "Host CPU/swap include unrelated activity; process CPU is surviving-process "
            "cumulative CPU, not a cgroup total.",
            "Dispatch/completion TPM attributes each request's entire token count to one "
            "timestamp; it is not token emission timing.",
            "Initial pair implementation hashes were recorded in INITIAL_SOURCE_RECORD.json "
            "after the single run, not in original manifests.",
            "DSH runtime-context messages can include the worker working-directory path "
            "even with persona runtime context disabled; no secret values were sent.",
            "Estimated offpeak cost is not a provider invoice. The cumulative ledger "
            "conservatively uses peak miss prices.",
        ],
    }
    (out / "RESULTS.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    (out / "RAW_MANIFEST.json").write_text(json.dumps(artifacts, indent=2) + "\n")
    print(
        json.dumps({k: v for k, v in report.items() if k not in ("runs", "limitations")}, indent=2)
    )


if __name__ == "__main__":
    main()
