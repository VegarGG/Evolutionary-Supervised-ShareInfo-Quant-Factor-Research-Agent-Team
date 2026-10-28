"""Prepare deterministic human/import requests; publication always uses HTTP.

These builders never import or execute the packaged runner and never include
licensed data. A caller supplies an explicit runtime contract, not a tag/default.
"""

import base64
import hashlib
import io
import json
import stat
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from qfr_core.contracts.artifacts import ArtifactReference
from qfr_core.contracts.enums import ArtifactKind
from qfr_core.contracts.intake import ExecutionContract
from qfr_core.contracts.publication import PublicationRequest, PublicationResponse, RunnerPackage
from qfr_core.data_layer.snapshots import canonical_json
from qfr_core.dsl.language import DSLConfig, analyze, parse
from qfr_core.pilot.features import PilotFeatureConfig
from qfr_core.registry_client import RegistryClient


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def frozen_archive(entries: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, content in sorted(entries.items()):
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or str(path) != name or "\\" in name:
                raise ValueError("invalid seed member")
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o444) << 16
            archive.writestr(info, content)
    return output.getvalue()


def verify_original(root: Path, model: str, expected_manifest: str) -> str:
    if model not in {"P0", "P1"}:
        raise ValueError("unknown original pilot package")
    source = root / f"{model}_English_Delivery_20261022"
    manifest = source / "SHA256SUMS.json"
    if manifest.is_symlink() or sha256(manifest.read_bytes()) != expected_manifest:
        raise ValueError("original manifest checksum mismatch")
    body = json.loads(manifest.read_bytes())
    if body["model"] != model or not body["files"]:
        raise ValueError("invalid original manifest")
    for relative, expected in body["files"].items():
        path = PurePosixPath(relative)
        if path.is_absolute() or ".." in path.parts or "\\" in relative or str(path) != relative:
            raise ValueError("unsafe original file path")
        target = source / relative
        if any(p.is_symlink() for p in [target, *target.parents] if p != source.parent):
            raise ValueError("original files cannot be symlinks")
        content = target.read_bytes()
        if len(content) != expected["bytes"] or sha256(content) != expected["sha256"]:
            raise ValueError("original file checksum mismatch")
    return expected_manifest


def definition(
    root: Path, program: str, name: str, kind: str, source_hashes: list[str], *, pilot: bool = False
) -> dict[str, Any]:
    config = json.loads((root / "configs/registry/seeds_v1.json").read_bytes())
    return {
        "schema_version": "1",
        "family_id": None,
        "parent_version_ids": [],
        "name": name,
        "title": name,
        "kind": kind,
        "payload_files": [],
        "parameters": {},
        "data_requirements": [],
        "eligible_protocols": [config["pilot_protocol"] if pilot else "generic-fixture/1"],
        "cycles": ["weekly", "monthly", "quarterly"],
        "output_schema_ref": "RunnerOutput/1",
        "rationale": {
            "hypothesis_id": None,
            "summary": "Frozen human/import acceptance fixture",
            "mechanism": "Declared reproducible computation; no fitting or live inference",
            "falsification": "Independent replay, causality and sandbox checks",
            "change_summary": None,
        },
        "complexity": 0,
        "provenance": {
            "program_id": program,
            "generation_id": None,
            "island_id": None,
            "task_id": None,
            "operator": "human_seed",
            "source_asset_ids": ["seed-source:" + name],
            "source_hashes": source_hashes,
            "blackboard_refs": [],
            "agent_runs": [],
            "research_snapshot_id": None,
            "qfr_core_version": "0.1.0",
            "exposure": config["pilot_exposure" if pilot else "synthetic_exposure"],
            "dependency_lock_sha256": sha256((root / "uv.lock").read_bytes()),
        },
        "research_side_checks": {
            "official": False,
            "dsl_validation": "not_applicable",
            "static_analysis": "not_run",
            "development_prefix_check": "not_run",
            "evidence_refs": [],
            "critic_verdict_id": None,
            "review_rounds": 0,
        },
    }


