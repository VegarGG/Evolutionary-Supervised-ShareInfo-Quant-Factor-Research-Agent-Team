"""Offline independent wire/accounting/provenance audit; no inference or data calls."""

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from qfh.experiment import write_new
from qfh.shared_state import Board


def audit(private, run_id):
    root = private / "module-runs" / run_id
    manifest = json.loads((root / "manifest.json").read_text())
    result = json.loads((root / "RESULT.json").read_text())
    hashes = json.loads((root / "ARTIFACT_HASHES.json").read_text())
    for record in hashes:
        path = (private / record["path"]).resolve()
        if not path.is_relative_to(private.resolve()):
            raise ValueError("artifact outside private evidence directory")
        raw = path.read_bytes()
        assert hashlib.sha256(raw).hexdigest() == record["sha256"]
        assert len(raw) == record["bytes"]
    db = sqlite3.connect(f"file:{private / 'campaign/spend.sqlite3'}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    calls = [
        dict(r)
        for r in db.execute(
            "SELECT * FROM calls WHERE step LIKE ? ORDER BY started", (f"module:{run_id}:%",)
        )
    ]
    assert len(calls) == result["model"]["requests"] and len(calls) <= 2
    rows = []
    for call in calls:
        folder = private / "campaign/wire" / call["id"]
        request = json.loads((folder / "request.json").read_text())
        http = json.loads((folder / "http.json").read_text())
        raw = (folder / "response.sse").read_text()
        assert http["status"] == 200 and http["endpoint"] == manifest["route"]["endpoint"]
        assert (
            http["request_sha256"]
            == hashlib.sha256((folder / "request.json").read_bytes()).hexdigest()
        )
        assert request["model"] == "glm-5.3-flash"
        assert request["max_tokens"] == manifest["config"]["max_output_tokens"]
        assert request["thinking"] == {"type": "enabled", "clear_thinking": False}
        assert not request.get("tools") and "data: [DONE]" in raw
        chunks = [json.loads(line[6:]) for line in raw.splitlines() if line.startswith("data: {")]
        assert {c["model"] for c in chunks if c.get("model")} == {"glm-5.3-flash"}
        usage = [c["usage"] for c in chunks if c.get("usage")][-1]
        cached = usage["prompt_tokens_details"]["cached_tokens"]
        tokens = {
            "input_cached": cached,
            "input_uncached": usage["prompt_tokens"] - cached,
            "input_cache_write": 0,
            "output": usage["completion_tokens"],
        }
        assert call["state"] == "settled" and tokens == json.loads(call["usage"])
        assert usage["total_tokens"] == sum(tokens.values())
        assert call["charged"] == usage["prompt_tokens"] * 2 + usage["completion_tokens"] * 8
        credits = json.loads(call["detail"])["quota_settled_upper_microcredits"]
        assert credits == usage["prompt_tokens"] * 230 + usage["completion_tokens"] * 800
        finished = [
            v["finish_reason"]
            for c in chunks
            for v in c.get("choices", [])
            if v.get("finish_reason")
        ][-1]
        rows.append(
            {
                "id": call["id"],
                "role": call["step"].split(":")[-1],
                "started": call["started"],
                "finished": call["finished"],
                "tokens": tokens,
                "reasoning_tokens": usage.get("completion_tokens_details", {}).get(
                    "reasoning_tokens"
                ),
                "finish_reason": finished,
                "charged": call["charged"],
                "credits": credits,
            }
        )
    for role, reported in [("all", result["model"]), *result["roles"].items()]:
        own = [r for r in rows if role == "all" or r["role"] == role]
        if not own:
            assert reported["requests"] == reported["total_tokens"] == 0
            assert reported["conservative_settled_cny"] == 0
            assert reported["input_cache_hit_ratio"] is None
            continue
        totals = {
            k: sum(r["tokens"][k] for r in own)
            for k in ("input_cached", "input_uncached", "input_cache_write", "output")
        }
        assert totals == reported["tokens"]
        inputs = totals["input_cached"] + totals["input_uncached"]
        assert reported["input_cache_hit_ratio"] == (
            totals["input_cached"] / inputs if inputs else None
        )
        assert sum(r["charged"] for r in own) / 1e6 == reported["conservative_settled_cny"]
        for timestamp, label in (("started", "dispatch"), ("finished", "completion")):
            points = [
                (datetime.fromisoformat(r[timestamp]), sum(r["tokens"].values())) for r in own
            ]
            windows = [
                [n for t, n in points if 0 <= (end - t).total_seconds() < 60] for end, _ in points
            ]
            assert max(map(len, windows), default=0) == reported[f"peak_rolling_60s_{label}_rpm"]
            assert max(map(sum, windows), default=0) == reported[f"peak_rolling_60s_{label}_tpm"]
    board = Board(root / "board").snapshot("author")
    assert board == result["board"]
    prompts = {}
    for role in ("reviewer", "author"):
        path = root / role / "started.json"
        if path.exists():
            prompts[role] = json.loads(path.read_text())["prompt"]
            assert "answer_key" not in prompts[role] and "expected" not in prompts[role]
    if "author" in prompts:
        assert prompts["author"]["sources"] == prompts["reviewer"]["sources"]
        assert prompts["author"]["initial_candidate"] == prompts["reviewer"]["initial_candidate"]
        if manifest["variant"] == "feedback_disabled":
            assert prompts["author"]["findings"] == [] and board["findings"] == []
        else:
            assert {f["finding_id"] for f in prompts["author"]["findings"]} == {
                e["id"] for e in board["findings"]
            }
    samples = [json.loads(line) for line in (root / "resources.jsonl").read_text().splitlines()]
    assert (
        max(s["process_tree_rss_bytes"] for s in samples)
        == result["resources"]["process_tree_peak_rss_bytes"]
    )
    output = {
        "run_id": run_id,
        "audit_status": "pass",
        "workflow_status": result["status"],
        "semantic_status": "Requires independent source-based review; not certified here.",
        "verified_files": len(hashes),
        "calls": rows,
        "checks": [
            "artifact hashes",
            "native endpoint and Flash identity",
            "wire usage and ledger",
            "all role tokens/cache/cost/rates",
            "board integrity and parentage",
            "source equality and feedback visibility",
            "resource hash and peak RSS",
        ],
    }
    db.close()
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--private", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    report = audit(args.private.resolve(), args.run_id)
    write_new(args.private / "module-runs" / args.run_id / "AUDIT.json", report)
    print(json.dumps({k: v for k, v in report.items() if k != "calls"}))
