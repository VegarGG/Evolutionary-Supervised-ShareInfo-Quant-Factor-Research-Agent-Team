"""Explicit native DSH case integration exercise with synthetic data/scripted inference."""

import argparse
import json
from pathlib import Path
from unittest.mock import patch

import yaml
from research_ui_smoke import Response
from start_research_ui import serve

from qfh.budget import ProviderAdmission
from qfh.case_factor import FactorSpec, definition
from qfh.case_research import CaseEpisode, CasePolicy, CaseResearch
from qfh.coding_plan import CodingPolicy
from qfh.research import Research
from qfh.shared_state import atomic_new, digest


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
        assert kwargs["headers"]["Authorization"] == "Bearer offline-case-key"
        sid = kwargs["headers"]["x-deepseek-harness-session-id"]
        scope = self.host.scope(sid)
        member = scope["member"]
        index = self.seen.get(sid, 0)
        self.seen[sid] = index + 1
        current = scope["head"]
        if member["role"] == "supervisor":
            if index == 0:
                return Response(tool="case_board", arguments={})
            if scope["finalized"]:
                return Response(text="OFFLINE case finalized.")
            if not scope["findings"]:
                stage, basis = "analyze", []
            elif current["kind"] == "initial_candidate":
                stage, basis = "design", [scope["findings"][0]["id"]]
            elif scope["reviews"] and scope["reviews"][-1]["body"]["candidate_id"] == current["id"]:
                review = scope["reviews"][-1]
                if review["body"]["verdict"] == "reviewed_with_limits":
                    return Response(
                        tool="finalize_case",
                        arguments={"output_id": current["id"], "review_id": review["id"]},
                    )
                stage, basis = "design", [review["id"]]
            else:
                stage, basis = "review", [scope["findings"][0]["id"]]
            return Response(
                tool="case_task",
                arguments={
                    "stage": stage,
                    "task": "Offline synthetic native integration task.",
                    "basis_ids": basis,
                },
            )
        stage = member["stage"]
        if index >= (2 if stage == "design" else 1):
            return Response(text="Accepted synthetic artifact submitted.")
        citation = {"evidence_id": "prices", "quote": "Observed prices vary."}
        if stage == "analyze":
            return Response(
                tool="submit_case_findings",
                arguments={
                    "payload_json": json.dumps(
                        {
                            "findings": [
                                {
                                    "candidate_id": current["id"],
                                    "topic": "normalization",
                                    "statement": "Observed prices vary.",
                                    "status": "supported",
                                    "citations": [citation],
                                    "contradicts": [],
                                }
                            ]
                        }
                    )
                },
            )
        if stage == "design":
            spec = {**scope["current_spec"], "lookback": 3}
            if index == 0:
                return Response(
                    tool="inspect_case_factor", arguments={"spec_json": json.dumps(spec)}
                )
            review = scope["reviews"][-1] if scope["reviews"] else None
            value = {
                "parent_id": current["id"],
                "spec": spec,
                "hypothesis": "Unproven three-observation hypothesis.",
                "rationale": "Synthetic mechanics exercise; no improvement evidence.",
                "decisions": [
                    {
                        "finding_id": f["id"],
                        "disposition": "adopt",
                        "reason": "Synthetic supported observation.",
                    }
                    for f in scope["findings"]
                    if f["body"]["candidate_id"] == current["id"]
                ],
                "citations": [citation],
                "limitations": ["Scripted fixture only."],
                "basis_review_id": review["id"] if review else None,
                "issue_resolutions": ["Clarified synthetic hypothesis."] if review else [],
            }
            return Response(
                tool="revise_case_factor", arguments={"payload_json": json.dumps(value)}
            )
        first_review = not scope["reviews"]
        return Response(
            tool="review_case_factor",
            arguments={
                "payload_json": json.dumps(
                    {
                        "candidate_id": current["id"],
                        "verdict": "needs_revision" if first_review else "reviewed_with_limits",
                        "checks": {
                            k: "Inspected synthetic fixture."
                            for k in (
                                "evidence_support",
                                "spec_and_prose",
                                "timing",
                                "scope_and_limits",
                            )
                        },
                        "issues": ["Clarify hypothesis."] if first_review else [],
                        "citations": [citation],
                        "limitations": ["Scripted test only."],
                    }
                )
            },
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--port", type=int, default=3081)
    parser.add_argument("--model", choices=["glm-5.3-flash", "glm-5.3"], default="glm-5.3-flash")
    parser.add_argument("--effort", choices=["low", "high", "max"], default="low")
    parser.add_argument("--output-cap", type=int, choices=[16384, 32768], default=16384)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    private = args.directory.resolve()
    private.mkdir(parents=True, exist_ok=False)
    (private / "OFFLINE_ONLY").write_text(
        "Synthetic fixture and scripted inference. No live requests."
    )
    config = root / "configs/research-trial.yaml"
    research = Research(config, private)
    research.ledger.set_provider_admission(
        ProviderAdmission(
            providers=["glm_coding"], authority="Explicit offline DSH integration only."
        )
    )
    raw = yaml.safe_load(
        (
            root
            / "configs"
            / (
                "glm53-coding-unseen-2026-11-16.yaml"
                if args.model == "glm-5.3"
                else "glm-coding-unseen-2026-11-16.yaml"
            )
        ).read_text()
    )
    raw["starts_at"] = "2000-01-01T00:00:00Z"
    raw["reasoning_effort"] = args.effort
    research.activate_model_route(CodingPolicy.model_validate(raw))
    spec = FactorSpec(
        lookback=5,
        direction=1,
        normalization="none",
        volatility_window=None,
        max_absolute_daily_return=None,
    )
    rows = [
        {"symbol": "600000.XSHG", "date": f"2026-01-{i:02}", "close": 10 + i * 0.1 + (i % 3) * 0.2}
        for i in range(1, 26)
    ]
    episode = CaseEpisode(
        episode_id="offline-case",
        synthetic_evidence=True,
        actors={
            "supervisor": "supervisor",
            **{f"{r}-{i}": r for i in range(1, 7) for r in ("author", "reviewer")},
        },
        sources={"prices": "Observed prices vary. No future outcome evidence."},
        initial=definition(spec, ["600000.XSHG"], "Synthetic unproven hypothesis."),
        initial_spec=spec,
        symbols=["600000.XSHG"],
        rows=rows,
        data_snapshot_sha256=digest(rows),
        start="2026-01-01",
        end="2026-01-31",
        policy={"max_events": 100, "max_findings": 12, "max_versions": 4, "max_text_length": 24000},
    )
    policy = CasePolicy(
        package_id="offline-case",
        study_id="offline",
        variant="adaptive",
        authority="Offline native integration only.",
        question="Exercise native follow-ups.",
        route_id=raw["id"],
        model=args.model,
        episode=episode,
        max_tasks=6,
        supervisor_requests=12,
        worker_requests=5,
        total_requests=32,
        max_output_tokens=args.output_cap,
        max_inspections=6,
    )
    package = private / "package.json"
    atomic_new(package, policy.model_dump())
    home = private / "research-ui-home"
    home.mkdir()
    credentials = home / ".credentials.yaml"
    credentials.write_text(
        yaml.safe_dump({"version": 1, "refs": {"ZAI_CODING_CN_API_KEY": "offline-case-key"}})
    )
    credentials.chmod(0o600)
    Response.model = args.model
    scripted = Scripted(CaseResearch(config, private, package))
    with patch("qfh.proxy.httpx.Client", return_value=scripted):
        serve(
            config,
            private,
            None,
            args.port,
            True,
            evidence_mode="synthetic_model_and_sources",
            case_package=package,
        )
