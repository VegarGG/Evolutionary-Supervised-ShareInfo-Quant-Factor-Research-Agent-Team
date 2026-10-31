"""Local bootstrap commands only; no provider calls or research actions."""

import json
import os
import secrets
import sys
from pathlib import Path

import yaml

root = Path(__file__).resolve().parents[1]
command = sys.argv[1]
if command == "init-secrets":
    target = root / ".env"
    values = {"POSTGRES_PASSWORD": secrets.token_urlsafe()}
    role_names = {
        "REGISTRY": ("registry_app", "registry_db"),
        "RESEARCH": ("research_rw", "research_db"),
        "EVAL": ("eval_rw", "eval_db"),
        "FEEDBACK": ("feedback_ro", "eval_db"),
        "CONTROL": ("control_rw", "control_db"),
    }
    for prefix, (role, database) in role_names.items():
        password = secrets.token_urlsafe()
        values[prefix + "_PASSWORD"] = password
        values[prefix + "_DB_URL"] = (
            f"postgresql+psycopg://{role}:{password}@postgres:5432/{database}"
        )
        if prefix != "FEEDBACK":
            migration_password = secrets.token_urlsafe()
            values[prefix + "_MIGRATION_PASSWORD"] = migration_password
            values[prefix + "_MIGRATION_URL"] = (
                f"postgresql+psycopg://{prefix.lower()}_migrator:{migration_password}"
                f"@postgres:5432/{database}"
            )
    for key in (
        "REGISTRY_PUBLISHER_TOKEN",
        "REGISTRY_READER_TOKEN",
        "REGISTRY_EVALUATOR_TOKEN",
        "REGISTRY_CONTROL_TOKEN",
        "FEEDBACK_READER_TOKEN",
        "RESEARCH_CONTROL_TOKEN",
        "EVAL_OWNER_TOKEN",
        "QFR_MCP_TOKEN",
    ):
        values[key] = secrets.token_urlsafe()
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write("\n".join(f"{k}={v}" for k, v in sorted(values.items())) + "\n")
    for directory in ("imports", "exports", "backups"):
        (root / directory).mkdir(exist_ok=True)
    print(
        "Generated .env with mode 0600. Existing secrets are never "
        "overwritten. No provider keys added."
    )
elif command == "mcp-config":
    values = dict(
        line.split("=", 1)
        for line in (root / ".env").read_text().splitlines()
        if "=" in line and not line.startswith("#")
    )
    config = yaml.safe_load((root / "configs/mcp.yaml").read_text())
    url = f"http://{config['bind']}:{config['port']}{config['path']}"
    token = values["QFR_MCP_TOKEN"]
    print(f"claude mcp add --transport http qfr {url} --header 'Authorization: Bearer {token}'")
    print(f'\n[mcp_servers.qfr]\nurl = "{url}"\nbearer_token_env_var = "QFR_MCP_TOKEN"')
    print(
        json.dumps(
            {"mcpServers": {"qfr": {"url": url, "headers": {"Authorization": f"Bearer {token}"}}}},
            indent=2,
        )
    )
elif command == "deferred":
    print(
        json.dumps(
            {
                "command": sys.argv[2],
                "status": "not_implemented_in_phase_0",
                "scheduled_phase": sys.argv[3],
            }
        )
    )
    sys.exit(2)
elif command == "rotate-mcp-token":
    # Section 13.2: a new owner token in .env; `just rotate-mcp-token` then recreates
    # qfr-mcp so the old token stops working, and `just mcp-config` prints the new one.
    target = root / ".env"
    lines = target.read_text().splitlines()
    if not any(line.startswith("QFR_MCP_TOKEN=") for line in lines):
        raise SystemExit("QFR_MCP_TOKEN is not in .env; run just init-secrets first")
    token = secrets.token_urlsafe()
    rotated = [
        f"QFR_MCP_TOKEN={token}" if line.startswith("QFR_MCP_TOKEN=") else line for line in lines
    ]
    staging = target.with_name(".env.rotating")
    fd = os.open(staging, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write("\n".join(rotated) + "\n")
    os.replace(staging, target)
    print(
        "Rotated QFR_MCP_TOKEN in .env (mode 0600). qfr-mcp is recreated next; then run "
        "`just mcp-config` and update the host agent's configuration."
    )
else:
    raise SystemExit("unknown operation")
