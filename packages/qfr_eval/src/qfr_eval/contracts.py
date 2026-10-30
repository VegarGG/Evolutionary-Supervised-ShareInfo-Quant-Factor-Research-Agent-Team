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


class OwnerEvidence(Contract):
    schema_version: Literal["owner_evidence/1"]
    visibility: Literal["owner_only"]
    version_id: UUID7
    official_records: list[OfficialRecord]
    gate_values: list[GateResult]
    series: list[SeriesReference]
    reference_strategy_stats: dict[str, FiniteFloat | None]
    simulation_state: dict[str, JsonValue] | None
    hygiene_warning: Literal[
        "Never copy owner-only evidence into research briefs or steering notes."
    ]


PRIVATE_CONTRACTS = {"official_record": OfficialRecord, "owner_evidence": OwnerEvidence}
