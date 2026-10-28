"""Bounded local Unix-socket Docker transport for the trusted controller only.

No context discovery, proxy, registry credentials, image pull, shell, or TCP API.
Errors expose status codes only, never daemon messages or candidate output.
"""

import http.client
import json
import socket
import struct
import threading
import time
from contextlib import suppress
from pathlib import PurePosixPath
from typing import Any


class DockerError(RuntimeError):
    def __init__(self, status: int):
        self.status = status
        super().__init__(f"local Docker operation failed (status {status})")


class DockerBoundExceeded(RuntimeError):
    pass


class _UnixConnection(http.client.HTTPConnection):
    def __init__(self, path: str, timeout: float):
        super().__init__("localhost", timeout=timeout)
        self.path = path
        self.connection_socket: socket.socket | None = None

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.connection_socket = self.sock
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.path)

    def abort(self) -> None:
        if self.connection_socket is not None:
            with suppress(OSError):
                self.connection_socket.shutdown(socket.SHUT_RDWR)


class DockerAPI:
    def __init__(self, socket_path: str):
        path = PurePosixPath(socket_path)
        if (
            not path.is_absolute()
            or ".." in path.parts
            or any(c in socket_path for c in "\r\n\0?%:")
        ):
            raise ValueError("Docker control requires an explicit absolute Unix socket path")
        self.socket_path = socket_path

    def request(
        self,
        method: str,
        path: str,
        *,
        timeout: float,
        limit: int = 1048576,
        value: object = None,
        body: bytes | None = None,
        raw_stream: bool = False,
    ) -> bytes:
        if not path.startswith("/") or any(c in path for c in "\r\n\0"):
            raise ValueError("invalid internal Docker path")
        if body is not None and value is not None:
            raise ValueError("ambiguous request encoding")
        headers = {"Content-Type": "application/x-tar" if body is not None else "application/json"}
        data = (
            body
            if body is not None
            else (
                json.dumps(value, allow_nan=False, separators=(",", ":")).encode()
                if value is not None
                else None
            )
        )
        deadline = time.monotonic() + timeout
        conn = _UnixConnection(self.socket_path, timeout)
        expired = threading.Event()

        def expire() -> None:
            expired.set()
            conn.abort()

        timer = threading.Timer(timeout, expire)
        timer.daemon = True
        timer.start()
        try:
            # Fixed API floor. Unsupported engines fail; no silent negotiation.
            conn.request(method, "/v1.45" + path, data, headers)
            response = conn.getresponse()
            if not 200 <= response.status < 300:
                raise DockerError(response.status)
            result = bytearray()
            pending = bytearray()
            framing_bytes = 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("bounded Docker operation timed out")
                # HTTP may detach the socket for a close-delimited response.
                if conn.sock is not None:
                    conn.sock.settimeout(remaining)
                chunk = response.read1(65536)
                if expired.is_set():
                    raise TimeoutError("bounded Docker operation timed out")
                if not chunk:
                    break
                if not raw_stream:
                    result.extend(chunk)
                else:
                    pending.extend(chunk)
                    while len(pending) >= 8:
                        stream, size = pending[0], struct.unpack(">I", pending[4:8])[0]
                        if stream not in (1, 2) or pending[1:4] != b"\0\0\0":
                            raise ValueError("invalid Docker exec framing")
                        if size > limit - len(result):
                            raise DockerBoundExceeded("bounded Docker exec output")
                        if len(pending) < size + 8:
                            break
                        # Stderr is not a diagnostic channel; reject it entirely.
                        if stream == 2 and size:
                            raise ValueError("unexpected sandbox diagnostic stream")
                        result.extend(pending[8 : 8 + size])
                        del pending[: 8 + size]
                        framing_bytes += 8
                        if framing_bytes > 1048576:
                            raise DockerBoundExceeded("bounded Docker exec frames")
                if len(result) > limit or len(pending) > limit + 8:
                    raise DockerBoundExceeded("bounded Docker response")
            if pending:
                raise ValueError("truncated Docker exec response")
            return bytes(result)
        except (OSError, http.client.HTTPException):
            if expired.is_set():
                raise TimeoutError("bounded Docker operation timed out") from None
            raise
        finally:
            timer.cancel()
            timer.join()
            conn.close()

    def json(self, method: str, path: str, *, timeout: float, value: object = None) -> Any:
        data = self.request(method, path, timeout=timeout, value=value)
        return json.loads(data) if data else None

    def exec(self, container: str, command: list[str], *, timeout: float, limit: int) -> bytes:
        started = time.monotonic()
        result = self.json(
            "POST",
            f"/containers/{container}/exec",
            timeout=timeout,
            value={
                "AttachStdout": True,
                "AttachStderr": True,
                "AttachStdin": False,
                "Tty": False,
                "Privileged": False,
                "Cmd": command,
            },
        )
        identity = result["Id"]
        if (
            not isinstance(identity, str)
            or len(identity) != 64
            or any(c not in "0123456789abcdef" for c in identity)
        ):
            raise ValueError("invalid Docker exec identity")
        remaining = timeout - (time.monotonic() - started)
        if remaining <= 0:
            raise TimeoutError("bounded Docker exec creation")
        output = self.request(
            "POST",
            f"/exec/{identity}/start",
            timeout=remaining,
            limit=limit,
            value={"Detach": False, "Tty": False},
            raw_stream=True,
        )
        remaining = timeout - (time.monotonic() - started)
        if remaining <= 0:
            raise TimeoutError("bounded Docker exec completion")
        state = self.json("GET", f"/exec/{identity}/json", timeout=remaining)
        if state["Running"] or state["ExitCode"] != 0:
            raise DockerExecError(state["ExitCode"])
        return output


class DockerExecError(RuntimeError):
    def __init__(self, code: int | None):
        self.code = code
        super().__init__("sandbox process did not complete successfully")
