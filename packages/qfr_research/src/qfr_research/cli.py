"""`qfr llm probe` and `qfr trace export`, available where qfr-research is installed.

The probe runs inside research-worker (the only service with provider keys):
`docker compose exec research-worker qfr llm probe --trigger setup`.
"""

import asyncio
import json
import os
from pathlib import Path
from uuid import UUID

import typer
from qfr_core.config import RuntimeSettings

from qfr_research.traces import export, history_markdown, iteration_history, trace_hash

llm_app = typer.Typer(no_args_is_help=True, help="Provider checks (research-worker only).")
trace_app = typer.Typer(no_args_is_help=True, help="Development traces.")


@llm_app.command("probe")
def probe(trigger: str = "manual") -> None:
    """List models, check prices, tool and json_object output and thinking per model."""
    from qfr_research.api import build_env
    from qfr_research.probe import run_probe

    if trigger not in ("setup", "daily", "job_start", "manual"):
        raise typer.BadParameter("trigger is one of setup, daily, job_start, manual")
    env = build_env(
        RuntimeSettings(service="research-worker", zone="research"), dict(os.environ), "worker"
    )
    report = asyncio.run(run_probe(env, trigger))  # type: ignore[arg-type]
    typer.echo(report.model_dump_json(indent=2))
    raise typer.Exit(0 if report.ok else 1)


@trace_app.command("export")
def trace_export(version_id: UUID, out: Path = Path("exports/traces")) -> None:
    """Write trace.json and iteration_history.md for one published version."""
    from qfr_research.api import build_env

    env = build_env(
        RuntimeSettings(service="research-api", zone="research"), dict(os.environ), "api"
    )
    with env.db.read() as conn:
        exported = export(conn, version_id=version_id)
        history = iteration_history(conn, version_id, env.clock.now(), exported)
    target = out / str(version_id)
    target.mkdir(parents=True, exist_ok=True)
    body = exported.model_dump(mode="json")
    (target / "trace.json").write_text(json.dumps(body, indent=2, sort_keys=True) + "\n")
    (target / "iteration_history.md").write_text(history_markdown(history))
    typer.echo(json.dumps({"path": str(target), "trace_hash": trace_hash(exported)}))