def request_for(
    manifest: dict[str, Any], files: dict[str, bytes], profile: str = "pilot_industry_v1"
) -> PublicationRequest:
    return PublicationRequest.model_validate(
        {
            "publish_key": "seed-v1:" + sha256(canonical_json(manifest)),
            "profile": profile,
            "manifest": manifest,
            "files": [
                {"asset_id": name, "data_base64": base64.b64encode(data).decode()}
                for name, data in sorted(files.items())
            ],
        }
    )


def package_seed(
    root: Path,
    program: str,
    name: str,
    kind: str,
    contract: ExecutionContract,
    *,
    source: bytes,
    weights: dict[str, Any],
    source_hashes: list[str],
    pilot: bool = False,
    references: tuple[ArtifactReference, ...] = (),
) -> PublicationRequest:
    lock = sha256((root / "uv.lock").read_bytes())
    if (
        contract.runner != "qfr-json-runner/1"
        or contract.interface != "function"
        or contract.function != "runner.py:run"
        or contract.input_schema_ref != "RunnerInput/1"
        or contract.output_schema_ref != "RunnerOutput/1"
        or contract.dependency_lock_sha256 != lock
    ):
        raise ValueError("explicit seed runtime contract differs from the frozen interface/lock")
    metadata = RunnerPackage(
        format="qfr-json-runner/1",
        kind=ArtifactKind(kind),
        entrypoint="runner.py:run",
        input_schema_ref="RunnerInput/1",
        output_schema_ref="RunnerOutput/1",
        dependency_lock_sha256=lock,
        fields_used=["close"],
        max_lookback_days=None if pilot else 1,
        weight_files=["weights.json"],
    )
    weight_bytes = canonical_json(weights)
    package = frozen_archive(
        {
            "runner.json": canonical_json(metadata.model_dump(mode="json")),
            "runner.py": source,
            "weights.json": weight_bytes,
        }
    )
    manifest = definition(
        root,
        program,
        name,
        kind,
        source_hashes + [sha256(source), sha256(weight_bytes)],
        pilot=pilot,
    )
    manifest["implementation"] = {
        "type": "declared_package_runner",
        "package_asset_id": "package",
        "execution_contract": contract.model_dump(mode="json"),
    }
    manifest["parameters"] = {"history_policy": "full_prefix" if pilot else "bounded"}
    files = {"package": package}
    if kind == "factor":
        manifest["payload"] = {
            "kind": kind,
            "expected_sign": 1,
            "horizon_days": 1,
            "fields_used": ["close"],
            "max_lookback_days": metadata.max_lookback_days,
            "formulation": "lagged close",
            "mechanism_card": {
                "event": "observation",
                "context": "synthetic fixture",
                "qualities": "causal",
                "direction": "positive",
                "output": "score",
            },
        }
    elif kind == "model":
        files["weights"] = weight_bytes
        manifest["payload"] = {
            "kind": kind,
            "specification": name,
            "weight_asset_ids": ["weights"],
            "preprocessing": "original frozen rules" if pilot else "lagged close return",
            "fallback_logic": "P1 original readiness falls back to P0" if pilot else "none",
            "fit_interface": None,
            "inference_interface": "runner.py:run",
            "serialization": "JSON",
            "training_dataset_refs": [],
        }
    elif kind == "strategy":
        manifest["payload"] = {
            "kind": kind,
            "signal_artifacts": [r.model_dump(mode="json") for r in references],
            "position_state_rules": "equal weights over declared contemporaneous eligible universe",
            "rebalance_timing": "each declared observation; next authorized execution price",
            "cost_policy_ref": "synthetic-fixture-zero-cost/1",
            "execution_prices_ref": "next_close/1",
        }
    elif kind == "data_product":
        manifest["payload"] = {
            "kind": kind,
            "dataset_manifest_ref": "authorized-input-prices",
            "output_schema_ref": "RunnerOutput/1",
            "deterministic_check_refs": ["identity-prices/1"],
        }
    else:
        raise ValueError("unsupported seed package kind")
    manifest["payload_files"] = [
        {
            "asset_id": key,
            "sha256": sha256(data),
            "media_type": "application/zip" if key == "package" else "application/json",
        }
        for key, data in sorted(files.items())
    ]
    requirements = [
        ("prices", ["date", "code", "close"], "daily"),
    ]
    if pilot:
        requirements += [
            ("features", ["date", "code", "available_date"], "weekly"),
            ("universe", ["code"], "frozen"),
        ]
        manifest["provenance"]["operator"] = "import"
    for table, fields, frequency in requirements:
        manifest["data_requirements"].append(
            {
                "table": table,
                "fields": fields,
                "universe": "declared authorized input universe",
                "frequency": frequency,
                "availability_rule": "available no later than observation",
                "minimum_timing_grade": "B" if pilot else None,
                "lookback": metadata.max_lookback_days,
                "unresolved": [],
            }
        )
    return request_for(manifest, files, "pilot_industry_v1" if pilot else "generic")


