"""control_db setup state, approval records, the front door's trace steps, deliveries,
operations alerts, alert acknowledgements and nightly runs (PLAN Sections 13.4 to 13.6,
14.5, 15.4 and 16.4).

Every table is insert-only: a setup change is a new setup_state row (the latest row per
step is current), an approval is never edited or removed, a re-import reuses the
DSL_VALIDATED step recorded for the same entry digest instead of writing a second one,
an operations alert is raised once per dedup key, and an acknowledgement is a new row
(one per alert) rather than a change to the alert.
"""

from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from typing import Annotated, Any, Literal, Protocol
from uuid import UUID

from pydantic import UUID7, AwareDatetime, JsonValue, StringConstraints
from qfr_core.config import canonical_json
from qfr_core.contracts import ApprovalRecord, Contract, TraceStep
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, RowMapping

SetupStep = Literal["pool", "providers", "data", "token"]
SETUP_STEPS: tuple[SetupStep, ...] = ("pool", "providers", "data", "token")
SetupStatus = Annotated[str, StringConstraints(pattern=r"^[a-z_]{1,32}$")]
SeedKind = Literal["factor", "strategy"]
AlertSource = Literal["evaluation", "research", "operations"]
OpsAlertKind = Literal["disk", "backup"]


class SetupState(Contract):
    state_id: UUID7
    at: AwareDatetime
    step: SetupStep
    status: SetupStatus
    details: dict[str, JsonValue]
    principal: str
    request_id: str


class Delivery(Contract):
    delivery_id: UUID7
    deliverable_id: UUID
    job_id: UUID
    fetched_at: AwareDatetime
    exported_path: str
    export_sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    files: int
    principal: str
    request_id: str


class OpsAlert(Contract):
    alert_id: UUID7
    kind: OpsAlertKind
    dedup_key: str
    at: AwareDatetime
    details: dict[str, JsonValue]
    principal: str
    request_id: str


class AlertAck(Contract):
    ack_id: UUID7
    source: AlertSource
    alert_id: UUID
    at: AwareDatetime
    note: Annotated[str, StringConstraints(min_length=1, max_length=2000)] | None = None
    principal: str
    request_id: str


class OpsRun(Contract):
    run_id: UUID7
    at: AwareDatetime
    kind: Literal["nightly"]
    due_at: AwareDatetime
    report: dict[str, JsonValue]
    request_id: str


class ControlStore(Protocol):
    def append_setup_state(self, state: SetupState) -> None: ...
    def latest_setup_states(self) -> dict[str, SetupState]: ...
    def append_trace_step(self, step: TraceStep) -> None: ...
    def find_validation(self, entry_digest: str) -> TraceStep | None: ...
    def latest_publication(self, kind: SeedKind, name: str) -> TraceStep | None: ...
    def publication_of(self, version_id: UUID) -> TraceStep | None: ...
    def append_approval(self, record: ApprovalRecord) -> None: ...
    def get_approval(self, approval_id: UUID) -> ApprovalRecord | None: ...
    def list_approvals(self, limit: int) -> list[ApprovalRecord]: ...
    def append_delivery(self, delivery: Delivery) -> None: ...
    def deliveries(self, deliverable_id: UUID) -> list[Delivery]: ...
    def raise_ops_alert(self, alert: OpsAlert) -> bool: ...
    def ops_alerts(self, limit: int) -> list[OpsAlert]: ...
    def acknowledge(self, ack: AlertAck) -> AlertAck: ...
    def acks(self, source: AlertSource, alert_ids: Sequence[UUID]) -> dict[UUID, AlertAck]: ...
    def append_ops_run(self, run: OpsRun) -> None: ...
    def latest_ops_run(self) -> OpsRun | None: ...
    def healthy(self) -> bool: ...


TRACE_COLUMNS = (
    "step_id, at, job_id, program_id, generation_id, task_id, candidate_id, version_id, "
    "step_type, actor_kind, actor, inputs, payload, outcome, request_id"
)


def _trace(row: RowMapping) -> TraceStep:
    return TraceStep.model_validate({"schema_version": "trace_step/1", **dict(row)})


