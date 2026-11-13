"""Offline export and wire audit of a native DSH completed-output review episode."""

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from qfh.adaptive_research import TOOLS, AdaptivePolicy
from qfh.coding_plan import CodingPolicy
from qfh.experiment import write_new
from qfh.final_output import FinalBoard
from qfh.research import Research
from qfh.shared_state import digest
from qfh.trial_metrics import model_metrics, resource_metrics, role_windows


def export(private, package_id, output=None):
    directory = private / "adaptive" / package_id
    output = output or directory
    output.mkdir(parents=True, exist_ok=True)
    policy = AdaptivePolicy.model_validate_json((directory / "package.json").read_bytes())
    board = FinalBoard(directory / "board")
    scope = board.snapshot("supervisor")
    with board.locked() as entries:
        events = list(entries)
    config = Path(__file__).resolve().parents[1] / "configs/research-trial.yaml"
    research = Research(config, private)
    budget = research.ledger.snapshot()
    calls = [c for c in budget["calls"] if c["step"].startswith(f"adaptive:{package_id}:")]
    assert calls and all(c["state"] == "settled" for c in calls)
    assert len(calls) <= policy.total_requests
    servers = []
    for path in (private / "research/servers").glob("*/manifest.json"):
        manifest = json.loads(path.read_bytes())
        package = manifest.get("adaptive_package")
        if package and package["package_id"] == package_id:
            servers.append((path.parent, manifest))
    assert len(servers) == 1, "Record explicit restart attribution before exporting"
    server, manifest = servers[0]
    route = CodingPolicy.model_validate(manifest["active_model_route"])
    assert route.id == policy.route_id
    assert manifest["adaptive_package"] == policy.model_dump(exclude_unset=True)
    assert manifest["active_model_route"] == route.model_dump(mode="json")
    source_checks = 0
    for name, sha in manifest["source_sha256"].items():
        assert hashlib.sha256((server / "source-snapshot" / name).read_bytes()).hexdigest() == sha
        source_checks += 1
    origin = policy.episode.import_origin
    assert hashlib.sha256(Path(origin["path"]).read_bytes()).hexdigest() == origin["file_sha256"]
    rows, files = (
        [],
        [directory / "package.json", directory / "root.json", server / "manifest.json"],
    )
    files.extend((directory / "bindings").glob("*.json"))
    if (directory / "final-ack.json").exists():
        files.append(directory / "final-ack.json")
    files.extend((directory / "board").glob("*.json"))
    files.extend(directory.glob("native-*.json"))
    tool_calls = []
    native_team = {}
    for call in calls:
        folder = private / "campaign/wire" / call["id"]
        request_bytes = (folder / "request.json").read_bytes()
        request = json.loads(request_bytes)
        http = json.loads((folder / "http.json").read_bytes())
        raw = (folder / "response.sse").read_text()
        assert http["status"] == 200 and http["endpoint"] == route.endpoint
        assert http["request_sha256"] == hashlib.sha256(request_bytes).hexdigest()
        assert request["model"] == route.model == "glm-5.3-flash"
        assert request["max_tokens"] == manifest.get(
            "effective_output_cap", manifest["policy"]["max_output_tokens"]
        )
        assert request["thinking"] == {"type": "enabled", "clear_thinking": False}
        assert request["reasoning_effort"] == route.reasoning_effort
        assert {t["function"]["name"] for t in request["tools"]} == TOOLS
        for message in request["messages"]:
            if message.get("role") != "tool":
                continue
            try:
                value = json.loads(message["content"])
            except (ValueError, TypeError):
                continue
            if isinstance(value, dict) and "team_task" in value:
                task = value["team_task"]
                native_team[(task["id"], task["revision"])] = task
        assert "data: [DONE]" in raw
        chunks = [json.loads(line[6:]) for line in raw.splitlines() if line.startswith("data: {")]
        assert {c["model"] for c in chunks if c.get("model")} == {route.model}
        usage = [c["usage"] for c in chunks if c.get("usage")][-1]
        cached = usage.get("prompt_tokens_details", {}).get("cached_tokens")
        detail = json.loads(call["detail"])
        assert detail["cache_tokens_reported"] == (cached is not None)
        tokens = {
            "input_cached": cached or 0,
            "input_uncached": usage["prompt_tokens"] - (cached or 0),
            "input_cache_write": 0,
            "output": usage["completion_tokens"],
        }
        assert call["usage"] == tokens and usage["total_tokens"] == sum(tokens.values())
        assert call["charged"] == usage["prompt_tokens"] * 2 + usage["completion_tokens"] * 8
        assert (
            detail["quota_settled_upper_microcredits"]
            == usage["prompt_tokens"] * route.input_microcredits_per_token
            + usage["completion_tokens"] * route.output_microcredits_per_token
        )
        stops = [
            choice["finish_reason"]
            for chunk in chunks
            for choice in chunk.get("choices", [])
            if choice.get("finish_reason")
        ]
        for chunk in chunks:
            for choice in chunk.get("choices", []):
                for tool in choice.get("delta", {}).get("tool_calls", []):
                    if tool.get("function", {}).get("name"):
                        tool_calls.append(
                            {
                                "call_id": call["id"],
                                "actor": call["step"].split(":")[-1],
                                "tool": tool["function"]["name"],
                            }
                        )
        rows.append(
            {
                "id": call["id"],
                "actor": call["step"].split(":")[-1],
                "tokens": tokens,
                "finish_reason": stops[-1],
                "started": call["started"],
                "finished": call["finished"],
                "charged": call["charged"],
            }
        )
        files.extend(folder.glob("*"))
    start = min(datetime.fromisoformat(c["started"]) for c in calls)
    finish = max(datetime.fromisoformat(c["finished"]) for c in calls)
    samples = [json.loads(line) for line in (server / "resources.jsonl").read_text().splitlines()]
    # Freeze the activity samples; the server's idle sampler may still be running.
    selected = [s for s in samples if start <= datetime.fromisoformat(s["at"]) <= finish]
    write_new(output / "resource-samples.json", selected)
    files.append(output / "resource-samples.json")
    write_new(output / "FINAL_BOARD.json", scope)
    files.append(output / "FINAL_BOARD.json")
    actors = sorted({r["actor"] for r in rows})
    members = [
        {
            "role": "supervisor",
            "session_id": json.loads((directory / "root.json").read_bytes())["session_id"],
        }
    ]
    normalized = []
    for event in events:
        if event["kind"] == "task_started":
            members.append(
                {"role": event["body"]["actor"], "session_id": event["body"]["child_id"]}
            )
        if event["kind"] in ("task_started", "task_finished"):
            normalized.append({**event, "kind": event["kind"].replace("task_", "worker_")})
    windows = role_windows(members, normalized, start, finish)
    synthetic = manifest["mode"] != "live"
    reports = {
        a: {
            "model": model_metrics(
                [c for c in calls if c["step"].endswith(":" + a)],
                route.model_dump(),
                synthetic=synthetic,
            ),
            "resources": resource_metrics(selected, windows[a]),
            "native_tasks": [e for e in scope["tasks"] if e["body"]["actor"] == a],
        }
        for a in actors
    }
    model = model_metrics(calls, route.model_dump(), synthetic=synthetic)
    # Independently check reported rolling rates from audited wire totals.
    for actor, metrics in [(None, model), *[(a, r["model"]) for a, r in reports.items()]]:
        own = [r for r in rows if actor is None or r["actor"] == actor]
        assert metrics["total_tokens"] == sum(sum(r["tokens"].values()) for r in own)
        if actor:
            assert len(own) <= (
                policy.supervisor_requests if actor == "supervisor" else policy.worker_requests
            )
        for time_field, label in (("started", "dispatch"), ("finished", "completion")):
            points = [
                (datetime.fromisoformat(r[time_field]), sum(r["tokens"].values())) for r in own
            ]
            rolling = [
                [n for t, n in points if 0 <= (end - t).total_seconds() < 60] for end, _ in points
            ]
            assert max(map(len, rolling), default=0) == metrics[f"peak_rolling_60s_{label}_rpm"]
            assert max(map(sum, rolling), default=0) == metrics[f"peak_rolling_60s_{label}_tpm"]
    for event in scope["tasks"]:
        if event["kind"] == "task_finished":
            result = json.loads((directory / f"native-{event['body']['actor']}.json").read_bytes())
            assert digest(result) == event["body"]["result_sha256"]
    accepted = scope["finalized"] is not None
    if accepted:
        final = scope["finalized"]["body"]
        assert final["output_id"] == scope["head"]["id"]
        review = next(e for e in scope["reviews"] if e["id"] == final["review_id"])
        assert review["body"]["output_id"] == final["output_id"]
        assert review["body"]["verdict"] == "reviewed_with_limits" and not review["body"]["issues"]
        assert scope["unit_proof"]["formula_ok"] and scope["unit_proof"]["structured_claims_ok"]
        assert scope["unit_proof"]["recognized_prose_ok"]
        for member in members:
            if member["role"] != "supervisor":
                assert any(
                    t["ownerId"] == member["session_id"] and t["status"] == "completed"
                    for t in native_team.values()
                ), "Native Team completion not observed"
    hashes = [
        {
            "path": str(p.relative_to(private)),
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            "bytes": p.stat().st_size,
        }
        for p in sorted(set(files))
        if p.is_file()
    ]
    write_new(output / "ARTIFACT_HASHES.json", hashes)
    result = {
        "package_id": package_id,
        "exported_at": datetime.now(UTC).isoformat(),
        "status": "finalized_diagnostic" if accepted else "incomplete",
        "mode": manifest["mode"],
        "source_files_verified": source_checks,
        "board": scope,
        "model": model,
        "actors": reports,
        "wire_calls": rows,
        "tools_called": tool_calls,
        "native_team_tasks": list(native_team.values()),
        "resources": resource_metrics(selected, [(start, finish)]),
        "recorded_artifact_bytes": sum(h["bytes"] for h in hashes),
        "budget_before": {k: v for k, v in manifest["budget_before"].items() if k != "calls"},
        "budget_after": {k: v for k, v in budget.items() if k != "calls"},
        "budget_snapshot_note": "Global campaign snapshots at server launch and export; "
        "new requests from other episodes may appear in a later re-export snapshot.",
        "audit": {
            "status": "pass",
            "checks": [
                "immutable source snapshot",
                "original import retained",
                "native Flash endpoint and no fallback",
                "wire usage, quota and cash",
                "all role rates",
                "native task attribution",
                "current version and final review",
                "artifact hashes",
            ],
            "semantic_limit": "Prose interpretation requires a separate source-based review.",
        },
    }
    write_new(output / "RESULT.json", result)
    return {
        k: result[k]
        for k in ("package_id", "status", "source_files_verified", "model", "resources", "audit")
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--private", type=Path, required=True)
    parser.add_argument("--package-id", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            export(
                args.private.resolve(),
                args.package_id,
                args.output.resolve() if args.output else None,
            ),
            indent=2,
        )
    )