def pilot_seed(
    root: Path, inputs: Path, program: str, model: str, contract: ExecutionContract
) -> PublicationRequest:
    config = json.loads((root / "configs/registry/seeds_v1.json").read_bytes())
    original = verify_original(inputs, model, config["original_manifest_sha256"][model])
    return package_seed(
        root,
        program,
        "frozen-" + model.lower(),
        "model",
        contract,
        source=(root / "fixtures/artifacts/runners/pilot.py").read_bytes(),
        weights={
            "variant": model,
            "p0": json.loads((root / "configs/pilot/p0_scoring.json").read_bytes()),
            "features": json.loads((root / "configs/pilot/stage1_features.json").read_bytes()),
        },
        source_hashes=[original],
        pilot=True,
    )


def dsl_seeds(root: Path, program: str) -> list[PublicationRequest]:
    features = PilotFeatureConfig.model_validate_json(
        (root / "configs/pilot/stage1_features.json").read_bytes()
    )
    config = DSLConfig.load(root / "configs/dsl/pilot_industry_v1.json")
    requests = []
    for name, expression in features.expressions().items():
        analysis = analyze(parse(expression, config), config)
        manifest = definition(
            root, program, "v4-" + name, "factor", [sha256(expression.encode())], pilot=True
        )
        manifest["implementation"] = {
            "type": "dsl",
            "language": "qfr-dsl/1",
            "expression": expression,
        }
        manifest["payload"] = {
            "kind": "factor",
            "expected_sign": 1,
            "horizon_days": 1,
            "fields_used": sorted(analysis.fields),
            "max_lookback_days": analysis.lookback,
            "formulation": expression,
            "mechanism_card": {
                "event": "past price change",
                "context": "frozen pilot v4 features",
                "qualities": name,
                "direction": "as defined",
                "output": "feature value",
            },
        }
        manifest["complexity"] = analysis.complexity
        manifest["output_schema_ref"] = "factor-panel/1"
        manifest["data_requirements"] = [
            {
                "table": "prices",
                "fields": ["date", "code", *sorted(analysis.fields)],
                "universe": "declared authorized industry universe",
                "frequency": "daily",
                "availability_rule": "observation at or before decision",
                "minimum_timing_grade": "B",
                "lookback": analysis.lookback,
                "unresolved": [],
            }
        ]
        requests.append(request_for(manifest, {}))
    return requests


def publish_mixed_bundle(
    client: RegistryClient, requests: list[PublicationRequest]
) -> list[PublicationResponse]:
    """No atomic bundle claim: each receipt is immutable and retries are idempotent."""
    return [client.publish(request) for request in requests]


def note_seed(root: Path, program: str) -> PublicationRequest:
    content = (
        b"# Synthetic registry note\n\n"
        b"A document is retained as evidence, not coerced into a predictive factor.\n"
        b"No performance claim, released report or licensed input is included.\n"
    )
    manifest = definition(root, program, "fixture-note", "research_note", [sha256(content)])
    manifest["implementation"] = {"type": "document", "asset_id": "document", "format": "markdown"}
    manifest["payload"] = {
        "kind": "research_note",
        "document_asset_id": "document",
        "citation_refs": [],
        "released_report_refs": [],
    }
    manifest["payload_files"] = [
        {"asset_id": "document", "sha256": sha256(content), "media_type": "text/markdown"}
    ]
    manifest["cycles"] = []
    manifest["output_schema_ref"] = "research-note/1"
    return request_for(manifest, {"document": content}, "generic")
