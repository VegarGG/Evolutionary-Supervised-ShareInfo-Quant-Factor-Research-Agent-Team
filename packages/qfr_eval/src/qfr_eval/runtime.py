"""Pinned local implementation identity; no environment/credential enumeration."""

import hashlib
import importlib.metadata
import json
import platform
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

import qfr_core
from qfr_core.data_layer.snapshots import canonical_json

import qfr_eval
from qfr_eval.backtest.scorers import ScorerSpec
from qfr_eval.records import RuntimeIdentity


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
            for name in ["numpy", "polars", "scipy", "pydantic", "psycopg"]
        },
    }


def verify_runtime(runtime: RuntimeIdentity) -> None:
    if (
        runtime.implementation_sha256 != implementation_hash()
        or runtime.software != software_identity()
    ):
        raise ValueError("pinned evaluator implementation or numerical runtime differs")


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
