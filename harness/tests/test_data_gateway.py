import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import httpx
import pandas as pd
import pytest
import yaml

from qfh.data_gateway import DataGuard, DataPolicy, dispatch
from qfh.ricequant import DataUnavailable

POLICY = DataPolicy.model_validate(
    yaml.safe_load((Path(__file__).parents[1] / "configs/data-pilot.yaml").read_text())
).model_copy(update={"provider_allowances": {}})


def request(**overrides):
    return {
        "provider": "ifind",
        "run_id": "session-1",
        "kind": "bars",
        "query": {"symbols": ["000001.XSHE"], "start": "2026-10-28", "end": "2026-10-30"},
        "credentials": {"access_token": "dummy-secret"},
        **overrides,
    }


def response():
    return {
        "errorcode": 0,
        "dataVol": 3,
        "tables": [
            {
                "thscode": "000001.SZ",
                "time": ["2026-10-28", "2026-10-29", "2026-10-30"],
                "table": {"close": ["10.25", 10.5, None]},
            }
        ],
    }


def client_for(body=None, status=200):
    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(status, json=body if body is not None else response())

    return httpx.Client(transport=httpx.MockTransport(handler)), calls


def test_small_quote_cache_and_scoped_read(tmp_path):
    client, calls = client_for()
    result = dispatch(request(), POLICY, tmp_path, ifind_client=client)
    assert result["row_count"] == 3
    assert result["content"][0]["close"] == 10.25
    assert result["reported_data_volume"] == 3
    assert not result["cache_reused"]
    assert len(calls) == 1
    wire = json.loads(calls[0].content)
    assert wire["codes"] == "000001.SZ"
    assert wire["indicators"] == "close"
    assert wire["functionpara"]["CPS"] == "no"
    cached = dispatch(request(run_id="session-2"), POLICY, tmp_path, ifind_client=client)
    assert cached["cache_reused"] and cached["evidence_id"] == result["evidence_id"]
    assert len(calls) == 1
    read = request(kind="read", evidence_id=result["evidence_id"], offset=1, limit=1)
    assert dispatch(read, POLICY, tmp_path)["content"][0]["close"] == 10.5
    with pytest.raises(DataUnavailable, match="not been granted"):
        dispatch({**read, "run_id": "unrelated"}, POLICY, tmp_path)
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert b"dummy-secret" not in path.read_bytes()


def test_changed_run_or_account_cannot_reset_global_allowance(tmp_path):
    client, calls = client_for()
    dispatch(request(), POLICY, tmp_path, ifind_client=client)
    changed = request(run_id="new", credentials={"access_token": "another-dummy"})
    with pytest.raises(DataUnavailable, match="allowance"):
        dispatch(changed, POLICY, tmp_path, ifind_client=client)
    assert len(calls) == 1


def test_no_switch_or_fallback_within_session(tmp_path):
    client, calls = client_for()
    dispatch(request(), POLICY, tmp_path, ifind_client=client)
    with pytest.raises(ValueError, match="pinned"):
        dispatch(request(provider="rqdata"), POLICY, tmp_path)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "query",
    [
        {"symbols": ["000001.XSHE", "600000.XSHG"], "start": "2026-10-28", "end": "2026-10-30"},
        {"symbols": ["000001.XSHE"], "start": "2026-10-27", "end": "2026-10-30"},
        {"symbols": ["000001.XSHE"], "start": "2026-11-01", "end": "2026-11-02"},
    ],
)
def test_scope_refused_before_dispatch(tmp_path, query):
    client, calls = client_for()
    with pytest.raises(ValueError):
        dispatch(request(query=query), POLICY, tmp_path, ifind_client=client)
    assert calls == []


@pytest.mark.parametrize("kind", ["news", "announcements", "report_summaries"])
def test_expensive_pilot_operations_are_disabled(tmp_path, kind):
    client, calls = client_for()
    with pytest.raises(ValueError, match="not enabled"):
        dispatch(request(kind=kind), POLICY, tmp_path, ifind_client=client)
    assert not calls


@pytest.mark.parametrize("code", [-1302, -4318, "dummy-secret"])
def test_business_error_is_not_http_success_and_never_retried(tmp_path, code):
    client, calls = client_for({"errorcode": code, "errmsg": "dummy-secret"})
    with pytest.raises(DataUnavailable) as error:
        dispatch(request(), POLICY, tmp_path, ifind_client=client)
    assert "dummy-secret" not in str(error.value)
    with pytest.raises(DataUnavailable, match="no automatic replay"):
        dispatch(request(), POLICY, tmp_path, ifind_client=client)
    assert len(calls) == 1
    with sqlite3.connect(tmp_path / "data-usage.sqlite3") as db:
        assert db.execute("SELECT outcome FROM requests").fetchone()[0] == "failed_or_unknown"


@pytest.mark.parametrize("mutation", ["stock", "arrays", "duplicate", "outside", "nan", "negative"])
def test_malformed_quotes_are_retained_as_failed_not_cached(tmp_path, mutation):
    body = deepcopy(response())
    table = body["tables"][0]
    if mutation == "stock":
        table["thscode"] = "600000.SH"
    if mutation == "arrays":
        table["time"] = []
    if mutation == "duplicate":
        table["time"][1] = table["time"][0]
    if mutation == "outside":
        table["time"][0] = "2026-11-01"
    if mutation == "nan":
        table["table"]["close"][0] = "NaN"
    if mutation == "negative":
        table["table"]["close"][0] = -1
    client, calls = client_for(body)
    with pytest.raises(DataUnavailable):
        dispatch(request(), POLICY, tmp_path, ifind_client=client)
    assert len(calls) == 1
    assert not list((tmp_path / "evidence").glob("*.json"))


