"""Bounded real-process runtime tests, without licensed data, DB or sandbox mocks."""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError
from qfr_eval.runtime import capture_runtime, verify_runtime
from qfr_eval.runtime_contracts import RuntimeCompatibilityError, RuntimeIdentity

ROOT = Path(__file__).resolve().parents[2]

CHILD = r"""
import hashlib, json, os, sys
from datetime import date
from qfr_eval.runtime_contracts import RuntimeIdentity, RuntimeCompatibilityError
from qfr_eval.runtime_bootstrap import prepare_execution

data = json.load(sys.stdin)
pin = RuntimeIdentity.model_validate(data['pin']) if data['pin'] else None
if data['restore']:
    assert not any(name in sys.modules for name in ('numpy', 'polars', 'scipy'))
    prepare_execution(pin)
import polars as pl
from qfr_eval.runtime import capture_runtime, verify_runtime
from qfr_eval.statistics.diagnostics import yearly_deltas
from qfr_core.data_layer.snapshots import canonical_json
pin = pin or capture_runtime(evaluator_git_sha='0'*40, image_digest='0'*64)
try:
    verify_runtime(pin)
except RuntimeCompatibilityError as error:
    print(json.dumps({'refused': error.reason, 'effective_threads': pl.thread_pool_size()}))
    sys.exit(7)
values = [0.1, 0.2, -0.3, 1.23456789012345e-8] * 4096
frame = pl.DataFrame({'execution_date': [date(2023, 1, 1)]*len(values),
                     'exit_date': [date(2023, 1, 8)]*len(values), 'delta': values})
result = yearly_deltas(frame, 'delta')
print(json.dumps({'pin': pin.model_dump(mode='json'), 'result': result,
                  'result_hash': hashlib.sha256(canonical_json(result)).hexdigest(),
                  'effective_threads': pl.thread_pool_size(),
                  'provider_key_present': 'DEEPSEEK_API_KEY' in os.environ}))
"""


