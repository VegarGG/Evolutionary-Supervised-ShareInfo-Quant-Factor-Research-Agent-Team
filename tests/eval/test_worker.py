"""eval-worker (P3.3, P3.4): the limited compute runner, screening checks, and W1 runs that
write runs, metrics, series, official records and trial-ledger rows in one transaction."""

import polars as pl
import pytest
from qfr_core.operators import evaluate
from qfr_eval.compute import ComputeRequest, InlineRunner, SubprocessRunner
from qfr_eval.contracts import OfficialRecord
from qfr_eval.plugins import results_hash

from tests.eval.eval_rig import eval_rig
from tests.registry_rig import factor_manifest
from tests.synthetic_fixtures import ELIGIBILITY, PROTOCOL

pytestmark = pytest.mark.postgres
GB = 1024**3


def request(zones, tmp_path, expression="Mean($close, 5) / Mean($close, 20) - 1", **overrides):
    values = {
        "snapshot_path": str(zones.full.path),
        "expression": expression,
        "dsl": PROTOCOL["dsl"],
        "eligibility": ELIGIBILITY,
        "rows": list(range(400, 440)),
        "probe_cuts": [405, 420],
        "tolerance": 1e-9,
        "cpu_seconds": 60.0,
        "memory_bytes": 4 * GB,
        "load_cpu_seconds": 60.0,
        "output_path": str(tmp_path / "values.npy"),
    }
    return ComputeRequest.model_validate(values | overrides)


def peeking(panel: pl.DataFrame, tree, eligibility) -> pl.Series:
    """A test-only lookahead operator: tomorrow's close, whatever the expression says."""
    evaluate(panel, tree, eligibility)
    return panel.select(pl.col("close").shift(-1).over("instrument")).to_series()


def test_subprocess_runner_matches_inline_and_passes_the_probe(small_zones, tmp_path):
    inline = InlineRunner().run(request(small_zones, tmp_path))
    child = SubprocessRunner(3, tmp_path / "scratch").run(request(small_zones, tmp_path))
    assert inline.result.status == child.result.status == "ok"
    assert [p.mismatches for p in child.result.probes] == [0, 0]
    assert child.values.shape == (40, child.result.instruments)
    assert ((child.values == inline.values) | (child.values != child.values)).all()


def test_runtime_limits_stop_the_child_on_cpu_and_memory(small_zones, tmp_path):
    runner = SubprocessRunner(3, tmp_path / "scratch")
    heavy = "Corr(Rank($close), Rank($volume), 250) * Skew($close, 250) + Kurt($volume, 250)"
    cpu = runner.run(request(small_zones, tmp_path, heavy, cpu_seconds=0.001,
                             load_cpu_seconds=1.0))  # fmt: skip
    assert (cpu.result.status, cpu.result.limit) == ("runtime_limit", "cpu")
    memory = runner.run(request(small_zones, tmp_path, memory_bytes=32 * 1024 * 1024))
    assert (memory.result.status, memory.result.limit) == ("runtime_limit", "memory")


def test_compute_reports_dsl_errors_by_code(small_zones, tmp_path):
    result = InlineRunner().run(request(small_zones, tmp_path, "Mean($close, 7)")).result
    assert result.status == "dsl_error" and result.error_code


def test_evl_03_the_prefix_probe_catches_an_injected_lookahead_operator(small_zones, tmp_path):
    with eval_rig(tmp_path, small_zones, runner=InlineRunner(peeking)) as rig:
        response = rig.registry.publish(factor_manifest("peek", "Mean($close, 5)"))
        version = response.json()["version"]["version_id"]
        rig.cycle()
        row = rig.db.rows(
            "SELECT state, reason_code FROM eval.intake WHERE version_id = :v", v=version
        )[0]
        assert row.state == "ScreenFailed"
        record = rig.db.rows(
            "SELECT metrics, summary FROM eval.official_records WHERE version_id = :v", v=version
        )[0]
        assert "LOOKAHEAD_DETECTED" in record.summary["reasons"]
        assert record.metrics["probe_mismatches"] > 0
        assert (
            rig.db.scalar("SELECT count(*) FROM eval.trial_ledger WHERE version_id = :v", v=version)
            == 0
        )  # screening failures are not W1 trials


@pytest.mark.parametrize(
    ("expression", "reason"),
    [("Sign($close)", "DEGENERATE"), ("Log(-$close)", "LOW_COVERAGE")],
)
def test_screening_failures_are_recorded_with_reason_codes(rig, expression, reason):
    version = rig.registry.publish(factor_manifest("screened", expression)).json()["version"]
    rig.cycle()
    record = rig.db.rows(
        "SELECT stage, summary FROM eval.official_records WHERE version_id = :v",
        v=version["version_id"],
    )
    assert [r.stage for r in record] == ["screening"]
    assert reason in record[0].summary["reasons"]
    rig.release.tick()
    screening = rig.db.rows(
        "SELECT report FROM eval.released_reports WHERE version_id = :v "
        "AND report_type = 'screening'",
        v=version["version_id"],
    )[0].report["content"]
    assert screening["status"] == "FAIL" and reason in screening["reasons"]


