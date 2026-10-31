"""release-worker (P3.5): REL-01 rounding, REL-02 immediate release, REL-04 schema and
whitelist; library changes are released immediately too."""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from qfr_core.contracts import ReleasedReport
from qfr_eval.plugins import quantize
from qfr_eval.runtime import eval_config
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


@pytest.mark.postgres
def test_rel_02_reports_are_released_as_soon_as_the_evaluator_records_them(rig):
    _, feedback_app = eval_apps(rig)
    version = rig.registry.publish(factor_manifest("timed", "Pct($close, 20)")).json()["version"]
    rig.cycle()  # pulled, screened and evaluated on W1 at 01:00
    queued = rig.db.rows("SELECT due_at, created_at FROM eval.release_queue")
    assert len(queued) == 3 and all(r.due_at == r.created_at for r in queued)
    with TestClient(feedback_app, base_url="http://feedback-api:8000") as client:
        client.headers["Authorization"] = f"Bearer {EVAL_TOKENS['feedback-api']}"
        released = rig.release.tick()  # the next tick, with no clock movement
        assert released.released == 3 and released.waiting == 0  # intake, screening, w1
        items = client.get("/v1/reports").json()["items"]
        assert [i["content"]["type"] for i in items] == ["intake", "screening", "w1"]
        assert {i["released_at"] for i in items} == {"2026-01-05T01:00:00Z"}
        status = client.get(f"/v1/artifacts/{version['version_id']}/status").json()
        assert status["report_type"] == "w1" and len(status["timeline"]) == 3
        assert rig.release.tick().released == 0  # each report is released once


def test_the_release_engine_looks_for_new_reports_every_second():
    assert eval_config(Path("configs")).release.interval_seconds <= 1


@pytest.mark.postgres
def test_a_report_stamped_in_the_future_stays_hidden_from_feedback(rig):
    # A guard in the feedback views (released_at <= now()); nothing is stamped ahead now.
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
