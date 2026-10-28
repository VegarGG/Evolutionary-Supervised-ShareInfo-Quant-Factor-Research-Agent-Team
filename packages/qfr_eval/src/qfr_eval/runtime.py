"""Pinned local implementation identity; no environment/credential enumeration."""

import hashlib
import importlib.metadata
import json
import os
import platform
from functools import lru_cache
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

import numpy as np
import polars as pl
import qfr_core
import scipy.linalg
from qfr_core.data_layer.snapshots import canonical_json
from threadpoolctl import threadpool_info

import qfr_eval
from qfr_eval.backtest.scorers import ScorerSpec
from qfr_eval.runtime_contracts import (
    THREAD_VARIABLES,
    NumericalExecution,
    NumericalLibrary,
    RuntimeCompatibilityError,
    RuntimeIdentity,
)
from qfr_eval.runtime_threads import initialize_thread_controls


def implementation_hash() -> str:
    digest = hashlib.sha256()
    for name, package in [("qfr_core", qfr_core), ("qfr_eval", qfr_eval)]:
        if package.__file__ is None:
            raise ValueError("installed evaluator source identity unavailable")
        root = Path(package.__file__).parent
        for path in sorted(root.rglob("*")):
            if path.suffix in {".py", ".sql", ".json"} and path.is_file():
                digest.update(
                    canonical_json([name, str(path.relative_to(root)), path.read_bytes().hex()])
                )
    return digest.hexdigest()


def software_identity() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        **{
            name: importlib.metadata.version(name)
            for name in ["numpy", "polars", "scipy", "pydantic", "psycopg", "threadpoolctl"]
        },
    }


@lru_cache(maxsize=32)
def _binary_hash(path: str, size: int, modified: int) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def numerical_execution() -> NumericalExecution:
    # Load the numerical backends used by measurement before inspecting their
    # actual pools. No configured environment label substitutes for observation.
    _ = np.linalg, scipy.linalg
    controls = {
        "openblas": "OPENBLAS_NUM_THREADS",
        "openmp": "OMP_NUM_THREADS",
        "mkl": "MKL_NUM_THREADS",
        "blis": "BLIS_NUM_THREADS",
    }
    environment = {key: os.environ.get(key) for key in THREAD_VARIABLES}
    for key in ("OMP_DYNAMIC", "MKL_DYNAMIC"):
        value = environment[key]
        if value is not None:
            environment[key] = value.upper()
    threads = pl.thread_pool_size()
    environment["POLARS_MAX_THREADS"] = str(threads)
    libraries = []
    counts: dict[str, int] = {}
    try:
        from qfr_eval import apple_runtime

        apple_consumers = apple_runtime.consumers()
        accelerate = apple_runtime.observe(apple_consumers) if apple_consumers else None
        for item in threadpool_info():
            api = item["internal_api"]
            if api not in controls:
                raise RuntimeCompatibilityError("unsupported_numerical_backend")
            count = item["num_threads"]
            if api in counts and counts[api] != count:
                raise RuntimeCompatibilityError("incompatible_library_thread_pools")
            counts[api] = count
            environment[controls[api]] = str(count)
            binary = Path(item["filepath"])
            stat = binary.stat()
            libraries.append(
                NumericalLibrary(
                    user_api=item["user_api"],
                    internal_api=api,
                    prefix=item["prefix"],
                    version=item.get("version"),
                    num_threads=count,
                    architecture=item.get("architecture"),
                    threading_layer=item.get("threading_layer"),
                    binary_sha256=_binary_hash(str(binary), stat.st_size, stat.st_mtime_ns),
                )
            )
        libraries.sort(key=lambda item: canonical_json(item.model_dump(mode="json")))
        return NumericalExecution(
            schema_version="2" if accelerate else "1",
            system=platform.system(),
            machine=platform.machine(),
            polars_threads=threads,
            thread_environment=environment,
            libraries=libraries,
            accelerate=accelerate,
        )
    except RuntimeCompatibilityError:
        raise
    except (ValueError, KeyError, TypeError, OSError):
        raise RuntimeCompatibilityError("unobservable_numerical_execution") from None


def capture_runtime(*, evaluator_git_sha: str, image_digest: str) -> RuntimeIdentity:
    from qfr_eval import apple_runtime

    # New threads select the fixed calling-thread profile. A later capture on
    # the same thread must observe drift rather than silently repairing it.
    initialize_thread_controls(accelerate=bool(apple_runtime.consumers()))
    return RuntimeIdentity(
        schema_version="2",
        evaluator_git_sha=evaluator_git_sha,
        implementation_sha256=implementation_hash(),
        image_digest=image_digest,
        software=software_identity(),
        numerical_execution=numerical_execution(),
    )


def _verified_implementation(runtime: RuntimeIdentity) -> NumericalExecution:
    if runtime.schema_version != "2" or runtime.numerical_execution is None:
        raise RuntimeCompatibilityError("legacy_runtime_missing_execution_identity")
    if (
        runtime.implementation_sha256 != implementation_hash()
        or runtime.software != software_identity()
    ):
        raise RuntimeCompatibilityError("implementation_or_software")
    return runtime.numerical_execution


def initialize_worker_thread(runtime: RuntimeIdentity) -> None:
    """Trusted worker/executor initializer, before measurement or claiming work.

    Process-wide pools/environment must already match the frozen pin. Only the
    calling thread's Accelerate mode can be initialized here, once. Every call
    still verifies actual execution; a reused thread cannot reset later drift.
    """
    execution = _verified_implementation(runtime)
    initialize_thread_controls(accelerate=execution.accelerate is not None)
    verify_runtime(runtime)


def verify_runtime(runtime: RuntimeIdentity) -> None:
    if _verified_implementation(runtime) != numerical_execution():
        raise RuntimeCompatibilityError("numerical_execution")


def builtin_definition(variant: str) -> tuple[UUID, str, ScorerSpec | None]:
    definitions = json.loads(Path(__file__).with_name("builtin_artifacts.json").read_text())
    if variant not in definitions["variants"]:
        raise ValueError("unsupported built-in scorer")
    params = definitions["variants"][variant]
    payload = {
        "definition_version": definitions["definition_version"],
        "variant": variant,
        "parameters": params,
    }
    digest = hashlib.sha256(canonical_json(payload)).hexdigest()
    spec = (
        None
        if params is None
        else ScorerSpec(
            variant,
            params["reversal_weight"],
            params["weekly_reversal_lag"],
            params["monthly_quarterly_reversal_lag"],
            params["momentum_lookback"],
        )
    )
    # Stage 2 built-in identity, not a claim of Registry publication (Stage 3).
    return uuid5(NAMESPACE_URL, "qfr-built-in:" + digest), digest, spec