def test_w1_writes_complete_records_and_a_ledger_row_per_trial(rig):
    versions = [
        rig.registry.publish(factor_manifest(n, e)).json()["version"]["version_id"]
        for n, e in (("a", "Pct($close, 20)"), ("b", "Corr($close, $volume, 10)"))
    ]
    rig.cycle()
    for version in versions:
        records = rig.db.rows(
            "SELECT * FROM eval.official_records WHERE version_id = :v ORDER BY stage", v=version
        )
        assert [r.stage for r in records] == ["screening", "w1"]
        for row in records:  # EVL-02: every reference is set and the record validates
            for column in ("version_id", "content_hash", "protocol_id", "protocol_version",
                           "snapshot_id", "code_version", "epoch_id", "image_digest"):  # fmt: skip
                assert getattr(row, column), column
            assert row.window_name == "W1"
            assert row.results_hash == results_hash(dict(row.metrics))
        w1 = records[1]
        ledger = rig.db.rows("SELECT * FROM eval.trial_ledger WHERE version_id = :v", v=version)
        assert len(ledger) == 1 and ledger[0].record_id == w1.record_id  # EVL-06
        assert ledger[0].window_name == "W1"
        runs = rig.db.rows("SELECT run_id, status FROM eval.runs WHERE version_id = :v", v=version)
        assert len(runs) == 2 and set(w1.run_ids) <= {r.run_id for r in runs}
        series = {
            r.kind
            for r in rig.db.rows(
                "SELECT kind FROM eval.series_files WHERE run_id = ANY(:runs)",
                runs=list(w1.run_ids),
            )
        }
        assert series == {"rankic", "ls_returns", "nav", "factor_values"}
        metrics = rig.db.scalar(
            "SELECT count(*) FROM eval.metrics WHERE run_id = ANY(:runs)", runs=list(w1.run_ids)
        )
        assert metrics == len(w1.metrics)
    evidence = rig.db.rows("SELECT * FROM eval.official_records")
    assert all(OfficialRecord.model_validate(
        {"schema_version": "official_record/1", **_record(r)}) for r in evidence)  # fmt: skip
    burn = rig.db.scalar("SELECT trials FROM eval.burn_meters WHERE window_name = 'W1'")
    assert burn == 2


def _record(row):
    return {
        "record_id": row.record_id, "version_id": row.version_id,
        "content_hash": row.content_hash, "protocol_id": row.protocol_id,
        "protocol_version": row.protocol_version, "data_snapshot_id": row.snapshot_id,
        "evaluator_code_version": row.code_version, "epoch_id": row.epoch_id,
        "family_id": row.family_id, "program_id": row.program_id, "job_id": row.job_id,
        "stage": row.stage, "window": row.window_name, "run_ids": list(row.run_ids),
        "container_image_digest": row.image_digest, "seed": row.seed,
        "summary": dict(row.summary), "metrics": dict(row.metrics),
        "results_hash": row.results_hash, "created_at": row.created_at,
        "principal": row.principal, "request_id": row.request_id,
    }  # fmt: skip


def test_an_internal_error_is_retried_then_released_as_internal_error(small_zones, tmp_path):
    def broken(panel, tree, eligibility):
        raise RuntimeError("evaluator bug")

    with eval_rig(tmp_path, small_zones, runner=InlineRunner(broken)) as rig:
        version = rig.registry.publish(factor_manifest("unlucky", "Pct($close, 5)")).json()
        version_id = version["version"]["version_id"]
        rig.cycle()
        for _ in range(8):  # fingerprint attempts, then screening attempts, with backoff
            rig.clock.advance(seconds=max(rig.worker.config.worker.retry_backoff_seconds) + 1)
            rig.cycle(1)
        state = rig.db.rows(
            "SELECT state, reason_code FROM eval.intake WHERE version_id = :v", v=version_id
        )[0]
        assert (state.state, state.reason_code) == ("ScreenFailed", "INTERNAL_ERROR")
        jobs = rig.db.rows(
            "SELECT attempts, state FROM eval.queue_jobs WHERE version_id = :v "
            "AND kind = 'evaluate'",
            v=version_id,
        )
        assert jobs[0].attempts == rig.worker.config.worker.max_attempts
        assert rig.db.scalar("SELECT count(*) FROM eval.trial_ledger") == 0
