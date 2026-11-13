"""Scripted model + cached synthetic data through the actual DSH web/team runtime.

Only this explicitly offline driver patches clocks/transport. It requires a new
private directory and has no API-key argument. Ordinary pytest never launches it.
"""

import argparse
import hashlib
import json
import threading
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import yaml
from start_research_ui import serve

from qfh.coding_plan import CodingPolicy
from qfh.data_gateway import DataPolicy, dispatch
from qfh.evidence import canonical
from qfh.research import Research
from qfh.research_samples import SampleActivation, compose_sample


class Response:
    status_code = 200
    model = "deepseek-flash"
    headers = {"content-type": "text/event-stream"}

    def __init__(self, text=None, tool=None, arguments=None, ident="synthetic"):
        self.text, self.tool, self.arguments, self.ident = text, tool, arguments, ident

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def iter_lines(self):
        if self.model == "glm-5.3-flash":
            delta = (
                {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": self.ident,
                            "type": "function",
                            "function": {
                                "name": self.tool,
                                "arguments": json.dumps(self.arguments),
                            },
                        }
                    ],
                }
                if self.tool
                else {"role": "assistant", "content": self.text}
            )
            for choice in (
                {"index": 0, "delta": delta, "finish_reason": None},
                {"index": 0, "delta": {}, "finish_reason": "tool_calls" if self.tool else "stop"},
            ):
                yield "data: " + json.dumps(
                    {
                        "id": self.ident,
                        "object": "chat.completion.chunk",
                        "created": 1,
                        "model": self.model,
                        "choices": [choice],
                    }
                )
                yield ""
            yield "data: " + json.dumps(
                {
                    "id": self.ident,
                    "model": self.model,
                    "choices": [],
                    "usage": {
                        "prompt_tokens": 96,
                        "completion_tokens": 16,
                        "total_tokens": 112,
                        "prompt_tokens_details": {"cached_tokens": 32},
                    },
                }
            )
            yield ""
            yield "data: [DONE]"
            yield ""
            return
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
                    "model": self.model,
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
    def __init__(self, research, evidence_id, worker_format="submitted"):
        self.research, self.evidence_id = research, evidence_id
        self.worker_format = worker_format
        self.counts = {}
        self.lock = threading.Lock()

    @staticmethod
    def specification_body():
        # Test-only fixture, never a production/default factor.
        return {
            "family": "close_return_contrast",
            "lookback": 1,
            "comparison": "lt",
            "threshold": "0",
            "tie_policy": "control",
            "label_horizon": 1,
            "expected_direction": "higher",
            "effect_margin": "0.001",
        }

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
                if self.worker_format in ("specification", "spec-repair"):
                    for key in ("formula", "signal_time", "execution_time"):
                        del draft[key]
                    draft["selected_specification_id"] = self.research.specification(
                        sid, self.evidence_id, json.dumps(self.specification_body())
                    )["specification_id"]
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
                arguments=self.research.scope(sid)["query"],
                ident=ident,
            )
        if index == 1:
            return Response(
                tool="research_metrics", arguments={"evidence_id": self.evidence_id}, ident=ident
            )
        if index == 2 and self.worker_format in ("specification", "spec-repair"):
            return Response(
                tool="research_specification",
                arguments={
                    "evidence_id": self.evidence_id,
                    "specification_json": json.dumps(self.specification_body()),
                },
                ident=ident,
            )
        report = {
            "summary": "Synthetic test report for the actual native DSH child session.",
            "evidence_ids": [self.evidence_id],
            "findings": ["The fixture contains synthetic observations."],
            "proposed_formula": None,
            "recommended_changes": [],
            "limitations": ["Not real market evidence."],
            "measurement_refs": [
                {
                    "measurement_id": self.research.metrics(sid, self.evidence_id)[
                        "measurement_id"
                    ],
                    "keys": ["sample.observations", "returns.mean", "lag.5.aligned_case_count"],
                }
            ],
        }
        if self.worker_format in ("specification", "spec-repair"):
            report["specification_id"] = self.research.specification(
                sid, self.evidence_id, json.dumps(self.specification_body())
            )["specification_id"]
            last_submission = 4 if self.worker_format == "spec-repair" else 3
            if index <= last_submission:
                if self.worker_format == "spec-repair" and index == 3:
                    report["findings"] = ["Deliberately oversized synthetic list."] * 9
                return Response(
                    tool="submit_worker_report",
                    arguments={"report_json": json.dumps(report)},
                    ident=ident,
                )
            return Response(text="Validated specification report submitted.", ident=ident)
        if self.worker_format in ("submitted", "repair"):
            submit_index = 3 if self.worker_format == "repair" else 2
            if index <= submit_index:
                if self.worker_format == "repair" and index == 2:
                    report["findings"] = ["Deliberately oversized synthetic list."] * 9
                return Response(
                    tool="submit_worker_report",
                    arguments={"report_json": json.dumps(report)},
                    ident=ident,
                )
            return Response(text="Validated report submitted.", ident=ident)
        text = json.dumps(report)
        if self.worker_format == "json-fence":
            text = "```json\n" + text + "\n```"
        elif self.worker_format == "invalid":
            text = "Invalid synthetic report; must remain rejected."
        return Response(text=text, ident=ident)


