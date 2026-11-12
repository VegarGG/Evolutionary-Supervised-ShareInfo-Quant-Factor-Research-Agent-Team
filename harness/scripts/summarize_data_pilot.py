"""Publish bounded data-test measurements and hashes, excluding vendor row dumps."""

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path


def resource_summary(path):
    samples = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    return {
        "sample_count": len(samples),
        "peak_process_tree_rss_bytes": max(
            (s["process_tree_rss_bytes"] for s in samples), default=None
        ),
        "peak_host_cpu_percent": max(
            (s["host_cpu_percent"] for s in samples if s.get("host_cpu_percent") is not None),
            default=None,
        ),
        "minimum_disk_free_bytes": min(
            (s["disk_free_bytes"] for s in samples if s.get("disk_free_bytes") is not None),
            default=None,
        ),
        "measurement_errors": sorted({e for s in samples for e in s.get("measurement_errors", [])}),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--private", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    private, out = args.private.resolve(), args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    comparisons, attempts, artifacts = [], [], []
    source = private / "free-source-comparison"
    for path in sorted(source.glob("*/result.json")):
        raw = json.loads(path.read_text())
        rows = raw.pop("rows", [])
        comparisons.append(
            {
                **raw,
                "row_count": len(rows),
                "resources": resource_summary(path.parent / "resources.jsonl"),
            }
        )
    bao = json.loads((source / "baostock/result.json").read_text())["rows"]
    em = json.loads((source / "akshare-eastmoney/result.json").read_text())["rows"]
    matching = [(r[0], float(r[2])) for r in bao] == [
        (row.split(",")[0], float(row.split(",")[2])) for row in em
    ]
    for path in sorted((private / "data/pilots").glob("*/result.json")):
        raw = json.loads(path.read_text())
        result = raw.pop("result", None)
        if result:
            result.pop("content", None)
        attempts.append(
            {
                **raw,
                "result_metadata": result,
                "resources": resource_summary(path.parent / "resources.jsonl"),
            }
        )
    with sqlite3.connect(f"file:{private / 'data/data-usage.sqlite3'}?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        usage = [
            dict(row)
            for row in db.execute(
                "SELECT provider,kind,outcome,COUNT(*) AS count,"
                "SUM(estimated_cells) AS estimated_cells "
                "FROM requests GROUP BY provider,kind,outcome ORDER BY provider,kind,outcome"
            )
        ]
    for folder in [
        source,
        private / "data/pilots",
        private / "data/baostock-wire",
        private / "data/evidence",
        private / "ui-qa-baostock",
    ]:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                artifacts.append(
                    {
                        "path": str(path.relative_to(private)),
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        "bytes": path.stat().st_size,
                    }
                )
    summary = {
        "status": "bounded_baostock_pilot_complete",
        "default_provider": "baostock",
        "paid_data_requests": 0,
        "paid_model_requests": 0,
        "comparison_closes_match": matching,
        "comparison_probes": comparisons,
        "guarded_attempts": attempts,
        "persistent_usage": usage,
        "native_tool_check": json.loads((private / "tool-smoke-baostock/RESULT.json").read_text()),
        "ui_check": json.loads((private / "ui-qa-baostock/RESULT.json").read_text()),
    }
    (out / "RESULTS.json").write_text(json.dumps(summary, indent=2) + "\n")
    (out / "RAW_MANIFEST.json").write_text(json.dumps(artifacts, indent=2) + "\n")
    print(
        json.dumps(
            {
                "status": summary["status"],
                "comparison_closes_match": matching,
                "attempts": len(attempts),
                "artifacts": len(artifacts),
            }
        )
    )


if __name__ == "__main__":
    main()
