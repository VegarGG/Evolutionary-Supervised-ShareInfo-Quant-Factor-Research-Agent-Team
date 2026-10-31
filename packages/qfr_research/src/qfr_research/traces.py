"""Trace exports and iteration histories (PLAN Sections 14.4 and 14.5).

Both are deterministic renderings of trace steps, agent runs, lineage edges and cached
released reports; no LLM writes any part of them. A trace export (trace/1) holds every
step for a version or candidate and its ancestors, ordered by (at, step_id), with the
agent runs inlined; its SHA-256 over canonical JSON is the trace_hash a deliverable
stores. Owner-grade records are never stored here: the front door joins them.
"""

import hashlib
from typing import Any
from uuid import UUID

from qfr_core.config import canonical_json
from qfr_core.contracts import (
    AgentRunRef,
    HistoryHop,
    IterationHistory,
    ReleasedReport,
    ResearchAssessment,
    TraceAgentRun,
    TraceExport,
    TraceLineageEdge,
    TraceStep,
)
from qfr_core.dsl import ast_diff, canonicalize, parse
from sqlalchemy import text
from sqlalchemy.engine import Connection

STEP_COLUMNS = (
    "step_id, at, job_id, program_id, generation_id, task_id, candidate_id, version_id, "
    "step_type, actor_kind, actor, provider, model_id, prompt_template_id, prompt_sha256, "
    "run_id, inputs, payload, outcome, request_id"
)


class TraceNotFound(LookupError):
    pass


def trace_hash(export: TraceExport) -> str:
    body = export.model_dump(mode="json", exclude={"owner_records"})
    return hashlib.sha256(canonical_json(body).encode()).hexdigest()


def _step(row: Any) -> TraceStep:
    data = dict(row._mapping)
    return TraceStep.model_validate({"schema_version": "trace_step/1"} | data)


def candidate_chain(conn: Connection, candidate_id: UUID) -> list[Any]:
    """The candidate and the earlier review rounds it revised, oldest first."""
    chain: list[Any] = []
    current: UUID | None = candidate_id
    while current is not None and len(chain) < 20:
        row = conn.execute(
            text(
                "SELECT c.*, p.job_id FROM candidates c JOIN programs p ON "
                "p.program_id = c.program_id WHERE c.candidate_id = :c"
            ),
            {"c": current},
        ).first()
        if row is None:
            break
        chain.append(row)
        current = row.parent_candidate_id
    return list(reversed(chain))


def version_candidate(conn: Connection, version_id: UUID) -> UUID | None:
    return conn.execute(
        text("SELECT candidate_id FROM candidate_versions WHERE version_id = :v"),
        {"v": version_id},
    ).scalar()


def ancestors(conn: Connection, version_id: UUID, depth: int = 20) -> list[UUID]:
    found: list[UUID] = []
    frontier = [version_id]
    while frontier and len(found) < depth:
        rows = conn.execute(
            text("SELECT parent_version_id FROM lineage_edges WHERE child_version_id = ANY(:v)"),
            {"v": frontier},
        ).all()
        frontier = [r.parent_version_id for r in rows if r.parent_version_id not in found]
        found += frontier
    return found


