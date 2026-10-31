"""Inserts into the insert-only research tables: trace steps, agent runs, job events and
the audit log (PLAN Sections 14.3 and 16.2).

Trace steps are written only by deterministic code (the tool layer, the workflow, the
packager, the job service), never by an agent. Every insert happens inside the caller's
transaction, so a step and the state change it records commit together.
"""

from dataclasses import dataclass, field, replace
from typing import Any
from uuid import UUID

from qfr_core.correlation import current
from qfr_core.ids import uuid7
from qfr_core.logging import JsonLogger
from sqlalchemy import text
from sqlalchemy.engine import Connection

from qfr_research.db import Clock, dumps


@dataclass(frozen=True)
class Ctx:
    """The research ids a step belongs to; also bound into every log line."""

    job_id: UUID | None = None
    program_id: UUID | None = None
    generation_id: UUID | None = None
    task_id: UUID | None = None
    candidate_id: UUID | None = None
    extra: dict[str, str] = field(default_factory=dict)

    def with_(self, **ids: UUID | None) -> "Ctx":
        return replace(self, **ids)  # type: ignore[arg-type]

    def log_ids(self) -> dict[str, str]:
        ids = {
            "job_id": self.job_id,
            "program_id": self.program_id,
            "generation_id": self.generation_id,
            "task_id": self.task_id,
            "candidate_id": self.candidate_id,
        }
        return {k: str(v) for k, v in ids.items() if v is not None}


@dataclass(frozen=True)
class LlmAttribution:
    provider: str
    model_id: str
    prompt_template_id: str
    prompt_sha256: str
    run_id: UUID


class TraceWriter:
    def __init__(self, logger: JsonLogger, clock: Clock) -> None:
        self.logger, self.clock = logger, clock

    def step(
        self,
        conn: Connection,
        step_type: str,
        ctx: Ctx,
        *,
        actor_kind: str = "deterministic",
        actor: str,
        inputs: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
        outcome: str = "ok",
        version_id: UUID | None = None,
        llm: LlmAttribution | None = None,
    ) -> UUID:
        step_id = uuid7()
        conn.execute(
            text(
                "INSERT INTO trace_steps (step_id, at, job_id, program_id, generation_id, "
                "task_id, candidate_id, version_id, step_type, actor_kind, actor, provider, "
                "model_id, prompt_template_id, prompt_sha256, run_id, inputs, payload, "
                "outcome, request_id) VALUES (:s, :at, :j, :p, :g, :t, :c, :v, :type, :ak, "
                ":a, :prov, :m, :tpl, :sha, :run, CAST(:i AS jsonb), CAST(:pl AS jsonb), :o, "
                ":r)"
            ),
            {
                "s": step_id,
                "at": self.clock.now(),
                "j": ctx.job_id,
                "p": ctx.program_id,
                "g": ctx.generation_id,
                "t": ctx.task_id,
                "c": ctx.candidate_id,
                "v": version_id,
                "type": step_type,
                "ak": actor_kind,
                "a": actor,
                "prov": llm.provider if llm else None,
                "m": llm.model_id if llm else None,
                "tpl": llm.prompt_template_id if llm else None,
                "sha": llm.prompt_sha256 if llm else None,
                "run": llm.run_id if llm else None,
                "i": dumps(inputs or {}),
                "pl": dumps(payload or {}),
                "o": outcome,
                "r": current().get("request_id", str(step_id)),
            },
        )
        return step_id


def insert_agent_run(conn: Connection, clock: Clock, ctx: Ctx, row: dict[str, Any]) -> None:
    conn.execute(
        text(
            "INSERT INTO agent_runs (run_id, step_id, job_id, program_id, generation_id, "
            "task_id, candidate_id, role, provider, model_id, prompt_template_id, "
            "prompt_sha256, request_messages, response_text, response_json, usage, settings, "
            "status, latency_ms, created_at) VALUES (:run, :step, :j, :p, :g, :t, :c, :role, "
            ":prov, :m, :tpl, :sha, CAST(:req AS jsonb), :resp, CAST(:rj AS jsonb), "
            "CAST(:u AS jsonb), CAST(:st AS jsonb), :status, :lat, :at)"
        ),
        {
            "run": row["run_id"],
            "step": row.get("step_id"),
            "j": ctx.job_id,
            "p": ctx.program_id,
            "g": ctx.generation_id,
            "t": ctx.task_id,
            "c": ctx.candidate_id,
            "role": row["role"],
            "prov": row["provider"],
            "m": row["model_id"],
            "tpl": row["prompt_template_id"],
            "sha": row["prompt_sha256"],
            "req": dumps(row["request_messages"]),
            "resp": row["response_text"],
            "rj": None if row.get("response_json") is None else dumps(row["response_json"]),
            "u": dumps(row["usage"]),
            "st": dumps(row["settings"]),
            "status": row["status"],
            "lat": row["latency_ms"],
            "at": clock.now(),
        },
    )


def job_event(
    conn: Connection, clock: Clock, job_id: UUID, kind: str, payload: dict[str, Any]
) -> int:
    seq = int(
        conn.execute(
            text("SELECT coalesce(max(seq), 0) + 1 FROM job_events WHERE job_id = :j"),
            {"j": job_id},
        ).scalar_one()
    )
    conn.execute(
        text(
            "INSERT INTO job_events (event_id, job_id, seq, at, kind, payload, request_id) "
            "VALUES (:e, :j, :s, :at, :k, CAST(:p AS jsonb), :r)"
        ),
        {
            "e": uuid7(),
            "j": job_id,
            "s": seq,
            "at": clock.now(),
            "k": kind,
            "p": dumps(payload),
            "r": current().get("request_id", "internal"),
        },
    )
    return seq


def audit(
    conn: Connection,
    clock: Clock,
    principal: str,
    action: str,
    entity_type: str,
    entity_id: object,
    payload: dict[str, Any],
) -> None:
    conn.execute(
        text(
            "INSERT INTO events (event_id, at, principal, action, entity_type, entity_id, "
            "request_id, payload) VALUES (:e, :at, :p, :a, :t, :i, :r, CAST(:pl AS jsonb))"
        ),
        {
            "e": uuid7(),
            "at": clock.now(),
            "p": principal,
            "a": action,
            "t": entity_type,
            "i": str(entity_id),
            "r": current().get("request_id", "internal"),
            "pl": dumps(payload),
        },
    )
