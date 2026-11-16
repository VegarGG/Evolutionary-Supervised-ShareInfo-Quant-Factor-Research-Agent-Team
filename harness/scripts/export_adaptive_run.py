"""Offline export and wire audit of a native DSH completed-output review episode."""

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from qfh.adaptive_research import TOOLS, AdaptivePolicy
from qfh.case_research import TOOLS as CASE_TOOLS
from qfh.case_research import CaseBoard, CasePolicy
from qfh.coding_plan import CodingPolicy
from qfh.experiment import write_new
from qfh.final_output import FinalBoard
from qfh.native_audit import assert_completed_tasks, audited_tasks, read_task_log
from qfh.research import Research
from qfh.shared_state import digest
from qfh.trial_metrics import model_metrics, resource_metrics, role_windows


def export(private, package_id, output=None, *, case=False, allow_unresolved=False):
    profile = "case" if case else "adaptive"
    directory = private / ("cases" if case else "adaptive") / package_id
    output = output or directory
    output.mkdir(parents=True, exist_ok=True)
    policy = (CasePolicy if case else AdaptivePolicy).model_validate_json(
        (directory / "package.json").read_bytes()
    )
    board = (CaseBoard if case else FinalBoard)(directory / "board")
    scope = board.snapshot("supervisor")
    with board.locked() as entries:
        events = list(entries)
    config = Path(__file__).resolve().parents[1] / "configs/research-trial.yaml"
    research = Research(config, private)
    budget = research.ledger.snapshot()
    calls = [c for c in budget["calls"] if c["step"].startswith(f"{profile}:{package_id}:")]
    assert calls and all(c["state"] != "pending" for c in calls), "Wait for guard drainage"
    unresolved = [c for c in calls if c["state"] != "settled"]
    assert not unresolved or allow_unresolved, "Explicit unresolved-usage export required"
    assert all(c["state"] in ("unknown", "rejected_reserved") for c in unresolved)
    assert len(calls) <= policy.total_requests
    servers = []
    for path in (private / "research/servers").glob("*/manifest.json"):
        manifest = json.loads(path.read_bytes())
        package = manifest.get(f"{profile}_package")
        if package and package["package_id"] == package_id:
            servers.append((path.parent, manifest))
    assert len(servers) == 1, "Record explicit restart attribution before exporting"
    server, manifest = servers[0]
    route = CodingPolicy.model_validate(manifest["active_model_route"])
    assert route.id == policy.route_id
    assert manifest[f"{profile}_package"] == policy.model_dump(exclude_unset=True)
    assert CodingPolicy.model_validate(manifest["active_model_route"]) == route
    source_checks = 0
    for name, sha in manifest["source_sha256"].items():
        assert hashlib.sha256((server / "source-snapshot" / name).read_bytes()).hexdigest() == sha
        source_checks += 1
    if not case:
        origin = policy.episode.import_origin
        assert (
            hashlib.sha256(Path(origin["path"]).read_bytes()).hexdigest() == origin["file_sha256"]
        )
    rows, files = (
        [],
        [directory / "package.json", directory / "root.json", server / "manifest.json"],
    )
    files.extend((directory / "bindings").glob("*.json"))
    if (directory / "final-ack.json").exists():
        files.append(directory / "final-ack.json")
    files.extend((directory / "board").glob("*.json"))
    files.extend(directory.glob("native-*.json"))
    if case:
        files.extend(directory.glob("calculation-*.json"))
    tool_calls = []
    native_team = {}
    for call in calls:
        folder = private / "campaign/wire" / call["id"]
        request_bytes = (folder / "request.json").read_bytes()
        request = json.loads(request_bytes)
        assert request["model"] == route.model
        assert route.model == (policy.model if case else "glm-5.3-flash")
        assert request["max_tokens"] == manifest.get(
            "effective_output_cap", manifest["policy"]["max_output_tokens"]
        )
        assert request["thinking"] == {"type": "enabled", "clear_thinking": False}
        assert request["reasoning_effort"] == route.reasoning_effort
        assert {t["function"]["name"] for t in request["tools"]} == (CASE_TOOLS if case else TOOLS)
        files.extend(folder.glob("*"))
        if call["state"] != "settled":
            # Missing provider usage is not a free call or a completed response.
            # Export it explicitly without modifying its blocking reservation.
            assert call["usage"] is None and call["charged"] is None and call["reserved"] > 0
            detail = json.loads(call["detail"])
            assert detail["quota_settled_upper_microcredits"] is None
            assert detail["quota_reserved_microcredits"] > 0
            http_path = folder / "http.json"
            if http_path.exists():
                receipt = json.loads(http_path.read_bytes())
                assert receipt["endpoint"] == route.endpoint
                assert receipt["request_sha256"] == hashlib.sha256(request_bytes).hexdigest()
            rows.append(
                {
                    "id": call["id"],
                    "actor": call["step"].split(":")[-1],
                    "tokens": None,
                    "finish_reason": None,
                    "started": call["started"],
                    "finished": call["finished"],
                    "charged": None,
                    "reserved": call["reserved"],
                    "state": call["state"],
                    "response_model_verified": False,
                    "http_receipt_present": http_path.exists(),
                }
            )
            continue
        http = json.loads((folder / "http.json").read_bytes())
        raw = (folder / "response.sse").read_text()
        assert http["status"] == 200 and http["endpoint"] == route.endpoint
        assert http["request_sha256"] == hashlib.sha256(request_bytes).hexdigest()
        for message in request["messages"]:
            if message.get("role") != "tool":
                continue
            try:
                value = json.loads(message["content"])
            except (ValueError, TypeError):
                continue
            if isinstance(value, dict) and "team_task" in value:
                task = value["team_task"]
                key = (task["id"], task["revision"])
                assert key not in native_team or native_team[key] == task
                native_team[key] = task
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
        assert call["charged"] == (
            usage["prompt_tokens"] * (route.cash_input_micro_cny_per_token or 2)
            + usage["completion_tokens"] * (route.cash_output_micro_cny_per_token or 8)
        )
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
    start = min(datetime.fromisoformat(c["started"]) for c in calls)
    finish = max(datetime.fromisoformat(c["finished"]) for c in calls)
    samples = [json.loads(line) for line in (server / "resources.jsonl").read_text().splitlines()]
    # Freeze the activity samples; the server's idle sampler may still be running.
    selected = [s for s in samples if start <= datetime.fromisoformat(s["at"]) <= finish]
    files.append(output / "resource-samples.json")
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
        assert metrics["total_tokens"] == sum(sum((r["tokens"] or {}).values()) for r in own)
        if actor:
            assert len(own) <= (
                policy.supervisor_requests if actor == "supervisor" else policy.worker_requests
            )
        for time_field, label in (("started", "dispatch"), ("finished", "completion")):
            points = [
                (datetime.fromisoformat(r[time_field]), sum((r["tokens"] or {}).values()))
                for r in own
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
    native_log = read_task_log(private / "research-ui-home", members[0]["session_id"])
    native_proof = native_log[1] if native_log else None
    native_tasks = audited_tasks(native_team, native_proof)
    accepted = scope["finalized"] is not None
    assert not (accepted and unresolved), "Unresolved usage cannot support accepted export"
    if accepted:
        final = scope["finalized"]["body"]
        assert final["output_id"] == scope["head"]["id"]
        review = next(e for e in scope["reviews"] if e["id"] == final["review_id"])
        assert review["body"]["candidate_id" if case else "output_id"] == final["output_id"]
        assert review["body"]["verdict"] == "reviewed_with_limits" and not review["body"]["issues"]
        if not case:
            assert scope["unit_proof"]["formula_ok"] and scope["unit_proof"]["structured_claims_ok"]
            assert scope["unit_proof"]["recognized_prose_ok"]
        assert_completed_tasks(members, native_tasks)
    write_new(output / "resource-samples.json", selected)
    write_new(output / "FINAL_BOARD.json", scope)
    if native_log:
        frozen_log = output / "native-session-log.zstd"
        if frozen_log.exists():
            assert frozen_log.read_bytes() == native_log[0], "Frozen native log changed"
        else:
            with frozen_log.open("xb") as stream:
                stream.write(native_log[0])
        write_new(output / "NATIVE_TEAM_AUDIT.json", native_proof)
        files.extend([frozen_log, output / "NATIVE_TEAM_AUDIT.json"])
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
        "status": ("finalized_research_prototype" if case else "finalized_diagnostic")
        if accepted
        else "incomplete",
        "mode": manifest["mode"],
        "source_files_verified": source_checks,
        "board": scope,
        "model": model,
        "actors": reports,
        "wire_calls": rows,
        "tools_called": tool_calls,
        "native_team_tasks": native_tasks,
        "native_team_evidence": "native_session_log" if native_log else "wire_tool_receipts",
        "resources": resource_metrics(selected, [(start, finish)]),
        "recorded_artifact_bytes": sum(h["bytes"] for h in hashes),
        "budget_before": {k: v for k, v in manifest["budget_before"].items() if k != "calls"},
        "budget_after": {k: v for k, v in budget.items() if k != "calls"},
        "budget_snapshot_note": "Global campaign snapshots at server launch and export; "
        "new requests from other episodes may appear in a later re-export snapshot.",
        "audit": {
            "status": "partial_unresolved_usage" if unresolved else "pass",
            "unresolved_call_ids": [c["id"] for c in unresolved],
            "model": route.model,
            "unknown_usage_limit": "Only retained requests and reservations verified for "
            "unresolved calls; response identity, tokens and charge remain unverified. "
            "No reservation was released and no provider retry was made."
            if unresolved
            else None,
            "checks": [
                "immutable source snapshot",
                "frozen research snapshot retained" if case else "original import retained",
                "frozen native model and endpoint; no fallback on settled calls",
                "wire usage, quota and cash",
                "all role rates",
                "native task attribution",
                "current version and final review" if accepted else "unfinished candidate retained",
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