def export(
    conn: Connection, *, version_id: UUID | None = None, candidate_id: UUID | None = None
) -> TraceExport:
    if version_id is not None and candidate_id is None:
        candidate_id = version_candidate(conn, version_id)
        if candidate_id is None:
            raise TraceNotFound(f"version {version_id} was not published by research")
    if candidate_id is None:
        raise TraceNotFound("give a version or a candidate")
    chain = candidate_chain(conn, candidate_id)
    if not chain:
        raise TraceNotFound(f"no candidate {candidate_id}")
    subject = chain[-1]
    versions = [version_id] if version_id is not None else []
    parent_versions = ancestors(conn, version_id) if version_id is not None else []
    ancestor_candidates = [
        c for v in parent_versions if (c := version_candidate(conn, v)) is not None
    ]
    candidate_ids = [c.candidate_id for c in chain]
    for ancestor in ancestor_candidates:
        candidate_ids += [c.candidate_id for c in candidate_chain(conn, ancestor)]
    tasks = {
        r.task_id
        for r in conn.execute(
            text("SELECT task_id FROM candidates WHERE candidate_id = ANY(:c)"),
            {"c": candidate_ids},
        ).all()
    }
    generations = {
        r.generation_id
        for r in conn.execute(
            text("SELECT generation_id FROM candidates WHERE candidate_id = ANY(:c)"),
            {"c": candidate_ids},
        ).all()
    }
    all_versions = versions + parent_versions
    rows = conn.execute(
        text(
            f"SELECT {STEP_COLUMNS} FROM trace_steps WHERE candidate_id = ANY(:c) "
            "OR (candidate_id IS NULL AND task_id = ANY(:t)) "
            "OR (task_id IS NULL AND candidate_id IS NULL AND generation_id = ANY(:g)) "
            "OR (generation_id IS NULL AND job_id = :j AND step_type IN ('BRIEF_RECEIVED', "
            "'CHARTER_DERIVED', 'SEEDS_PUBLISHED', 'STEERING_ADDED')) "
            "OR (version_id = ANY(:v)) ORDER BY at, step_id"
        ),
        {
            "c": candidate_ids,
            "t": list(tasks),
            "g": list(generations),
            "j": subject.job_id,
            "v": all_versions,
        },
    ).all()
    steps = [_step(r) for r in rows]
    run_ids = sorted({s.run_id for s in steps if s.run_id is not None}, key=str)
    runs = conn.execute(
        text(
            "SELECT run_id, step_id, role, provider, model_id, prompt_template_id, "
            "prompt_sha256, request_messages, response_text, response_json, usage, settings, "
            "status, latency_ms FROM agent_runs WHERE run_id = ANY(:r) ORDER BY created_at, run_id"
        ),
        {"r": run_ids},
    ).all()
    lineage = conn.execute(
        text(
            "SELECT child_version_id, parent_version_id, relation, operator, ast_diff FROM "
            "lineage_edges WHERE child_version_id = ANY(:v) ORDER BY created_at, "
            "parent_version_id"
        ),
        {"v": all_versions},
    ).all()
    reports = conn.execute(
        text(
            "SELECT content FROM report_cache WHERE version_id = ANY(:v) "
            "ORDER BY released_at, report_id"
        ),
        {"v": all_versions},
    ).all()
    return TraceExport(
        schema_version="trace/1",
        version_id=version_id,
        candidate_id=subject.candidate_id,
        job_id=subject.job_id,
        ancestors=parent_versions,
        steps=steps,
        agent_runs=[TraceAgentRun.model_validate(dict(r._mapping)) for r in runs],
        lineage=[TraceLineageEdge.model_validate(dict(r._mapping)) for r in lineage],
        released_reports=[ReleasedReport.model_validate(r.content) for r in reports],
    )


