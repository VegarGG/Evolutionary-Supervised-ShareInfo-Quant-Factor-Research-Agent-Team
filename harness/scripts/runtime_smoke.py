"""Exercise the real DSH executable against an in-process synthetic response."""

import argparse
import json
from pathlib import Path
from unittest.mock import patch

import yaml
from deepseek_harness import DeepSeekHarness

from qfh.budget import BudgetPolicy, Ledger
from qfh.proxy import GuardProxy


class Response:
    status_code = 200
    headers = {"content-type": "text/event-stream"}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def iter_lines(self):
        usage = {
            "input_tokens": 12,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
            "output_tokens": 0,
        }
        events = [
            {
                "type": "message_start",
                "message": {
                    "id": "synthetic-001",
                    "type": "message",
                    "role": "assistant",
                    "model": "deepseek-flash",
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": usage,
                },
            },
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "synthetic runtime smoke"},
            },
            {"type": "content_block_stop", "index": 0},
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                "usage": {**usage, "output_tokens": 4},
            },
            {"type": "message_stop"},
        ]
        for event in events:
            yield "event: " + event["type"]
            yield "data: " + json.dumps(event)
            yield ""


class Client(Response):
    def stream(self, *_args, **_kwargs):
        return Response()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    directory = args.directory.resolve()
    config = yaml.safe_load((root / "configs/phase1.yaml").read_text())
    ledger = Ledger(
        directory / "synthetic-ledger.sqlite3", BudgetPolicy.model_validate(config["budget"])
    )
    directory.mkdir(parents=True, exist_ok=True)
    workspace = directory / "workspace"
    workspace.mkdir(exist_ok=True)
    with patch("qfh.proxy.httpx.Client", return_value=Client()):
        with patch("qfh.budget.admission_open", return_value=True):
            with GuardProxy(
                ledger, directory / "wire", "no-real-key", "deepseek-flash", 8192, 524288, 30
            ) as proxy:
                proxy.step = "synthetic-runtime-smoke"
                with DeepSeekHarness(
                    dsh_home=str(directory / "home"),
                    cwd=str(workspace),
                    runtime_cwd=str(workspace),
                    profile="sdk-minimal",
                    patches=(str(root / "configs/diagnostic.patch.yml"),),
                    provider="deepseek-official",
                    model="deepseek-flash",
                    max_tokens=8192,
                    reasoning_effort="high",
                    api_key=proxy.local_key,
                    base_url=proxy.base_url,
                    env={"DSH_PRIMARY_RUNTIME": ""},
                    shutdown_timeout_seconds=10,
                ) as harness:
                    result = harness.run(
                        "This is an offline transport test. Reply briefly.",
                        session_id="qfh-offline-smoke",
                    )
                    assert result.finish_reason == "completed", result
                    assert result.final_response == "synthetic runtime smoke", result
    requests = list((directory / "wire").glob("*/request.json"))
    assert len(requests) == 1
    request = json.loads(requests[0].read_text())
    assert request.get("tools", []) == []
    assert not any(k.startswith("dsh_") for k in request)
    print(
        json.dumps(
            {
                "status": "pass",
                "runtime": "real DSH 0.2.2rc2",
                "provider": "synthetic in-process response; zero real API requests",
                "request_keys": sorted(request),
                "tool_count": 0,
            }
        )
    )


if __name__ == "__main__":
    main()
