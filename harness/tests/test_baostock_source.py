import zlib
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from qfh.baostock_source import HOST, BoundedSocket, normalize_rows
from qfh.evidence import Query
from qfh.ricequant import DataUnavailable

QUERY = Query(symbols=["000001.XSHE"], start="2026-10-28", end="2026-10-30")


def result(**overrides):
    return SimpleNamespace(
        **{
            "error_code": "0",
            "fields": ["date", "code", "close"],
            "code": "sz.000001",
            "adjustflag": "3",
            "frequency": "d",
            "data": [["2026-10-28", "sz.000001", "11.3100"]],
            **overrides,
        }
    )


def test_daily_price_identity_and_no_sdk_pagination():
    # next/get_data are deliberately absent: neither can fetch an implicit second page.
    assert normalize_rows(result(), QUERY) == [
        {"symbol": "000001.XSHE", "date": "2026-10-28", "close": 11.31}
    ]


@pytest.mark.parametrize(
    "overrides",
    [
        {"error_code": "10001006"},
        {"adjustflag": "2"},
        {"frequency": "w"},
        {"fields": ["date", "close"]},
        {"code": "sh.600000"},
        {"data": [["2026-10-28", "sh.600000", "11.31"]]},
        {"data": [["2026-10-31", "sz.000001", "11.31"]]},
        {"data": [["2026-10-28", "sz.000001", "NaN"]]},
        {"data": [["2026-10-28", "sz.000001", "0"]]},
        {"data": [["2026-10-28", "sz.000001", "11.31"]] * 2},
        {"data": [["2026-10-28", "sz.000001", "11.31"]] * 4},
    ],
)
def test_invalid_provider_rows_are_not_evidence(overrides):
    with pytest.raises(DataUnavailable):
        normalize_rows(result(**overrides), QUERY)


class Socket:
    def __init__(self, content=b""):
        self.content, self.sent = content, []

    def settimeout(self, _):
        pass

    def connect(self, address):
        assert address == HOST

    def sendall(self, content):
        self.sent.append(content)

    def recv(self, size):
        value, self.content = self.content[:size], self.content[size:]
        return value


def test_socket_stops_extra_pages_retries_and_wrong_endpoint():
    raw = Socket()
    wire = BoundedSocket(raw, 30, 1024)
    wire.connect(HOST)
    wire.send(b"00.9.40\x0100\x010\x01login\n")
    wire.send(b"00.9.40\x0195\x010\x01query\n")
    with pytest.raises(DataUnavailable, match="extra request"):
        wire.send(b"00.9.40\x0195\x010\x01another-page\n")
    assert len(raw.sent) == 2
    with pytest.raises(DataUnavailable, match="endpoint"):
        BoundedSocket(raw, 30, 1024).connect(("vip-api.baostock.com", 10030))


def test_socket_bounds_eof_bytes_deadline_and_decompression():
    with pytest.raises(DataUnavailable, match="closed"):
        BoundedSocket(Socket(), 30, 1024).recv(8192)
    with pytest.raises(DataUnavailable, match="byte limit"):
        BoundedSocket(Socket(b"x" * 1025), 30, 1024).recv(8192)
    wire = BoundedSocket(Socket(), 30, 1024)
    wire.deadline = 0
    with pytest.raises(DataUnavailable, match="deadline"):
        wire.connect(HOST)
    with pytest.raises(DataUnavailable, match="decompressed"):
        wire.decompress(zlib.compress(b"x" * 1025))
    assert wire.decompress(zlib.compress(b"short result")) == b"short result\n"
    assert wire.decompress(zlib.compress(b"short result\n")) == b"short result\n"


def test_real_sdk_preserves_adjustment_when_server_omits_final_newline():
    import baostock as bs
    import baostock.common.context as context
    import baostock.util.socketutil as transport

    body = (
        b"0\x01success\x01query_history_k_data_plus\x01anonymous\x011\x012000\x01"
        b'{"record":[["2026-10-28","sz.000001","11.3100"]]}\x01sz.000001\x01'
        b"date,code,close\x012026-10-28\x012026-10-30\x01d\x013"
    )
    wire = BoundedSocket(Socket(), 30, 1024)
    response = "00.9.40\x0196\x010000000000" + wire.decompress(zlib.compress(body)).decode()
    with (
        patch.object(context, "user_id", "anonymous", create=True),
        patch.object(transport, "send_msg", return_value=response),
    ):
        actual = bs.query_history_k_data_plus(
            "sz.000001",
            "date,code,close",
            start_date="2026-10-28",
            end_date="2026-10-30",
            frequency="d",
            adjustflag="3",
        )
    assert actual.adjustflag == "3"
    assert normalize_rows(actual, QUERY)[0]["close"] == 11.31
