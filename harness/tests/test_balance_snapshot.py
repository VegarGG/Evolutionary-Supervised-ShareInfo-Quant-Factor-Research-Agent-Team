import importlib.util
import json
import sys
from pathlib import Path

import pytest


def load_script():
    path = Path(__file__).resolve().parents[1] / "scripts/balance_snapshot.py"
    spec = importlib.util.spec_from_file_location("balance_snapshot", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_balance_observation_is_read_only_redacted_and_not_replayed(tmp_path, monkeypatch):
    module = load_script()
    secret = "sk-synthetic-key-for-offline-test-only"
    key = tmp_path / "key.txt"
    key.write_text(secret)
    output = tmp_path / "balance.jsonl"
    monkeypatch.setattr(sys, "argv", ["snapshot", "--key-file", str(key), "--output", str(output)])
    monkeypatch.setattr(module, "admission_open", lambda _: True)
    requests = []

    class Client:
        def __init__(self, **kwargs):
            assert kwargs["trust_env"] is False
            assert kwargs["follow_redirects"] is False

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def stream(self, method, endpoint, headers):
            assert method == "GET" and endpoint == "https://api.deepseek.com/user/balance"
            assert headers == {"Authorization": "Bearer " + secret}
            requests.append(endpoint)
            return self

        def raise_for_status(self):
            pass

        def iter_bytes(self):
            yield json.dumps(
                {
                    "is_available": True,
                    "balance_infos": [
                        {
                            "currency": "CNY",
                            "total_balance": "10.123456",
                            "granted_balance": "0",
                            "topped_up_balance": "10.123456",
                        }
                    ],
                    "unexpected_secret_echo": secret,
                }
            ).encode()

    monkeypatch.setattr(module.httpx, "Client", Client)
    module.main()
    records = [json.loads(line) for line in output.read_text().splitlines()]
    assert [r["status"] for r in records] == ["attempting", "success"]
    assert records[1]["account"]["balance_infos"][0]["total_balance"] == "10.123456"
    assert secret not in output.read_text()
    assert output.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        module.main()
    assert len(requests) == 1


def test_balance_observation_closed_window_stops_before_key_or_network(tmp_path, monkeypatch):
    module = load_script()
    output = tmp_path / "balance.jsonl"
    monkeypatch.setattr(
        sys, "argv", ["snapshot", "--key-file", "missing-key", "--output", str(output)]
    )
    monkeypatch.setattr(module, "admission_open", lambda _: False)
    monkeypatch.setattr(module.httpx, "Client", lambda **_: pytest.fail("must not request"))
    with pytest.raises(SystemExit, match="deferred"):
        module.main()
    assert not output.exists()
