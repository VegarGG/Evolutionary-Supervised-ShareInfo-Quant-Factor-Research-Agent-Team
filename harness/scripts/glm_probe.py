"""One explicit tiny Coding Plan transport probe, before a native team trial."""

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import yaml

from qfh.coding_plan import CodingLedger, CodingPolicy, read_coding_credential
from qfh.experiment import Resources, write_new
from qfh.proxy import GuardProxy
from qfh.research import Research


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--private", type=Path, required=True)
    parser.add_argument("--stage", type=int, choices=(1, 2), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repair-of", help="One reviewed authentication rejection to repair")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    private = args.private.resolve()
    if (private / "OFFLINE_ONLY").exists():
        raise ValueError("live probe cannot use a synthetic directory")
    research = Research(root / "configs/research-trial.yaml", private)
    with research.db() as db:
        route = CodingPolicy.model_validate(research.active_model_route(db))
    if not route.admission_open(datetime.now(UTC)):
        raise ValueError("outside GLM authorization window")
    key = read_coding_credential(private)
    probe_config = (
        "glm-probes-native-2026-11-13.yaml"
        if route.transport == "openai-completions"
        else "glm-probes-2026-11-13.yaml"
    )
    config = yaml.safe_load((root / "configs" / probe_config).read_text())
    probe = config["probes"][args.stage - 1]
    args.output.mkdir(parents=True, exist_ok=False)
    write_new(
        args.output / "ATTEMPT.json",
        {
            "at": datetime.now(UTC).isoformat(),
            "stage": args.stage,
            "repair_of": args.repair_of,
            "route": route.model_dump(mode="json"),
            "probe": probe,
            "budget_before": {k: v for k, v in research.ledger.snapshot().items() if k != "calls"},
        },
    )
    step = f"glm-probe:{route.id}:{args.stage}"
    ledger = CodingLedger(research.ledger, route)
    if args.repair_of:
        previous = next((c for c in ledger.snapshot()["calls"] if c["id"] == args.repair_of), None)
        if (
            not previous
            or previous["state"] != "rejected_reserved"
            or not previous["step"].startswith("glm-probe:")
            or not previous["step"].endswith(f":{args.stage}")
        ):
            raise ValueError("repair must reference this stage's reviewed authentication rejection")
        step += f":repair:{args.repair_of}"
        group = f"glm-probe-repair:{args.repair_of}"
        limit = 1
    else:
        group, limit = f"glm-probes:{route.id}", len(config["probes"])
    ledger.grant_step(step, group, 1, limit, route.authority)
    body = {
        "model": route.model,
        "stream": True,
        "max_tokens": probe["max_tokens"],
        "thinking": probe["thinking"],
        "messages": [{"role": "user", "content": probe["prompt"]}],
    }
    if "tool" in probe:
        body["tools"] = [probe["tool"]]
    chat = route.transport == "openai-completions"
    if chat:
        body["stream_options"] = {"include_usage": True}
        body["tool_stream"] = True
        body["reasoning_effort"] = route.reasoning_effort
        if "tool" in probe:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": probe["tool"]["name"],
                        "description": probe["tool"]["description"],
                        "parameters": probe["tool"]["input_schema"],
                    },
                }
            ]
    started = time.monotonic()
    try:
        with (
            Resources(args.output / "resources.jsonl", config["sample_seconds"]),
            GuardProxy(
                ledger,
                private / "campaign/wire",
                None,
                route.model,
                research.policy.max_output_tokens,
                research.policy.max_body_bytes,
                config["request_timeout_seconds"],
                coding_policy=route,
            ) as guard,
        ):
            guard.step = step
            guard.allowed_tools = {probe["tool"]["name"]} if "tool" in probe else set()
            with httpx.Client(timeout=config["request_timeout_seconds"], trust_env=False) as client:
                response = client.post(
                    guard.base_url + ("/chat/completions" if chat else "/v1/messages"),
                    json=body,
                    headers={
                        **(
                            {"x-qfh-relay-key": guard.local_key, "Authorization": "Bearer " + key}
                            if chat
                            else {"x-api-key": guard.local_key, "x-qfh-glm-key": key}
                        ),
                        "x-deepseek-harness-session-id": step,
                        "x-qfh-session-id": step,
                    },
                )
            events = [
                json.loads(line[6:])
                for line in response.text.splitlines()
                if line.startswith("data: ") and line[6:].strip() != "[DONE]"
            ]
        calls = [c for c in ledger.snapshot()["calls"] if c["step"] == step]
        if response.status_code != 200 or len(calls) != 1 or calls[0]["state"] != "settled":
            raise ValueError("probe did not settle successfully; inspect retained wire and quota")
        models = [e["message"]["model"] for e in events if e.get("type") == "message_start"]
        if chat:
            models = sorted({e["model"] for e in events if e.get("model")})
        if any(model.lower() != route.model for model in models):
            raise ValueError("returned model identity differs from the authorized Flash model")
        text = "".join(e.get("delta", {}).get("text", "") for e in events)
        tools = [
            e["content_block"]
            for e in events
            if e.get("type") == "content_block_start"
            and e["content_block"].get("type") == "tool_use"
        ]
        fragments = "".join(e.get("delta", {}).get("partial_json", "") for e in events)
        if chat:
            deltas = [c.get("delta", {}) for e in events for c in e.get("choices", [])]
            text = "".join(d.get("content") or "" for d in deltas)
            chunks = [t for d in deltas for t in d.get("tool_calls", [])]
            tools = [
                {"name": t["function"]["name"], "input": {}}
                for t in chunks
                if t.get("function", {}).get("name")
            ]
            fragments = "".join(t.get("function", {}).get("arguments", "") for t in chunks)
        if "expected_text" in probe:
            assert text.strip() == probe["expected_text"], "probe text did not match"
        else:
            assert len(tools) == 1 and tools[0]["name"] == probe["tool"]["name"]
            assert (json.loads(fragments) if fragments else tools[0]["input"]) == probe[
                "expected_arguments"
            ]
        result = {
            "status": "pass",
            "stage": args.stage,
            "model_identity": models,
            "elapsed_seconds": time.monotonic() - started,
            "calls": calls,
            "scope": "Small transport probe; no worker, factor research or data request.",
        }
    except Exception as exc:
        result = {
            "status": "failed_or_unknown",
            "stage": args.stage,
            "error_type": type(exc).__name__,
            "elapsed_seconds": time.monotonic() - started,
            "action": "Inspect saved wire and accounting; do not automatically retry.",
        }
    write_new(args.output / "RESULT.json", result)
    print(json.dumps({k: v for k, v in result.items() if k != "calls"}))


if __name__ == "__main__":
    main()
