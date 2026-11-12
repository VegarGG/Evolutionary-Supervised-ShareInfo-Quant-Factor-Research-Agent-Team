"""Real DSH tool-loop smoke against synthetic model output and local fixture evidence."""

import argparse
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import httpx
import yaml
from deepseek_harness import DeepSeekHarness
from runtime_smoke import Response

from qfh.budget import BudgetPolicy, Ledger
from qfh.data_gateway import DataGuard, DataPolicy, dispatch
from qfh.evidence import EvidenceStore
from qfh.proxy import GuardProxy

TOOLS = {
    "market_daily_bars",
    "research_reports",
    "company_announcements",
    "research_news",
    "read_research_evidence",
}


class ToolResponse(Response):
    def __init__(self, tool, arguments):
        self.tool, self.arguments = tool, arguments

    def iter_lines(self):
        for line in super().iter_lines():
            if not line.startswith("data: "):
                yield line
                continue
            event = json.loads(line[6:])
            if event["type"] == "content_block_start":
                event["content_block"] = {
                    "type": "tool_use",
                    "id": "synthetic-read-1",
                    "name": self.tool,
                    "input": {},
                }
            elif event["type"] == "content_block_delta":
                event["delta"] = {
                    "type": "input_json_delta",
                    "partial_json": json.dumps(self.arguments),
                }
            elif event["type"] == "message_delta":
                event["delta"]["stop_reason"] = "tool_use"
            yield "data: " + json.dumps(event)


