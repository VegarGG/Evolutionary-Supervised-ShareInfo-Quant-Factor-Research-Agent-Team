"""Replay screened, immutable Registry artifacts without Registry/network access."""

from typing import Literal
from uuid import UUID

import polars as pl
from psycopg import Connection
from qfr_core.contracts.artifacts import PackageImplementation
from qfr_core.contracts.enums import ArtifactKind, ReasonCode
from qfr_core.contracts.execution import RunnerInput, RunnerOutput
from qfr_core.pilot.baseline import P0History
from qfr_core.runner_tables import pack_table

from qfr_eval.artifact_store import EvidenceStore
from qfr_eval.execution_bundle import ArtifactExecutionBundle
from qfr_eval.protocols.models import Cycle, FrozenProtocol
from qfr_eval.records import EvaluationRequest, RegistryExecutionBinding, StoredFile
from qfr_eval.sandbox.client import configured_runner
from qfr_eval.sandbox.runner import SandboxUnavailable
from qfr_eval.scheduler.dedup import digest
from qfr_eval.screening.execution import StaticFailure, prepare_execution
from qfr_eval.screening.persistence import verify_screening_receipt
from qfr_eval.screening.pilot import PilotArtifactOutput, PilotOutputError, validate_pilot_output
from qfr_eval.screening.records import ScreeningReceipt, ScreeningRecord


class RegistryExecutionFailure(ValueError):
    def __init__(self, reason: ReasonCode) -> None:
        super().__init__(reason.value)
        self.reason = reason


def screening_source(
    conn: Connection, record_id: UUID, store: EvidenceStore
) -> tuple[ScreeningRecord, ScreeningReceipt, ArtifactExecutionBundle]:
    row = conn.execute(
        "SELECT payload FROM eval.official_records WHERE id=%s", [record_id]
    ).fetchone()
    if row is None:
        raise ValueError("screening evidence is unavailable")
    record = ScreeningRecord.model_validate(row[0]["record"])
    receipt = ScreeningReceipt.model_validate(row[0]["receipt"])
    verify_screening_receipt(receipt, store)
    if (
        record.record_id != record_id
        or record.outcome.status != "passed"
        or receipt.record_id != record_id
        or receipt.trial_id != record.trial_id
        or receipt.identity != record.identity
        or receipt.request_hash != record.request_hash
        or receipt.results_hash != record.results_hash
        or ScreeningRecord.model_validate_json(store.read(receipt.files["record"])) != record
        or "execution_bundle" not in receipt.files
    ):
        raise ValueError("measurement requires passing pinned executable screening evidence")
    bundle = ArtifactExecutionBundle.model_validate_json(
        store.read(receipt.files["execution_bundle"])
    )
    development = RunnerInput.model_validate_json(store.read(receipt.files["development_input"]))
    probes = RunnerInput.model_validate_json(store.read(receipt.files["probe_input"]))
    output = RunnerOutput.model_validate_json(store.read(receipt.files["output"]))
    artifact = bundle.artifact.manifest
    if (
        artifact.artifact_version_id != record.identity.artifact_version_id
        or artifact.content_hash != record.identity.content_hash
        or digest(bundle.execution_policy.model_dump(mode="json"))
        != record.request.execution_policy_hash
        or digest(bundle.adapter_profile.model_dump(mode="json"))
        != record.request.adapter_profile_hash
        or digest(development.model_dump(mode="json")) != record.request.development_input_sha256
        or digest(probes.model_dump(mode="json")) != record.request.probe_input_sha256
        or digest(output.model_dump(mode="json")) != record.outcome.output_sha256
    ):
        raise ValueError("frozen execution bundle differs from its screened artifact")
    return record, receipt, bundle


def binding_for_screen(
    conn: Connection, record_id: UUID, store: EvidenceStore
) -> RegistryExecutionBinding:
    _, receipt, _ = screening_source(conn, record_id, store)
    return RegistryExecutionBinding(
        screening_record_id=record_id,
        screening_receipt_hash=receipt.receipt_hash,
        execution_bundle=receipt.files["execution_bundle"],
    )