class PostgresControlStore:
    """control_rw access. `begin` opens one transaction; tests pass a savepoint factory."""

    def __init__(
        self,
        url: str | None = None,
        *,
        begin: Callable[[], AbstractContextManager[Connection]] | None = None,
    ) -> None:
        if begin is None:
            if not url:
                raise ValueError("CONTROL_DB_URL is required")
            begin = create_engine(url, pool_pre_ping=True).begin
        self._begin = begin

    def append_setup_state(self, state: SetupState) -> None:
        values: dict[str, Any] = state.model_dump(mode="json")
        values["details"] = canonical_json(state.details)
        with self._begin() as conn:
            conn.execute(
                text("""INSERT INTO setup_state
                        (state_id, at, step, status, details, principal, request_id)
                        VALUES (:state_id, :at, :step, :status, CAST(:details AS jsonb),
                                :principal, :request_id)"""),
                values,
            )

    def latest_setup_states(self) -> dict[str, SetupState]:
        with self._begin() as conn:
            rows = conn.execute(
                text("""SELECT DISTINCT ON (step)
                               state_id, at, step, status, details, principal, request_id
                        FROM setup_state ORDER BY step, at DESC, state_id DESC""")
            ).mappings()
            return {row["step"]: SetupState.model_validate(dict(row)) for row in rows}

    def append_trace_step(self, step: TraceStep) -> None:
        values: dict[str, Any] = step.model_dump(mode="json")
        values["inputs"] = canonical_json(step.inputs)
        values["payload"] = canonical_json(step.payload)
        with self._begin() as conn:
            conn.execute(
                text(f"""INSERT INTO trace_steps ({TRACE_COLUMNS})
                        VALUES (:step_id, :at, :job_id, :program_id, :generation_id, :task_id,
                                :candidate_id, :version_id, :step_type, :actor_kind, :actor,
                                CAST(:inputs AS jsonb), CAST(:payload AS jsonb), :outcome,
                                :request_id)"""),
                values,
            )

    def _one(self, where: str, params: dict[str, Any]) -> TraceStep | None:
        with self._begin() as conn:
            row = (
                conn.execute(
                    text(f"""SELECT {TRACE_COLUMNS} FROM trace_steps WHERE {where}
                             ORDER BY at DESC, step_id DESC LIMIT 1"""),
                    params,
                )
                .mappings()
                .first()
            )
            return None if row is None else _trace(row)

    def find_validation(self, entry_digest: str) -> TraceStep | None:
        return self._one(
            "step_type = 'DSL_VALIDATED' AND outcome = 'ok' AND inputs->>'entry_digest' = :d",
            {"d": entry_digest},
        )

    def latest_publication(self, kind: SeedKind, name: str) -> TraceStep | None:
        return self._one(
            "step_type = 'SEEDS_PUBLISHED' AND inputs->>'kind' = :k AND inputs->>'name' = :n",
            {"k": kind, "n": name},
        )

    def publication_of(self, version_id: UUID) -> TraceStep | None:
        return self._one("step_type = 'SEEDS_PUBLISHED' AND version_id = :v", {"v": version_id})

    def append_approval(self, record: ApprovalRecord) -> None:
        document = record.model_dump(mode="json")
        with self._begin() as conn:
            conn.execute(
                text("""INSERT INTO approvals
                        (approval_id, created_at, decision, scope, owner_confirmation,
                         rationale, short_codes_matched, principal, request_id, record)
                        VALUES (:id, :at, :decision, CAST(:scope AS jsonb), :confirmation,
                                :rationale, :codes, :principal, :request_id,
                                CAST(:record AS jsonb))"""),
                {
                    "id": record.approval_id,
                    "at": record.created_at,
                    "decision": record.decision,
                    "scope": canonical_json(document["scope"]),
                    "confirmation": record.owner_confirmation,
                    "rationale": record.rationale,
                    "codes": list(record.short_codes_matched),
                    "principal": record.principal,
                    "request_id": record.request_id,
                    "record": canonical_json(document),
                },
            )

    def get_approval(self, approval_id: UUID) -> ApprovalRecord | None:
        with self._begin() as conn:
            record = conn.execute(
                text("SELECT record FROM approvals WHERE approval_id = :id"), {"id": approval_id}
            ).scalar()
            return None if record is None else ApprovalRecord.model_validate(record)

    def list_approvals(self, limit: int) -> list[ApprovalRecord]:
        with self._begin() as conn:
            rows: Sequence[Any] = (
                conn.execute(
                    text("""SELECT record FROM approvals
                        ORDER BY created_at DESC, approval_id DESC LIMIT :n"""),
                    {"n": limit},
                )
                .scalars()
                .all()
            )
            return [ApprovalRecord.model_validate(r) for r in rows]

    def append_delivery(self, delivery: Delivery) -> None:
        with self._begin() as conn:
            conn.execute(
                text("""INSERT INTO deliveries
                        (delivery_id, deliverable_id, job_id, fetched_at, exported_path,
                         export_sha256, files, principal, request_id)
                        VALUES (:delivery_id, :deliverable_id, :job_id, :fetched_at,
                                :exported_path, :export_sha256, :files, :principal,
                                :request_id)"""),
                delivery.model_dump(),
            )

    def deliveries(self, deliverable_id: UUID) -> list[Delivery]:
        with self._begin() as conn:
            rows = conn.execute(
                text("""SELECT * FROM deliveries WHERE deliverable_id = :d
                        ORDER BY fetched_at, delivery_id"""),
                {"d": deliverable_id},
            ).mappings()
            return [Delivery.model_validate(dict(r)) for r in rows]

    def raise_ops_alert(self, alert: OpsAlert) -> bool:
        values: dict[str, Any] = alert.model_dump()
        values["details"] = canonical_json(alert.details)
        with self._begin() as conn:
            inserted = conn.execute(
                text("""INSERT INTO ops_alerts
                        (alert_id, kind, dedup_key, at, details, principal, request_id)
                        VALUES (:alert_id, :kind, :dedup_key, :at, CAST(:details AS jsonb),
                                :principal, :request_id)
                        ON CONFLICT (dedup_key) DO NOTHING RETURNING 1"""),
                values,
            ).first()
            return inserted is not None

    def ops_alerts(self, limit: int) -> list[OpsAlert]:
        with self._begin() as conn:
            rows = conn.execute(
                text("SELECT * FROM ops_alerts ORDER BY at DESC, alert_id DESC LIMIT :n"),
                {"n": limit},
            ).mappings()
            return [OpsAlert.model_validate(dict(r)) for r in rows]

    def acknowledge(self, ack: AlertAck) -> AlertAck:
        """Record the acknowledgement; a second one for the same alert returns the first."""
        with self._begin() as conn:
            conn.execute(
                text("""INSERT INTO alert_acks
                        (ack_id, source, alert_id, at, note, principal, request_id)
                        VALUES (:ack_id, :source, :alert_id, :at, :note, :principal,
                                :request_id)
                        ON CONFLICT (source, alert_id) DO NOTHING"""),
                ack.model_dump(),
            )
            row = (
                conn.execute(
                    text("SELECT * FROM alert_acks WHERE source = :s AND alert_id = :a"),
                    {"s": ack.source, "a": ack.alert_id},
                )
                .mappings()
                .one()
            )
            return AlertAck.model_validate(dict(row))

    def acks(self, source: AlertSource, alert_ids: Sequence[UUID]) -> dict[UUID, AlertAck]:
        if not alert_ids:
            return {}
        with self._begin() as conn:
            rows = conn.execute(
                text("SELECT * FROM alert_acks WHERE source = :s AND alert_id = ANY(:ids)"),
                {"s": source, "ids": list(alert_ids)},
            ).mappings()
            found = [AlertAck.model_validate(dict(r)) for r in rows]
            return {a.alert_id: a for a in found}

    def append_ops_run(self, run: OpsRun) -> None:
        values: dict[str, Any] = run.model_dump()
        values["report"] = canonical_json(run.report)
        with self._begin() as conn:
            conn.execute(
                text("""INSERT INTO ops_runs (run_id, at, kind, due_at, report, request_id)
                        VALUES (:run_id, :at, :kind, :due_at, CAST(:report AS jsonb),
                                :request_id)"""),
                values,
            )

    def latest_ops_run(self) -> OpsRun | None:
        with self._begin() as conn:
            row = (
                conn.execute(
                    text("""SELECT * FROM ops_runs WHERE kind = 'nightly'
                            ORDER BY due_at DESC, at DESC, run_id DESC LIMIT 1""")
                )
                .mappings()
                .first()
            )
            return None if row is None else OpsRun.model_validate(dict(row))

    def healthy(self) -> bool:
        try:
            with self._begin() as conn:
                found = conn.execute(
                    text("SELECT to_regclass('public.setup_state') IS NOT NULL")
                ).scalar()
                return found is True
        except Exception:
            return False


