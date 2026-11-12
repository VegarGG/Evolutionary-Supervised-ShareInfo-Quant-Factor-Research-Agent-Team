"""Scripted model + cached synthetic data through the actual DSH web/team runtime.

Only this explicitly offline driver patches clocks/transport. It requires a new
private directory and has no API-key argument. Ordinary pytest never launches it.
"""

import argparse
import json
import threading
from pathlib import Path
from unittest.mock import patch

from start_research_ui import serve

from qfh.data_gateway import dispatch
from qfh.research import Research


class Response:
    status_code = 200
    headers = {"content-type": "text/event-stream"}

    def __init__(self, text=None, tool=None, arguments=None, ident="synthetic"):
        self.text, self.tool, self.arguments, self.ident = text, tool, arguments, ident

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def iter_lines(self):
        usage = {
            "input_tokens": 64,
            "cache_read_input_tokens": 32,
            "cache_creation_input_tokens": 0,
            "output_tokens": 0,
        }
        block = (
            {"type": "tool_use", "id": self.ident, "name": self.tool, "input": {}}
            if self.tool
            else {"type": "text", "text": ""}
        )
        delta = (
            {"type": "input_json_delta", "partial_json": json.dumps(self.arguments)}
            if self.tool
            else {"type": "text_delta", "text": self.text}
        )
        events = [
            {
                "type": "message_start",
                "message": {
                    "id": self.ident,
                    "type": "message",
                    "role": "assistant",
                    "model": "deepseek-flash",
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": usage,
                },
            },
            {"type": "content_block_start", "index": 0, "content_block": block},
            {"type": "content_block_delta", "index": 0, "delta": delta},
            {"type": "content_block_stop", "index": 0},
            {
                "type": "message_delta",
                "delta": {
                    "stop_reason": "tool_use" if self.tool else "end_turn",
                    "stop_sequence": None,
                },
                "usage": {**usage, "output_tokens": 16},
            },
            {"type": "message_stop"},
        ]
        for event in events:
            yield "event: " + event["type"]
            yield "data: " + json.dumps(event)
            yield ""


class ScriptedClient:
    def __init__(self, research, evidence_id, worker_format="bare"):
        self.research, self.evidence_id = research, evidence_id
        self.worker_format = worker_format
        self.counts = {}
        self.lock = threading.Lock()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def stream(self, *_args, **kwargs):
        sid = kwargs["headers"]["x-deepseek-harness-session-id"]
        role = self.research.member(sid)["role"]
        with self.lock:
            index = self.counts.get(sid, 0)
            self.counts[sid] = index + 1
        print(
            json.dumps({"synthetic_model_request": True, "role": role, "index": index}), flush=True
        )
        ident = f"synthetic-{sid}-{index}"
        if role == "supervisor":
            if index == 2 and self.worker_format == "invalid":
                return Response(text="OFFLINE EXPECTED WORKER FAILURE. No replay.", ident=ident)
            if index == 0:
                return Response(tool="research_scope", arguments={}, ident=ident)
            if index in (1, 2):
                return Response(
                    tool="research_worker",
                    arguments={
                        "role": "researcher" if index == 1 else "reviewer",
                        "task": "Inspect the synthetic cached evidence and return a cited report. "
                        "This is an offline software test.",
                    },
                    ident=ident,
                )
            if index == 3:
                draft = {
                    "title": "Offline integration fixture",
                    "hypothesis": "Synthetic software fixture without research meaning.",
                    "formula": "fixture_only",
                    "signal_time": "close_t",
                    "execution_time": "next_trading_day_close",
                    "evidence_ids": [self.evidence_id],
                    "decisions": [
                        {
                            "worker": r,
                            "adopted": True,
                            "reason": "Retain this synthetic fixture contribution.",
                        }
                        for r in ("researcher", "reviewer")
                    ],
                    "limitations": ["Synthetic fixture, not a real finding."],
                    "next_steps": ["No evaluation or publication."],
                }
                return Response(
                    tool="submit_research_draft",
                    arguments={"draft_json": json.dumps(draft)},
                    ident=ident,
                )
            return Response(
                text="OFFLINE INTEGRATION COMPLETE. Scripted model and synthetic data; "
                "no real provider inference, backtest or publication.",
                ident=ident,
            )
        if index == 0:
            return Response(
                tool="market_daily_bars",
                arguments=self.research.policy.query.model_dump(mode="json"),
                ident=ident,
            )
        if index == 1:
            return Response(
                tool="research_metrics", arguments={"evidence_id": self.evidence_id}, ident=ident
            )
        report = {
            "summary": "Synthetic test report for the actual native DSH child session.",
            "evidence_ids": [self.evidence_id],
            "findings": ["The fixture contains ten synthetic observations."],
            "proposed_formula": None,
            "recommended_changes": [],
            "limitations": ["Not real market evidence."],
        }
        text = json.dumps(report)
        if self.worker_format == "json-fence":
            text = "```json\n" + text + "\n```"
        elif self.worker_format == "invalid":
            text = "Invalid synthetic report; must remain rejected."
        return Response(text=text, ident=ident)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--port", type=int, default=3081)
    parser.add_argument(
        "--worker-format", choices=("bare", "json-fence", "invalid"), default="bare"
    )
    args = parser.parse_args()
    private = args.directory.resolve()
    private.mkdir(parents=True, exist_ok=False)
    (private / "OFFLINE_ONLY").write_text(
        "Synthetic model and cached fixture; forbid uncached provider access.\n"
    )
    config = Path(__file__).resolve().parents[1] / "configs/research-trial.yaml"
    research = Research(config, private)
    rows = [
        {"symbol": "000001.XSHE", "date": f"2026-10-{day}", "close": 10 + i / 10}
        for i, day in enumerate([19, 20, 21, 22, 23, 26, 27, 28, 29, 30])
    ]
    data = dispatch(
        {
            "provider": "baostock",
            "kind": "bars",
            "run_id": "offline-fixture",
            "query": research.policy.query.model_dump(mode="json"),
            "credentials": {},
        },
        research.data_policy,
        research.data_root,
        baostock_fetch=lambda *_: (rows, {"synthetic": True, "external_requests": 0}),
    )
    key_file = private / "dummy-key.txt"
    key_file.write_text("sk-offline-placeholder-never-sent-to-any-provider")
    key_file.chmod(0o600)
    client = ScriptedClient(research, data["evidence_id"], args.worker_format)
    with (
        patch("qfh.proxy.httpx.Client", return_value=client),
        patch("qfh.budget.admission_open", return_value=True),
        patch("qfh.research.admission_open", return_value=True),
    ):
        serve(config, private, key_file, args.port, True, evidence_mode="synthetic_model_and_data")


if __name__ == "__main__":
    main()
