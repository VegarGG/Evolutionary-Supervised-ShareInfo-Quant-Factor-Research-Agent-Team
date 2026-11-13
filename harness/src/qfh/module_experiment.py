"""Bounded native-DSH shared-state/review demonstration, separate from the UI pilot.

No custom inference loop: each role is a native DSH SDK session with one request.
The comparison holds evidence, model, request count and output ceilings equal;
actual compute may differ. It tests a standalone module, not adaptive supervision.
"""

from __future__ import annotations

import dataclasses
import hashlib
import importlib.metadata
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import yaml
from deepseek_harness import DeepSeekHarness

from qfh.coding_plan import CodingLedger, CodingPolicy, read_coding_credential
from qfh.experiment import Resources, write_new
from qfh.proxy import GuardProxy
from qfh.research import Research
from qfh.shared_state import Board, Episode, Review, Revision, digest
from qfh.trial_metrics import model_metrics, resource_metrics


def native_call(root, directory, guard, route, key, step, prompt, config):
    """Private key enters the native provider via its own reference, never argv/files."""
    workspace = directory / "workspace"
    workspace.mkdir()
    env = {
        "DSH_PRIMARY_RUNTIME": "",
        "DSH_TELEMETRY_MODE": "DISABLED",
        "OTEL_SDK_DISABLED": "true",
        "DEEPSEEK_API_KEY": "",
        "OPENAI_API_KEY": "",
        "ANTHROPIC_API_KEY": "",
        "ZAI_CODING_CN_API_KEY": key,
        "QFH_RELAY_URL": guard.base_url,
        "QFH_RELAY_CREDENTIAL": guard.local_key,
        "QFH_MODULE_STEP": step,
        "QFH_MAX_TOKENS": str(config["max_output_tokens"]),
    }
    with DeepSeekHarness(
        dsh_home=str(directory / "dsh-home"),
        cwd=str(workspace),
        runtime_cwd=str(workspace),
        profile="sdk-minimal",
        patches=(
            str(root / "configs/diagnostic.patch.yml"),
            str(root / "configs/sdk-glm-module.patch.yml"),
        ),
        provider="zai-coding-cn",
        model=route.model,
        max_tokens=config["max_output_tokens"],
        reasoning_effort=route.reasoning_effort,
        env=env,
        request_timeout_seconds=config["request_timeout_seconds"],
        shutdown_timeout_seconds=10,
    ) as dsh:
        result = dsh.run(json.dumps(prompt, ensure_ascii=False), session_id=step)
    write_new(directory / "runtime.json", dataclasses.asdict(result))
    if result.finish_reason != "completed":
        raise ValueError("native DSH turn did not complete; inspect private runtime evidence")
    return result.final_response


def parse_output(schema, text):
    # A whole-object markdown envelope is accepted; never repair JSON or substitute
    # a synthetic response when inference fails its contract.
    if text.strip().startswith("```json\n") and text.strip().endswith("\n```"):
        text = text.strip()[8:-4]
    return schema.model_validate_json(text)


