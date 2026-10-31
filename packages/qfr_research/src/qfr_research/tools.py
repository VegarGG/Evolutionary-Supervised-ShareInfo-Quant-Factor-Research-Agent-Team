"""The research tool layer (P4.3, PLAN Section 11.3).

Each tool is a typed function registered with an allow-list of roles. The layer checks
the calling role on every invocation, logs the call and appends a trace step. There is
deliberately no tool that touches evaluation scheduling, protocols, simulations,
official records, pools or the owner's jobs; BND-02 snapshots this registry.

Agents receive the read and analysis tools as PydanticAI tools. blackboard.write and
registry.publish are not offered to any model: the workflow and the packager call them
on a role's behalf after validating its structured output, and the write scopes below
are checked on every write.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

from pydantic_ai import RunContext, Tool
from qfr_core.dsl import canonicalize, parse, validate
from qfr_core.dsl.explain import explain
from qfr_core.dsl.similarity import ast_similarity
from qfr_core.metrics.fingerprint import behavioral_similarity
from sqlalchemy import text

from qfr_research.env import ResearchEnv
from qfr_research.store import Ctx

ToolRole = Literal[
    "supervisor", "hypothesis", "engineer", "critic", "analyst", "evolution", "packager"
]
ALL_ROLES: frozenset[str] = frozenset(
    {"supervisor", "hypothesis", "engineer", "critic", "analyst", "evolution", "packager"}
)
# The interpretation reviewer is the critic prompt in interpretation mode (Section 11.2).
ROLE_ALIASES = {"interp_review": "critic"}

# Section 11.3, write scopes of blackboard.write.
WRITE_SCOPES: dict[str, frozenset[str]] = {
    "supervisor": frozenset({"plan", "task"}),
    "hypothesis": frozenset({"hypothesis"}),
    "engineer": frozenset({"candidate", "strategy_draft"}),
    "critic": frozenset({"review", "interpretation_challenge"}),
    "analyst": frozenset({"interpretation", "knowledge_item"}),
    "evolution": frozenset({"population_member", "archive_cell", "bandit_state"}),
    "packager": frozenset({"publication_link", "lineage_edge"}),
}
WORKBENCH_FIELDS = (
    "rankic_mean",
    "rankic_ir",
    "rankic_t_nw",
    "hit_ratio",
    "coverage",
    "top_turnover",
    "ls_net_sharpe",
    "monotonicity",
    "rank_autocorrelation",
)
IN_SAMPLE = "W0 only, in-sample and optimistic; not an official evaluation"


class ToolForbidden(PermissionError):
    pass


@dataclass
class ToolDeps:
    env: ResearchEnv
    role: str
    ctx: Ctx
    calls: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    roles: frozenset[str]
    description: str
    llm_name: str | None  # None: never offered to a model


def _roles(*names: str) -> frozenset[str]:
    return frozenset(names)


SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        "blackboard.read", ALL_ROLES, "Read research entities by id or recency.", "blackboard_read"
    ),
    ToolSpec("blackboard.write", ALL_ROLES, "Write the role's own entity types only.", None),
    ToolSpec(
        "kb.search",
        _roles("supervisor", "hypothesis", "engineer", "critic", "analyst"),
        "Search failure modes and insights.",
        "kb_search",
    ),
    ToolSpec(
        "dsl.validate",
        _roles("engineer", "critic", "evolution", "packager"),
        "Parse, type-check and constrain an expression; canonical form and hash.",
        "dsl_validate",
    ),
    ToolSpec(
        "dsl.explain",
        _roles("engineer", "critic", "evolution", "packager"),
        "Deterministic plain-language explanation of an expression.",
        "dsl_explain",
    ),
    ToolSpec(
        "workbench.evaluate",
        _roles("engineer", "critic", "evolution"),
        "W0-only metrics with the evaluator's definitions (in-sample).",
        "workbench_evaluate",
    ),
    ToolSpec(
        "similarity.search",
        _roles("hypothesis", "engineer", "critic", "evolution", "packager"),
        "AST and behavioral similarity against the pools and the program.",
        "similarity_search",
    ),
    ToolSpec(
        "feedback.read",
        _roles("supervisor", "engineer", "analyst", "evolution"),
        "Released reports research has synced, and the public cards.",
        "feedback_read",
    ),
    ToolSpec(
        "registry.read",
        ALL_ROLES,
        "Manifests of published versions, and the pools.",
        "registry_read",
    ),
    ToolSpec("registry.publish", _roles("packager"), "Publish an artifact version.", None),
    ToolSpec("budget.read", _roles("supervisor", "evolution"), "Remaining budgets.", "budget_read"),
)
TOOLS: dict[str, ToolSpec] = {spec.name: spec for spec in SPECS}


def tool_role(role: str) -> str:
    return ROLE_ALIASES.get(role, role)


def check(role: str, name: str) -> ToolSpec:
    spec = TOOLS.get(name)
    if spec is None or tool_role(role) not in spec.roles:
        raise ToolForbidden(f"role {role} may not call {name}")
    return spec


def require_write(env: ResearchEnv, role: str, entity: str, ctx: Ctx) -> None:
    """blackboard.write: the role's own entity types only."""
    check(role, "blackboard.write")
    if entity not in WRITE_SCOPES.get(tool_role(role), frozenset()):
        env.logger.logger.warning(
            "blackboard_write_refused",
            outcome="failed",
            error_code="WRITE_SCOPE",
            payload={"role": role, "entity": entity},
            **ctx.log_ids(),
        )
        raise ToolForbidden(f"role {role} may not write {entity}")


