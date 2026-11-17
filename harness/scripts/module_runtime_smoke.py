"""Run the actual native DSH/GLM adapter against a synthetic stream; no internet."""

import argparse
import json
from pathlib import Path
from unittest.mock import patch

import yaml

from qfh.coding_plan import CodingLedger, CodingPolicy
from qfh.experiment import write_new
from qfh.module_experiment import native_call
from qfh.proxy import GuardProxy
from qfh.research import Research


class SyntheticChat:
    status_code = 200
    headers = {"content-type": "text/event-stream"}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def stream(self, method, url, **kwargs):
        assert url == "https://open.bigmodel.cn/api/coding/paas/v4/chat/completions"
        assert kwargs["headers"]["Authorization"] == "Bearer synthetic-module-key"
        return self

    def iter_lines(self):
        for chunk in [
            {
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant", "content": '{"ready":true}'},
                        "finish_reason": None,
                    }
                ]
            },
            {
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                "usage": {
                    "prompt_tokens": 20,
                    "completion_tokens": 4,
                    "total_tokens": 24,
                    "prompt_tokens_details": {"cached_tokens": 0},
                },
            },
        ]:
            yield "data: " + json.dumps(
                {
                    "id": "offline-module",
                    "object": "chat.completion.chunk",
                    "created": 0,
                    "model": "glm-5.3-flash",
                    **chunk,
                }
            )
            yield ""
        yield "data: [DONE]"
        yield ""


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    folder = args.directory.resolve()
    folder.mkdir(parents=True, exist_ok=False)
    (folder / "OFFLINE_ONLY").touch()
    research = Research(root / "configs/research-trial.yaml", folder)
    route = CodingPolicy.model_validate(
        yaml.safe_load((root / "configs/glm-coding-modular-2026-11-13.yaml").read_text())
    )
    ledger = CodingLedger(research.ledger, route)
    config = yaml.safe_load((root / "configs/module-pilot.yaml").read_text())
    with patch("qfh.proxy.httpx.Client", return_value=SyntheticChat()):
        with GuardProxy(
            ledger,
            folder / "wire",
            None,
            route.model,
            config["max_output_tokens"],
            config["max_body_bytes"],
            30,
            coding_policy=route,
        ) as guard:
            guard.step = "offline-module"
            guard.allowed_tools = set()
            result = native_call(
                root,
                folder,
                guard,
                route,
                "synthetic-module-key",
                guard.step,
                {"instruction": "Return a ready JSON flag"},
                config,
            )
    assert json.loads(result) == {"ready": True}
    calls = ledger.snapshot()["calls"]
    assert len(calls) == 1 and calls[0]["state"] == "settled"
    write_new(
        folder / "RESULT.json",
        {
            "status": "pass",
            "real_provider_requests": 0,
            "native_runtime": True,
            "synthetic_calls": 1,
        },
    )
    print(json.dumps({"status": "pass", "real_provider_requests": 0}))