def expanded_fixture(research, config):
    """Explicitly synthetic larger fixture; no provider call or production candidate."""
    from qfh.evidence import Query

    policy = DataPolicy.model_validate(
        yaml.safe_load((config.parent / "data-expansion-2026-11-13.yaml").read_text())
    )
    plan = yaml.safe_load((config.parent / "sample-expansion-2026-11-13.yaml").read_text())

    def synthetic_fetch(query, *_):
        day, rows = query.start, []
        while day <= query.end:
            if day.weekday() < 5:
                rows.append(
                    {
                        "symbol": query.symbols[0],
                        "date": day.isoformat(),
                        "close": 100 + day.toordinal() % 2,
                    }
                )
            day += timedelta(days=1)
        return rows, {"synthetic": True, "external_requests": 0}

    parents = []
    for query in [research.policy.query, *[Query.model_validate(q) for q in plan["steps"][:4]]]:
        result = dispatch(
            {
                "provider": "baostock",
                "kind": "bars",
                "run_id": "offline-expanded",
                "query": query.model_dump(mode="json"),
                "credentials": {},
            },
            policy,
            research.data_root,
            baostock_fetch=synthetic_fetch,
        )
        parents.append(result["evidence_id"])
    plan_id = "offline-expanded-fixture"
    plan_hash = hashlib.sha256(
        canonical({"synthetic": True, "source_evidence_ids": parents})
    ).hexdigest()
    ident, record = compose_sample(
        research.store, parents, policy.research_cutoff, plan_id, plan_hash, 4, synthetic=True
    )
    research.activate_sample(
        SampleActivation(
            id=plan_id,
            authority="Explicit offline fixture; no actual model or market data access.",
            expected_previous_id=None,
            evidence_id=ident,
            query=record["query"],
            plan_id=plan_id,
            plan_sha256=plan_hash,
            fixed_definition=ScriptedClient.specification_body(),
            statistical_protocol_sha256=hashlib.sha256(
                canonical(research.statistics.model_dump(mode="json"))
            ).hexdigest(),
            preview_rows=20,
            alignment_preview_rows=2,
        )
    )
    return ident


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--port", type=int, default=3081)
    parser.add_argument("--expanded-fixture", action="store_true")
    parser.add_argument("--glm-coding", action="store_true")
    parser.add_argument(
        "--worker-format",
        choices=(
            "specification",
            "spec-repair",
            "submitted",
            "repair",
            "bare",
            "json-fence",
            "invalid",
        ),
        default="specification",
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
    data = (
        dispatch(
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
        if not args.expanded_fixture
        else {"evidence_id": expanded_fixture(research, config)}
    )
    key_file = private / "dummy-key.txt"
    key_file.write_text("sk-offline-placeholder-never-sent-to-any-provider")
    key_file.chmod(0o600)
    if args.glm_coding:
        coding = CodingPolicy.model_validate(
            yaml.safe_load((config.parent / "glm-coding-native-2026-11-13.yaml").read_text())
        )
        research.activate_model_route(coding)
        home = private / "research-ui-home"
        home.mkdir()
        credential = home / ".credentials.yaml"
        credential.write_text(
            yaml.safe_dump(
                {
                    "version": 1,
                    "refs": {
                        "QFH_GLM_CODING_CREDENTIAL": json.dumps(
                            {
                                "api_key": "offline-only-legacy-glm-key",
                                "platform": "bigmodel-cn",
                                "plan": "coding",
                                "model": coding.model,
                                "tier": "Pro",
                            }
                        )
                    },
                }
            )
        )
        credential.chmod(0o600)
        Response.model = coding.model
    client = ScriptedClient(research, data["evidence_id"], args.worker_format)
    with (
        patch("qfh.proxy.httpx.Client", return_value=client),
        patch("qfh.budget.admission_open", return_value=True),
        patch("qfh.research.admission_open", return_value=True),
        patch.object(CodingPolicy, "admission_open", return_value=True),
        patch(
            "qfh.research.REPORT_CONTRACT",
            "measured-observations-v2"
            if args.worker_format in ("bare", "json-fence")
            else "executable-contrast-v4"
            if args.worker_format in ("specification", "spec-repair")
            else "submitted-reports-v3",
        ),
    ):
        serve(config, private, key_file, args.port, True, evidence_mode="synthetic_model_and_data")


if __name__ == "__main__":
    main()