def test_refresh_reads_current_token_without_rotation(tmp_path):
    calls = []

    def handler(req):
        calls.append(req)
        if req.url.path.endswith("/get_access_token"):
            assert req.headers["refresh_token"] == "dummy-refresh"
            return httpx.Response(
                200, json={"errorcode": 0, "data": {"access_token": "dummy-access"}}
            )
        assert req.headers["access_token"] == "dummy-access"
        return httpx.Response(200, json=response())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = dispatch(
        request(credentials={"refresh_token": "dummy-refresh"}),
        POLICY,
        tmp_path,
        ifind_client=client,
    )
    assert result["row_count"] == 3
    assert len(calls) == 2
    assert all("update_access_token" not in str(x.url) for x in calls)
    assert dispatch(
        request(credentials={"refresh_token": "dummy-refresh"}),
        POLICY,
        tmp_path,
        ifind_client=client,
    )["cache_reused"]
    assert len(calls) == 2


def test_data_allowance_is_atomic_across_workers(tmp_path):
    def attempt(n):
        guard = DataGuard(tmp_path / "quota.sqlite3", POLICY)
        try:
            return guard.reserve(str(n), "ifind", "bars", 3)[0]
        except DataUnavailable:
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(attempt, range(8)))
    assert sum(x is not None for x in results) == 1


def test_rqdata_uses_same_close_only_query_and_cache(tmp_path):
    seen = []

    def price(**kwargs):
        seen.append(kwargs)
        return pd.DataFrame([{"date": "2026-10-28", "close": 10.25}])

    result = dispatch(
        request(provider="rqdata", credentials={"license": "dummy-license"}),
        POLICY,
        tmp_path,
        rq_client=SimpleNamespace(get_price=price),
    )
    assert result["row_count"] == 1
    assert seen[0]["fields"] == ["close"]
    assert seen[0]["adjust_type"] == "none"
    assert dispatch(
        request(provider="rqdata", credentials={"license": "dummy-license"}),
        POLICY,
        tmp_path,
        rq_client=SimpleNamespace(get_price=price),
    )["cache_reused"]
    assert len(seen) == 1


def test_provider_value_error_is_redacted(tmp_path):
    def price(**_):
        raise ValueError("license=dummy-license")

    with pytest.raises(DataUnavailable) as error:
        dispatch(
            request(provider="rqdata", credentials={"license": "dummy-license"}),
            POLICY,
            tmp_path,
            rq_client=SimpleNamespace(get_price=price),
        )
    assert "dummy-license" not in str(error.value)


def test_request_validation_never_echoes_credentials_or_dispatches(tmp_path):
    client, calls = client_for()
    with pytest.raises(ValueError) as error:
        dispatch(
            request(credentials={"access_token": {"secret": "do-not-echo"}}),
            POLICY,
            tmp_path,
            ifind_client=client,
        )
    assert "do-not-echo" not in str(error.value)
    assert not calls


def test_free_source_needs_no_key_and_does_not_spend_ifind_allowance(tmp_path):
    free_calls = []

    def fetch(query, policy, guard, key):
        free_calls.append(query)
        auth_id, _ = guard.reserve("bao-auth:" + key, "baostock", "auth", 0)
        guard.record(auth_id, "success")
        return [{"date": "2026-10-28", "symbol": "000001.XSHE", "close": 11.31}], {}

    free = request(provider="baostock", credentials={})
    result = dispatch(free, POLICY, tmp_path, baostock_fetch=fetch)
    assert result["provider"] == "baostock" and not result["cache_reused"]
    assert dispatch(
        {**free, "run_id": "another-free-session"}, POLICY, tmp_path, baostock_fetch=fetch
    )["cache_reused"]
    assert len(free_calls) == 1
    with pytest.raises(ValueError, match="pinned"):
        dispatch(request(), POLICY, tmp_path)
    client, paid_calls = client_for()
    dispatch(request(run_id="paid-session"), POLICY, tmp_path, ifind_client=client)
    assert len(paid_calls) == 1
    changed = {
        **free,
        "run_id": "third-free-session",
        "query": {**free["query"], "start": "2026-10-29"},
    }
    with pytest.raises(DataUnavailable, match="allowance"):
        dispatch(changed, POLICY, tmp_path, baostock_fetch=fetch)
    assert len(free_calls) == 1


def test_free_source_rejects_accidental_credentials_and_cannot_read_paid_evidence(tmp_path):
    with pytest.raises(ValueError, match="invalid data request"):
        dispatch(request(provider="baostock"), POLICY, tmp_path)
    client, _ = client_for()
    paid = dispatch(request(), POLICY, tmp_path, ifind_client=client)
    with pytest.raises(DataUnavailable, match="not been granted"):
        dispatch(
            request(
                provider="baostock",
                credentials={},
                run_id="free",
                kind="read",
                evidence_id=paid["evidence_id"],
            ),
            POLICY,
            tmp_path,
        )


def test_free_retry_allowance_cannot_increase_paid_caps(tmp_path):
    from qfh.data_gateway import DataAllowance

    policy = POLICY.model_copy(
        update={
            "provider_allowances": {
                "baostock": DataAllowance(
                    max_business_requests=2, max_auth_requests=2, max_estimated_cells=6
                )
            }
        }
    )
    guard = DataGuard(tmp_path / "usage.sqlite3", policy)
    guard.reserve("free-1", "baostock", "bars", 3)
    guard.reserve("free-2", "baostock", "bars", 3)
    with pytest.raises(DataUnavailable, match="allowance"):
        guard.reserve("free-3", "baostock", "bars", 3)
    guard.reserve("paid-1", "ifind", "bars", 3)
    with pytest.raises(DataUnavailable, match="allowance"):
        guard.reserve("paid-2", "ifind", "bars", 3)
