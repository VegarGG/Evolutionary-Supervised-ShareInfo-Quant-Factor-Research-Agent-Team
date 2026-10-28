"""Evaluator-only Unix RPC controller. Holds Docker authority, no database secrets.

The socket directory is private (0700), the socket 0600, and the server serial.
Request bodies contain only the frozen contract and bounded bytes, never Docker
options, host paths, credentials or service-control operations.
"""

import argparse
import base64
import contextlib
import json
import os
import signal
import socket
import socketserver
import stat
import struct
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from qfr_core.data_layer.snapshots import canonical_json

from qfr_eval.sandbox.models import DockerControllerConfiguration, DockerControllerRequest
from qfr_eval.sandbox.native import DockerNativeRunner
from qfr_eval.sandbox.native_plan import LABEL
from qfr_eval.sandbox.runner import SandboxCleanupError, SandboxUnavailable


def receive(stream: socket.socket, limit: int, deadline: float) -> bytes:
    def exact(size: int) -> bytes:
        result = bytearray()
        while len(result) < size:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("private controller request deadline")
            stream.settimeout(remaining)
            data = stream.recv(min(65536, size - len(result)))
            if not data:
                raise ValueError("truncated controller frame")
            result.extend(data)
        return bytes(result)

    size = struct.unpack(">Q", exact(8))[0]
    if size > limit:
        raise ValueError("private controller frame exceeds bound")
    return exact(size)


def send(stream: socket.socket, data: bytes, timeout: float) -> None:
    stream.settimeout(timeout)
    stream.sendall(struct.pack(">Q", len(data)) + data)


def request_bound(config: DockerControllerConfiguration) -> int:
    return (
        config.profile.max_input_bytes + 4 * ((config.profile.max_package_bytes + 2) // 3) + 65536
    )


class Controller:
    def __init__(self, config: DockerControllerConfiguration):
        self.config = config
        self.runner = DockerNativeRunner(
            config.profile, config.image_digest, socket_path=config.docker_socket
        )
        self.poisoned = False

    def require_quiescent_start(self) -> None:
        """An interrupted predecessor is an operator-visible blocker, not success.

        This read-only guard never deletes a resource owned by another process.
        Graceful shutdown finishes the bounded job; crash recovery must first
        verify and remove only the recorded orphan identities.
        """
        query = urlencode({"filters": json.dumps({"label": [LABEL]})})
        timeout = self.config.profile.control_timeout_seconds
        containers = self.runner.api.json(
            "GET", "/containers/json?all=true&" + query, timeout=timeout
        )
        volumes = self.runner.api.json("GET", "/volumes?" + query, timeout=timeout)
        if containers or volumes.get("Volumes"):
            raise SandboxUnavailable("native resources remain; verify predecessor cleanup")

    def dispatch(self, data: bytes) -> dict[str, Any]:
        if self.poisoned:
            return {"status": "unavailable"}
        try:
            request = DockerControllerRequest.model_validate_json(data)
            if (
                request.profile_sha256 != self.config.profile.sha256
                or request.image_digest != self.config.image_digest
            ):
                raise ValueError("controller frozen identity mismatch")
            if request.operation == "readiness":
                return {
                    "status": "readiness",
                    "value": self.runner.readiness().model_dump(mode="json"),
                }
            assert request.contract is not None and request.package_base64 is not None
            assert request.request is not None
            if len(request.package_base64) > 4 * ((self.config.profile.max_package_bytes + 2) // 3):
                raise ValueError("package transport exceeds frozen bound")
            package = base64.b64decode(request.package_base64, validate=True)
            result = self.runner.execute(request.contract, package, request.request)
            return {
                "status": "result",
                "code": result.code,
                "output": result.output.model_dump(mode="json") if result.output else None,
                "output_sha256": result.output_sha256,
                "isolation": result.isolation,
            }
        except SandboxCleanupError:
            # No new job after an uncertain cleanup, even if a caller retries.
            self.poisoned = True
            return {"status": "cleanup_uncertain"}
        except (ValueError, OSError, SandboxUnavailable):
            return {"status": "unavailable"}


class _Server(socketserver.UnixStreamServer):
    request_queue_size = 1

    def __init__(self, controller: Controller):
        self.controller = controller
        super().__init__(controller.config.control_socket, _Handler)

    def handle_error(
        self, request: socket.socket | tuple[bytes, socket.socket], client_address: object
    ) -> None:
        # Request or daemon error strings are never logged.
        self.controller.poisoned = True


class _Handler(socketserver.BaseRequestHandler):
    server: _Server

    def handle(self) -> None:
        controller = self.server.controller
        p = controller.config.profile
        # Filesystem-only channel: Linux peers must match this trusted UID.
        # On native macOS the 0700 directory and 0600 socket remain authoritative.
        if hasattr(socket, "SO_PEERCRED"):
            _, uid, _ = struct.unpack(
                "3i", self.request.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
            )
            if uid != os.getuid():
                return
        try:
            data = receive(
                self.request,
                request_bound(controller.config),
                time.monotonic() + p.control_timeout_seconds,
            )
            result = controller.dispatch(data)
            send(self.request, canonical_json(result), p.control_timeout_seconds)
        except (OSError, ValueError):
            return


def serve(config: DockerControllerConfiguration) -> None:
    path = Path(config.control_socket)
    parent = path.parent
    if (
        not parent.is_dir()
        or parent.is_symlink()
        or parent.stat().st_uid != os.getuid()
        or stat.S_IMODE(parent.stat().st_mode) != 0o700
    ):
        raise ValueError("controller requires its own pre-provisioned 0700 socket directory")
    if path.exists() or path.is_symlink():
        # Don't delete an existing live or uncertain socket to pretend startup succeeded.
        raise ValueError("controller socket already exists; verify previous shutdown")
    controller = Controller(config)
    controller.require_quiescent_start()
    previous = os.umask(0o177)
    try:
        server = _Server(controller)
    finally:
        os.umask(previous)
    previous_signals = {}

    def stop(signum: int, frame: object) -> None:
        # Let the one bounded in-flight job finish and perform its cleanup.
        threading.Thread(target=server.shutdown, daemon=True).start()

    if threading.current_thread() is threading.main_thread():
        for number in (signal.SIGTERM, signal.SIGINT):
            previous_signals[number] = signal.signal(number, stop)
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        server.server_close()
        path.unlink(missing_ok=True)
        for number, handler in previous_signals.items():
            signal.signal(number, handler)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("configuration", type=Path)
    args = parser.parse_args()
    config = DockerControllerConfiguration.model_validate_json(args.configuration.read_bytes())
    with contextlib.suppress(KeyboardInterrupt):
        serve(config)


if __name__ == "__main__":
    main()
