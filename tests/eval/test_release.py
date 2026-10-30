"""release-worker (P3.5): REL-01 rounding, REL-02 batch-time visibility, REL-04 schema and
whitelist; library changes are released immediately."""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from qfr_core.contracts import ReleasedReport
from qfr_eval.plugins import quantize
from qfr_eval.reports import next_w1_batch
from starlette.testclient import TestClient

from tests.eval.stack_rig import eval_apps
from tests.mcp.setup_rig import EVAL_TOKENS
from tests.registry_rig import factor_manifest

SCHEMA = json.loads(Path("schemas/public/released_report.json").read_text())


@pytest.mark.parametrize(
    ("value", "step", "expected"),
    [
        (0.0125, 0.005, 0.015),
        (-0.0125, 0.005, -0.015),
        (0.01249, 0.005, 0.01),
        (0.0, 0.005, 0.0),
        (-0.001, 0.005, 0.0),
        (1.13, 0.25, 1.25),
        (0.6249, 0.05, 0.6),
        (0.625, 0.05, 0.65),
    ],
)
def test_rel_01_values_round_half_away_from_zero_to_the_policy_step(value, step, expected):
    released = quantize(value, step)
    assert released == expected
    assert (Decimal(repr(released)) / Decimal(repr(step))) % 1 == 0


@pytest.mark.parametrize(
    ("decided", "batch"),
    [
        ("2026-01-05T01:00:00", "2026-01-05T06:00:00"),
        ("2026-01-05T06:00:00", "2026-01-05T12:00:00"),  # strictly after the decision
        ("2026-01-05T05:59:59", "2026-01-05T06:00:00"),
        ("2026-01-05T23:10:00", "2026-01-06T00:00:00"),
    ],
)
def test_w1_batches_are_the_next_six_hour_boundary_in_utc(decided, batch):
    at = datetime.fromisoformat(decided).replace(tzinfo=UTC)
    assert next_w1_batch(at, 6) == datetime.fromisoformat(batch).replace(tzinfo=UTC)


@pytest.mark.postgres
def test_rel_02_reports_become_visible_only_at_their_batch_time(rig):
    _, feedback_app = eval_apps(rig)
    version = rig.registry.publish(factor_manifest("timed", "Pct($close, 20)")).json()["version"]
    rig.cycle()  # decided at 01:00; the batch is 06:00
    with TestClient(feedback_app, base_url="http://feedback-api:8000") as client:
        client.headers["Authorization"] = f"Bearer {EVAL_TOKENS['feedback-api']}"
        assert rig.release.tick().released == 0
        rig.clock.advance(hours=4, minutes=59)
        assert rig.release.tick().released == 0
        assert client.get("/v1/reports").json()["items"] == []
        assert client.get(f"/v1/artifacts/{version['version_id']}/status").status_code == 404
        rig.clock.advance(minutes=1)
        released = rig.release.tick()
        assert released.released == 3  # intake, screening, w1
        items = client.get("/v1/reports").json()["items"]
        assert [i["content"]["type"] for i in items] == ["intake", "screening", "w1"]
        assert {i["released_at"] for i in items} == {"2026-01-05T06:00:00Z"}
        status = client.get(f"/v1/artifacts/{version['version_id']}/status").json()
        assert status["report_type"] == "w1" and len(status["timeline"]) == 3


@pytest.mark.postgres
def test_rel_02_a_report_dated_in_the_future_stays_hidden_from_feedback(rig):
    _, feedback_app = eval_apps(rig)
    rig.registry.publish(factor_manifest("future", "Pct($close, 10)"))
    rig.cycle()
    rig.clock.at = datetime.now(UTC) + timedelta(days=2)
    assert rig.release.tick().released == 3
    assert rig.db.scalar("SELECT count(*) FROM eval.released_reports") == 3
    with TestClient(feedback_app, base_url="http://feedback-api:8000") as client:
        client.headers["Authorization"] = f"Bearer {EVAL_TOKENS['feedback-api']}"
        assert client.get("/v1/reports").json()["items"] == []


@pytest.mark.postgres
def test_rel_04_every_released_report_validates_and_carries_only_whitelisted_fields(rig):
    validator = Draft202012Validator(SCHEMA)
    for name, expression in (("ok", "Pct($close, 20)"), ("flat", "Sign($close)"),
                             ("dup", "Pct($close,20)")):  # fmt: skip
        rig.registry.publish(factor_manifest(name, expression))
    rig.cycle()
    rig.clock.advance(hours=6)
    rig.release.tick()
    rows = rig.db.rows("SELECT report_type, report FROM eval.released_reports")
    assert {r.report_type for r in rows} == {"intake", "screening", "w1"}
    for row in rows:
        validator.validate(row.report)
        ReleasedReport.model_validate(row.report)
        text = json.dumps(row.report)
        for forbidden in ("Traceback", "stack", "seconds", "peak_rss", "probe_cuts", "W1\"",
                          "2011-"):  # fmt: skip
            assert forbidden not in text, (forbidden, row.report_type)
    # The schema itself forbids anything outside the whitelist.
    report = rows[0].report | {"debug": "x"}
    assert not validator.is_valid(report)
    w1 = next(r.report for r in rows if r.report_type == "w1")
    assert not validator.is_valid(w1 | {"content": w1["content"] | {"rankic_raw": 0.0123}})
    flagged = w1["content"]["flags"]
    assert set(flagged) <= set(SCHEMA["$defs"]["DiagnosticFlag"]["enum"])


@pytest.mark.postgres
def test_library_changes_are_released_immediately(stack_full):
    from tests.eval.test_e2e import entries

    stack_full.mcp.ok("qfr.pool.import", entries=entries()[:2])
    stack_full.eval.scheduler.tick()
    released = stack_full.eval.release.tick()
    assert released.by_type.get("library") == 2
    library = stack_full.mcp.ok("qfr.report.list", type="library")["data"]["items"]
    assert {r["content"]["status"] for r in library} == {"seed"}


@pytest.fixture
def stack_full(tmp_path, monkeypatch, small_zones):
    from tests.eval.stack_rig import stack

    with stack(tmp_path, monkeypatch, small_zones) as built:
        yield built
