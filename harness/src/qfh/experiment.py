"""Sequential, checkpointed DSH capability treatments with equal evidence."""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import importlib.metadata
import json
import re
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import psutil
import yaml
from deepseek_harness import DeepSeekHarness

from qfh.budget import BudgetPolicy, Ledger, admission_open
from qfh.evidence import Proposal, canonical
from qfh.proxy import GuardProxy

VARIANTS = ("single", "blackboard", "independent", "self_revision", "review", "debate")


def write_new(path: Path, value) -> None:
    """Evidence is append-only; filenames never silently overwrite an attempt."""
    with path.open("xb") as out:
        out.write(canonical(value))


class Resources:
    def __init__(self, path: Path, interval: float):
        self.path, self.interval = path, interval
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.sample, daemon=True)

    def sample(self):
        root = psutil.Process()
        with self.path.open("a") as stream:
            while not self.stop.is_set():
                errors = []
                try:
                    processes = [root, *root.children(recursive=True)]
                except (OSError, psutil.Error) as exc:
                    processes = [root]
                    errors.append("process_tree:" + type(exc).__name__)
                rss, cpu = 0, 0.0
                pids = []
                for process in processes:
                    try:
                        rss += process.memory_info().rss
                        times = process.cpu_times()
                        cpu += times.user + times.system
                        pids.append(process.pid)
                    except (OSError, psutil.Error) as exc:
                        errors.append("process:" + type(exc).__name__)
                        continue
                host = {}
                for name, reader in [
                    ("host_memory", lambda: psutil.virtual_memory()._asdict()),
                    ("host_swap", lambda: psutil.swap_memory()._asdict()),
                    ("host_cpu_percent", psutil.cpu_percent),
                    ("disk_free_bytes", lambda: psutil.disk_usage(self.path.parent).free),
                ]:
                    try:
                        host[name] = reader()
                    except (OSError, psutil.Error) as exc:
                        host[name] = None
                        errors.append(name + ":" + type(exc).__name__)
                stream.write(
                    json.dumps(
                        {
                            "at": datetime.now(UTC).isoformat(),
                            "process_tree_rss_bytes": rss,
                            "process_tree_cpu_seconds": cpu,
                            "pids": pids,
                            **host,
                            "measurement_errors": errors,
                        }
                    )
                    + "\n"
                )
                stream.flush()
                self.stop.wait(self.interval)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.stop.set()
        self.thread.join()


def treatment_steps(variant: str) -> list[tuple[str, str]]:
    if variant not in VARIANTS:
        raise ValueError("unknown treatment")
    first = ("A", "Independently revise the initial factor using all sources.")
    if variant == "single":
        return [
            (
                "A",
                "Independently solve the task, check your own answer, and return a final revision.",
            )
        ]
    middle = {
        "blackboard": (
            "B",
            "Contribute to the shared board: inspect A's proposal and all sources. "
            "Add supported corrections or missing connections as your own proposal.",
        ),
        "independent": ("B", "Independently revise the initial factor using all sources."),
        "self_revision": ("A", "Critically recheck your own proposal against all sources."),
        "review": (
            "B",
            "Review A's proposal against all sources. Identify unsupported claims "
            "and return a corrected proposal, retaining unresolved issues.",
        ),
        "debate": (
            "B",
            "Challenge A's proposal with the strongest source-supported opposing "
            "interpretation. Return your alternative proposal and explicit objections.",
        ),
    }[variant]
    final = (
        "A",
        "Compare the available proposals against the original sources. Return the final "
        "factor revision. Identify adopted and rejected changes with reasons. Reference "
        "the contribution ids actually used; do not defer to agreement or agent count.",
    )
    return [first, middle, final]


