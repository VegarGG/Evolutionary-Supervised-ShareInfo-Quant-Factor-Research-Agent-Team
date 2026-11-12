"""Loopback-only DeepSeek Messages relay with admission before every HTTP dispatch."""

from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx

from qfh.budget import BudgetRefused, Ledger, Usage

UPSTREAM = "https://api.deepseek.com/anthropic/v1/messages"


def parse_usage(events: list[dict]) -> Usage:
    """Message delta usage is cumulative; reasoning is already inside output."""
    usage: dict = {}
    complete = False
    final = False
    for event in events:
        if event.get("type") == "message_start":
            usage.update(event["message"]["usage"])
        elif event.get("type") == "message_delta":
            usage.update(event["usage"])
            final = "output_tokens" in event["usage"]
        elif event.get("type") == "message_stop":
            complete = True
        if usage.get("server_tool_use"):
            raise ValueError("unexpected separately charged server tool")
    if not (complete and final):
        raise ValueError("incomplete provider stream; charge remains reserved")
    return Usage(
        input_uncached=usage["input_tokens"],
        input_cached=usage["cache_read_input_tokens"],
        input_cache_write=usage["cache_creation_input_tokens"],
        output=usage["output_tokens"],
    )


def validate_request(body: dict, model: str, max_tokens: int, allowed_tools: set[str]) -> None:
    allowed = {
        "model",
        "messages",
        "system",
        "max_tokens",
        "stream",
        "thinking",
        "output_config",
        "temperature",
        "top_p",
        "stop_sequences",
        "tools",
        "metadata",
    }
    if set(body) - allowed:
        raise BudgetRefused("unapproved request extension")
    if body.get("model") != model or body.get("stream") is not True:
        raise BudgetRefused("only the configured streaming DeepSeek model is allowed")
    if type(body.get("max_tokens")) is not int or not 0 < body["max_tokens"] <= max_tokens:
        raise BudgetRefused("missing or excessive requested output cap")
    for tool in body.get("tools", []):
        if "type" in tool or tool.get("name") not in allowed_tools:
            raise BudgetRefused("unapproved or separately billed tool")


