"""Verified artifact bytes to DSL execution or the validated sandbox only."""

import hashlib
import io
import json
import zipfile
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

import polars as pl
from qfr_core.contracts.artifacts import (
    DSLImplementation,
    FactorPayload,
    ModelPayload,
    PackageImplementation,
    PythonImplementation,
)
from qfr_core.contracts.enums import ArtifactKind, ReasonCode
from qfr_core.contracts.execution import RunnerInput, RunnerOutput
from qfr_core.contracts.publication import PublishedArtifact, RunnerPackage
from qfr_core.dsl.language import DSLConfig
from qfr_core.dsl.operators import evaluate
from qfr_core.runner_tables import pack_table, unpack_table

from qfr_eval.sandbox.runner import (
    ExecutionResult,
    SandboxRunner,
    SandboxUnavailable,
    unpack_package,
)
from qfr_eval.scheduler.dedup import digest
from qfr_eval.screening.adapters import prices_input
from qfr_eval.screening.models import ScreeningExecutionPolicy
from qfr_eval.screening.static import check_source


class StaticFailure(ValueError):
    def __init__(self, code: ReasonCode):
        super().__init__(code.value)
        self.code = code


@dataclass(frozen=True)
class PreparedExecution:
    mode: Literal["dsl", "sandbox"]
    execute: Callable[[RunnerInput], ExecutionResult]


def _archive(files: dict[str, bytes]) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100444 << 16
            archive.writestr(info, data)
    return stream.getvalue()


