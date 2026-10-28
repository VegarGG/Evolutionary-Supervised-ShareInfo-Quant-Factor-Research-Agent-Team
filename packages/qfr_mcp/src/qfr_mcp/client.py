"""Small independent standard MCP client; no model, provider or job background loop."""

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from pydantic import BaseModel
from qfr_core.contracts.access import PublicServiceClientConfiguration
from qfr_core.service_client import PublicServiceClient
from qfr_core.service_runtime import load_contract


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate tool argument key")
        result[key] = value
    return result


def _nonfinite(value: str) -> Any:
    raise ValueError("nonfinite tool argument")


async def request(
    config: PublicServiceClientConfiguration,
    token: str,
    action: str,
    *,
    tool: str | None = None,
    arguments: dict[str, Any] | None = None,
    uri: str | None = None,
) -> BaseModel:
    """Each call connects, negotiates and disconnects; server work remains durable."""
    async with httpx2.AsyncClient(
        headers={"Authorization": "Bearer " + token},
        timeout=config.timeout_seconds,
        trust_env=False,
    ) as http:
        async with streamable_http_client(
            str(config.base_url).rstrip("/") + "/mcp",
            http_client=http,
            max_sse_event_size=config.max_response_bytes,
        ) as (read, write):
            async with ClientSession(
                read, write, read_timeout_seconds=config.timeout_seconds
            ) as session:
                await session.initialize()
                if action == "list-tools":
                    result: BaseModel = await session.list_tools()
                elif action == "call" and tool is not None:
                    # Discover actual schemas/capabilities rather than assume one vendor version.
                    await session.list_tools()
                    result = await session.call_tool(tool, arguments)
                elif action == "read-resource" and uri is not None:
                    result = await session.read_resource(uri)
                else:
                    raise ValueError("unsupported MCP client operation")
                if len(result.model_dump_json().encode()) > config.max_response_bytes:
                    raise ValueError("MCP result exceeds client output limit")
                return result


def main(arguments: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-config", type=Path, required=True)
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("list-tools")
    call = commands.add_parser("call")
    call.add_argument("tool")
    call.add_argument("arguments", type=Path)
    resource = commands.add_parser("read-resource")
    resource.add_argument("uri")
    args = parser.parse_args(arguments)
    try:
        config = load_contract(args.client_config, PublicServiceClientConfiguration)
        client = PublicServiceClient.from_environment(config, os.environ)
        values = None
        if args.action == "call":
            with args.arguments.open("rb") as stream:
                raw = stream.read(config.max_request_bytes + 1)
            if len(raw) > config.max_request_bytes:
                raise ValueError("tool arguments exceed client bound")
            values = json.loads(raw, object_pairs_hook=_object, parse_constant=_nonfinite)
            if not isinstance(values, dict):
                raise ValueError("tool arguments must be an object")
        result = asyncio.run(
            request(
                config,
                client.token,
                args.action,
                tool=getattr(args, "tool", None),
                arguments=values,
                uri=getattr(args, "uri", None),
            )
        )
    except Exception as error:
        # Protocol/transport validation may otherwise include private request text.
        parser.exit(1, "MCP client request refused: " + type(error).__name__ + "\n")
    print(result.model_dump_json(by_alias=True))
    if getattr(result, "is_error", False):
        parser.exit(2, "MCP tool refused; job state must be read explicitly\n")


if __name__ == "__main__":
    main()
