import json
import threading
import urllib.error
import urllib.request
from http.client import RemoteDisconnected
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from qfh.budget import BudgetPolicy, Ledger
from qfh.proxy import GuardProxy


class SyntheticResponse:
    status_code = 200
    headers = {"content-type": "text/event-stream"}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def stream(self, *_args, **kwargs):
        assert kwargs["headers"]["x-deepseek-harness-session-id"] == "session-test"
        return self

    def iter_lines(self):
        events = [
            {
                "type": "message_start",
                "message": {
                    "usage": {
                        "input_tokens": 10,
                        "cache_read_input_tokens": 0,
                        "cache_creation_input_tokens": 0,
                        "output_tokens": 0,
                    }
                },
            },
            {"type": "message_delta", "usage": {"output_tokens": 10}},
            {"type": "message_stop"},
        ]
        for event in events:
            yield "event: " + event["type"]
            yield "data: " + json.dumps(event)
            yield ""


def ledger(tmp_path):
    config = Path(__file__).resolve().parents[1] / "configs/phase1.yaml"
    return Ledger(
        tmp_path / "ledger.sqlite3",
        BudgetPolicy.model_validate(yaml.safe_load(config.read_text())["budget"]),
    )


def request(proxy, key=None):
    return urllib.request.Request(
        proxy.base_url + "/v1/messages",
        data=json.dumps(
            {"model": "deepseek-flash", "stream": True, "max_tokens": 8192, "messages": []}
        ).encode(),
        headers={
            "x-api-key": key or proxy.local_key,
            "x-deepseek-harness-session-id": "session-test",
        },
    )


def test_every_loop_request_is_attributed_and_settled_before_terminal_event(tmp_path):
    book = ledger(tmp_path)
    book.grant_step("root", "trial", 2, 2, "offline test authority")
    with (
        patch("qfh.proxy.httpx.Client", return_value=SyntheticResponse()),
        patch("qfh.budget.admission_open", return_value=True),
    ):
        with GuardProxy(
            book,
            tmp_path / "wire",
            "fake",
            "deepseek-flash",
            8192,
            524288,
            10,
            session_admitter=lambda sid: "root" if sid == "session-test" else None,
        ) as proxy:
            for index in range(2):
                with urllib.request.urlopen(request(proxy), timeout=10) as response:
                    for line in response:
                        if line.startswith(b'data: {"type": "message_stop"'):
                            snap = book.snapshot()
                            assert snap["unresolved_micro_cny"] == 0
                            assert len(snap["calls"]) == index + 1
                            break
            with pytest.raises(urllib.error.HTTPError) as err:
                urllib.request.urlopen(request(proxy), timeout=10)
            assert err.value.code == 409
    assert len(book.snapshot()["calls"]) == 2


def test_invalid_local_credential_never_dispatches(tmp_path):
    book = ledger(tmp_path)
    with patch("qfh.proxy.httpx.Client", side_effect=AssertionError("must not dispatch")):
        with GuardProxy(
            book, tmp_path / "wire", "fake", "deepseek-flash", 8192, 524288, 10
        ) as proxy:
            with pytest.raises(urllib.error.HTTPError) as err:
                urllib.request.urlopen(request(proxy, "wrong-key"), timeout=10)
            assert err.value.code == 401
    assert not book.snapshot()["calls"]


def test_disconnected_browser_before_headers_still_drains_and_settles(tmp_path):
    book = ledger(tmp_path)
    drained = threading.Event()

    class Drained(SyntheticResponse):
        def iter_lines(self):
            yield from super().iter_lines()
            drained.set()

    with (
        patch("qfh.proxy.httpx.Client", return_value=Drained()),
        patch("qfh.budget.admission_open", return_value=True),
        patch("qfh.proxy.BaseHTTPRequestHandler.end_headers", side_effect=BrokenPipeError),
    ):
        with GuardProxy(
            book, tmp_path / "wire", "fake", "deepseek-flash", 8192, 524288, 10
        ) as proxy:
            proxy.step = "disconnected"
            with pytest.raises(RemoteDisconnected):
                urllib.request.urlopen(request(proxy), timeout=10)
            assert drained.wait(5)
    snap = book.snapshot()
    assert len(snap["calls"]) == 1
    assert snap["calls"][0]["state"] == "settled"
    assert snap["unresolved_micro_cny"] == 0
    result = json.loads(next((tmp_path / "wire").glob("*/result.json")).read_text())
    assert result["peer_connected"] is False


def test_window_close_drains_inflight_and_refuses_next_call(tmp_path):
    book = ledger(tmp_path)
    entered, release = threading.Event(), threading.Event()
    is_open = [True]

    class Slow(SyntheticResponse):
        def iter_lines(self):
            entered.set()
            assert release.wait(5)
            yield from super().iter_lines()

    errors = []
    with (
        patch("qfh.proxy.httpx.Client", return_value=Slow()),
        patch("qfh.budget.admission_open", side_effect=lambda _: is_open[0]),
    ):
        with GuardProxy(
            book, tmp_path / "wire", "fake", "deepseek-flash", 8192, 524288, 10
        ) as proxy:
            proxy.step = "first"

            def consume():
                try:
                    with urllib.request.urlopen(request(proxy), timeout=10) as response:
                        response.read()
                except Exception as exc:
                    errors.append(exc)

            thread = threading.Thread(target=consume)
            thread.start()
            assert entered.wait(5)
            is_open[0] = False
            release.set()
            thread.join(5)
            assert not errors and not thread.is_alive()
            assert book.snapshot()["unresolved_micro_cny"] == 0
            proxy.step = "second"
            with pytest.raises(urllib.error.HTTPError) as err:
                urllib.request.urlopen(request(proxy), timeout=10)
            assert err.value.code == 409
            assert "window" in json.load(err.value)["error"]["message"]
    assert len(book.snapshot()["calls"]) == 1