class GuardProxy:
    def __init__(
        self,
        ledger: Ledger,
        directory: Path,
        key: str,
        model: str,
        max_tokens: int,
        max_body_bytes: int,
        timeout_seconds: int,
        session_admitter: Callable[[str], str] | None = None,
    ):
        self.ledger, self.directory, self.key = ledger, directory, key
        self.model, self.max_tokens = model, max_tokens
        self.max_body_bytes, self.timeout_seconds = max_body_bytes, timeout_seconds
        self.allowed_tools: set[str] = set()
        self.local_key = "sk-" + secrets.token_hex(16)
        self.step: str | None = None
        self.session_admitter = session_admitter
        directory.mkdir(parents=True, exist_ok=True)
        proxy = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass  # Request bodies, credentials and raw provider errors never go to stdout.

            def do_POST(self):
                self.close_connection = True
                request_id = None
                response_started = False
                session_id = self.headers.get("x-deepseek-harness-session-id", "")
                try:
                    if self.path not in ("/anthropic/v1/messages", "/anthropic/messages"):
                        raise BudgetRefused("endpoint not allowed")
                    if not secrets.compare_digest(
                        self.headers.get("x-api-key", ""), proxy.local_key
                    ):
                        raise BudgetRefused("invalid local credential")
                    size = int(self.headers.get("Content-Length", "0"))
                    if not 0 < size <= proxy.max_body_bytes:
                        raise BudgetRefused("request body size limit")
                    raw = self.rfile.read(size)
                    body = json.loads(raw)
                    validate_request(body, proxy.model, proxy.max_tokens, proxy.allowed_tools)
                    step = (
                        proxy.session_admitter(session_id) if proxy.session_admitter else proxy.step
                    )
                    if not step:
                        raise BudgetRefused("no admitted experiment step")
                    candidate_id = uuid.uuid4().hex
                    proxy.ledger.reserve(candidate_id, step, datetime.now(UTC))
                    request_id = candidate_id
                    target = proxy.directory / request_id
                    target.mkdir()
                    (target / "request.json").write_bytes(raw)
                    started = time.monotonic()
                    events = []
                    peer_connected = True
                    terminal = None
                    timings = []
                    with httpx.Client(
                        timeout=proxy.timeout_seconds, trust_env=False, follow_redirects=False
                    ) as client:
                        with client.stream(
                            "POST",
                            UPSTREAM,
                            content=raw,
                            headers={
                                "x-api-key": proxy.key,
                                "content-type": "application/json",
                                "anthropic-version": "2023-06-01",
                                "user-agent": "qfh-experiment/0.1",
                                "x-deepseek-harness-session-id": session_id,
                            },
                        ) as response:
                            (target / "http.json").write_text(
                                json.dumps(
                                    {
                                        "status": response.status_code,
                                        "endpoint": UPSTREAM,
                                        "request_sha256": hashlib.sha256(raw).hexdigest(),
                                        "step": step,
                                        "session_id": session_id,
                                    }
                                )
                            )
                            # A disconnected browser must not interrupt upstream
                            # usage collection, including before the first header.
                            response_started = True
                            try:
                                self.send_response(response.status_code)
                                self.send_header(
                                    "Content-Type",
                                    response.headers.get("content-type", "text/event-stream"),
                                )
                                self.end_headers()
                            except (BrokenPipeError, ConnectionResetError):
                                peer_connected = False
                            with (target / "response.sse").open("w") as output:
                                for line in response.iter_lines():
                                    output.write(line + "\n")
                                    output.flush()
                                    if line.startswith("data: "):
                                        event = json.loads(line[6:])
                                        events.append(event)
                                        timings.append(
                                            {
                                                "event": event.get("type"),
                                                "at": datetime.now(UTC).isoformat(),
                                                "elapsed_seconds": time.monotonic() - started,
                                            }
                                        )
                                        if event.get("type") == "message_stop":
                                            # Settle before the client can start its next
                                            # tool/model step. Otherwise a fast loop can
                                            # race our pending concurrency reservation.
                                            terminal = line
                                            continue
                                    if terminal is not None:
                                        continue
                                    if peer_connected:
                                        try:
                                            self.wfile.write((line + "\n").encode())
                                            self.wfile.flush()
                                        except (BrokenPipeError, ConnectionResetError):
                                            peer_connected = False  # Drain and account upstream.
                            if response.status_code != 200:
                                raise ValueError("provider rejected request; charge unverified")
                    usage = parse_usage(events)
                    proxy.ledger.settle(request_id, usage)
                    if peer_connected and terminal:
                        try:
                            self.wfile.write((terminal + "\n\n").encode())
                            self.wfile.flush()
                        except (BrokenPipeError, ConnectionResetError):
                            peer_connected = False
                    (target / "result.json").write_text(
                        json.dumps(
                            {
                                "usage": usage.model_dump(),
                                "latency_seconds": time.monotonic() - started,
                                "peer_connected": peer_connected,
                                "event_timings": timings,
                            },
                            indent=2,
                        )
                    )
                except Exception as exc:
                    if request_id:
                        proxy.ledger.unknown(request_id, type(exc).__name__)
                    with (proxy.directory / "refusals.jsonl").open("a") as output:
                        output.write(
                            json.dumps(
                                {
                                    "at": datetime.now(UTC).isoformat(),
                                    "session_id": session_id[:200],
                                    "request_id": request_id,
                                    "reason": str(exc)
                                    if isinstance(exc, BudgetRefused)
                                    else type(exc).__name__,
                                }
                            )
                            + "\n"
                        )
                    if not response_started:
                        self.send_response(403)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(
                            json.dumps(
                                {
                                    "error": {
                                        "type": "qfh_admission_refused",
                                        "message": str(exc)
                                        if isinstance(exc, BudgetRefused)
                                        else "Request stopped; inspect accounting before retrying.",
                                    }
                                }
                            ).encode()
                        )

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}/anthropic"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
