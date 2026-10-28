"""Explicit MCP service launch; uses public HTTP clients and creates no jobs."""

import argparse
import os
from collections.abc import Mapping
from pathlib import Path

import uvicorn
from qfr_core.access import BearerAuthority
from qfr_core.contracts.services import MCPServiceConfiguration
from qfr_core.service_runtime import load_contract, server_arguments
from qfr_core.signatures import EvidenceVerifier
from starlette.applications import Starlette

from qfr_mcp.gateway import Gateway
from qfr_mcp.server import create_app


def application(config: MCPServiceConfiguration, environment: Mapping[str, str]) -> Starlette:
    return create_app(
        Gateway.configured(
            config.backends,
            environment,
            config.policy,
            config.export_policy,
            EvidenceVerifier(config.verification),
        ),
        authority=BearerAuthority(config.authentication, environment),
    )


def main(arguments: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("configuration", type=Path)
    args = parser.parse_args(arguments)
    try:
        config = load_contract(args.configuration, MCPServiceConfiguration)
        app = application(config, os.environ)
    except (ValueError, OSError, PermissionError) as error:
        parser.exit(1, "MCP startup refused: " + type(error).__name__ + "\n")
    uvicorn.run(app, **server_arguments(config.server))


if __name__ == "__main__":
    main()
