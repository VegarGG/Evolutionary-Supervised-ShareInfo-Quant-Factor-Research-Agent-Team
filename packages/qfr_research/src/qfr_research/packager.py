"""The packager (P4.7, PLAN Sections 7.7, 14.5 and 16.5).

Deterministic code: for a selected candidate it runs the trace completeness check
(TRACE_CHECKED), assembles the manifest with full provenance and publishes it to
registry-api with the publisher token. A candidate whose trace lacks a required step for
its operator is refused: the refusal is a failed TRACE_CHECKED step and a WARNING line,
and the candidate becomes not_selected with reason TRACE_INCOMPLETE (TRC-01).
"""

import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from qfr_core.contracts import FactorManifest, StrategyManifest
from qfr_core.dsl import ast_diff, canonicalize, parse
from qfr_core.ids import uuid7
from qfr_core.registry_api import VersionRecord
from sqlalchemy import text
from sqlalchemy.engine import Connection

from qfr_research.clients import ServiceRefused, ServiceUnavailable
from qfr_research.env import QFR_CORE_VERSION, ResearchEnv
from qfr_research.store import Ctx
from qfr_research.tools import require_write

LLM_DEVELOPMENT = (
    ("engineer_run", "PROMPT_SENT"),
    ("engineer_run", "MODEL_RESPONDED"),
    ("candidate", "DRAFT_CREATED"),
    ("candidate", "DSL_VALIDATED"),
    ("candidate", "WORKBENCH_EVALUATED"),
    ("candidate", "SIMILARITY_CHECKED"),
    ("candidate", "CRITIC_REVIEWED"),
    ("candidate", "PRESCREEN_EVALUATED"),
    ("candidate", "SELECTED"),
)
APPLIED = {
    "llm_mutation": "MUTATION_APPLIED",
    "crossover": "CROSSOVER_APPLIED",
    "repair": "REPAIR_APPLIED",
}
# Section 14.5: the steps each operator needs before PUBLISHED.
REQUIRED: dict[str, tuple[tuple[str, str], ...]] = {
    "explore": (
        ("job", "BRIEF_RECEIVED"),
        ("generation", "PLAN_WRITTEN"),
        ("hypothesis", "HYPOTHESIS_PROPOSED"),
        *LLM_DEVELOPMENT,
    ),
    **{
        operator: (
            ("job", "BRIEF_RECEIVED"),
            ("generation", "PLAN_WRITTEN"),
            ("candidate", "PARENT_SELECTED"),
            ("candidate", step),
            *LLM_DEVELOPMENT,
        )
        for operator, step in APPLIED.items()
    },
    "syntactic_mutation": (
        ("candidate", "PARENT_SELECTED"),
        ("candidate", "SYNTACTIC_MUTATION_APPLIED"),
        ("candidate", "DSL_VALIDATED"),
        ("candidate", "WORKBENCH_EVALUATED"),
        ("candidate", "SIMILARITY_CHECKED"),
        ("candidate", "PRESCREEN_EVALUATED"),
        ("candidate", "SELECTED"),
    ),
    "compose_strategy": (
        ("candidate", "STRATEGY_COMPOSED"),
        *LLM_DEVELOPMENT,
    ),
}


@dataclass(frozen=True)
class TraceCheck:
    complete: bool
    required: list[str]
    present: list[str]
    missing: list[str]


def check_trace(conn: Connection, candidate: Any) -> TraceCheck:
    operator = "compose_strategy" if candidate.kind == "strategy" else candidate.operator
    required = REQUIRED.get(operator, REQUIRED["explore"])
    present: list[str] = []
    missing: list[str] = []
    for scope, step in required:
        found = _has_step(conn, candidate, scope, step)
        (present if found else missing).append(f"{scope}:{step}")
    if candidate.operator in APPLIED or candidate.operator == "syntactic_mutation":
        parents = list(candidate.payload.get("parent_version_ids", []))
        if not parents:
            missing.append("lineage:parents")
    return TraceCheck(not missing, [f"{s}:{t}" for s, t in required], present, missing)


def _has_step(conn: Connection, candidate: Any, scope: str, step: str) -> bool:
    clauses = {
        "job": ("job_id = :id", candidate.job_id),
        "generation": ("generation_id = :id", candidate.generation_id),
        "candidate": ("candidate_id = :id", candidate.candidate_id),
        "engineer_run": ("run_id = :id AND actor = 'engineer'", candidate.engineer_run_id),
        "hypothesis": ("payload ->> 'hypothesis_id' = CAST(:id AS text)", candidate.hypothesis_id),
    }
    clause, value = clauses[scope]
    if value is None:
        return False
    return (
        conn.execute(
            text(
                f"SELECT 1 FROM trace_steps WHERE step_type = :t AND outcome = 'ok' AND {clause} "
                "LIMIT 1"
            ),
            {"t": step, "id": value},
        ).first()
        is not None
    )


CANDIDATE_SQL = (
    "SELECT c.*, g.job_id, h.payload AS hypothesis FROM candidates c "
    "JOIN programs g ON g.program_id = c.program_id "
    "LEFT JOIN hypotheses h ON h.hypothesis_id = c.hypothesis_id WHERE c.candidate_id = :c"
)