def snapshot() -> dict[str, list[str]]:
    """The registry as BND-02 sees it: tool name to allowed roles."""
    return {spec.name: sorted(spec.roles) for spec in SPECS}


# Implementations -----------------------------------------------------------------------


def _program_rows(deps: ToolDeps, sql: str, **params: Any) -> list[dict[str, Any]]:
    with deps.env.db.read() as conn:
        rows = conn.execute(text(sql), {"p": deps.ctx.program_id} | params).mappings().all()
    return [_jsonable(dict(r)) for r in rows]


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, UUID):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


BLACKBOARD_QUERIES = {
    "hypothesis": (
        "SELECT hypothesis_id, island_key, status, source, payload FROM hypotheses "
        "WHERE program_id = :p AND (CAST(:id AS uuid) IS NULL OR hypothesis_id = :id) "
        "ORDER BY created_at DESC LIMIT :n"
    ),
    "candidate": (
        "SELECT candidate_id, island_key, kind, operator, expression, state, reason, "
        "workbench FROM candidates WHERE program_id = :p AND "
        "(CAST(:id AS uuid) IS NULL OR candidate_id = :id) ORDER BY created_at DESC LIMIT :n"
    ),
    "knowledge_item": (
        "SELECT item_id, kind, statement, tags, evidence_report_ids FROM knowledge_items "
        "WHERE program_id = :p AND (CAST(:id AS uuid) IS NULL OR item_id = :id) "
        "ORDER BY created_at DESC LIMIT :n"
    ),
    "interpretation": (
        "SELECT interpretation_id, report_ids, version_id, status, "
        "coalesce(final_payload, payload) AS payload FROM interpretations WHERE program_id = :p "
        "AND (CAST(:id AS uuid) IS NULL OR interpretation_id = :id) "
        "ORDER BY created_at DESC LIMIT :n"
    ),
}


def blackboard_read(
    deps: ToolDeps, entity: str, entity_id: str | None = None, limit: int = 10
) -> dict[str, Any]:
    if entity not in BLACKBOARD_QUERIES:
        return {"error": f"entity must be one of {sorted(BLACKBOARD_QUERIES)}"}
    items = _program_rows(deps, BLACKBOARD_QUERIES[entity], id=entity_id, n=max(1, min(limit, 50)))
    return {"entity": entity, "items": items}


def kb_search(deps: ToolDeps, query: str, limit: int = 5) -> dict[str, Any]:
    words = [w for w in re.findall(r"[a-z0-9_]+", query.lower()) if len(w) > 2][:8]
    if not words:
        return {"items": []}
    clauses = " OR ".join(f"lower(statement) LIKE :w{i}" for i in range(len(words)))
    params = {f"w{i}": f"%{w}%" for i, w in enumerate(words)}
    items = _program_rows(
        deps,
        "SELECT item_id, kind, statement, tags, evidence_report_ids FROM knowledge_items "
        f"WHERE program_id = :p AND ({clauses}) ORDER BY created_at DESC LIMIT :n",
        n=max(1, min(limit, 20)),
        **params,
    )
    return {"items": items}


def dsl_validate(deps: ToolDeps, expression: str) -> dict[str, Any]:
    check_ = validate(expression, deps.env.limits)
    result: dict[str, Any] = {"ok": check_.ok, "errors": [dict(e) for e in check_.errors]}
    if check_.analysis is not None:
        result["analysis"] = check_.analysis.model_dump(mode="json")
    return result