def iteration_history(
    conn: Connection, version_id: UUID, generated_at: Any, trace: TraceExport
) -> IterationHistory:
    """One hop per published version on the path from the root to this version."""
    path = list(reversed(ancestors(conn, version_id))) + [version_id]
    hops: list[HistoryHop] = []
    roots: list[UUID] = []
    discarded: list[dict[str, Any]] = []
    calls = tokens = 0
    cost = 0.0
    for current in path:
        candidate_id = version_candidate(conn, current)
        if candidate_id is None:
            roots.append(current)  # a seed or pool version the lineage starts from
            continue
        chain = candidate_chain(conn, candidate_id)
        final = chain[-1]
        hypothesis = (
            conn.execute(
                text("SELECT payload FROM hypotheses WHERE hypothesis_id = :h"),
                {"h": final.hypothesis_id},
            ).scalar()
            or {}
        )
        if not final.payload.get("parent_version_ids") and final.hypothesis_id is not None:
            roots.append(final.hypothesis_id)
        parents = [UUID(p) for p in final.payload.get("parent_version_ids", [])]
        before = []
        for parent in parents:
            manifest = conn.execute(
                text(
                    "SELECT payload -> 'manifest' -> 'implementation' ->> 'expression' AS e "
                    "FROM trace_steps WHERE step_type = 'PUBLISHED' AND version_id = :v"
                ),
                {"v": parent},
            ).scalar()
            if manifest:
                before.append(manifest)
        after = final.expression or canonical_json(final.payload.get("components", []))
        diff: list[dict[str, Any]] = []
        if final.expression and len(before) == 1:
            diff = [
                dict(e)
                for e in ast_diff(canonicalize(parse(before[0])), canonicalize(parse(after)))
            ]
        engineer = conn.execute(
            text(
                "SELECT role, provider, model_id, prompt_template_id, prompt_sha256, run_id "
                "FROM agent_runs WHERE run_id = :r"
            ),
            {"r": final.engineer_run_id},
        ).first()
        reviews = conn.execute(
            text(
                "SELECT r.verdict, r.payload, r.round, a.provider, a.model_id FROM reviews r "
                "JOIN agent_runs a ON a.run_id = r.run_id WHERE r.candidate_id = ANY(:c) "
                "ORDER BY r.round"
            ),
            {"c": [c.candidate_id for c in chain]},
        ).all()
        last = reviews[-1] if reviews else None
        critic = None
        if last is not None:
            scores = {
                k: last.payload.get(k)
                for k in ("c1", "c2", "plausibility", "parsimony", "originality", "lookahead_risk")
            }
            critic = {
                "provider": last.provider,
                "model_id": last.model_id,
                "verdict": last.verdict,
                "scores": scores,
                "rounds": len(reviews),
            }
        workbench = final.workbench or {}
        seq: int = conn.execute(
            text("SELECT seq FROM generations WHERE generation_id = :g"),
            {"g": final.generation_id},
        ).scalar_one()
        reports = [
            ReleasedReport.model_validate(r.content)
            for r in conn.execute(
                text(
                    "SELECT content FROM report_cache WHERE version_id = :v "
                    "ORDER BY released_at, report_id"
                ),
                {"v": current},
            ).all()
        ]
        flags = (
            sorted(
                {f for r in reports for f in getattr(r.content, "flags", [])}, key=lambda f: f.value
            )
            if parents
            else []
        )
        hops.append(
            HistoryHop(
                from_version_ids=parents,
                to_version_id=current,
                candidate_id=final.candidate_id,
                generation_seq=seq,
                operator=final.operator,
                targeted_flags=flags,
                hypothesis_title=str(hypothesis.get("title", "")),
                change_summary=str(
                    final.payload.get("change_summary")
                    or "New expression implementing the hypothesis (as written by the engineer)."
                ),
                expression_before=before,
                expression_after=after,
                ast_diff=diff,
                engineer=None
                if engineer is None
                else AgentRunRef.model_validate(
                    {k: getattr(engineer, k) for k in engineer._fields}
                ),
                critic=critic,
                workbench=ResearchAssessment.model_validate(
                    {
                        "visibility": "research_non_official",
                        "window": "W0",
                        "metrics": dict(workbench.get("metrics") or {}),
                    }
                )
                if workbench.get("metrics")
                else None,
                evaluation=reports,
                owner_grade=None,
                outcome="published",
            )
        )
        for sibling in conn.execute(
            text(
                "SELECT candidate_id, state, reason, expression FROM candidates WHERE "
                "task_id = :t AND candidate_id <> ALL(:c) AND state IN ('not_selected', "
                "'rejected', 'invalid', 'approved') ORDER BY created_at"
            ),
            {"t": final.task_id, "c": [c.candidate_id for c in chain]},
        ).all():
            discarded.append(
                {
                    "candidate_id": str(sibling.candidate_id),
                    "state": sibling.state,
                    "reason": sibling.reason,
                    "expression": sibling.expression,
                }
            )
        usage = conn.execute(
            text(
                "SELECT count(*) AS n, coalesce(sum(tokens_in + tokens_out), 0) AS tokens, "
                "coalesce(sum(cost_cny), 0) AS cost FROM budget_ledger WHERE task_id = :t"
            ),
            {"t": final.task_id},
        ).one()
        calls += int(usage.n)
        tokens += int(usage.tokens)
        cost += float(usage.cost)
    family = conn.execute(
        text(
            "SELECT payload ->> 'family_id' FROM trace_steps WHERE step_type = 'PUBLISHED' "
            "AND version_id = :v"
        ),
        {"v": version_id},
    ).scalar()
    trials: int = conn.execute(
        text(
            "SELECT count(*) FROM trace_steps WHERE step_type = 'PUBLISHED' AND outcome = 'ok' "
            "AND payload ->> 'family_id' = :f"
        ),
        {"f": family},
    ).scalar_one()
    return IterationHistory(
        schema_version="iteration_history/1",
        version_id=version_id,
        job_id=trace.job_id,
        generated_at=generated_at,
        trace_hash=trace_hash(trace),
        roots=roots,
        hops=hops,
        discarded=discarded,
        totals={
            "hops": len(hops),
            "llm_calls": calls,
            "tokens": tokens,
            "cost_cny": round(cost, 6),
            "trials_in_family": int(trials),
        },
    )


def history_markdown(history: IterationHistory) -> str:
    """The owner-facing rendering: one section per hop (Section 14.4)."""
    lines = [f"# Iteration history of {history.version_id}", ""]
    for i, hop in enumerate(history.hops, 1):
        lines += [
            f"## Hop {i}: {hop.operator} (generation {hop.generation_seq})",
            f"- Hypothesis: {hop.hypothesis_title}",
            f"- Change (as written by the engineer): {hop.change_summary}",
            f"- Before: {', '.join(hop.expression_before) or 'none (new expression)'}",
            f"- After: {hop.expression_after}",
        ]
        if hop.engineer is not None:
            lines.append(f"- Engineer: {hop.engineer.provider}/{hop.engineer.model_id}")
        if hop.critic is not None:
            lines.append(
                f"- Critic: {hop.critic['provider']}/{hop.critic['model_id']}, "
                f"{hop.critic['verdict']} after {hop.critic['rounds']} round(s)"
            )
        if hop.workbench is not None:
            lines.append(
                f"- Workbench (W0, in-sample): {canonical_json(dict(hop.workbench.metrics))}"
            )
        for report in hop.evaluation:
            values = canonical_json(report.content.model_dump(mode="json"))
            lines.append(f"- Released {report.content.type}: {values}")
        lines.append("")
    lines.append(f"Totals: {canonical_json(history.totals)}")
    return "\n".join(lines) + "\n"
