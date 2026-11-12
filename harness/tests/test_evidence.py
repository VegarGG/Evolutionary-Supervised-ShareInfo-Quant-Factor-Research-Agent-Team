from datetime import datetime
from types import SimpleNamespace

import pandas as pd
import pytest

from qfh.evidence import EvidenceStore, Query
from qfh.ricequant import DataUnavailable, RiceQuantTools


def test_evidence_is_content_addressed_and_detects_tampering(tmp_path):
    store = EvidenceStore(tmp_path)
    digest = store.put({"text": "中国 A 股"})
    assert store.put({"text": "中国 A 股"}) == digest
    assert store.get(digest)["text"] == "中国 A 股"
    with pytest.raises(ValueError):
        store.get("../../secrets")
    (tmp_path / f"{digest}.json").write_text("{}")
    with pytest.raises(ValueError, match="hash"):
        store.get(digest)


def test_late_ingestion_is_withheld_even_if_publication_is_earlier(tmp_path):
    frame = pd.DataFrame(
        [
            {"info_date": "2024-01-02", "rice_create_tm": "2024-02-01", "title": "late"},
            {"info_date": "2024-01-02", "rice_create_tm": "2024-01-03", "title": "eligible"},
        ]
    )
    client = SimpleNamespace(get_announcement=lambda **_: frame)
    tools = RiceQuantTools(
        client, EvidenceStore(tmp_path), datetime.fromisoformat("2024-01-31T23:59:59.999999+08:00")
    )
    result = tools.fetch(
        "announcements", Query(symbols=["000001.XSHE"], start="2024-01-01", end="2024-01-31")
    )
    assert result["row_count"] == result["excluded_rows"] == 1
    assert result["preview"][0]["title"] == "eligible"
    with pytest.raises(ValueError, match="cutoff"):
        tools.fetch(
            "announcements", Query(symbols=["000001.XSHE"], start="2024-02-01", end="2024-02-02")
        )


def test_source_failure_never_returns_fixture_data_or_credentials(tmp_path):
    def failed(**_):
        raise RuntimeError("password=secret-value")

    tools = RiceQuantTools(
        SimpleNamespace(get_price=failed),
        EvidenceStore(tmp_path),
        datetime.fromisoformat("2024-01-31T23:59:59.999999+08:00"),
    )
    with pytest.raises(DataUnavailable) as caught:
        tools.fetch("bars", Query(symbols=["000001.XSHE"], start="2024-01-02", end="2024-01-03"))
    assert "secret-value" not in str(caught.value)
    assert list(tmp_path.iterdir()) == []


def test_query_limits_apply_before_source_call():
    for args in [
        {"symbols": ["AAPL"]},
        {"symbols": ["000001.XSHE"] * 6},
        {"symbols": ["000001.XSHE"], "end": "2025-01-01"},
    ]:
        with pytest.raises(ValueError):
            Query(**{"start": "2024-01-01", "end": "2024-01-02", **args})