def run(
    config_path: Path, case_path: Path, variant: str, run_id: str, private: Path, key_path: Path
) -> dict:
    config = yaml.safe_load(config_path.read_text())
    case = json.loads(case_path.read_text())
    policy = BudgetPolicy.model_validate(config["budget"])
    ledger = Ledger(private / "spend.sqlite3", policy)
    steps = treatment_steps(variant)
    run_dir = private / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    home = run_dir / "dsh-home"
    workspace = run_dir / "worker-workspace"
    workspace.mkdir(exist_ok=True)
    patch = config_path.parent / "diagnostic.patch.yml"
    manifest = {
        "run_id": run_id,
        "variant": variant,
        "case_id": case["id"],
        "category": case["category"],
        "synthetic": case["synthetic"],
        "config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
        "patch_sha256": hashlib.sha256(patch.read_bytes()).hexdigest(),
        "case_sha256": hashlib.sha256(canonical(case)).hexdigest(),
        "implementation_sha256": {
            name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
            for name in ("experiment.py", "budget.py", "proxy.py", "evidence.py")
        },
        "runtime_packages": {
            name: importlib.metadata.version(name)
            for name in ("deepseek-harness-sdk", "deepseek-harness-runtime-bin")
        },
        "steps": [list(step) for step in steps],
        "max_total_output_tokens": config["output_allowance"],
        "started_at": datetime.now(UTC).isoformat(),
    }
    saved = run_dir / "manifest.json"
    if saved.exists():
        original = json.loads(saved.read_text())
        if {k: v for k, v in manifest.items() if k != "started_at"} != {
            k: v for k, v in original.items() if k != "started_at"
        }:
            raise ValueError("resume inputs differ from frozen manifest")
    else:
        write_new(saved, manifest)
    outputs = []
    # Each completed step is reloaded without another model call. An interrupted
    # step requires explicit inspection; session repair alone cannot authorize replay.
    for index in range(len(steps)):
        file = run_dir / f"step-{index}.json"
        marker = run_dir / f"step-{index}.started.json"
        if file.exists():
            outputs.append(json.loads(file.read_text()))
        elif marker.exists():
            raise RuntimeError("interrupted step; reconcile retained wire/session evidence first")
        else:
            break
    if len(outputs) == len(steps):
        return {"status": "already_completed", "run_id": run_id}
    if not admission_open(datetime.now(UTC)):
        return {"status": "waiting_for_window", "run_id": run_id}
    matches = re.findall(r"sk-[A-Za-z0-9_-]{20,}", key_path.read_text())
    if len(set(matches)) != 1:
        raise ValueError("expected one DeepSeek credential")
    cap = config["output_allowance"] // len(steps)
    with GuardProxy(
        ledger,
        private / "wire",
        matches[0],
        config["model"],
        cap,
        config["max_body_bytes"],
        config["request_timeout_seconds"],
    ) as guard:
        with Resources(run_dir / "resources.jsonl", config["sample_seconds"]):
            with DeepSeekHarness(
                dsh_home=str(home),
                cwd=str(workspace),
                runtime_cwd=str(workspace),
                profile="sdk-minimal",
                patches=(str(patch.resolve()),),
                provider="deepseek-official",
                model=config["model"],
                max_tokens=cap,
                reasoning_effort=config["reasoning_effort"],
                base_url=guard.base_url,
                api_key=guard.local_key,
                shutdown_timeout_seconds=10,
                env={"DSH_PRIMARY_RUNTIME": "", "OTEL_SDK_DISABLED": "true"},
            ) as harness:
                for index, (role, instruction) in enumerate(steps[len(outputs) :], len(outputs)):
                    if not admission_open(datetime.now(UTC)):
                        return {"status": "waiting_for_window", "run_id": run_id}
                    contribution_id = f"{run_id}:{index}:{role}"
                    peers = outputs if not (variant == "independent" and index == 1) else []
                    prompt = {
                        "case": case,
                        "instruction": instruction,
                        "contribution_id": contribution_id,
                        "available_contributions": [
                            {"id": x["contribution_id"], "proposal": x["proposal"]} for x in peers
                        ],
                        "required_output_schema": Proposal.model_json_schema(),
                    }
                    guard.step = contribution_id
                    write_new(
                        run_dir / f"step-{index}.started.json",
                        {
                            "at": datetime.now(UTC).isoformat(),
                            "prompt": prompt,
                            "session_id": f"{run_id}-{role}",
                            "contribution_id": contribution_id,
                        },
                    )
                    started = time.monotonic()
                    # New role handles open the same session within this runtime. On
                    # resumed runs we use explicit evidence, not an implicit saved transcript.
                    result = harness.run(
                        json.dumps(prompt, ensure_ascii=False), session_id=f"{run_id}-{role}"
                    )
                    raw = dataclasses.asdict(result)
                    write_new(run_dir / f"step-{index}.runtime.json", raw)
                    if result.finish_reason != "completed":
                        raise RuntimeError(f"DSH step ended with {result.finish_reason}")
                    proposal = Proposal.model_validate_json(result.final_response)
                    source_ids = {s["id"] for s in case["sources"]}
                    if any(set(c.evidence_ids) - source_ids for c in proposal.claims):
                        raise ValueError("proposal cites evidence not supplied")
                    peer_ids = {x["contribution_id"] for x in peers}
                    if set(proposal.peer_contribution_ids) - peer_ids:
                        raise ValueError("proposal cites an unavailable contribution")
                    output = {
                        "contribution_id": contribution_id,
                        "role": role,
                        "at": datetime.now(UTC).isoformat(),
                        "latency_seconds": time.monotonic() - started,
                        "proposal": proposal.model_dump(mode="json"),
                    }
                    write_new(run_dir / f"step-{index}.json", output)
                    outputs.append(output)
                    print(
                        json.dumps({"run_id": run_id, "step": index, "status": "completed"}),
                        flush=True,
                    )
    summary = {
        "status": "completed",
        "run_id": run_id,
        "completed_at": datetime.now(UTC).isoformat(),
        "steps": len(outputs),
        "final": outputs[-1]["proposal"],
        "budget": ledger.snapshot(),
    }
    write_new(run_dir / "result.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--case", type=Path, required=True)
    parser.add_argument("--variant", choices=VARIANTS, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--private", type=Path, required=True)
    parser.add_argument("--key-file", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9-]{1,80}", args.run_id):
        parser.error("run id must be a safe lowercase identifier")
    result = run(
        args.config.resolve(),
        args.case.resolve(),
        args.variant,
        args.run_id,
        args.private.resolve(),
        args.key_file.resolve(),
    )
    print(json.dumps({k: v for k, v in result.items() if k not in ("final", "budget")}))


if __name__ == "__main__":
    main()
