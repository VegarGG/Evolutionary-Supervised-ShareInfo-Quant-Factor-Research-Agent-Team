"""Evaluator-private contracts; never imported by research or MCP."""

from typing import Literal

from pydantic import UUID7, AwareDatetime, Field, FiniteFloat, JsonValue
from qfr_core.contracts import Contract, EvidenceRef, Hash


class OfficialRecord(EvidenceRef):
    schema_version: Literal["official_record/1"]
    record_id: UUID7
    epoch_id: str
    family_id: UUID7
    program_id: UUID7 | None
    job_id: UUID7 | None
    stage: Literal["screening", "w1", "w2", "holdout", "simulation"]
    window: Literal["W1", "W2", "W3", "W4"]
    run_ids: list[UUID7] = Field(min_length=1)
    container_image_digest: str
    seed: int
    summary: dict[str, JsonValue]
    metrics: dict[str, FiniteFloat | None]
    results_hash: Hash
    created_at: AwareDatetime
    principal: str
    request_id: str


class SeriesReference(Contract):
    run_id: UUID7
    window: Literal["W1", "W2", "W3", "W4"]
    kind: Literal["nav", "rankic", "ls_returns"]
    uri: str
    sha256: Hash


class GateResult(Contract):
    name: str
    passed: bool
    value: FiniteFloat | None
    threshold: FiniteFloat | None
    skipped_reason: str | None
    # Which record or case the gate belongs to: w1, w2, holdout or acceptance, and the
    # window it measured (the acceptance gates span the incubation, so no window).
    stage: Literal["w1", "w2", "holdout", "acceptance"] | None = None
    window: Literal["W1", "W2", "W3", "W4"] | None = None


class WindowEvidence(Contract):
    """One evaluated window of the version: the index the owner reads first."""

    stage: Literal["screening", "w1", "w2", "holdout", "simulation"]
    window: Literal["W1", "W2", "W3", "W4"]
    record_id: UUID7
    status: str | None
    created_at: AwareDatetime
    results_hash: Hash
    series_kinds: list[Literal["nav", "rankic", "ls_returns"]]


class SimulationEvidence(Contract):
    """One simulation account of the version (incubation or monitoring) without its
    day-by-day rows; qfr.deliverable.export writes its NAV."""

    sim_id: UUID7
    purpose: Literal["incubation", "monitoring"]
    mode: Literal["forward", "replay"]
    status: str
    start_date: str | None
    last_day: str | None
    days_done: int
    required_days: int | None
    error_code: str | None
    metrics: dict[str, FiniteFloat | None]
    last_checkpoint: dict[str, JsonValue] | None


class EvaluationState(Contract):
    """Where the version is in the evaluator's lifecycle (Section 7.9)."""

    state: str
    reason_code: str | None
    duplicate_of: UUID7 | None
    discovered_at: AwareDatetime
    decided_at: AwareDatetime | None


class OwnerEvidence(Contract):
    schema_version: Literal["owner_evidence/1"]
    visibility: Literal["owner_only"]
    version_id: UUID7
    evaluation: EvaluationState | None
    official_records: list[OfficialRecord]
    windows: list[WindowEvidence]
    gate_values: list[GateResult]
    series: list[SeriesReference]
    reference_strategy_stats: dict[str, FiniteFloat | None]
    library_correlation: dict[str, JsonValue] | None
    simulation_state: list[SimulationEvidence]
    acceptance_cases: list[dict[str, JsonValue]]
    hygiene_warning: Literal[
        "Never copy owner-only evidence into research briefs or steering notes."
    ]


PRIVATE_CONTRACTS = {"official_record": OfficialRecord, "owner_evidence": OwnerEvidence}