class MemoryControlStore:
    """In-process store for tests and dry runs; same semantics as the tables."""

    def __init__(self) -> None:
        self.states: list[SetupState] = []
        self.steps: list[TraceStep] = []
        self.approvals: list[ApprovalRecord] = []
        self.delivered: list[Delivery] = []
        self.alerts: list[OpsAlert] = []
        self.acked: list[AlertAck] = []
        self.runs: list[OpsRun] = []

    def append_setup_state(self, state: SetupState) -> None:
        self.states.append(state)

    def latest_setup_states(self) -> dict[str, SetupState]:
        latest: dict[str, SetupState] = {}
        for state in sorted(self.states, key=lambda s: (s.at, s.state_id)):
            latest[state.step] = state
        return latest

    def append_trace_step(self, step: TraceStep) -> None:
        self.steps.append(step)

    def _last(self, match: Callable[[TraceStep], bool]) -> TraceStep | None:
        found = [s for s in self.steps if match(s)]
        return max(found, key=lambda s: (s.at, s.step_id)) if found else None

    def find_validation(self, entry_digest: str) -> TraceStep | None:
        return self._last(
            lambda s: (
                s.step_type == "DSL_VALIDATED"
                and s.outcome == "ok"
                and s.inputs.get("entry_digest") == entry_digest
            )
        )

    def latest_publication(self, kind: SeedKind, name: str) -> TraceStep | None:
        return self._last(
            lambda s: (
                s.step_type == "SEEDS_PUBLISHED"
                and s.inputs.get("kind") == kind
                and s.inputs.get("name") == name
            )
        )

    def publication_of(self, version_id: UUID) -> TraceStep | None:
        return self._last(lambda s: s.step_type == "SEEDS_PUBLISHED" and s.version_id == version_id)

    def append_approval(self, record: ApprovalRecord) -> None:
        if any(a.approval_id == record.approval_id for a in self.approvals):
            raise ValueError("approval ids are unique")
        self.approvals.append(record)

    def get_approval(self, approval_id: UUID) -> ApprovalRecord | None:
        return next((a for a in self.approvals if a.approval_id == approval_id), None)

    def list_approvals(self, limit: int) -> list[ApprovalRecord]:
        ordered = sorted(self.approvals, key=lambda a: (a.created_at, a.approval_id), reverse=True)
        return ordered[:limit]

    def append_delivery(self, delivery: Delivery) -> None:
        self.delivered.append(delivery)

    def deliveries(self, deliverable_id: UUID) -> list[Delivery]:
        found = [d for d in self.delivered if d.deliverable_id == deliverable_id]
        return sorted(found, key=lambda d: (d.fetched_at, d.delivery_id))

    def raise_ops_alert(self, alert: OpsAlert) -> bool:
        if any(a.dedup_key == alert.dedup_key for a in self.alerts):
            return False
        self.alerts.append(alert)
        return True

    def ops_alerts(self, limit: int) -> list[OpsAlert]:
        ordered = sorted(self.alerts, key=lambda a: (a.at, a.alert_id), reverse=True)
        return ordered[:limit]

    def acknowledge(self, ack: AlertAck) -> AlertAck:
        for existing in self.acked:
            if (existing.source, existing.alert_id) == (ack.source, ack.alert_id):
                return existing
        self.acked.append(ack)
        return ack

    def acks(self, source: AlertSource, alert_ids: Sequence[UUID]) -> dict[UUID, AlertAck]:
        wanted = set(alert_ids)
        return {a.alert_id: a for a in self.acked if a.source == source and a.alert_id in wanted}

    def append_ops_run(self, run: OpsRun) -> None:
        self.runs.append(run)

    def latest_ops_run(self) -> OpsRun | None:
        return max(self.runs, key=lambda r: (r.due_at, r.at, r.run_id), default=None)

    def healthy(self) -> bool:
        return True
