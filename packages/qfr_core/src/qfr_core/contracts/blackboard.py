"""Research-owned references and interpretations; never private official records."""

from typing import Literal

from pydantic import AwareDatetime

from qfr_core.contracts.base import Contract, Text


class BlackboardRecord(Contract):
    schema_version: Literal["1"]
    record_id: Text
    project_id: Text
    kind: Literal[
        "hypothesis", "task", "note", "population_member", "lineage_edge", "rejected_idea", "plan"
    ]
    author_role: Text
    task_id: Text | None
    text: Text
    artifact_version_refs: list[Text]
    released_report_refs: list[Text]
    parent_record_refs: list[Text]
    status: Literal["open", "in_progress", "published", "rejected", "blocked_on_data", "closed"]
    created_at: AwareDatetime


class AuditEvent(Contract):
    schema_version: Literal["1"]
    event_id: Text
    principal: Text
    request_id: Text
    action: Text
    entity_ref: Text
    evidence_refs: list[Text]
    at: AwareDatetime