class Client(Response):
    def __init__(self, tool, arguments):
        self.calls, self.tool, self.arguments = [], tool, arguments

    def stream(self, *_args, **kwargs):
        self.calls.append(json.loads(kwargs["content"]))
        return ToolResponse(self.tool, self.arguments) if len(self.calls) == 1 else Response()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--cached-fetch", action="store_true")
    parser.add_argument(
        "--real-cache-root",
        type=Path,
        help="Read already-fetched BaoStock evidence; model replies stay synthetic",
    )
    args = parser.parse_args()
    directory = args.directory.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[1]
    subprocess.run(
        [
            str(Path(sys.executable).with_name("dsh")),
            "plugin",
            "--profile",
            "sdk-minimal",
            "add",
            f"file:{root / 'dsh-plugin'}",
        ],
        env={**os.environ, "DSH_HOME": str(directory / "home")},
        check=True,
    )
    policy = DataPolicy.model_validate(
        yaml.safe_load((root / "configs/data-pilot.yaml").read_text())
    )
    data = directory / "data"
    provider, expected_price = "ifind", "10.25"
    evidence_id = EvidenceStore(data / "evidence").put(
        {
            "provider": "ifind",
            "synthetic": True,
            "research_cutoff": policy.research_cutoff.isoformat(),
            "content": [{"date": "2026-10-28", "close": 10.25, "symbol": "000001.XSHE"}],
        }
    )
    guard = DataGuard(data / "data-usage.sqlite3", policy)
    guard.pin("qfh-tool-smoke", "ifind")
    guard.grant("qfh-tool-smoke", evidence_id)
    tool, arguments = "read_research_evidence", {"evidence_id": evidence_id, "limit": 1}
    if args.cached_fetch and not args.real_cache_root:
        credentials = {"access_token": "qfh-dummy-tool-smoke"}
        query = {"symbols": ["000001.XSHE"], "start": "2026-10-28", "end": "2026-10-30"}
        response = {
            "errorcode": 0,
            "tables": [
                {"thscode": "000001.SZ", "time": ["2026-10-28"], "table": {"close": [10.25]}}
            ],
        }
        with httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response))
        ) as mock:
            dispatch(
                {
                    "provider": "ifind",
                    "kind": "bars",
                    "run_id": "qfh-tool-smoke",
                    "query": query,
                    "credentials": credentials,
                },
                policy,
                data,
                ifind_client=mock,
            )
        credential_file = directory / "home/.credentials.yaml"
        credential_file.write_text(
            yaml.safe_dump(
                {
                    "version": 1,
                    "refs": {"QFH_IFIND_CREDENTIAL": json.dumps(credentials)},
                    "records": {},
                }
            )
        )
        credential_file.chmod(0o600)
        tool, arguments = "market_daily_bars", query
    if args.real_cache_root:
        data = args.real_cache_root.resolve()
        provider = "baostock"
        with sqlite3.connect(f"file:{data / 'data-usage.sqlite3'}?mode=ro", uri=True) as db:
            saved = db.execute(
                "SELECT result_id FROM requests WHERE provider='baostock' "
                "AND kind='bars' AND outcome='success'"
            ).fetchall()
            before = db.execute("SELECT COUNT(*) FROM requests").fetchone()[0]
        assert len(saved) == 1, "A completed BaoStock pilot is required"
        real = EvidenceStore(data / "evidence").get(saved[0][0])
        tool, arguments = "market_daily_bars", real["query"]
        expected_price = str(real["content"][0]["close"])
        guard = DataGuard(data / "data-usage.sqlite3", policy)
    else:
        before = int(args.cached_fetch)
    plugin = directory / "data.patch.yml"
    plugin.write_text(
        yaml.safe_dump(
            [
                {
                    "insert": [
                        {
                            "id": "qfh-credentials",
                            "name": "@deepseek-ai/dsh-credentials-local",
                            "config": {"path": str(directory / "home/.credentials.yaml")},
                        },
                        {
                            "id": "qfh-data-test",
                            "name": "@qfh/dsh-data",
                            "config": {
                                "activeProvider": provider,
                                "python": sys.executable,
                                "sourceRoot": str(root / "src"),
                                "policyPath": str(root / "configs/data-pilot.yaml"),
                                "privateRoot": str(data),
                                "requestTimeoutMs": 90000,
                            },
                        },
                    ]
                },
                {"id": "qfh-data", "disabled": True},
            ]
        )
    )
    config = yaml.safe_load((root / "configs/phase1.yaml").read_text())["budget"]
    config["max_requests_per_step"] = 2
    ledger = Ledger(directory / "synthetic-ledger.sqlite3", BudgetPolicy.model_validate(config))
    client = Client(tool, arguments)
    with patch("qfh.proxy.httpx.Client", return_value=client):
        with patch("qfh.budget.admission_open", return_value=True):
            with GuardProxy(
                ledger, directory / "wire", "no-real-key", "deepseek-flash", 8192, 524288, 30
            ) as proxy:
                proxy.allowed_tools = TOOLS
                proxy.step = "synthetic-tool-smoke"
                with DeepSeekHarness(
                    dsh_home=str(directory / "home"),
                    cwd=str(directory),
                    runtime_cwd=str(directory),
                    profile="sdk-minimal",
                    patches=(str(root / "configs/diagnostic.patch.yml"), str(plugin)),
                    provider="deepseek-official",
                    model="deepseek-flash",
                    max_tokens=8192,
                    api_key=proxy.local_key,
                    base_url=proxy.base_url,
                    env={"DSH_PRIMARY_RUNTIME": ""},
                    shutdown_timeout_seconds=10,
                ) as harness:
                    result = harness.run("Read the given evidence.", session_id="qfh-tool-smoke")
                    (directory / "runtime-stderr.txt").write_text(
                        "\n".join(harness.client._stderr_lines)
                    )
                    assert result.finish_reason == "completed", result
    assert len(client.calls) == 2
    assert {t["name"] for t in client.calls[0]["tools"]} == TOOLS
    returned = [
        part
        for message in client.calls[1]["messages"]
        for part in message["content"]
        if isinstance(part, dict) and part.get("type") == "tool_result"
    ]
    assert returned and not any(part.get("is_error") for part in returned), returned
    assert expected_price in json.dumps(returned), returned
    if args.real_cache_root:
        assert '"cache_reused":true' in json.dumps(returned).replace('\\"', '"').replace(" ", "")
    with guard.db() as db:
        assert db.execute("SELECT COUNT(*) FROM requests").fetchone()[0] == before
    assert "qfh-dummy-tool-smoke" not in json.dumps(client.calls)
    report = {
        "status": "pass",
        "actual_runtime": "DSH 0.2.2rc2",
        "tools": sorted(TOOLS),
        "provider_requests": 0,
        "data_requests": 0,
        "source": "real BaoStock cached evidence"
        if args.real_cache_root
        else "synthetic cached evidence",
        "model": "synthetic response through the actual DSH runtime",
    }
    (directory / "RESULT.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == "__main__":
    main()