def reserved_lineage(conn: Connection, record: ScreeningRecord) -> str:
    request = record.request
    rows = conn.execute(
        "SELECT lineage_id FROM eval.feedback_reservations WHERE program_id=%s "
        "AND generation_id=%s AND artifact_version_id=%s ORDER BY lineage_id",
        [request.program_id, request.generation_id, request.artifact_version_id],
    ).fetchall()
    lineages = [r[0] for r in rows]
    if not lineages:
        raise ValueError("screened version has no evaluator-owned exposure reservation")
    # Composite models retain every reservation. This label groups the already
    # recorded roots; it never grants a new lineage or feedback allowance.
    return lineages[0] if len(lineages) == 1 else "registry-lineages:" + digest(lineages)


def request_from_screen(
    conn: Connection,
    record_id: UUID,
    store: EvidenceStore,
    *,
    epoch_id: str,
    cohort_id: str,
    window: Literal["development", "validation"],
    cycle: Cycle,
) -> EvaluationRequest:
    """Private owner helper. No execution, publication, release or reservation."""
    record, receipt, _ = screening_source(conn, record_id, store)
    source = record.request
    return EvaluationRequest(
        schema_version="1",
        variant="registry",
        artifact_version_id=source.artifact_version_id,
        content_hash=source.content_hash,
        protocol_id=source.protocol_id,
        protocol_version=source.protocol_version,
        protocol_hash=source.protocol_hash,
        snapshot_id=source.snapshot_id,
        epoch_id=epoch_id,
        window=window,
        cycle=cycle,
        program_id=source.program_id,
        family_id=source.family_id,
        economic_lineage_id=reserved_lineage(conn, record),
        generation_id=source.generation_id,
        cohort_id=cohort_id,
        intent="withheld" if record.feedback_disposition == "withheld:budget" else "evaluated",
        runtime=source.runtime,
        registry_execution=RegistryExecutionBinding(
            screening_record_id=record_id,
            screening_receipt_hash=receipt.receipt_hash,
            execution_bundle=receipt.files["execution_bundle"],
        ),
    )