def dsl_explain(deps: ToolDeps, expression: str) -> dict[str, Any]:
    check_ = validate(expression, deps.env.limits)
    if check_.analysis is None:
        return {"ok": False, "errors": [dict(e) for e in check_.errors]}
    return explain(canonicalize(parse(expression)), check_.analysis).model_dump(mode="json")


def workbench_evaluate(deps: ToolDeps, expression: str, expected_sign: int) -> dict[str, Any]:
    check_ = validate(expression, deps.env.limits)
    if not check_.ok:
        return {"ok": False, "errors": [dict(e) for e in check_.errors]}
    sign: Literal[1, -1] = 1 if expected_sign >= 0 else -1
    assert check_.analysis is not None
    report = factor_report(deps.env, check_.analysis.canonical, sign)
    metrics = report.metrics.model_dump(mode="json")
    return {
        "ok": True,
        "visibility": report.visibility,
        "window": report.window,
        "label": IN_SAMPLE,
        "snapshot_id": report.snapshot_id,
        "sign": sign,
        "metrics": {k: metrics.get(k) for k in WORKBENCH_FIELDS},
        "decay": metrics.get("decay"),
        "reference_sharpe": report.reference_strategy.sharpe,
    }


FACTOR_REPORTS_MAX = 2048


def factor_report(env: ResearchEnv, canonical: str, sign: Literal[1, -1]) -> Any:
    """The W0 workbench report of a validated expression, computed once per env."""
    key = (canonical, sign)
    report = env.factor_reports.get(key)
    if report is None:
        report = env.workbench.factor(canonical, sign)
        if len(env.factor_reports) >= FACTOR_REPORTS_MAX:
            env.factor_reports.pop(next(iter(env.factor_reports)))
        env.factor_reports[key] = report
    return report


def _fingerprint(env: ResearchEnv, canonical: str) -> Any:
    if canonical not in env.fingerprints:
        env.fingerprints[canonical] = env.workbench.fingerprint(canonical)
    return env.fingerprints[canonical]


def comparison_set(deps: ToolDeps) -> list[dict[str, str]]:
    """Factors a new draft is compared with: the factor pool, this program's approved,
    selected and published candidates, and the population's other members (seeds, a
    parent job's members and migrants; Section 12.5)."""
    others: list[dict[str, str]] = []
    try:
        page = deps.env.registry.pool("factor")
        for entry in page.items:
            version = deps.env.registry.version(entry.version_id)
            manifest = version.manifest
            expression = getattr(getattr(manifest, "implementation", None), "expression", None)
            if expression:
                others.append(
                    {"source": "pool", "ref": str(entry.version_id), "expression": expression}
                )
    except Exception:  # noqa: BLE001 - the registry being down must not stop drafting
        deps.env.logger.logger.warning("similarity_pool_unavailable", outcome="failed")
    for row in _program_rows(
        deps,
        "SELECT candidate_id, expression FROM candidates WHERE program_id = :p AND "
        "kind = 'factor' AND state IN ('approved', 'selected', 'published') "
        "AND (CAST(:c AS uuid) IS NULL OR candidate_id <> :c)",
        c=deps.ctx.candidate_id,
    ):
        others.append(
            {"source": "program", "ref": row["candidate_id"], "expression": row["expression"]}
        )
    known = {o["expression"] for o in others}
    for row in _program_rows(
        deps,
        "SELECT DISTINCT version_id, expression FROM population_members WHERE program_id = :p "
        "AND expression IS NOT NULL AND source <> 'program' ORDER BY version_id",
    ):
        if row["expression"] not in known:
            known.add(row["expression"])
            others.append(
                {"source": "population", "ref": row["version_id"], "expression": row["expression"]}
            )
    return others