def prepare_execution(
    artifact: PublishedArtifact,
    assets: dict[str, bytes],
    policy: ScreeningExecutionPolicy,
    dsl_config: DSLConfig | None,
    sandbox: SandboxRunner | None,
    *,
    anonymous_universe: tuple[str, ...],
) -> PreparedExecution:
    manifest, implementation = artifact.manifest, artifact.manifest.implementation
    if set(assets) != {item.asset_id for item in manifest.payload_files} or any(
        hashlib.sha256(assets[item.asset_id]).hexdigest() != item.sha256
        for item in manifest.payload_files
    ):
        raise StaticFailure(ReasonCode.DECLARATION_MISMATCH)
    if isinstance(implementation, DSLImplementation):
        if dsl_config is None or not isinstance(manifest.payload, FactorPayload):
            raise StaticFailure(ReasonCode.DECLARATION_MISMATCH)

        def run_dsl(request: RunnerInput) -> ExecutionResult:
            try:
                frame = prices_input(request).rename({"code": "instrument"})
                output = (
                    evaluate(implementation.expression, frame, dsl_config)
                    .rename({"instrument": "code", "value": "score"})
                    .select("date", "code", "score")
                    .sort("date", "code")
                )
                result = RunnerOutput(
                    schema_version="1",
                    kind=ArtifactKind.FACTOR,
                    tables={"output": pack_table(output)},
                )
                return ExecutionResult("ok", result, digest(result.model_dump(mode="json")), {})
            except (ValueError, TypeError, KeyError, pl.exceptions.PolarsError):
                return ExecutionResult("failed:invalid_output", None, None, {})

        return PreparedExecution("dsl", run_dsl)
    if not isinstance(implementation, (PackageImplementation, PythonImplementation)):
        raise StaticFailure(ReasonCode.KIND_UNSUPPORTED)
    if sandbox is None:
        raise SandboxUnavailable("no approved sandbox configured for executable artifact")
    contract = implementation.execution_contract
    if isinstance(implementation, PackageImplementation):
        package = assets[implementation.package_asset_id]
        try:
            files = unpack_package(package, sandbox.profile)
            metadata = RunnerPackage.model_validate_json(files["runner.json"])
            entrypoint = (
                contract.function
                if contract.interface == "function"
                else contract.command[-1]
                if contract.command
                else None
            )
            if (
                metadata.kind != manifest.kind
                or metadata.entrypoint != entrypoint
                or metadata.dependency_lock_sha256 != contract.dependency_lock_sha256
                or metadata.input_schema_ref != contract.input_schema_ref
                or metadata.output_schema_ref != contract.output_schema_ref
            ):
                raise ValueError("package metadata differs")
            payload = manifest.payload
            if isinstance(payload, ModelPayload):
                if (
                    payload.serialization != "JSON"
                    or payload.fit_interface is not None
                    or payload.inference_interface != contract.function
                    or not payload.weight_asset_ids
                    or not metadata.weight_files
                ):
                    raise StaticFailure(ReasonCode.KIND_UNSUPPORTED)
                weights = [assets[name] for name in payload.weight_asset_ids]
                if Counter(weights) != Counter(files[name] for name in metadata.weight_files):
                    raise ValueError("frozen weight assets differ from packaged inference weights")
                for value in weights:
                    json.loads(value)  # Data only: never pickle/load or fit on private inputs.
        except (ValueError, KeyError, zipfile.BadZipFile) as exc:
            if isinstance(exc, StaticFailure):
                raise
            raise StaticFailure(ReasonCode.DECLARATION_MISMATCH) from exc
        constrained = False
    else:
        if manifest.kind != ArtifactKind.FACTOR or not isinstance(manifest.payload, FactorPayload):
            raise StaticFailure(ReasonCode.KIND_UNSUPPORTED)
        if contract.interface != "function" or contract.function != implementation.entrypoint:
            raise StaticFailure(ReasonCode.DECLARATION_MISMATCH)
        source_name = implementation.entrypoint.split(":")[0]
        files = {source_name: assets[implementation.source_asset_id]}
        package = _archive(files)
        # Reuse the same bounded path/size checks as declared packages.
        unpack_package(package, sandbox.profile)
        constrained = True
    for name, source in files.items():
        if name.endswith(".py"):
            violation = check_source(source, policy, constrained_factor=constrained)
            if violation:
                raise StaticFailure(violation)

    def run(request: RunnerInput) -> ExecutionResult:
        if not constrained:
            return sandbox.execute(contract, package, request)
        payload = manifest.payload
        assert isinstance(payload, FactorPayload)
        source = prices_input(request).sort("code", "date")
        mapping = pl.DataFrame(
            {"code": list(anonymous_universe), "series": list(range(len(anonymous_universe)))},
            schema={"code": pl.String, "series": pl.Int64},
        )
        indexed = source.join(mapping, on="code", how="left", validate="m:1").with_columns(
            (pl.col("date").cum_count().over("code") - 1).cast(pl.Int64).alias("observation")
        )
        fields = [
            "ret_1d" if f.removeprefix("$") == "ret" else f.removeprefix("$")
            for f in payload.fields_used
        ]
        if indexed["series"].null_count() or any(
            not indexed.schema[f].is_numeric() for f in fields
        ):
            raise ValueError("constrained factor input fields or anonymous universe differ")
        anonymous = RunnerInput(
            schema_version="1",
            seed=request.seed,
            tables={"values": pack_table(indexed.select("series", "observation", *fields))},
        )
        result = sandbox.execute(contract, package, anonymous)
        if result.code != "ok" or result.output is None:
            return result
        try:
            if result.output.kind != ArtifactKind.FACTOR or set(result.output.tables) != {"output"}:
                raise ValueError("invalid anonymous output")
            raw = unpack_table(result.output.tables["output"])
            if raw.columns != ["series", "observation", "score"]:
                raise ValueError("anonymous output cannot invent identifiers")
            keys = indexed.select("series", "observation", "date", "code")
            if (
                raw.height != keys.height
                or raw.join(keys, on=["series", "observation"], how="anti").height
            ):
                raise ValueError("anonymous output grid differs")
            output = (
                raw.join(keys, on=["series", "observation"], how="left", validate="1:1")
                .select("date", "code", "score")
                .sort("date", "code")
            )
            typed = RunnerOutput(
                schema_version="1", kind=ArtifactKind.FACTOR, tables={"output": pack_table(output)}
            )
            return ExecutionResult(
                "ok", typed, digest(typed.model_dump(mode="json")), result.isolation
            )
        except (ValueError, KeyError, pl.exceptions.PolarsError):
            return ExecutionResult("failed:invalid_output", None, None, result.isolation)

    return PreparedExecution("sandbox", run)
