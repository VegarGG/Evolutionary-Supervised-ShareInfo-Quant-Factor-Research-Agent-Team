"""Private official measurement and all-attempt accounting. No research imports."""

from typing import Literal, Self

from pydantic import AwareDatetime, NonNegativeInt, model_validator
from qfr_core.contracts.base import Contract, Sha256, Text
from qfr_core.contracts.enums import ReasonCode
from qfr_core.contracts.reports import EvidenceIdentity, MetricValue


class OfficialRecord(Contract):
    schema_version: Literal["1"]
    record_id: Text
    identity: EvidenceIdentity
    epoch_id: Text
    window: Text
    stage: Text
    run_ids: list[Text]
    image_digest: Sha256
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
    sharpe_daily: MetricValue
    n_obs: NonNegativeInt
    skew: MetricValue
    kurt_raw: MetricValue
    fingerprint_ref: Text | None
    counted_at: AwareDatetime

    @model_validator(mode="after")
    def diagnostics_are_not_selectable(self) -> Self:
        if self.status == "diagnostic" and self.selectable:
            raise ValueError("diagnostic trials cannot be selected")
        return self