class Packager:
    def __init__(self, env: ResearchEnv) -> None:
        self.env = env

    def publish(self, ctx: Ctx, candidate_id: UUID) -> VersionRecord | None:
        env = self.env
        cctx = ctx.with_(candidate_id=candidate_id)
        with env.db.transaction() as conn:
            row = conn.execute(text(CANDIDATE_SQL), {"c": candidate_id}).one()
            cctx = cctx.with_(task_id=row.task_id)
            check = check_trace(conn, row)
            env.trace.step(
                conn,
                "TRACE_CHECKED",
                cctx,
                actor="packager",
                inputs={"operator": row.operator, "required": check.required},
                payload={"present": check.present, "missing": check.missing},
                outcome="ok" if check.complete else "failed",
            )
            if not check.complete:
                conn.execute(
                    text(
                        "UPDATE candidates SET state = 'not_selected', "
                        "reason = 'TRACE_INCOMPLETE', updated_at = :now WHERE candidate_id = :c"
                    ),
                    {"now": env.clock.now(), "c": candidate_id},
                )
        if not check.complete:
            env.logger.logger.warning(
                "publication_refused",
                outcome="failed",
                error_code="TRACE_INCOMPLETE",
                payload={"missing": check.missing},
                **cctx.log_ids(),
            )
            return None
        with env.db.read() as conn:
            manifest = self.manifest(conn, row)
        try:
            response = env.registry.publish(manifest, f"cand:{candidate_id}")
        except (ServiceRefused, ServiceUnavailable) as error:
            with env.db.transaction() as conn:
                conn.execute(
                    text(
                        "UPDATE candidates SET state = 'publish_failed', reason = :r, "
                        "updated_at = :now WHERE candidate_id = :c"
                    ),
                    {"r": str(error)[:300], "now": env.clock.now(), "c": candidate_id},
                )
                env.trace.step(
                    conn,
                    "PUBLISHED",
                    cctx,
                    actor="packager",
                    inputs={"publish_key": f"cand:{candidate_id}"},
                    payload={"error": str(error)[:500]},
                    outcome="failed",
                )
            env.logger.logger.error(
                "publication_failed",
                outcome="failed",
                payload={"error": str(error)[:300]},
                **cctx.log_ids(),
            )
            return None
        version = response.version
        with env.db.transaction() as conn:
            require_write(env, "packager", "publication_link", cctx)
            step_id = env.trace.step(
                conn,
                "PUBLISHED",
                cctx,
                actor="packager",
                version_id=version.version_id,
                inputs={"publish_key": f"cand:{candidate_id}", "created": response.created},
                payload={
                    "version_id": str(version.version_id),
                    "family_id": str(version.family_id),
                    "version_no": version.version_no,
                    "content_hash": version.content_hash,
                    "canonical_hash": version.canonical_hash,
                    "manifest": manifest.model_dump(mode="json"),
                },
            )
            conn.execute(
                text(
                    "INSERT INTO candidate_versions (candidate_id, version_id, family_id, "
                    "content_hash, published_at, step_id) VALUES (:c, :v, :f, :h, :at, :s) "
                    "ON CONFLICT (candidate_id) DO NOTHING"
                ),
                {
                    "c": candidate_id,
                    "v": version.version_id,
                    "f": version.family_id,
                    "h": version.content_hash,
                    "at": version.published_at,
                    "s": step_id,
                },
            )
            conn.execute(
                text(
                    "UPDATE candidates SET state = 'published', updated_at = :now "
                    "WHERE candidate_id = :c"
                ),
                {"now": env.clock.now(), "c": candidate_id},
            )
            self._lineage(conn, cctx, row, version.version_id)
        env.logger.logger.info(
            "candidate_published",
            outcome="ok",
            version_id=str(version.version_id),
            family_id=str(version.family_id),
            payload={"created": response.created, "operator": row.operator},
            **cctx.log_ids(),
        )
        return version

    def _lineage(self, conn: Connection, ctx: Ctx, row: Any, version_id: UUID) -> None:
        parents = [UUID(p) for p in row.payload.get("parent_version_ids", [])]
        if not parents:
            return
        require_write(self.env, "packager", "lineage_edge", ctx)
        relation = {
            "crossover": "crossover",
            "compose_strategy": "composition",
        }.get(row.operator, "mutation" if row.kind == "factor" else "composition")
        for parent in parents:
            diff = None
            if row.kind == "factor":
                try:
                    parent_expression = self.env.registry.version(parent).manifest
                    before = getattr(parent_expression.implementation, "expression", None)
                    if before:
                        diff = ast_diff(
                            canonicalize(parse(before)), canonicalize(parse(row.expression))
                        )
                except Exception:  # noqa: BLE001 - lineage diff is best effort; parents stay
                    diff = None
            conn.execute(
                text(
                    "INSERT INTO lineage_edges (child_version_id, parent_version_id, relation, "
                    "operator, ast_diff, candidate_id, program_id, created_at) VALUES (:c, :p, "
                    ":r, :o, CAST(:d AS jsonb), :cand, :prog, :now) ON CONFLICT DO NOTHING"
                ),
                {
                    "c": version_id,
                    "p": parent,
                    "r": relation,
                    "o": row.operator,
                    "d": None if diff is None else _dumps(diff),
                    "cand": row.candidate_id,
                    "prog": row.program_id,
                    "now": self.env.clock.now(),
                },
            )

    def manifest(self, conn: Connection, row: Any) -> FactorManifest | StrategyManifest:
        payload, hypothesis = row.payload, row.hypothesis or {}
        reviews = conn.execute(
            text(
                "SELECT review_id, round, run_id, provider FROM reviews WHERE candidate_id = :c "
                "ORDER BY round"
            ),
            {"c": row.candidate_id},
        ).all()
        runs = conn.execute(
            text(
                "SELECT run_id, role, provider, model_id, prompt_template_id, prompt_sha256 "
                "FROM agent_runs WHERE status = 'ok' AND (run_id = :e OR run_id = ANY(:r)) "
                "ORDER BY created_at"
            ),
            {"e": row.engineer_run_id, "r": [r.run_id for r in reviews]},
        ).all()
        agent_runs = [
            {
                "role": r.role,
                "provider": r.provider,
                "model_id": r.model_id,
                "prompt_template_id": r.prompt_template_id,
                "prompt_sha256": r.prompt_sha256,
                "run_id": str(r.run_id),
            }
            for r in runs
        ]
        generation = conn.execute(
            text(
                "SELECT g.generation_id, p.research_snapshot_id, p.job_id FROM generations g "
                "JOIN programs p ON p.program_id = g.program_id WHERE g.generation_id = :g"
            ),
            {"g": row.generation_id},
        ).one()
        title = str(hypothesis.get("title") or payload.get("title") or "Research candidate")
        provenance = {
            "job_id": str(generation.job_id),
            "program_id": str(row.program_id),
            "generation_id": str(row.generation_id),
            "island_id": row.island_key,
            "operator": row.operator if row.kind == "factor" else "explore",
            "parent_version_ids": list(payload.get("parent_version_ids", [])),
            "agent_runs": agent_runs,
            "trace_ref": str(row.candidate_id),
            "research_snapshot_id": generation.research_snapshot_id,
            "qfr_core_version": QFR_CORE_VERSION,
        }
        rationale = {
            "hypothesis_id": str(row.hypothesis_id),
            "summary": str(payload.get("description", title))[:1500],
            "mechanism": str(hypothesis.get("mechanism", payload.get("description", "")))[:1500]
            or "Not stated.",
            "falsification": str(hypothesis.get("falsification", "Not stated."))[:600],
            "change_summary": payload.get("change_summary"),
        }
        review = {"verdict_id": str(reviews[-1].review_id), "rounds": len(reviews)}
        workbench = row.workbench or {}
        assessment = {
            "visibility": "research_non_official",
            "window": "W0",
            "metrics": {k: v for k, v in (workbench.get("metrics") or {}).items()},
        }
        name = _slug(f"{row.island_key}-{title}", str(row.candidate_id))
        if row.kind == "factor":
            analysis = row.analysis or {}
            return FactorManifest.model_validate(
                {
                    "schema_version": "1",
                    "kind": "factor",
                    "family_id": None,
                    "name": name,
                    "title": title[:120],
                    "implementation": {"language": "qfr-dsl/1", "expression": row.expression},
                    "declared": {
                        "expected_sign": payload["expected_sign"],
                        "horizon_days": payload["horizon_days"],
                        "fields_used": analysis["fields"],
                        "max_lookback_days": analysis["max_lookback_days"],
                    },
                    "rationale": rationale,
                    "provenance": provenance,
                    "self_assessment": assessment,
                    "review": review,
                }
            )
        return StrategyManifest.model_validate(
            {
                "schema_version": "1",
                "kind": "strategy",
                "family_id": None,
                "name": name,
                "title": title[:120],
                "implementation": {
                    "language": "qfr-strategy/1",
                    "components": payload["components"],
                    "combination": "zscore_weighted_sum",
                    "portfolio": {
                        "type": "topk_dropout",
                        "top_k": payload["portfolio"]["top_k"],
                        "dropout": payload["portfolio"]["dropout"],
                        "rebalance": "daily",
                        "long_only": True,
                    },
                },
                "declared": {"expected_sign": 1, "horizon_days": payload["expected_horizon_days"]},
                "rationale": rationale
                | {
                    "composition_rationale": payload["composition_rationale"][:1000],
                    "change_summary": payload.get("change_summary") or "Composed from components.",
                },
                "provenance": provenance,
                "self_assessment": assessment,
                "review": review,
            }
        )


def _slug(title: str, unique: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:48] or "candidate"
    return f"{base}-{unique.replace('-', '')[-12:]}"


def _dumps(value: Any) -> str:
    from qfr_research.db import dumps

    return dumps(value)


def new_review_id() -> UUID:
    return uuid7()
