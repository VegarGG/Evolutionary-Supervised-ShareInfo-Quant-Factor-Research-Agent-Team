"""Research-owned references and interpretations; never private official records."""

from typing import Literal

from pydantic import AwareDatetime, JsonValue, PositiveInt

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


class ResearchProgram(Contract):
    """Research context; an active program alone does not admit work."""

    schema_version: Literal["1"]
    program_id: Text
    name: Text
    status: Literal["inactive", "active", "paused"]
    charter_revision: PositiveInt
    charter: dict[str, JsonValue]
    created_by: Text
    created_at: AwareDatetime


class ResearchQueueLease(Contract):
    """One fenced task lease, separate from a research job's delivery state."""

    schema_version: Literal["1"]
    queue_entry_id: Text
    program_id: Text
    research_job_id: Text
    queue: Text
    worker: Text
    fence: PositiveInt
    attempt: PositiveInt
    lease_until: AwareDatetime
    payload: dict[str, JsonValue]
