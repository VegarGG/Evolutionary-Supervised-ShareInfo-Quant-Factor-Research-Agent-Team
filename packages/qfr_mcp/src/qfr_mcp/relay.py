"""Bounded fixed-destination TCP relay; carries no application credentials or jobs."""

import argparse
import asyncio
import json
import signal
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RelayPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    revision: Literal[1]
    host: Literal["0.0.0.0"]
    port: Literal[8000]
    upstream_host: Literal["mcp-api"]
    upstream_port: Literal[8000]
    max_connections: int = Field(ge=1, le=16)
    chunk_bytes: int = Field(ge=1, le=65536)
    connect_timeout_seconds: int = Field(ge=1, le=5)
    inactivity_timeout_seconds: int = Field(ge=1, le=60)


async def bridge(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    policy: RelayPolicy,
    activity: list[float],
) -> None:
    while True:
        data = await reader.read(policy.chunk_bytes)
        if not data:
            return
        writer.write(data)
        await writer.drain()
        activity[0] = asyncio.get_running_loop().time()


async def transfer(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter, policy: RelayPolicy
) -> None:
    upstream = None
    tasks = []
    try:
        incoming, upstream = await asyncio.wait_for(
            asyncio.open_connection(policy.upstream_host, policy.upstream_port),
            policy.connect_timeout_seconds,
        )
        activity = [asyncio.get_running_loop().time()]

        async def idle() -> None:
            while True:
                remaining = policy.inactivity_timeout_seconds - (
                    asyncio.get_running_loop().time() - activity[0]
                )
                if remaining <= 0:
                    return
                await asyncio.sleep(remaining)

        tasks = [
            asyncio.create_task(bridge(reader, upstream, policy, activity)),
            asyncio.create_task(bridge(incoming, writer, policy, activity)),
            asyncio.create_task(idle()),
        ]
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    except (OSError, TimeoutError):
        pass  # No addresses, request bytes or exception payloads in logs.
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for stream in (writer, upstream):
            if stream is not None:
                stream.close()
                try:
                    await asyncio.wait_for(stream.wait_closed(), 1)
                except (OSError, TimeoutError):
                    pass


async def serve(policy: RelayPolicy) -> None:
    active: set[asyncio.Task[None]] = set()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    def accept(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        if stop.is_set() or len(active) >= policy.max_connections:
            writer.close()
            return
        task = asyncio.create_task(transfer(reader, writer, policy))
        active.add(task)
        task.add_done_callback(active.discard)

    server = await asyncio.start_server(accept, policy.host, policy.port, limit=policy.chunk_bytes)
    try:
        await stop.wait()
    finally:
        server.close()
        await server.wait_closed()
        for task in list(active):
            task.cancel()
        await asyncio.gather(*active, return_exceptions=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("configuration", type=Path)
    args = parser.parse_args()
    try:
        with args.configuration.open("rb") as stream:
            raw = stream.read(4097)
        if len(raw) > 4096:
            raise ValueError("oversized configuration")
        policy = RelayPolicy.model_validate(json.loads(raw))
    except (ValueError, OSError):
        raise SystemExit("relay configuration refused") from None
    asyncio.run(serve(policy))


if __name__ == "__main__":
    main()