def similarity_search(
    deps: ToolDeps, expression: str, limit: int = 5, behavioral: bool = True
) -> dict[str, Any]:
    check_ = validate(expression, deps.env.limits)
    if check_.analysis is None:
        return {"ok": False, "errors": [dict(e) for e in check_.errors]}
    tree = canonicalize(parse(expression))
    mine = _fingerprint(deps.env, check_.analysis.canonical) if behavioral else None
    rows: list[dict[str, Any]] = []
    for other in comparison_set(deps):
        other_check = validate(other["expression"], deps.env.limits)
        if other_check.analysis is None:
            continue
        ast = ast_similarity(tree, canonicalize(parse(other["expression"])))
        beh = None
        if mine is not None:
            beh = behavioral_similarity(
                mine, _fingerprint(deps.env, other_check.analysis.canonical)
            )
        rows.append(other | {"ast_similarity": round(ast, 6), "behavioral_similarity": beh})
    rows.sort(
        key=lambda r: (-float(r["behavioral_similarity"] or 0.0), -float(r["ast_similarity"]))
    )
    max_ast = max((float(r["ast_similarity"]) for r in rows), default=0.0)
    behaviors = [
        float(r["behavioral_similarity"]) for r in rows if r["behavioral_similarity"] is not None
    ]
    # The pool is research's view of the library: provisional fitness uses the maximum
    # behavioral similarity to it as the library-correlation term (Section 12.2).
    pool = [
        float(r["behavioral_similarity"])
        for r in rows
        if r["source"] == "pool" and r["behavioral_similarity"] is not None
    ]
    return {
        "ok": True,
        "compared": len(rows),
        "max_ast_similarity": max_ast,
        "originality": round(1.0 - max_ast, 6),
        "max_behavioral_similarity": max(behaviors, default=None),
        "max_pool_behavioral_similarity": max(pool, default=None),
        "pool_compared": len(pool),
        "nearest": rows[: max(1, min(limit, 20))],
        "vacuous": not rows,
    }


def feedback_read(
    deps: ToolDeps, version_id: str | None = None, report_type: str | None = None, limit: int = 20
) -> dict[str, Any]:
    items = _program_rows(
        deps,
        "SELECT r.report_id, r.version_id, r.report_type, r.released_at, r.content "
        "FROM report_cache r WHERE (r.program_id = :p OR r.version_id IN (SELECT "
        "(jsonb_array_elements_text(seed_version_ids))::uuid FROM research_jobs j "
        "JOIN programs g ON g.job_id = j.job_id WHERE g.program_id = :p)) "
        "AND (CAST(:v AS uuid) IS NULL OR r.version_id = :v) "
        "AND (CAST(:t AS text) IS NULL OR r.report_type = :t) "
        "ORDER BY r.released_at DESC LIMIT :n",
        v=version_id,
        t=report_type,
        n=max(1, min(limit, 100)),
    )
    gates = deps.env.public_cards.get("protocol", {}).get("gates")
    return {"reports": items, "public_gates": gates, "note": "values are released (coarsened)"}


def registry_read(
    deps: ToolDeps, version_id: str | None = None, pool: str | None = None
) -> dict[str, Any]:
    if version_id:
        record = deps.env.registry.version(UUID(version_id))
        return {"version": record.model_dump(mode="json")}
    if pool in ("factor", "strategy"):
        page = deps.env.registry.pool(pool)
        return {"pool": pool, "items": [e.model_dump(mode="json") for e in page.items]}
    return {"error": "give version_id, or pool factor or strategy"}


def budget_read(deps: ToolDeps) -> dict[str, Any]:
    with deps.env.db.read() as conn:
        left = deps.env.ledger.remaining(conn, deps.ctx, deps.env.clock.now())
    return {
        "binding_scope": left.scope,
        "remaining_cny": float(left.amount),
        "spent_cny": float(left.spent),
        "cap_cny": float(left.cap),
    }


IMPLEMENTATIONS: dict[str, Callable[..., dict[str, Any]]] = {
    "blackboard.read": blackboard_read,
    "kb.search": kb_search,
    "dsl.validate": dsl_validate,
    "dsl.explain": dsl_explain,
    "workbench.evaluate": workbench_evaluate,
    "similarity.search": similarity_search,
    "feedback.read": feedback_read,
    "registry.read": registry_read,
    "budget.read": budget_read,
}


def invoke(
    deps: ToolDeps,
    name: str,
    *,
    step_type: str = "TOOL_CALLED",
    record: bool = True,
    **args: Any,
) -> dict[str, Any]:
    """Run one tool as deps.role: role check, call log line and trace step."""
    check(deps.role, name)
    fn = IMPLEMENTATIONS[name]
    try:
        result = fn(deps, **args)
        outcome = "failed" if result.get("ok") is False or "error" in result else "ok"
    except Exception as error:  # noqa: BLE001 - the model sees the error, the trace records it
        result = {"ok": False, "error": f"{type(error).__name__}: {error}"[:500]}
        outcome = "failed"
    deps.calls.append({"tool": name, "args": args, "outcome": outcome})
    deps.env.logger.logger.info(
        "tool_called",
        outcome=outcome,
        payload={"tool": name, "role": deps.role, "args": _summary(args)},
        **deps.ctx.log_ids(),
    )
    if record:
        with deps.env.db.transaction() as conn:
            deps.env.trace.step(
                conn,
                step_type,
                deps.ctx,
                actor=f"tool:{name}",
                inputs={"role": deps.role, "tool": name, "args": args},
                payload=result,
                outcome=outcome,
            )
    return result