def run(private: Path, case_path: Path, run_id: str, variant: str):
    root = Path(__file__).resolve().parents[2]
    if variant not in ("peer_review", "feedback_disabled"):
        raise ValueError("unknown module comparison arm")
    if (private / "OFFLINE_ONLY").exists():
        raise ValueError("live module runner cannot use a synthetic campaign")
    config = yaml.safe_load((root / "configs/module-pilot.yaml").read_text())
    case = json.loads(case_path.read_bytes())
    episode = Episode(
        episode_id=run_id,
        category=case["category"],
        synthetic_evidence=case["synthetic_evidence"],
        actors={"author": "author", "reviewer": "reviewer"},
        sources=case["sources"],
        initial=case["initial"],
        policy=yaml.safe_load((root / "configs/shared-state.yaml").read_text()),
    )
    research = Research(root / "configs/research-trial.yaml", private)
    with research.db() as db:
        route = CodingPolicy.model_validate(research.active_model_route(db))
    if route.transport != "openai-completions" or not route.admission_open(datetime.now(UTC)):
        raise ValueError("an active native GLM Coding Plan route is required")
    ledger = CodingLedger(research.ledger, route)
    control = ledger.snapshot()["provider_admission"]
    if not control or control["providers"] != ["glm_coding"]:
        raise ValueError("modular development requires the GLM-only campaign restriction")
    key = read_coding_credential(private)
    directory = private / "module-runs" / run_id
    directory.mkdir(parents=True, exist_ok=False)  # Existing attempts never redispatch.
    board = Board.create(directory / "board", episode)
    started = datetime.now(UTC)
    write_new(
        directory / "manifest.json",
        {
            "run_id": run_id,
            "variant": variant,
            "case_id": case["id"],
            "category": case["category"],
            "synthetic_evidence": case["synthetic_evidence"],
            "real_model_inference": True,
            "started_at": started.isoformat(),
            "case_sha256": digest(case),
            "config": config,
            "board_policy": episode.policy.model_dump(),
            "route": route.model_dump(mode="json"),
            "provider_admission": control,
            "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root)
            .decode()
            .strip(),
            "dirty_diff_sha256": hashlib.sha256(
                subprocess.check_output(["git", "diff", "--binary", "HEAD"], cwd=root)
            ).hexdigest(),
            "source_sha256": {
                str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(root.rglob("*"))
                if p.is_file()
                and p.suffix in (".py", ".yml", ".yaml", ".json")
                and not any(s in p.parts for s in ("node_modules", "__pycache__"))
            },
            "runtime": {
                p: importlib.metadata.version(p)
                for p in ("deepseek-harness-sdk", "deepseek-harness-runtime-bin", "psutil")
            },
            "logical_cpus": os.cpu_count(),
            "comparison": "Two calls and equal output ceilings per arm; actual tokens differ. "
            "The disabled arm records the review but withholds it from the author.",
        },
    )
    failure = None
    try:
        with (
            Resources(directory / "resources.jsonl", config["sample_seconds"]),
            GuardProxy(
                ledger,
                private / "campaign/wire",
                None,
                route.model,
                config["max_output_tokens"],
                config["max_body_bytes"],
                config["request_timeout_seconds"],
                coding_policy=route,
            ) as guard,
        ):
            guard.allowed_tools = set()
            for actor, schema in (("reviewer", Review), ("author", Revision)):
                step = f"module:{run_id}:{actor}"
                ledger.grant_step(
                    step, f"module:{run_id}", 1, config["max_requests_per_arm"], route.authority
                )
                guard.step = step
                snapshot = board.snapshot(actor)
                instruction = (
                    "Review the initial candidate against all sources. Identify at most "
                    f"{config['max_findings_per_review']} concrete defects or unresolved "
                    "assumptions. Cite exact short excerpts. Return findings pinned to "
                    "the supplied candidate_id. "
                    "contradicts is empty for this initial independent review."
                    if actor == "reviewer"
                    else "Revise the initial factor against the sources and any findings shown. "
                    "Correct supported specification defects; preserve sound parts. Return a "
                    "complete definition, exact source excerpts and an explicit adopt/reject/defer "
                    "decision for EVERY supplied finding_id. If none are supplied, decisions is "
                    "empty and perform "
                    "an independent revision. Use the supplied candidate_id as parent_id. "
                    "State unresolved hypotheses. Never invent a measurement or "
                    "a peer contribution."
                )
                prompt = {
                    "question": case["question"],
                    "role": actor,
                    "instruction": instruction,
                    "candidate_id": snapshot["head"]["id"],
                    "initial_candidate": snapshot["head"]["body"]["definition"],
                    "sources": case["sources"],
                    "findings": [
                        {"finding_id": e["id"], "principal": e["actor"], **e["body"]}
                        for e in snapshot["findings"]
                    ],
                    "required_output_schema": schema.model_json_schema(),
                }
                attempt = directory / actor
                attempt.mkdir()
                write_new(
                    attempt / "started.json",
                    {
                        "at": datetime.now(UTC).isoformat(),
                        "step": step,
                        "prompt": prompt,
                        "prompt_sha256": digest(prompt),
                    },
                )
                output = parse_output(
                    schema, native_call(root, attempt, guard, route, key, step, prompt, config)
                )
                if actor == "reviewer":
                    if len(output.findings) > config["max_findings_per_review"]:
                        raise ValueError("review finding limit exceeded")
                    for finding in output.findings:
                        # Validate even in the ablation; publish only in the peer arm.
                        board._citations(finding.citations)
                        if finding.candidate_id != snapshot["head"]["id"] or finding.contradicts:
                            raise ValueError("review targets an unavailable candidate or finding")
                        if variant == "peer_review":
                            board.publish(actor, finding)
                else:
                    board.revise(actor, output)
                write_new(attempt / "accepted.json", output.model_dump())
                print(
                    json.dumps({"run_id": run_id, "role": actor, "status": "recorded"}), flush=True
                )
    except Exception as exc:
        failure = {"type": type(exc).__name__, "message": str(exc)[:600]}
        # DSH errors may contain provider details; this artifact stays private.
        write_new(directory / "FAILURE.json", failure)
    finished = datetime.now(UTC)
    calls = [c for c in ledger.snapshot()["calls"] if c["step"].startswith(f"module:{run_id}:")]
    samples = [
        json.loads(line) for line in (directory / "resources.jsonl").read_text().splitlines()
    ]
    roles = {}
    for actor in ("reviewer", "author"):
        own = [c for c in calls if c["step"].endswith(":" + actor)]
        windows = [
            (
                datetime.fromisoformat(c["started"]),
                datetime.fromisoformat(c["finished"]) if c["finished"] else finished,
            )
            for c in own
        ]
        roles[actor] = {
            **model_metrics(own, route.model_dump(mode="json")),
            "shared_resources_during_requests": resource_metrics(samples, windows),
        }
    result = {
        "run_id": run_id,
        "status": "structural_pass" if failure is None else "failed",
        "semantic_status": "pending_independent_review",
        "variant": variant,
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "wall_seconds": (finished - started).total_seconds(),
        "failure_type": failure["type"] if failure else None,
        "model": model_metrics(calls, route.model_dump(mode="json")),
        "roles": roles,
        "resources": resource_metrics(samples, [(started, finished)]),
        "board": board.snapshot("author"),
        "budget_after": {k: v for k, v in ledger.snapshot().items() if k != "calls"},
        "request_ids": [c["id"] for c in calls],
    }
    if failure is None and (len(calls) != 2 or any(c["state"] != "settled" for c in calls)):
        result.update(status="failed", failure_type="UsageNotFullySettled")
    write_new(directory / "RESULT.json", result)
    files = [p for p in directory.rglob("*") if p.is_file()]
    files += [
        p for c in calls for p in (private / "campaign/wire" / c["id"]).rglob("*") if p.is_file()
    ]
    write_new(
        directory / "ARTIFACT_HASHES.json",
        [
            {
                "path": str(p.relative_to(private)),
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                "bytes": p.stat().st_size,
            }
            for p in sorted(files)
        ],
    )
    return {
        "run_id": run_id,
        "status": result["status"],
        "requests": len(calls),
        "conservative_cny": result["model"]["conservative_settled_cny"],
    }
