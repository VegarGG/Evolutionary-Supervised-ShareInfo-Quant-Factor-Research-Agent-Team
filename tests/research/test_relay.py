"""Synthetic bounded TCP checks; no provider or real credential traffic."""

import asyncio
from pathlib import Path

import pytest
from pydantic import ValidationError
from qfr_mcp.relay import RelayPolicy, transfer


def policy():
    return RelayPolicy.model_validate_json(Path("configs/infra/mcp_relay_v1.json").read_bytes())


@pytest.mark.parametrize(
    "change",
    [
        {"upstream_host": "example.org"},
        {"port": 9000},
        {"max_connections": 17},
        {"chunk_bytes": 65537},
        {"connect_timeout_seconds": 6},
        {"inactivity_timeout_seconds": 61},
        {"unexpected": True},
    ],
)
def test_relay_refuses_destination_and_bound_changes(change):
    with pytest.raises(ValidationError):
        RelayPolicy.model_validate({**policy().model_dump(), **change})


def test_relay_transfers_exact_bytes_and_closes_idle_without_retry(monkeypatch):
    async def scenario():
        original = asyncio.open_connection
        calls = []
        tasks = set()

        async def echo(reader, writer):
            try:
                while data := await reader.read(65536):
                    writer.write(data)
                    await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()

        upstream = await asyncio.start_server(echo, "127.0.0.1", 0)
        port = upstream.sockets[0].getsockname()[1]

        async def connect(host, target):
            assert (host, target) == ("mcp-api", 8000)
            calls.append((host, target))
            return await original("127.0.0.1", port)

        monkeypatch.setattr(asyncio, "open_connection", connect)
        p = policy().model_copy(update={"inactivity_timeout_seconds": 1})

        def accept(reader, writer):
            task = asyncio.create_task(transfer(reader, writer, p))
            tasks.add(task)
            task.add_done_callback(tasks.discard)

        relay = await asyncio.start_server(accept, "127.0.0.1", 0)
        try:
            reader, writer = await original("127.0.0.1", relay.sockets[0].getsockname()[1])
            payload = bytes(range(256)) * 1024
            writer.write(payload)
            await writer.drain()
            assert await asyncio.wait_for(reader.readexactly(len(payload)), 3) == payload
            assert await asyncio.wait_for(reader.read(), 3) == b""
            writer.close()
            await writer.wait_closed()
            assert calls == [("mcp-api", 8000)]
        finally:
            relay.close()
            upstream.close()
            await relay.wait_closed()
            await upstream.wait_closed()
            await asyncio.gather(*tasks)

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["refused", "timeout"])
def test_relay_upstream_failure_closes_client_without_retry(monkeypatch, failure):
    async def scenario():
        original = asyncio.open_connection
        calls = []
        tasks = set()

        async def unavailable(host, port):
            calls.append((host, port))
            if failure == "refused":
                raise ConnectionRefusedError("synthetic")
            await asyncio.Future()

        monkeypatch.setattr(asyncio, "open_connection", unavailable)
        p = policy().model_copy(update={"connect_timeout_seconds": 1})

        def accept(reader, writer):
            task = asyncio.create_task(transfer(reader, writer, p))
            tasks.add(task)
            task.add_done_callback(tasks.discard)

        server = await asyncio.start_server(accept, "127.0.0.1", 0)
        writer = None
        try:
            reader, writer = await original("127.0.0.1", server.sockets[0].getsockname()[1])
            assert await asyncio.wait_for(reader.read(), 3) == b""
            assert calls == [("mcp-api", 8000)]
        finally:
            if writer is not None:
                writer.close()
                await writer.wait_closed()
            server.close()
            await server.wait_closed()
            await asyncio.gather(*tasks)

    asyncio.run(scenario())