def child(pool, pin=None, *, restore=False):
    # Independent of test-runner/provider credentials and its numerical defaults.
    environment = {
        "PATH": str(Path(sys.executable).parent),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "37",
        "POLARS_MAX_THREADS": str(pool),
        "OPENBLAS_NUM_THREADS": "1",
        "OMP_NUM_THREADS": "1",
    }
    result = subprocess.run(
        [sys.executable, "-c", CHILD],
        cwd=ROOT,
        env=environment,
        input=json.dumps({"pin": pin, "restore": restore}),
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert result.returncode in {0, 7}, result.stderr
    return result.returncode, json.loads(result.stdout)


@pytest.fixture(scope="module")
def pinned_child():
    code, result = child(1)
    assert code == 0 and result["effective_threads"] == 1
    return result


def test_same_settings_reproduce_exact_unrounded_yearly_mean(pinned_child, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "synthetic-secret-never-forwarded")
    code, result = child(1, pinned_child["pin"])
    assert code == 0
    assert result["result_hash"] == pinned_child["result_hash"]
    assert result["result"] == pinned_child["result"]
    assert result["provider_key_present"] is False


def test_actual_different_pool_refused_before_measurement(pinned_child):
    code, result = child(2, pinned_child["pin"])
    assert code == 7
    assert result == {"refused": "numerical_execution", "effective_threads": 2}
    assert "result_hash" not in result


def test_frozen_startup_restored_before_library_initialization(pinned_child):
    code, result = child(2, pinned_child["pin"], restore=True)
    assert code == 0 and result["effective_threads"] == 1
    assert result["result_hash"] == pinned_child["result_hash"]
    assert result["pin"] == pinned_child["pin"]


def test_legacy_identity_preserves_serialization_and_refuses_execution():
    path = ROOT / "packages/qfr_eval/src/qfr_eval/private_contracts/RuntimeIdentity.valid.json"
    original = json.loads(path.read_bytes())
    legacy = RuntimeIdentity.model_validate(original)
    assert legacy.model_dump(mode="json") == original
    with pytest.raises(
        RuntimeCompatibilityError, match="legacy_runtime_missing_execution_identity"
    ):
        verify_runtime(legacy)


def test_execution_identity_requires_closed_validated_environment():
    runtime = capture_runtime(evaluator_git_sha="0" * 40, image_digest="0" * 64)
    value = runtime.model_dump(mode="json")
    value["numerical_execution"]["thread_environment"]["PYTHONPATH"] = "/unapproved"
    with pytest.raises(ValidationError, match="allowlist"):
        RuntimeIdentity.model_validate(value)
    value = runtime.model_dump(mode="json")
    value["numerical_execution"]["thread_environment"]["OMP_DYNAMIC"] = "TRUE"
    with pytest.raises(ValidationError, match="dynamic"):
        RuntimeIdentity.model_validate(value)
    with pytest.raises(ValidationError, match="v2 requires"):
        RuntimeIdentity.model_validate(
            {**runtime.model_dump(mode="json"), "numerical_execution": None}
        )


def test_effective_blas_change_is_rejected_and_restored():
    from qfr_eval.screening.worker import ScreeningWorker
    from threadpoolctl import threadpool_limits

    runtime = capture_runtime(evaluator_git_sha="0" * 40, image_digest="0" * 64)
    if runtime.numerical_execution.accelerate is not None:
        from qfr_eval.apple_runtime import threading_api

        getter, setter = threading_api()
        assert getter() == 1
        try:
            assert setter(0) == 0 and getter() == 0
            with pytest.raises(RuntimeCompatibilityError, match="accelerate_not_single_threaded"):
                verify_runtime(runtime)
            worker = object.__new__(ScreeningWorker)
            worker.runtime = runtime
            with pytest.raises(RuntimeCompatibilityError, match="accelerate_not_single_threaded"):
                worker.run_once()
        finally:
            assert setter(1) == 0 and getter() == 1
        verify_runtime(runtime)
        return
    pools = {
        lib.num_threads for lib in runtime.numerical_execution.libraries if lib.user_api == "blas"
    }
    changed = 2 if pools == {1} else 1
    with threadpool_limits(limits=changed, user_api="blas"):
        with pytest.raises(RuntimeCompatibilityError, match="numerical_execution"):
            verify_runtime(runtime)
        # Drift after worker construction must fail before claiming queued work.
        worker = object.__new__(ScreeningWorker)
        worker.runtime = runtime
        with pytest.raises(RuntimeCompatibilityError, match="numerical_execution"):
            worker.run_once()
    verify_runtime(runtime)


def test_bootstrap_refuses_late_initialization_without_touching_environment():
    from qfr_eval.runtime_bootstrap import prepare_execution

    runtime = capture_runtime(evaluator_git_sha="0" * 40, image_digest="0" * 64)
    original = os.environ.get("POLARS_MAX_THREADS")
    with pytest.raises(RuntimeCompatibilityError, match="already_initialized"):
        prepare_execution(runtime)
    assert os.environ.get("POLARS_MAX_THREADS") == original


def test_early_context_loader_checks_hash_and_path_before_using_identity(tmp_path, monkeypatch):
    from qfr_eval import runtime_bootstrap as bootstrap

    runtime = capture_runtime(evaluator_git_sha="0" * 40, image_digest="0" * 64)
    content = json.dumps({"request": {"runtime": runtime.model_dump(mode="json")}}).encode()
    context = tmp_path / "context.json"
    context.write_bytes(content)
    record_id = UUID(int=17)
    descriptor = {
        "relative_path": "context.json",
        "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }
    payload = {
        "record": {"record_id": str(record_id)},
        "receipt": {"files": {"context": descriptor}},
    }

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, query, parameters):
            assert query.startswith("SELECT ") and parameters == [record_id]
            return self

        def fetchone(self):
            return (payload,)

    # Unit test of the file/identity boundary; this is not a live database gate.
    monkeypatch.setattr(bootstrap, "connection_dsn", lambda: "synthetic")
    monkeypatch.setattr(bootstrap.psycopg, "connect", lambda *a, **k: Connection())
    assert bootstrap._reproduction_runtime(record_id, tmp_path) == runtime
    context.write_bytes(content + b" ")
    with pytest.raises(RuntimeCompatibilityError, match="frozen_context_hash"):
        bootstrap._reproduction_runtime(record_id, tmp_path)
    context.write_bytes(content)
    descriptor["relative_path"] = "../outside"
    with pytest.raises(RuntimeCompatibilityError, match="frozen_context_path"):
        bootstrap._reproduction_runtime(record_id, tmp_path)


def test_v2_schema_fixture_round_trip():
    from jsonschema import Draft202012Validator

    root = ROOT / "packages/qfr_eval/src/qfr_eval/private_contracts"
    value = json.loads((root / "RuntimeIdentityV2.valid.json").read_bytes())
    Draft202012Validator(
        json.loads((root / "RuntimeIdentityV2.schema.json").read_bytes())
    ).validate(value)
    assert RuntimeIdentity.model_validate(value).model_dump(mode="json") == value
    assert value["schema_version"] == "2"
