"""Bounded worker lifecycle checks; Apple API checks require the actual Mac."""

import hashlib
import os
import platform
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import polars as pl
import pytest
from qfr_core.data_layer.snapshots import canonical_json
from qfr_eval import apple_runtime
from qfr_eval.runtime import capture_runtime, initialize_worker_thread, verify_runtime
from qfr_eval.runtime_contracts import (
    THREAD_VARIABLES,
    RuntimeCompatibilityError,
    RuntimeIdentity,
)
from qfr_eval.runtime_threads import initialize_thread_controls
from qfr_eval.statistics.diagnostics import yearly_deltas


def pin():
    return capture_runtime(evaluator_git_sha="0" * 40, image_digest="0" * 64)


def exact_result():
    values = [0.1, 0.2, -0.3, 1.23456789012345e-8] * 512
    frame = pl.DataFrame(
        {
            "execution_date": [date(2023, 1, 1)] * len(values),
            "exit_date": [date(2023, 1, 8)] * len(values),
            "delta": values,
        }
    )
    return hashlib.sha256(canonical_json(yearly_deltas(frame, "delta"))).hexdigest()


def test_each_real_worker_initializes_verifies_and_matches_exact_result():
    runtime = pin()
    expected = exact_result()
    environment = {key: os.environ.get(key) for key in THREAD_VARIABLES}
    barrier = threading.Barrier(4, timeout=20)

    def work():
        barrier.wait()
        verify_runtime(runtime)
        result = exact_result()
        # Reusing an initialized worker must still observe its actual state.
        initialize_worker_thread(runtime)
        return threading.get_ident(), result

    with ThreadPoolExecutor(4, initializer=initialize_worker_thread, initargs=(runtime,)) as pool:
        futures = [pool.submit(work) for _ in range(4)]
        results = [future.result(timeout=30) for future in futures]
    assert len({identity for identity, _ in results}) == 4
    assert {result for _, result in results} == {expected}
    assert {key: os.environ.get(key) for key in THREAD_VARIABLES} == environment
    verify_runtime(runtime)


def test_worker_refuses_process_wide_pool_mismatch_without_reconfiguring_it():
    runtime = pin()
    value = runtime.model_dump(mode="json")
    execution = value["numerical_execution"]
    execution["polars_threads"] += 1
    execution["thread_environment"]["POLARS_MAX_THREADS"] = str(execution["polars_threads"])
    incompatible = RuntimeIdentity.model_validate(value)
    environment = {key: os.environ.get(key) for key in THREAD_VARIABLES}
    pool_size = pl.thread_pool_size()

    def work():
        with pytest.raises(RuntimeCompatibilityError, match="numerical_execution"):
            initialize_worker_thread(incompatible)
        assert pl.thread_pool_size() == pool_size
        assert {key: os.environ.get(key) for key in THREAD_VARIABLES} == environment

    with ThreadPoolExecutor(1) as pool:
        pool.submit(work).result(timeout=20)
    verify_runtime(runtime)


def test_worker_checks_implementation_before_any_thread_configuration(monkeypatch):
    runtime = pin().model_copy(update={"implementation_sha256": "0" * 64})

    def forbidden(**kwargs):
        raise AssertionError("must refuse before initialization")

    monkeypatch.setattr("qfr_eval.runtime.initialize_thread_controls", forbidden)
    with ThreadPoolExecutor(1) as pool:
        with pytest.raises(RuntimeCompatibilityError, match="implementation_or_software"):
            pool.submit(initialize_worker_thread, runtime).result(timeout=20)


def test_synthetic_thread_setup_is_independent_once_and_never_repairs_drift(monkeypatch):
    # This unit tests lifecycle bookkeeping; it is not native Accelerate evidence.
    state = threading.local()
    barrier = threading.Barrier(2, timeout=5)

    def configure():
        state.calls = getattr(state, "calls", 0) + 1
        state.mode = 1

    monkeypatch.setattr(apple_runtime, "initialize_single_thread", configure)

    def work():
        initialize_thread_controls(accelerate=True)
        barrier.wait()
        assert state.calls == 1 and state.mode == 1
        state.mode = 0
        initialize_thread_controls(accelerate=True)
        assert state.calls == 1 and state.mode == 0
        with pytest.raises(RuntimeCompatibilityError, match="thread_numerical_backend_changed"):
            initialize_thread_controls(accelerate=False)
        return threading.get_ident()

    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(work) for _ in range(2)]
        assert len({future.result(timeout=10) for future in futures}) == 2


def test_synthetic_failed_thread_setup_cannot_retry_into_success(monkeypatch):
    calls = []

    def unavailable():
        calls.append(threading.get_ident())
        raise RuntimeCompatibilityError("accelerate_single_thread_request_failed")

    monkeypatch.setattr(apple_runtime, "initialize_single_thread", unavailable)
    with ThreadPoolExecutor(1) as pool:
        with pytest.raises(
            RuntimeCompatibilityError, match="accelerate_single_thread_request_failed"
        ):
            pool.submit(initialize_thread_controls, accelerate=True).result(timeout=10)
        with pytest.raises(RuntimeCompatibilityError, match="thread_initialization_failed"):
            pool.submit(initialize_thread_controls, accelerate=True).result(timeout=10)
    assert len(calls) == 1


@pytest.mark.skipif(
    platform.system() != "Darwin", reason="UNRUN: native Apple worker APIs required"
)
def test_native_reused_worker_and_capture_refuse_drift_before_claim():
    from qfr_eval.screening.worker import ScreeningWorker

    runtime = pin()
    assert runtime.numerical_execution.accelerate is not None
    getter, setter = apple_runtime.threading_api()

    def work():
        assert getter() == 1
        try:
            assert setter(0) == 0 and getter() == 0
            for check in (initialize_worker_thread, verify_runtime):
                with pytest.raises(
                    RuntimeCompatibilityError, match="accelerate_not_single_threaded"
                ):
                    check(runtime)
                assert getter() == 0
            with pytest.raises(RuntimeCompatibilityError, match="accelerate_not_single_threaded"):
                pin()
            worker = object.__new__(ScreeningWorker)
            worker.runtime = runtime
            with pytest.raises(RuntimeCompatibilityError, match="accelerate_not_single_threaded"):
                worker.run_once()  # Has no scheduler: any claim attempt would fail this assertion.
            assert getter() == 0
        finally:
            assert setter(1) == 0 and getter() == 1
        verify_runtime(runtime)

    with ThreadPoolExecutor(1, initializer=initialize_worker_thread, initargs=(runtime,)) as pool:
        pool.submit(work).result(timeout=30)
    assert getter() == 1
    verify_runtime(runtime)
