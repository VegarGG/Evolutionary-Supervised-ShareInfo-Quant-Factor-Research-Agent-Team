"""qfr llm probe (P4.2, PLAN Sections 11.8 and 13.6): at setup, daily and at job start.

For every model that roles.yaml names, the probe checks that the provider lists the
model, that the model has a complete price, that a tool-output request and a
json_object request both succeed with the role's thinking setting, and, on Moonshot,
that the configured account concurrency covers request.concurrency and the balance is
positive. A model without a price is never called. Probe calls are tiny and are
recorded in the budget ledger under the role "probe".
"""

import time
from collections import defaultdict
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from pydantic_ai import Agent, PromptedOutput, ToolOutput, capture_run_messages
from pydantic_ai.messages import ModelResponse
from qfr_core.ids import uuid7
from qfr_core.research_api import ModelProbe, ProbeReport, RoleProbe
from sqlalchemy import text

from qfr_research.db import dumps
from qfr_research.env import ResearchEnv
from qfr_research.providers import ModelRef, NoPrice, TokenUsage
from qfr_research.settings import ROLES
from qfr_research.store import Ctx

Trigger = Literal["setup", "daily", "job_start", "manual"]
Check = Literal["pass", "fail", "skipped"]
PROBE_PROMPT = (
    "This is a connectivity check. Return ok=true and echo the word 'qfr' in the field "
    "token. Do not add anything else."
)


