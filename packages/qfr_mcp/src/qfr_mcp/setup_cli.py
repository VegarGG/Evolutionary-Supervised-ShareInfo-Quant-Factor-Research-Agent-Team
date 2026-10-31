"""`qfr setup` (run as `just setup` on the Mac): the four questions of PLAN Section 13.6.

The command is a client of the MCP front door, so setup through the CLI and setup driven
conversationally by a host agent run the same tools and leave the same records:
qfr.status, qfr.pool.import and qfr.setup.status. It never calls a model provider.
"""

import json
import os
from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Annotated, Any

import httpx
import typer
from qfr_core.config import RuntimeSettings, mcp_config

DONE_STATUSES = frozenset({"ok", "imported", "empty", "kept"})
IMPORT_TIMEOUT_SECONDS = 300.0

app = typer.Typer(
    help="Owner setup: raw factor pool, providers, data and token (through the MCP front door).",
    invoke_without_command=True,
)


class SetupError(RuntimeError):
    pass


class FrontDoor:
    """A minimal JSON-RPC caller for the stateless MCP endpoint."""

    def __init__(self, client: httpx.Client, url: str, token: str) -> None:
        self.client, self.url, self.token = client, url, token

    def call(self, tool: str, **arguments: Any) -> dict[str, Any]:
        response = self.client.post(
            self.url,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": tool, "arguments": arguments},
            },
        )
        if response.status_code != 200:
            raise SetupError(f"{tool}: the MCP front door answered HTTP {response.status_code}")
        body = response.json()
        if "error" in body:
            raise SetupError(f"{tool}: {body['error'].get('message', 'protocol error')}")
        result = body["result"]
        if result.get("isError"):
            text = " ".join(str(c.get("text", "")) for c in result.get("content", []))
            raise SetupError(f"{tool}: {text}")
        structured = result.get("structuredContent")
        if not isinstance(structured, dict):
            raise SetupError(f"{tool}: no structured result")
        return structured


def owner_token(env_file: Path) -> str:
    """QFR_MCP_TOKEN from the environment, else from the .env written by init-secrets."""
    token = os.environ.get("QFR_MCP_TOKEN")
    if token:
        return token
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "QFR_MCP_TOKEN" and value.strip():
                return value.strip()
    raise SetupError("QFR_MCP_TOKEN is not set; run `just init-secrets` and `just up` first")


def _entry_line(outcome: dict[str, Any]) -> str:
    name = outcome.get("name") or f"entry #{outcome['index']}"
    line = f"  {outcome['outcome']:<9} {outcome.get('kind') or '-':<8} {name}"
    reasons = [f"{r['reason_code']} ({r['message']})" for r in outcome.get("reasons", [])]
    if outcome.get("registry_error"):
        error = outcome["registry_error"]
        reasons.append(f"{error['error']} ({error['message']})")
    return line + (": " + "; ".join(reasons) if reasons else "")


def run_setup(
    door: FrontDoor,
    pool_file: str | None,
    no_pool: bool,
    echo: Callable[[str], None],
    ask: Callable[[str], str] | None,
) -> dict[str, Any]:
    """Ask the four questions; `ask` is None when running non-interactively."""
    status = door.call("qfr.status")["data"]
    echo(f"QFR setup, phase {status['phase']}. Your host agent can do the same through MCP.")

    echo("\n1/4 Raw factor pool")
    if pool_file is None and not no_pool:
        if ask is None:
            raise SetupError("give --pool-file NAME or --no-pool when running non-interactively")
        answer = ask("File under imports/ to import (press Enter for none)").strip()
        pool_file, no_pool = (answer, False) if answer else (None, True)
    if pool_file is not None:
        report = door.call("qfr.pool.import", file=pool_file)["data"]
    else:
        report = door.call("qfr.pool.import", no_pool=True)["data"]
    for outcome in report["entries"]:
        echo(_entry_line(outcome))
    counts = report["counts"]
    if pool_file is not None:
        echo(
            f"  {counts['published']} published, {counts['unchanged']} unchanged, "
            f"{counts['invalid']} invalid, {counts['failed']} failed"
        )
    if report["notice"]:
        echo(report["notice"])

    echo("\n2/4 Providers")
    echo(
        "  The provider probe (qfr llm probe) arrives in Phase 4. Setup cannot finish "
        "before it passes. No provider was called."
    )
    echo("\n3/4 Data")
    echo(
        "  Build snapshots with `just data-build --source synthetic` for a dry run, or "
        "`just data-build --source cn` for the CSI 300 release."
    )
    echo("\n4/4 Token")
    echo(
        "  The owner token works: this setup authenticated with it. Run `just mcp-config` "
        "to print the host-agent configuration."
    )

    final = door.call("qfr.setup.status")["data"]
    steps = final["steps"]
    return {
        "setup_complete": final["setup_complete"],
        "pool": steps["pool"]["status"],
        "setup_ref": report["setup_ref"],
        "import_counts": counts if pool_file is not None else None,
        "pool_counts": final["pool_counts"],
        "remaining": [s for s, v in steps.items() if v.get("status") not in DONE_STATUSES],
        "notice": final["notice"],
        "provider_calls_made": 0,
    }


def http_client() -> AbstractContextManager[httpx.Client]:
    return httpx.Client(timeout=IMPORT_TIMEOUT_SECONDS, trust_env=False)


@app.callback()
def setup(
    pool_file: Annotated[
        str | None, typer.Option("--pool-file", help="File under imports/ to import.")
    ] = None,
    no_pool: Annotated[
        bool, typer.Option("--no-pool", help="Start with empty pools (no defaults).")
    ] = False,
    non_interactive: Annotated[
        bool, typer.Option("--non-interactive", help="Never prompt.")
    ] = False,
    url: Annotated[str | None, typer.Option(help="MCP URL; defaults to configs/mcp.yaml.")] = None,
    env_file: Annotated[
        Path, typer.Option(help="Read QFR_MCP_TOKEN from this file when it is not set.")
    ] = Path(".env"),
) -> None:
    """Run setup through the MCP front door and print a JSON summary."""
    if pool_file is not None and no_pool:
        raise typer.BadParameter("--pool-file and --no-pool are exclusive")
    config = mcp_config(RuntimeSettings().config_dir)
    target = url or f"http://{config.bind}:{config.port}{config.path}"

    def ask(question: str) -> str:
        return str(typer.prompt(question, default="", show_default=False))

    try:
        token = owner_token(env_file)
        with http_client() as client:
            summary = run_setup(
                FrontDoor(client, target, token),
                pool_file,
                no_pool,
                typer.echo,
                None if non_interactive else ask,
            )
    except (SetupError, httpx.HTTPError) as error:
        typer.echo(json.dumps({"status": "failed", "error": str(error)}), err=True)
        raise typer.Exit(1) from None
    typer.echo(json.dumps(summary, indent=2))
