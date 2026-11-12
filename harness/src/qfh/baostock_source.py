"""Anonymous BaoStock daily data through its pinned SDK and a bounded socket.

The SDK owns message construction/parsing. Its transport is scoped to this call
under a lock because the upstream SDK uses process-global connection state.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import socket
import threading
import time
import zlib
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from qfh.evidence import Query
from qfh.ricequant import DataUnavailable

_SDK_LOCK = threading.Lock()
HOST = ("public-api.baostock.com", 10030)


class BoundedSocket:
    """One anonymous login, one first-page history request, one optional logout."""

    def __init__(self, raw, timeout: int, max_bytes: int):
        self.raw, self.max_bytes = raw, max_bytes
        self.deadline = time.monotonic() + timeout
        self.wire: list[dict] = []
        self.received = 0
        self.response_hash = hashlib.sha256()
        self.failure: str | None = None
        self.raw_response = bytearray()

    def refuse(self, reason):
        self.failure = reason
        raise DataUnavailable(reason)

    def timed(self):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            self.refuse("BaoStock query deadline exceeded")
        self.raw.settimeout(remaining)

    def connect(self, address):
        if address != HOST:
            self.refuse("BaoStock endpoint is not allowed")
        self.timed()
        self.raw.connect(address)

    def send(self, content):
        parts = content.split(b"\x01")
        expected = [b"00", b"95", b"02"]
        if len(self.wire) >= 3 or len(parts) < 3 or parts[1] != expected[len(self.wire)]:
            self.refuse("BaoStock extra request or automatic retry refused")
        self.timed()
        self.wire.append(
            {
                "kind": ["auth", "bars", "logout"][len(self.wire)],
                "request_sha256": hashlib.sha256(content).hexdigest(),
                "request_bytes": len(content),
            }
        )
        self.raw.sendall(content)
        return len(content)

    def recv(self, size):
        self.timed()
        content = self.raw.recv(min(size, self.max_bytes + 1 - self.received))
        if not content:
            self.refuse("BaoStock connection closed before a complete response")
        self.received += len(content)
        self.raw_response.extend(content)
        self.response_hash.update(content)
        if self.received > self.max_bytes:
            self.refuse("BaoStock response exceeds local byte limit")
        return content

    def decompress(self, content):
        decoder = zlib.decompressobj()
        result = decoder.decompress(content, self.max_bytes + 1)
        if len(result) > self.max_bytes or not decoder.eof or decoder.unused_data:
            self.refuse("BaoStock decompressed response exceeds limit or is incomplete")
        # SDK 0.9.4 slices off the final character as a newline. Observed public
        # responses omit that newline, which otherwise truncates adjustflag "3".
        return result if result.endswith(b"\n") else result + b"\n"

    def close(self):
        self.raw.close()


def normalize_rows(result, query: Query) -> list[dict]:
    code = ("sz." if query.symbols[0].endswith(".XSHE") else "sh.") + query.symbols[0][:6]
    if result.error_code != "0":
        raise DataUnavailable("BaoStock history query failed; no automatic retry")
    if result.fields != ["date", "code", "close"] or result.code != code:
        raise DataUnavailable("BaoStock response identity or fields differ")
    if result.adjustflag != "3" or result.frequency != "d":
        raise DataUnavailable("BaoStock response is not unadjusted daily data")
    # Deliberately consume the first response only. SDK next()/get_data() can paginate.
    raw_rows = result.data
    if not isinstance(raw_rows, list) or len(raw_rows) > (query.end - query.start).days + 1:
        raise DataUnavailable("BaoStock response exceeds requested row scope")
    rows, seen = [], set()
    try:
        for raw_day, raw_code, raw_close in raw_rows:
            day = date.fromisoformat(raw_day)
            number = Decimal(raw_close)
            if (
                raw_code != code
                or day in seen
                or not query.start <= day <= query.end
                or not number.is_finite()
                or number <= 0
            ):
                raise ValueError
            seen.add(day)
            rows.append(
                {"symbol": query.symbols[0], "date": day.isoformat(), "close": float(number)}
            )
    except (ValueError, TypeError, InvalidOperation):
        raise DataUnavailable("BaoStock invalid, duplicate or out-of-range daily row") from None
    return sorted(rows, key=lambda row: row["date"])


def daily_close(query: Query, policy, guard, request_key: str) -> tuple[list[dict], dict]:
    import baostock as bs
    import baostock.common.context as state
    import baostock.util.socketutil as transport

    auth_id, _ = guard.reserve("baostock-auth:" + request_key, "baostock", "auth", 0)
    wire = BoundedSocket(
        socket.socket(socket.AF_INET, socket.SOCK_STREAM),
        policy.timeout_seconds,
        policy.max_response_bytes,
    )
    code = ("sz." if query.symbols[0].endswith(".XSHE") else "sh.") + query.symbols[0][:6]
    try:
        with (
            _SDK_LOCK,
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
            patch.object(state, "apiKey", "0", create=True),
            patch.object(
                transport,
                "socket",
                SimpleNamespace(
                    socket=lambda *_: wire, AF_INET=socket.AF_INET, SOCK_STREAM=socket.SOCK_STREAM
                ),
            ),
            patch.object(transport, "zlib", SimpleNamespace(decompress=wire.decompress)),
        ):
            if bs.login().error_code != "0":
                raise DataUnavailable(wire.failure or "BaoStock anonymous login failed")
            guard.record(auth_id, "success")
            result = bs.query_history_k_data_plus(
                code,
                "date,code,close",
                start_date=query.start.isoformat(),
                end_date=query.end.isoformat(),
                frequency="d",
                adjustflag="3",
            )
            if wire.failure:
                raise DataUnavailable(wire.failure)
            rows = normalize_rows(result, query)
            logout = bs.logout()
            return rows, {
                "sdk": "baostock==0.9.4",
                "endpoint": "public-api.baostock.com:10030",
                "requests": wire.wire,
                "received_bytes": wire.received,
                "response_sha256": wire.response_hash.hexdigest(),
                "logout_succeeded": logout.error_code == "0",
            }
    except Exception as exc:
        guard.record(auth_id, "failed_or_unknown")
        reason = str(exc) if isinstance(exc, DataUnavailable) else type(exc).__name__
        wire.failure = wire.failure or reason
        raise DataUnavailable(f"BaoStock {wire.failure}; no replay") from None
    finally:
        wire.close()
        audit = Path(guard.path).parent / "baostock-wire"
        audit.mkdir(exist_ok=True)
        with (audit / f"{request_key}.json").open("x") as stream:
            json.dump(
                {
                    "requests": wire.wire,
                    "failure": wire.failure,
                    "received_bytes": wire.received,
                    "response_sha256": wire.response_hash.hexdigest(),
                },
                stream,
            )
        with (audit / f"{request_key}.bin").open("xb") as stream:
            stream.write(wire.raw_response)
