"""control_db setup state and the front door's trace steps (PLAN Sections 13.6 and 14.5).

Both tables are insert-only: a setup change is a new setup_state row (the latest row per
step is current), and a re-import reuses the DSL_VALIDATED step recorded for the same
entry digest instead of writing a second one.
"""

from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Annotated, Any, Literal, Protocol
from uuid import UUID

from pydantic import UUID7, AwareDatetime, JsonValue, StringConstraints
from qfr_core.config import canonical_json
from qfr_core.contracts import Contract, TraceStep
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, RowMapping

SetupStep = Literal["pool", "providers", "data", "token"]
SETUP_STEPS: tuple[SetupStep, ...] = ("pool", "providers", "data", "token")
SetupStatus = Annotated[str, StringConstraints(pattern=r"^[a-z_]{1,32}$")]
SeedKind = Literal["factor", "strategy"]


class SetupState(Contract):
    state_id: UUID7
    at: AwareDatetime
    step: SetupStep
    status: SetupStatus
    details: dict[str, JsonValue]
    principal: str
    request_id: str


class ControlStore(Protocol):
    def append_setup_state(self, state: SetupState) -> None: ...
    def latest_setup_states(self) -> dict[str, SetupState]: ...
    def append_trace_step(self, step: TraceStep) -> None: ...
    def find_validation(self, entry_digest: str) -> TraceStep | None: ...
    def latest_publication(self, kind: SeedKind, name: str) -> TraceStep | None: ...
    def publication_of(self, version_id: UUID) -> TraceStep | None: ...
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

    def healthy(self) -> bool:
        return True