def _summary(args: dict[str, Any]) -> dict[str, Any]:
    return {k: (v[:200] if isinstance(v, str) else v) for k, v in args.items()}


# PydanticAI wrappers. They are async so tools run on the event loop's thread, like the
# rest of the workflow's database access.


async def _blackboard_read(
    ctx: RunContext[ToolDeps],
    entity: Literal["hypothesis", "candidate", "knowledge_item", "interpretation"],
    entity_id: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Read this program's hypotheses, candidates, knowledge items or interpretations.

    Args:
        entity: Which entity type to read.
        entity_id: One entity's id, or omit for the most recent ones.
        limit: How many to return (at most 50).
    """
    return invoke(ctx.deps, "blackboard.read", entity=entity, entity_id=entity_id, limit=limit)


async def _kb_search(ctx: RunContext[ToolDeps], query: str, limit: int = 5) -> dict[str, Any]:
    """Search this program's knowledge items (failure modes, insights, anti-patterns).

    Args:
        query: Words to look for.
        limit: How many to return (at most 20).
    """
    return invoke(ctx.deps, "kb.search", query=query, limit=limit)


async def _dsl_validate(ctx: RunContext[ToolDeps], expression: str) -> dict[str, Any]:
    """Parse, type-check and constrain a qfr-dsl/1 expression with the evaluator's limits.

    Args:
        expression: The expression to check.
    """
    return invoke(ctx.deps, "dsl.validate", expression=expression)


async def _dsl_explain(ctx: RunContext[ToolDeps], expression: str) -> dict[str, Any]:
    """Explain a qfr-dsl/1 expression in plain language, deterministically.

    Args:
        expression: The expression to explain.
    """
    return invoke(ctx.deps, "dsl.explain", expression=expression)


async def _workbench_evaluate(
    ctx: RunContext[ToolDeps], expression: str, expected_sign: Literal[-1, 1]
) -> dict[str, Any]:
    """Measure a factor on W0 with the evaluator's metric definitions.

    The numbers are in-sample and optimistic; they are never an official evaluation.

    Args:
        expression: The factor expression.
        expected_sign: 1 if larger values should predict higher returns, else -1.
    """
    return invoke(
        ctx.deps, "workbench.evaluate", expression=expression, expected_sign=expected_sign
    )


async def _similarity_search(
    ctx: RunContext[ToolDeps], expression: str, limit: int = 5
) -> dict[str, Any]:
    """Find the most similar factors in the pools and this program (AST and behavior).

    Args:
        expression: The expression to compare.
        limit: How many neighbours to return.
    """
    return invoke(ctx.deps, "similarity.search", expression=expression, limit=limit)


async def _feedback_read(
    ctx: RunContext[ToolDeps],
    version_id: str | None = None,
    report_type: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Read released reports this program has synced (coarsened values), and the public gates.

    Args:
        version_id: Only reports of this version.
        report_type: Only this report type (intake, screening, w1, w2, ...).
        limit: How many to return (at most 100).
    """
    return invoke(
        ctx.deps, "feedback.read", version_id=version_id, report_type=report_type, limit=limit
    )


async def _registry_read(
    ctx: RunContext[ToolDeps], version_id: str | None = None, pool: str | None = None
) -> dict[str, Any]:
    """Read one published version's manifest, or the entries of the factor or strategy pool.

    Args:
        version_id: A published version id.
        pool: factor or strategy.
    """
    return invoke(ctx.deps, "registry.read", version_id=version_id, pool=pool)


async def _budget_read(ctx: RunContext[ToolDeps]) -> dict[str, Any]:
    """Remaining LLM budget for this generation, day and job, in CNY."""
    return invoke(ctx.deps, "budget.read")


WRAPPERS: dict[str, Callable[..., Any]] = {
    "blackboard.read": _blackboard_read,
    "kb.search": _kb_search,
    "dsl.validate": _dsl_validate,
    "dsl.explain": _dsl_explain,
    "workbench.evaluate": _workbench_evaluate,
    "similarity.search": _similarity_search,
    "feedback.read": _feedback_read,
    "registry.read": _registry_read,
    "budget.read": _budget_read,
}


def llm_tools(role: str) -> list[Tool[ToolDeps]]:
    """The PydanticAI tools a role's model may call."""
    tools: list[Tool[ToolDeps]] = []
    for spec in SPECS:
        if spec.llm_name is None or tool_role(role) not in spec.roles:
            continue
        tools.append(Tool(WRAPPERS[spec.name], name=spec.llm_name, takes_ctx=True))
    return tools
