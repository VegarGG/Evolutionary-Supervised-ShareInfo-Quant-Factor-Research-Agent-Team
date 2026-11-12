"""Serve the DSH research UI with one shared, durable DeepSeek budget boundary."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from qfh.experiment import Resources, write_new
from qfh.proxy import GuardProxy
from qfh.research import Research

TOOLS = {
    "market_daily_bars",
    "read_research_evidence",
    "research_scope",
    "research_metrics",
    "research_worker",
    "submit_worker_report",
    "submit_research_draft",
}


def serve(
    config: Path,
    private: Path,
    key_file: Path,
    port: int,
    install_plugin: bool,
    *,
    evidence_mode="live",
):
    root = Path(__file__).resolve().parents[1]
    private.mkdir(parents=True, exist_ok=True)
    private.chmod(0o700)
    research = Research(config, private)
    policy = research.policy
    credential = set(re.findall(r"sk-[A-Za-z0-9_-]{20,}", key_file.read_text()))
    if len(credential) != 1:
        raise ValueError("expected one operator-held DeepSeek credential")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    evidence = private / "research/servers" / stamp
    evidence.mkdir(parents=True)
    workspace = private / "research-workspace"
    workspace.mkdir(exist_ok=True)
    home = private / "research-ui-home"
    home.mkdir(exist_ok=True)
    # Preserve credentials already entered in the earlier setup UI. Later
    # saves belong to the research UI's own credential store.
    old_credentials = private / "ui-home/.credentials.yaml"
    credentials = home / ".credentials.yaml"
    if old_credentials.exists() and not credentials.exists():
        shutil.copyfile(old_credentials, credentials)
        credentials.chmod(0o600)
    dsh = str(Path(sys.executable).with_name("dsh"))
    source_files = sorted(
        p
        for p in root.rglob("*")
        if p.is_file()
        and p.suffix in (".py", ".js", ".json", ".yaml", ".yml", ".toml", ".lock")
        and not any(x in p.parts for x in ("__pycache__", "node_modules", ".venv"))
    )
    write_new(
        evidence / "manifest.json",
        {
            "mode": evidence_mode,
            "started_at": datetime.now(UTC).isoformat(),
            "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root)
            .decode()
            .strip(),
            "dirty_diff_sha256": hashlib.sha256(
                subprocess.check_output(["git", "diff", "--binary", "HEAD"], cwd=root)
            ).hexdigest(),
            "source_sha256": {
                str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in source_files
            },
            "runtime": {
                name: importlib.metadata.version(name)
                for name in (
                    "deepseek-harness-sdk",
                    "deepseek-harness-runtime-bin",
                    "baostock",
                    "psutil",
                )
            },
            "host": {
                "platform": platform.platform(),
                "machine": platform.machine(),
                "logical_cpus": os.cpu_count(),
            },
            "policy": policy.model_dump(mode="json"),
            "budget_before": research.ledger.snapshot(),
        },
    )
    with GuardProxy(
        research.ledger,
        private / "campaign/wire",
        credential.pop(),
        policy.roles["supervisor"].model,
        policy.max_output_tokens,
        policy.max_body_bytes,
        policy.request_timeout_seconds,
        session_admitter=research.admit,
    ) as guard:
        guard.allowed_tools = TOOLS
        # The real API key stays only in this parent relay. Neither DSH nor tools
        # receive it, even if the launching shell happens to export another key.
        env = {
            k: v
            for k, v in os.environ.items()
            if k
            not in ("DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL", "ANTHROPIC_API_KEY", "OPENAI_API_KEY")
        }
        env.update(
            {
                "DSH_HOME": str(home),
                "QFH_WORKSPACE_BASE": str(workspace),
                "QFH_PYTHON": sys.executable,
                "QFH_SOURCE_ROOT": str(root / "src"),
                "QFH_PRIVATE": str(private),
                "QFH_DATA_POLICY": str(config.parent / policy.data_config),
                "QFH_DATA_PRIVATE": str(private / "data"),
                "QFH_RESEARCH_CONFIG": str(config),
                "QFH_RELAY_URL": guard.base_url,
                "QFH_RELAY_CREDENTIAL": guard.local_key,
                "QFH_MODEL": policy.roles["supervisor"].model,
                "QFH_MAX_TOKENS": str(policy.max_output_tokens),
                "QFH_REASONING_EFFORT": policy.roles["supervisor"].reasoning_effort,
                "DSH_TELEMETRY_MODE": "DISABLED",
                "OTEL_SDK_DISABLED": "true",
                "DSH_PRIMARY_RUNTIME": "",
            }
        )
        if install_plugin:
            for arguments in (
                ["add", f"file:{root / 'dsh-plugin'}"],
                ["link", str(root / "dsh-plugin")],
            ):
                subprocess.run([dsh, "plugin", "--profile", "web", *arguments], env=env, check=True)
        with Resources(evidence / "resources.jsonl", policy.sample_seconds):
            child = subprocess.Popen(
                [
                    dsh,
                    "web",
                    "--patch",
                    str(root / "configs/web-credentials.patch.yml"),
                    "--patch",
                    str(root / "configs/web-research.patch.yml"),
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--no-open",
                ],
                env=env,
                cwd=workspace,
            )
            try:
                print(
                    json.dumps(
                        {
                            "status": "starting_guarded_ui",
                            "port": port,
                            "mode": evidence_mode,
                            "evidence": str(evidence),
                        }
                    ),
                    flush=True,
                )
                child.wait()
            except KeyboardInterrupt:
                child.terminate()
                child.wait(timeout=30)
            finally:
                write_new(
                    evidence / "stopped.json",
                    {
                        "at": datetime.now(UTC).isoformat(),
                        "budget": research.ledger.snapshot(),
                        "child_exit_code": child.returncode,
                    },
                )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--private", type=Path, required=True)
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "configs/research-trial.yaml",
    )
    parser.add_argument("--port", type=int, default=3080)
    parser.add_argument("--install-plugin", action="store_true")
    args = parser.parse_args()
    serve(
        args.config.resolve(),
        args.private.resolve(),
        args.key_file.resolve(),
        args.port,
        args.install_plugin,
    )


if __name__ == "__main__":
    main()
