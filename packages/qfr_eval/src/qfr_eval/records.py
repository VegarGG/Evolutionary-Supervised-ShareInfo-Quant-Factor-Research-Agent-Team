"""Private official measurement and all-attempt accounting. No research imports."""

import hashlib
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    JsonValue,
    NonNegativeInt,
    SerializerFunctionWrapHandler,
    model_serializer,
    model_validator,
)
from qfr_core.contracts.base import Contract, Sha256, Text
from qfr_core.contracts.enums import ReasonCode
from qfr_core.contracts.reports import EvidenceIdentity, MetricValue
from qfr_core.data_layer.snapshots import canonical_json

from qfr_eval.protocols.models import Cycle
from qfr_eval.runtime_contracts import RuntimeIdentity as RuntimeIdentity
from qfr_eval.statistics.bootstrap import Interval
from qfr_eval.statistics.family import FamilyInterval, FamilyStatistics, TrialObservation
from qfr_eval.statistics.hurdles import GateStatus, TurnoverResult
from qfr_eval.statistics.incremental import IncrementalResult


class StoredFile(Contract):
    sha256: Sha256
    bytes: NonNegativeInt
    relative_path: Text
    media_type: Literal["application/json", "application/vnd.apache.parquet", "text/markdown"]
    logical_sha256: Sha256 | None


class RegistryExecutionBinding(Contract):
    screening_record_id: UUID
    screening_receipt_hash: Sha256
    execution_bundle: StoredFile

    @model_validator(mode="after")
    def private_json_bundle(self) -> Self:
        if self.execution_bundle.media_type != "application/json":
            raise ValueError("registry execution requires a frozen private JSON bundle")
        return self


class EvaluationRequest(Contract):
    schema_version: Literal["1"]
    variant: Literal[
        "registry",
        "baseline",
        "P1_reversal_momentum",
        "N1_reversal_weight040",
        "N2_reversal_weight060",
        "N3_reversal_lag_short",
        "N4_reversal_lag_long",
        "N5_momentum_lookback100",
        "N6_momentum_lookback140",
    ]
    artifact_version_id: UUID
    content_hash: Sha256
    protocol_id: Text
    protocol_version: Text
    protocol_hash: Sha256
    snapshot_id: Sha256
    epoch_id: Text
    window: Literal["development", "validation"]
    cycle: Cycle
    program_id: Text
    family_id: Text
    economic_lineage_id: Text
    generation_id: Text
    cohort_id: Text
    intent: Literal["evaluated", "withheld", "diagnostic"]
    runtime: RuntimeIdentity
    registry_execution: RegistryExecutionBinding | None = None

    @model_validator(mode="after")
    def frozen_neighbor(self) -> Self:
        if self.variant.startswith("N") and self.intent != "diagnostic":
            raise ValueError("frozen neighbors are non-selectable diagnostics only")
        if (self.variant == "registry") != (self.registry_execution is not None):
            raise ValueError("registry measurements require an explicit screened execution binding")
        return self

    @model_serializer(mode="wrap")
    def preserve_builtin_serialization(
        self, handler: SerializerFunctionWrapHandler
    ) -> dict[str, Any]:
        value: dict[str, Any] = handler(self)
        if self.registry_execution is None:
            value.pop("registry_execution", None)
        return value

    @property
    def sha256(self) -> str:
        return hashlib.sha256(canonical_json(self.model_dump(mode="json"))).hexdigest()


class Measurement(Contract):
    status: Literal["complete", "failed"]
    metrics: dict[Text, MetricValue]
    reason_codes: list[ReasonCode]
    observation: TrialObservation
    period_count: NonNegativeInt
    used_seeds: dict[Text, NonNegativeInt]
    uncertainty: Interval | None
    sensitivity: list[Interval]
    family_interval: FamilyInterval | None
    family_statistics: FamilyStatistics | None
    incremental: IncrementalResult | None
    turnover: dict[Literal["top", "bottom"], TurnoverResult]
    hurdle: dict[Text, GateStatus]
    diagnostics: dict[Text, JsonValue]

    @property
    def results_hash(self) -> str:
        return hashlib.sha256(canonical_json(self.metrics_json())).hexdigest()

    def metrics_json(self) -> dict[str, object]:
        # Trial IDs and audit clocks are excluded; the frozen cohort and input
        # identities are bound by the separate request/receipt, not by RNG state.
        return self.model_dump(mode="json", exclude={"observation"})


class OfficialRecord(Contract):
    schema_version: Literal["1"]
    record_id: Text
    identity: EvidenceIdentity
    epoch_id: Text
    window: Text
    stage: Text
    run_ids: list[Text]
    image_digest: Sha256
    protocol_hash: Sha256
    request_hash: Sha256
    sampling_unit: Literal["mature_matched_decision"]
    cycle: Cycle
    seed: NonNegativeInt
    status: Literal["complete", "failed", "withheld"]
    metrics: dict[Text, MetricValue]
    series_refs: list[Text]
    results_hash: Sha256
    reason_codes: list[ReasonCode]
    created_by: Text
    request_id: Text
    created_at: AwareDatetime


class TrialLedgerEntry(Contract):
    schema_version: Literal["1"]
    trial_id: Text
    official_record_id: Text
    identity: EvidenceIdentity
    window: Text
    epoch_id: Text
    family_id: Text
    program_id: Text
    status: Literal["attempted", "evaluated", "failed", "withheld", "diagnostic"]
    selectable: bool
    sampling_unit: Literal["mature_matched_decision"]
    sharpe_per_period: MetricValue
    n_obs: NonNegativeInt
    skew: MetricValue
    kurt_raw: MetricValue
    fingerprint_ref: Text | None
    observation: TrialObservation
    counted_at: AwareDatetime

    @model_validator(mode="after")
    def diagnostics_are_not_selectable(self) -> Self:
        if self.status == "diagnostic" and self.selectable:
            raise ValueError("diagnostic trials cannot be selected")
        if self.observation.trial_id != self.trial_id or self.observation.status != self.status:
            raise ValueError("trial observation identity or status differs")
        return self


class MeasurementReceipt(Contract):
    """Private Stage 2 integrity receipt; signing/release belongs to Stage 4."""

    schema_version: Literal["1"]
    kind: Literal["private_measurement"]
    authenticity: Literal["internal_unsigned"]
    record_id: Text
    trial_id: Text
    identity: EvidenceIdentity
    protocol_hash: Sha256
    dataset_manifest_hash: Sha256
    implementation_sha256: Sha256
    image_digest: Sha256
    request_hash: Sha256
    results_hash: Sha256
    files: dict[Text, StoredFile]
    receipt_hash: Sha256


class ReproductionResult(Contract):
    record_id: Text
    status: Literal["match", "mismatch"]
    expected_results_hash: Sha256
    actual_results_hash: Sha256
    series_match: bool
    fingerprint_match: bool
    clusters_match: bool
    checked_files: NonNegativeInt
    verification_only: Literal[True]
