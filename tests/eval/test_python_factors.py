"""Python factors end to end (P8.1): the registry checks a qfr-python/1 module without
running it, and the evaluator measures it only through the sandbox."""

from pathlib import Path

import pytest
from qfr_eval.compute import InlineRunner
from qfr_eval.reproduce import reproduce
from qfr_eval.runtime import EvalConfig, eval_config
from qfr_eval.worker import Evaluator, MarketCache, make_python_runner

from tests.eval.eval_rig import eval_rig
from tests.eval.test_sandbox import CUMULATIVE_PY, LOOKAHEAD_PY
from tests.registry_rig import factor_manifest, headers, python_manifest, strategy_manifest

pytestmark = pytest.mark.postgres


def local_sandbox() -> EvalConfig:
    config = eval_config(Path("configs"))
    return config.model_copy(
        update={"sandbox": config.sandbox.model_copy(update={"mode": "local"})}
    )


@pytest.fixture
def prig(tmp_path, small_zones):
    with eval_rig(tmp_path, small_zones, config=local_sandbox()) as built:
        yield built


def _state(rig, version):
    return rig.db.rows(
        "SELECT state, reason_code FROM eval.intake WHERE version_id = :v", v=version
    )[0]


def test_the_registry_checks_python_modules_without_running_them(prig):
    registry = prig.registry
    ok = registry.publish(python_manifest())
    assert ok.status_code == 201, ok.json()
    version = ok.json()["version"]
    assert version["analysis"]["language"] == "qfr-python/1"
    assert version["analysis"]["fields"] == ["close"]
    refused = registry.publish(
        python_manifest("bad", "import os\ndef factor(close):\n    return close\n")
    )
    assert refused.status_code == 400 and refused.json()["error"] == "FORBIDDEN_CONSTRUCT"
    mismatch = registry.publish(python_manifest("wrong", fields=["close", "volume"]))
    assert mismatch.status_code == 400 and mismatch.json()["error"] == "DECLARATION_MISMATCH"
    # A Python version derived from a DSL parent: the edge names the two modules.
    parent = registry.publish(factor_manifest("dsl_parent")).json()["version"]
    published = registry.publish(python_manifest("py_child", parents=[parent["version_id"]]))
    child = published.json()["version"]
    view = registry.client.get(
        f"/v1/artifacts/{child['version_id']}/lineage?depth=1", headers=headers("reader")
    ).json()
    edge = next(e for e in view["edges"] if e["version_id"] == child["version_id"])
    [step] = edge["ast_diff"]
    assert (step["op"], step["path"]) == ("replace_module", [])
    assert step["from"] == parent["analysis"]["canonical"]
    assert len(step["to"]) == 64 and step["to"] != step["from"]  # the module's hash


def test_a_python_factor_is_screened_and_measured_on_w1_through_the_sandbox(prig):
    version = prig.registry.publish(python_manifest()).json()["version"]["version_id"]
    prig.cycle()
    records = prig.db.rows(
        "SELECT stage, metrics, summary, results_hash FROM eval.official_records "
        "WHERE version_id = :v ORDER BY stage",
        v=version,
    )
    assert [r.stage for r in records] == ["screening", "w1"]
    screening = records[0]
    assert screening.summary["status"] == "PASS"
    assert screening.metrics["probe_mismatches"] == 0
    assert screening.metrics["window_probe_mismatches"] == 0
    assert screening.metrics["window_probe_cut_dates"] == 5
    runs = prig.db.rows(
        "SELECT resources FROM eval.runs WHERE version_id = :v AND stage = 'screening'",
        v=version,
    )
    assert runs[0].resources["sandbox"]["sandbox_runs"] >= 6
    # EVL-04 holds for Python factors: reproduce re-runs the sandbox and matches.
    evaluator = Evaluator(
        prig.env, InlineRunner(), MarketCache(prig.env.full_snapshot_dir),
        make_python_runner(local_sandbox(), prig.env, prig.tmp_path / "repro"),
    )  # fmt: skip
    record_ids = prig.db.rows(
        "SELECT record_id FROM eval.official_records WHERE version_id = :v", v=version
    )
    for row in record_ids:
        result = reproduce(prig.db, prig.env, local_sandbox(), row.record_id, evaluator)
        assert result["match"] is True, result


@pytest.mark.parametrize(
    ("source", "reason", "metric"),
    [
        (LOOKAHEAD_PY, "LOOKAHEAD_DETECTED", "probe_mismatches"),
        (CUMULATIVE_PY, "DECLARATION_MISMATCH", "window_probe_mismatches"),
    ],
)
def test_evl_03_python_lookahead_and_dishonest_lookback_fail_screening(
    prig, source, reason, metric
):
    lookback = 1 if source == LOOKAHEAD_PY else 20
    manifest = python_manifest("cheat", source, lookback=lookback)
    version = prig.registry.publish(manifest).json()["version"]["version_id"]
    prig.cycle()
    assert _state(prig, version).state == "ScreenFailed"
    record = prig.db.rows(
        "SELECT metrics, summary FROM eval.official_records WHERE version_id = :v", v=version
    )[0]
    assert reason in record.summary["reasons"]
    assert record.metrics[metric] > 0


def test_a_python_factor_can_be_a_strategy_component(prig):
    python = prig.registry.publish(python_manifest()).json()["version"]["version_id"]
    dsl = prig.registry.publish(factor_manifest("dsl_leg", "Corr($close, $volume, 10)")).json()
    prig.cycle()
    strategy = prig.registry.publish(
        strategy_manifest([(python, 1, 0.5), (dsl["version"]["version_id"], -1, 0.5)])
    ).json()["version"]["version_id"]
    prig.cycle()
    stages = [
        r.stage
        for r in prig.db.rows(
            "SELECT stage FROM eval.official_records WHERE version_id = :v ORDER BY stage",
            v=strategy,
        )
    ]
    assert stages[:1] == ["screening"]
    assert _state(prig, strategy).state not in ("Failed", "InternalError")


def test_without_a_sandbox_a_python_factor_is_never_run_in_the_worker(tmp_path, small_zones):
    # The shipped config sends Python factors to the exchange volume; with none mounted
    # the worker has no Python runner and the job fails as an internal error.
    with eval_rig(tmp_path, small_zones) as rig:
        assert rig.worker.evaluator.python is None
        version = rig.registry.publish(python_manifest()).json()["version"]["version_id"]
        rig.cycle()
        assert _state(rig, version).state != "W1Evaluated"
        assert not rig.db.rows(
            "SELECT 1 FROM eval.official_records WHERE version_id = :v AND stage = 'w1'",
            v=version,
        )
