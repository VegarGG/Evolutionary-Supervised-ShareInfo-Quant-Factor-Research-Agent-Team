"""Restore frozen numerical startup settings before importing measurement code."""

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from uuid import UUID

import psycopg

from qfr_eval.credentials import connection_dsn
from qfr_eval.runtime_contracts import RuntimeCompatibilityError, RuntimeIdentity
from qfr_eval.runtime_threads import initialize_thread_controls


def prepare_execution(runtime: RuntimeIdentity) -> None:
    try:
        runtime = RuntimeIdentity.model_validate(runtime.model_dump(mode="json"))
    except ValueError:
        raise RuntimeCompatibilityError("invalid_execution_identity") from None
    if runtime.schema_version != "2" or runtime.numerical_execution is None:
        raise RuntimeCompatibilityError("legacy_runtime_missing_execution_identity")
    if any(name in sys.modules for name in ("numpy", "polars", "scipy")):
        raise RuntimeCompatibilityError("numerical_libraries_already_initialized")
    # The model permits only fixed numerical controls. Never copy the caller's
    # environment, provider keys, Python paths or arbitrary JSON keys.
    for key, value in runtime.numerical_execution.thread_environment.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    initialize_thread_controls(accelerate=runtime.numerical_execution.accelerate is not None)


def _reproduction_runtime(record_id: UUID, root: Path) -> RuntimeIdentity:
    with psycopg.connect(connection_dsn(), autocommit=True) as conn:
        row = conn.execute(
            "SELECT payload FROM eval.official_records WHERE id=%s", [record_id]
        ).fetchone()
    if row is None:
        raise RuntimeCompatibilityError("unknown_record")
    payload = row[0]
    if payload["record"]["record_id"] != str(record_id):
        raise RuntimeCompatibilityError("frozen_context_identity")
    context_file = payload["receipt"]["files"]["context"]
    relative = Path(context_file["relative_path"])
    if relative.is_absolute() or ".." in relative.parts:
        raise RuntimeCompatibilityError("frozen_context_path")
    resolved_root = root.resolve(strict=True)
    path = (resolved_root / relative).resolve(strict=True)
    if not path.is_relative_to(resolved_root) or not path.is_file():
        raise RuntimeCompatibilityError("frozen_context_path")
    content = path.read_bytes()
    if (
        len(content) != context_file["bytes"]
        or hashlib.sha256(content).hexdigest() != context_file["sha256"]
    ):
        raise RuntimeCompatibilityError("frozen_context_hash")
    # Full receipt/request/snapshot verification still runs in reproduce() before
    # computation. This early read sets only the closed startup-control allowlist.
    return RuntimeIdentity.model_validate(json.loads(content)["request"]["runtime"])


def bootstrap_cli(arguments: list[str]) -> None:
    if (
        not arguments
        or arguments[0]
        not in {
            "reproduce",
            "evaluate",
            "cluster-trials",
            "screen-one",
        }
        or any(arg in {"--help", "-h"} for arg in arguments)
    ):
        return
    parser = argparse.ArgumentParser(add_help=False)
    action = arguments[0]
    if action == "reproduce":
        parser.add_argument("record_id", type=UUID)
        parser.add_argument("--evidence-root", type=Path, required=True)
    else:
        parser.add_argument(
            "--configuration" if action == "screen-one" else "--request", type=Path, required=True
        )
    args, _ = parser.parse_known_args(arguments[1:])
    try:
        if action == "reproduce":
            runtime = _reproduction_runtime(args.record_id, args.evidence_root)
        else:
            path = args.configuration if action == "screen-one" else args.request
            runtime = RuntimeIdentity.model_validate(json.loads(path.read_bytes())["runtime"])
        prepare_execution(runtime)
    except RuntimeCompatibilityError:
        raise
    except (psycopg.Error, OSError, KeyError, TypeError, ValueError):
        raise RuntimeCompatibilityError("frozen_runtime_unavailable_or_invalid") from None
