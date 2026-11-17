"""Explicit offline native DSH UI exercise. All model responses are scripted."""

import argparse
import json
from pathlib import Path
from unittest.mock import patch

import yaml
from prepare_adaptive_review import prepare
from research_ui_smoke import Response
from start_research_ui import serve

from qfh.adaptive_research import AdaptiveResearch
from qfh.budget import ProviderAdmission
from qfh.coding_plan import CodingPolicy
from qfh.research import Research


class Scripted:
    def __init__(self, host):
        self.host = host
        self.seen = {}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def stream(self, method, url, **kwargs):
        assert url == self.host.route.endpoint
        assert kwargs["headers"]["Authorization"] == "Bearer offline-adaptive-key"
        sid = kwargs["headers"]["x-deepseek-harness-session-id"]
        scope = self.host.scope(sid)
        role = scope["member"]["role"]
        index = self.seen.get(sid, 0)
        self.seen[sid] = index + 1
        if role == "supervisor":
            if index == 0:
                return Response(tool="research_board", arguments={})
            if scope["finalized"]:
                return Response(text="OFFLINE adaptive diagnostic finalized.")
            if not scope["reviews"]:
                return Response(
                    tool="research_delegate",
                    arguments={"role": "reviewer", "task": "Review the complete output."},
                )
            review = scope["reviews"][-1]
            if review["body"]["verdict"] == "reviewed_with_limits":
                return Response(
                    tool="finalize_research_output",
                    arguments={"output_id": scope["head"]["id"], "review_id": review["id"]},
                )
            return Response(
                tool="research_followup",
                arguments={
                    "role": "author"
                    if review["body"]["output_id"] == scope["head"]["id"]
                    else "reviewer",
                    "task": "Address the unit explanation issue, then review the amended artifact.",
                    "review_id": review["id"],
                },
            )
        if index:
            return Response(text="Accepted diagnostic artifact submitted.")
        if role == "reviewer":
            bad = "understates" in scope["head"]["output"]["rationale"]
            review = {
                "output_id": scope["head"]["id"],
                "verdict": "needs_revision" if bad else "reviewed_with_limits",
                "checks": {
                    k: "Inspected synthetic fixture."
                    for k in ("formula_units", "explanations", "source_support", "scope_and_limits")
                },
                "issues": [
                    {
                        "path": "/rationale",
                        "quote": "understates",
                        "explanation": "Raw magnitude is 10000 times target; add exact claims.",
                        "citations": [
                            {"evidence_id": "income", "quote": "10000 CNY"},
                            {"evidence_id": "capital", "quote": "100000000 CNY"},
                        ],
                    }
                ]
                if bad
                else [],
                "limitations": ["Offline scripted diagnostic only."],
            }
            return Response(
                tool="submit_final_review", arguments={"review_json": json.dumps(review)}
            )
        amendment = {
            "parent_id": scope["head"]["id"],
            "review_id": scope["reviews"][-1]["id"],
            "output": {
                **scope["head"]["output"],
                "rationale": "The raw ratio magnitude overstates the target magnitude by 10000.",
                "unit_claims": scope["unit_proof"]["expected_claims"],
            },
            "resolutions": [
                {
                    "issue_index": 0,
                    "action": "correct",
                    "reason": "Correct magnitude and exact scale.",
                }
            ],
        }
        return Response(
            tool="amend_final_output", arguments={"amendment_json": json.dumps(amendment)}
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--port", type=int, default=3081)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    private = args.directory.resolve()
    private.mkdir(parents=True, exist_ok=False)
    (private / "OFFLINE_ONLY").write_text(
        "Scripted inference, synthetic sources. No external requests.\n"
    )
    config = root / "configs/research-trial.yaml"
    research = Research(config, private)
    research.ledger.set_provider_admission(
        ProviderAdmission(
            providers=["glm_coding"],
            authority="Explicit offline native DSH integration check. No external model request.",
        )
    )
    raw = yaml.safe_load((root / "configs/glm-coding-modular-2026-11-13.yaml").read_text())
    raw["starts_at"] = "2000-01-01T00:00:00Z"
    research.activate_model_route(CodingPolicy.model_validate(raw))
    case = json.loads((root / "cases/module-units.json").read_bytes())
    origin = private / "origin.json"
    origin.write_text(
        json.dumps(
            {
                "board": {
                    "head": {
                        "id": "a" * 64,
                        "body": {
                            "definition": {
                                **case["initial"],
                                "expression": "profit_reported / capitalization_reported * 1e-4",
                                "input_units": "Profit: ten thousand CNY; "
                                "capitalization: hundred million CNY.",
                            },
                            "decisions": [],
                            "citations": [{"evidence_id": "income", "quote": "10000 CNY"}],
                            "rationale": "The raw ratio understates the target by 10000.",
                            "unresolved": ["Synthetic fixture only."],
                        },
                    }
                }
            }
        )
    )
    package = prepare(private, "offline-adaptive", origin)
    home = private / "research-ui-home"
    home.mkdir()
    credentials = home / ".credentials.yaml"
    credentials.write_text(
        yaml.safe_dump({"version": 1, "refs": {"ZAI_CODING_CN_API_KEY": "offline-adaptive-key"}})
    )
    credentials.chmod(0o600)
    Response.model = "glm-5.3-flash"
    scripted = Scripted(AdaptiveResearch(config, private, package))
    with patch("qfh.proxy.httpx.Client", return_value=scripted):
        serve(
            config,
            private,
            None,
            args.port,
            True,
            evidence_mode="synthetic_model_and_sources",
            adaptive_package=package,
        )
