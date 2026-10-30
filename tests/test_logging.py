import io
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pytest
from qfr_core.config import logging_config, mcp_config
from qfr_core.contracts import LogLine
from qfr_core.correlation import bind, current, from_headers, from_queue, to_headers, to_queue
from qfr_core.log_reader import LogQuery, LogReader
from qfr_core.logging import JsonLogger, assert_provider_boundary

SERVICES = {
    "qfr-mcp": "control",
    "research-api": "research",
    "research-worker": "research",
    "registry-api": "registry",
    "eval-scheduler": "eval",
    "eval-worker": "eval",
    "release-worker": "eval",
    "sim-engine": "eval",
    "feedback-api": "eval",
    "eval-admin-api": "eval",
    "data-ingest": "eval",
    "migrate": "control",
    "cli": "control",
}


@pytest.mark.parametrize("service,zone", SERVICES.items())
def test_log_01_log_02_all_services_redact_every_sink(tmp_path, monkeypatch, service, zone):
    arbitrary_secret = "unshaped-test-secret-2d7b"
    monkeypatch.setenv("TEST_DATABASE_PASSWORD", arbitrary_secret)
    output = io.StringIO()
    logger = JsonLogger(service, zone, tmp_path, logging_config(Path("configs")), stdout=output)
    fake = "sk-" + "1234abcdefgh" * 4
    with bind(request_id="r1", job_id="j1", version_id="v1"):
        try:
            raise RuntimeError("injected " + fake + " " + arbitrary_secret)
        except RuntimeError:
            logger.logger.error(
                "test_exception",
                exc_info=True,
                payload={
                    "config": {"API_KEY": fake},
                    "prompt": fake,
                    "nested": [fake],
                    fake: "secret-shaped dictionary key",
                },
            )
    stdout = output.getvalue()
    files = "".join(p.read_text() for p in tmp_path.glob("*/*.jsonl"))
    assert stdout == files
    assert fake not in stdout
    assert arbitrary_secret not in stdout
    row = LogLine.model_validate_json(stdout)
    assert row.service == service and row.zone == zone
    assert row.request_id == "r1" and row.job_id == "j1" and row.version_id == "v1"
    assert "[REDACTED]" in stdout


def test_context_headers_and_queue_round_trip_isolate_concurrent_tasks():
    def task(job):
        with bind(request_id=job, job_id=job):
            assert from_headers(to_headers())["job_id"] == job
            assert from_queue(to_queue())["request_id"] == job
            return current()

    with ThreadPoolExecutor() as executor:
        values = list(executor.map(task, ["a", "b"]))
    assert [v["job_id"] for v in values] == ["a", "b"]
    assert not current()


def test_log_rotation_pagination_and_correlation(tmp_path):
    config = logging_config(Path("configs")).model_copy(update={"rotate_bytes": 450})
    logger = JsonLogger("cli", "control", tmp_path, config, stdout=io.StringIO())
    with bind(request_id="r", job_id="job"):
        for i in range(8):
            logger.logger.info("state_changed", payload={"sequence": i})
    assert len(list(tmp_path.glob("cli/*.jsonl"))) > 1
    reader = LogReader(tmp_path, config, mcp_config(Path("configs")))
    query = LogQuery(limit=3)
    first = reader.search(query)
    second = reader.search(query.model_copy(update={"cursor": first.next_cursor}))
    assert [r.payload["sequence"] for r in first.lines + second.lines] == list(range(6))
    assert [r.payload["sequence"] for r in reader.tail(n=2).lines] == [6, 7]
    correlated = reader.correlate("job", "job", LogQuery())
    assert len(correlated["lines"]) == 8
    assert list(correlated["grouped_by_service"]) == ["cli"]
    with pytest.raises(ValueError):
        reader.search(query.model_copy(update={"text": "changed", "cursor": first.next_cursor}))
    with pytest.raises(ValueError):
        reader.search(LogQuery(limit=2001))


def test_log_reader_will_not_follow_outside_symlinks(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "logs"
    root.mkdir()
    (root / "service").symlink_to(outside, target_is_directory=True)
    row = {
        "ts": datetime.now(UTC).isoformat(),
        "level": "INFO",
        "service": "service",
        "zone": "eval",
        "event": "secret_record",
        "request_id": "r",
    }
    (outside / (row["ts"][:10] + ".jsonl")).write_text(json.dumps(row))
    reader = LogReader(root, logging_config(Path("configs")), mcp_config(Path("configs")))
    assert not reader.search(LogQuery()).lines


def test_bnd_07_startup_refuses_even_an_empty_provider_variable(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    with pytest.raises(RuntimeError, match="BND-07"):
        assert_provider_boundary("qfr-mcp")
    assert_provider_boundary("research-worker")


def test_long_log_ranges_require_both_explicit_dates(tmp_path):
    reader = LogReader(tmp_path, logging_config(Path("configs")), mcp_config(Path("configs")))
    with pytest.raises(ValueError, match="explicit dates"):
        reader.search(LogQuery.model_validate({"from": "2000-01-01T00:00:00Z"}))
    assert not reader.search(
        LogQuery.model_validate(
            {
                "from": "2000-01-01T00:00:00Z",
                "to": "2000-02-01T00:00:00Z",
            }
        )
    ).lines
