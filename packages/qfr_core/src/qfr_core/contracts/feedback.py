"""Released-only API envelopes and bounded read policy."""

from typing import Literal, Self
from uuid import UUID

from pydantic import PositiveInt, model_validator

from qfr_core.contracts.base import Contract
from qfr_core.contracts.reports import PublicProtocolCard, PublicReleasePolicyCard, ReleasedReport

ReportKind = Literal[
    "intake",
    "screening",
    "pilot",
    "w1",
    "w2",
    "withheld",
    "advancement",
    "sim",
    "decision",
    "library",
]


class FeedbackReadPolicy(Contract):
    revision: PositiveInt
    max_page_size: PositiveInt
    max_page_bytes: PositiveInt
    statement_timeout_ms: PositiveInt


class ReportPage(Contract):
    schema_version: Literal["1"]
    items: list[ReleasedReport]
    next_after_id: UUID | None
    has_more: bool

    @model_validator(mode="after")
    def cursor_is_last_report(self) -> Self:
        if self.items:
            if self.next_after_id != UUID(self.items[-1].report_id):
                raise ValueError("cursor must identify the last returned report")
        elif self.has_more:
            raise ValueError("empty page cannot claim more reports")
        return self


class ArtifactFeedback(Contract):
    schema_version: Literal["1"]
    artifact_version_id: UUID
    latest_released: ReleasedReport | None
    timeline: ReportPage

    @model_validator(mode="after")
    def same_version(self) -> Self:
        reports = [*self.timeline.items, *([self.latest_released] if self.latest_released else [])]
        if any(UUID(r.identity.artifact_version_id) != self.artifact_version_id for r in reports):
            raise ValueError("artifact feedback contains a different version")
        return self


class PublicCards(Contract):
    schema_version: Literal["1"]
    policies: list[PublicReleasePolicyCard]
    protocols: list[PublicProtocolCard]