class RegistryPilotExecution:
    """Each distinct input is executed once per measurement/reproduction call.

    This in-memory cache never crosses calls. Reproduction always creates a fresh
    instance and executes the frozen bytes again; output evidence is not a scorer.
    """

    def __init__(
        self,
        request: EvaluationRequest,
        protocol: FrozenProtocol,
        record: ScreeningRecord,
        receipt: ScreeningReceipt,
        bundle: ArtifactExecutionBundle,
        store: EvidenceStore,
    ) -> None:
        implementation = bundle.artifact.manifest.implementation
        if (
            request.variant != "registry"
            or request.registry_execution is None
            or bundle.artifact.profile != "pilot_industry_v1"
            or bundle.artifact.manifest.kind != ArtifactKind.MODEL
            or bundle.adapter_profile.adapter != "pilot_rotation_v1"
            or bundle.sandbox_profile is None
            or not isinstance(implementation, PackageImplementation)
        ):
            raise ValueError("official pilot measurement requires the declared pilot model adapter")
        binding = request.registry_execution
        screened = record.request
        if (
            binding.screening_receipt_hash != receipt.receipt_hash
            or binding.execution_bundle != receipt.files["execution_bundle"]
            or request.artifact_version_id != screened.artifact_version_id
            or request.content_hash != screened.content_hash
            or request.snapshot_id != screened.snapshot_id
            or request.protocol_hash != screened.protocol_hash
            or request.protocol_id != screened.protocol_id
            or request.protocol_version != screened.protocol_version
            or protocol.sha256 != request.protocol_hash
            or request.runtime != screened.runtime
            or request.program_id != screened.program_id
            or request.family_id != screened.family_id
            or request.generation_id != screened.generation_id
            or request.intent
            != ("withheld" if record.feedback_disposition == "withheld:budget" else "evaluated")
        ):
            raise ValueError("measurement identity or disposition differs from screening")
        self.request, self.protocol, self.record = request, protocol, record
        self.receipt, self.bundle, self.store = receipt, bundle, store
        self.sandbox = configured_runner(
            bundle.sandbox_profile, implementation.execution_contract.image_digest
        )
        self.cache: dict[str, PilotArtifactOutput] = {}
        self.inputs: dict[str, RunnerInput] = {}
        self.outputs: dict[str, RunnerOutput] = {}

    def history(self, tables: dict[str, pl.DataFrame]) -> tuple[pl.DataFrame, P0History]:
        cutoff = self.protocol.windows[self.request.window].end
        data = {
            "prices": tables["prices_daily"],
            "features": tables["features"],
            "universe": tables["universe"],
        }
        for frame in data.values():
            for column in ("date", "available_date"):
                if column in frame.columns and (
                    frame.schema[column] != pl.Date
                    or frame[column].null_count()
                    or (frame[column] > cutoff).any()
                ):
                    raise ValueError("registry inference input exceeds its authorized window")
        value = RunnerInput(
            schema_version="1",
            seed=self.protocol.diagnostics.root_seed,
            tables={name: pack_table(frame) for name, frame in data.items()},
        )
        key = digest(value.model_dump(mode="json"))
        if key not in (
            self.record.request.development_input_sha256,
            self.record.request.probe_input_sha256,
        ):
            raise RegistryExecutionFailure(ReasonCode.DECLARATION_MISMATCH)
        if key not in self.cache:
            try:
                prepared = prepare_execution(
                    self.bundle.artifact,
                    self.bundle.assets(),
                    self.bundle.execution_policy,
                    self.bundle.dsl_config,
                    self.sandbox,
                    anonymous_universe=tuple(sorted(tables["universe"]["code"].to_list())),
                )
            except StaticFailure as exc:
                raise RegistryExecutionFailure(exc.code) from exc
            result = prepared.execute(value)
            if result.code == "failed:backend_unavailable":
                raise SandboxUnavailable("registry inference backend unavailable")
            if result.code != "ok" or result.output is None:
                raise RegistryExecutionFailure(
                    ReasonCode.DECLARATION_MISMATCH
                    if result.code == "failed:invalid_output"
                    else ReasonCode.RUNTIME_LIMIT
                )
            if result.output_sha256 != digest(result.output.model_dump(mode="json")):
                raise RegistryExecutionFailure(ReasonCode.DECLARATION_MISMATCH)
            if (
                key == self.record.request.probe_input_sha256
                and result.output_sha256 != self.record.outcome.output_sha256
            ):
                raise RegistryExecutionFailure(ReasonCode.DECLARATION_MISMATCH)
            try:
                parsed = validate_pilot_output(result.output, value, self.protocol)
            except PilotOutputError as exc:
                raise RegistryExecutionFailure(exc.code) from exc
            except (ValueError, KeyError, pl.exceptions.PolarsError) as exc:
                raise RegistryExecutionFailure(ReasonCode.DECLARATION_MISMATCH) from exc
            quality = parsed.quality(self.protocol)
            if quality.status != "passed":
                raise RegistryExecutionFailure(quality.reason_codes[0])
            self.inputs[key], self.outputs[key], self.cache[key] = value, result.output, parsed
        candidate = self.cache[key]
        return candidate.panel, candidate.history

    def evidence_files(self) -> dict[str, StoredFile]:
        return {
            "registry_execution_bundle": self.receipt.files["execution_bundle"],
            "registry_screening_receipt": self.store.json(self.receipt.model_dump(mode="json")),
            **{
                "registry_input_" + key: self.store.json(value.model_dump(mode="json"))
                for key, value in self.inputs.items()
            },
            **{
                "registry_output_" + key: self.store.json(value.model_dump(mode="json"))
                for key, value in self.outputs.items()
            },
        }


def load_registry_execution(
    conn: Connection,
    request: EvaluationRequest,
    protocol: FrozenProtocol,
    store: EvidenceStore,
) -> RegistryPilotExecution:
    binding = request.registry_execution
    if binding is None:
        raise ValueError("registry execution binding missing")
    record, receipt, bundle = screening_source(conn, binding.screening_record_id, store)
    if request.economic_lineage_id != reserved_lineage(conn, record):
        raise ValueError("measurement lineage differs from evaluator-owned exposure history")
    return RegistryPilotExecution(request, protocol, record, receipt, bundle, store)