class Ping(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool
    token: str


async def run_probe(env: ResearchEnv, trigger: Trigger, ctx: Ctx | None = None) -> ProbeReport:
    started = time.monotonic()
    users: dict[ModelRef, list[str]] = defaultdict(list)
    for role in ROLES:
        for ref in env.planner.chain(role):
            users[ref].append(role)
    listed: dict[str, list[str] | None] = {}
    notes: list[str] = []
    for provider in sorted({r.provider for r in users}):
        try:
            listed[provider] = await env.models.list_models(provider)
        except Exception as error:  # noqa: BLE001 - every failure is a probe result
            listed[provider] = None
            notes.append(f"{provider}: model list unavailable ({type(error).__name__})")
    models: list[ModelProbe] = []
    account = await kimi_account(env) if any(r.provider == "kimi" for r in users) else None
    for ref, used_by in sorted(users.items(), key=lambda kv: str(kv[0])):
        found = await probe_model(env, ref, used_by[0], listed.get(ref.provider), ctx)
        if ref.provider == "kimi" and account is not None:
            checks = found.checks | account["checks"]
            found = found.model_copy(
                update={
                    "checks": checks,
                    "detail": found.detail | account["detail"],
                    "ok": all(v != "fail" for v in checks.values()),
                }
            )
        models.append(found)
    ok_refs = {f"{m.provider}/{m.model_id}" for m in models if m.ok}
    roles: dict[str, RoleProbe] = {}
    for role in ROLES:
        chain = [str(r) for r in env.planner.chain(role)]
        usable = [r for r in chain if r in ok_refs]
        roles[role] = RoleProbe(
            primary=chain[0], primary_ok=chain[0] in ok_refs, usable=usable, ok=chain[0] in ok_refs
        )
    report = ProbeReport(
        probe_id=uuid7(),
        at=env.clock.now(),
        trigger=trigger,
        ok=all(r.ok for r in roles.values()),
        models=models,
        roles=roles,
        notes=notes,
    )
    with env.db.transaction() as conn:
        conn.execute(
            text(
                "INSERT INTO llm_probes (probe_id, at, trigger, ok, report, request_id) VALUES "
                "(:p, :at, :t, :ok, CAST(:r AS jsonb), :rid)"
            ),
            {
                "p": report.probe_id,
                "at": report.at,
                "t": trigger,
                "ok": report.ok,
                "r": dumps(report.model_dump(mode="json")),
                "rid": str(report.probe_id),
            },
        )
    emit = env.logger.logger.info if report.ok else env.logger.logger.warning
    emit(
        "llm_probe_completed",
        outcome="ok" if report.ok else "failed",
        error_code=None if report.ok else "PROBE_FAILED",
        payload={
            "trigger": trigger,
            "failed_models": [f"{m.provider}/{m.model_id}" for m in models if not m.ok],
            "failed_roles": [k for k, v in roles.items() if not v.ok],
            "duration_ms": round((time.monotonic() - started) * 1000, 1),
        },
        **(ctx.log_ids() if ctx else {}),
    )
    return report


async def probe_model(
    env: ResearchEnv, ref: ModelRef, role: str, listed: list[str] | None, ctx: Ctx | None
) -> ModelProbe:
    checks: dict[str, Check] = {}
    detail: dict[str, Any] = {"role_used": role}
    if listed is None:
        checks["listed"] = "skipped"
    else:
        checks["listed"] = "pass" if ref.model_id in listed else "fail"
    missing = env.prices.missing(ref)
    checks["price"] = "fail" if missing else "pass"
    if missing:
        detail["price_missing"] = missing
    if missing or checks["listed"] == "fail":
        for name in ("tool_output", "json_object", "thinking"):
            checks[name] = "skipped"
        detail["skipped_reason"] = "no price" if missing else "model not listed"
        return ModelProbe(
            provider=ref.provider, model_id=ref.model_id, ok=False, checks=checks, detail=detail
        )
    plan = env.planner.plan(role, ref)
    detail["thinking"] = plan.thinking
    for name, mode in (("tool_output", "tool"), ("json_object", "prompted")):
        outcome = await _call(env, ref, role, plan, mode, ctx)
        checks[name] = "pass" if outcome["ok"] else "fail"
        detail[name] = outcome
    checks["thinking"] = (
        "pass" if checks["tool_output"] == checks["json_object"] == "pass" else "fail"
    )
    return ModelProbe(
        provider=ref.provider,
        model_id=ref.model_id,
        ok=all(v != "fail" for v in checks.values()),
        checks=checks,
        detail=detail,
    )


async def _call(
    env: ResearchEnv, ref: ModelRef, role: str, plan: Any, mode: str, ctx: Ctx | None
) -> dict[str, Any]:
    started = time.monotonic()
    try:
        model = env.models.model(role, ref)
        quote = env.prices.quote(ref, env.clock.now())
    except (NoPrice, RuntimeError) as error:
        return {"ok": False, "error": type(error).__name__, "message": str(error)[:200]}
    spec: Any = ToolOutput(Ping, name="final_result") if mode == "tool" else PromptedOutput(Ping)
    agent: Agent[None, Any] = Agent(model, output_type=spec, retries=1)
    messages: list[Any] = []
    result: dict[str, Any]
    with capture_run_messages() as captured:
        try:
            run = await agent.run(PROBE_PROMPT, model_settings=plan.model_settings())
            messages = list(run.all_messages())
            result = {"ok": bool(run.output.ok)}
        except Exception as error:  # noqa: BLE001 - every failure is a probe result
            messages = list(captured)
            result = {"ok": False, "error": type(error).__name__, "message": str(error)[:300]}
    responses = [m for m in messages if isinstance(m, ModelResponse)]
    usage = TokenUsage(
        input_tokens=sum(r.usage.input_tokens for r in responses),
        output_tokens=sum(r.usage.output_tokens for r in responses),
        cache_read_tokens=sum(r.usage.cache_read_tokens for r in responses),
        cache_write_tokens=sum(r.usage.cache_write_tokens for r in responses),
        requests=len(responses),
    )
    if responses:
        with env.db.transaction() as conn:
            cost = env.ledger.record(
                conn,
                ctx or Ctx(),
                env.clock.now(),
                run_id=uuid7(),
                role="probe",
                quote=quote,
                usage=usage,
            )
        result["cost_cny"] = float(cost)
    result["latency_ms"] = round((time.monotonic() - started) * 1000, 1)
    result["requests"] = len(responses)
    return result


async def kimi_account(env: ResearchEnv) -> dict[str, Any]:
    """Moonshot publishes no tier API: the configured limit must cover the concurrency."""
    profile = env.config.providers.providers["kimi"]
    configured = int(str(env.config.providers.request["concurrency"]))
    limit = profile.account.concurrency_limit if profile.account is not None else None
    checks: dict[str, Check] = {}
    detail: dict[str, Any] = {"concurrency_required": configured, "concurrency_limit": limit}
    checks["concurrency"] = "pass" if limit is not None and int(limit) >= configured else "fail"
    if limit is None:
        detail["concurrency_note"] = (
            "Set providers.kimi.account.concurrency_limit from the Moonshot console "
            "(rate limits page)."
        )
    try:
        balance = await env.models.balance("kimi")
        available = balance.get("available_balance")
        detail["available_balance"] = available
        checks["balance"] = "pass" if available is not None and float(available) > 0 else "fail"
    except Exception as error:  # noqa: BLE001 - every failure is a probe result
        checks["balance"] = "fail"
        detail["balance_error"] = type(error).__name__
    return {"checks": checks, "detail": detail}


def latest_ok(env: ResearchEnv, since: Any) -> UUID | None:
    with env.db.read() as conn:
        return conn.execute(
            text("SELECT probe_id FROM llm_probes WHERE at >= :s ORDER BY at DESC LIMIT 1"),
            {"s": since},
        ).scalar()
