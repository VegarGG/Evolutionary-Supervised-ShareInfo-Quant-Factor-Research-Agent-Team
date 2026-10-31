"""Running a research role's model (P4.5, PLAN Sections 11.2, 11.7 and 11.8).

One call of RoleRunner.run is one agent step: the role's provider chain is tried in
order (primary, then fallbacks; the critic skips the engineer's provider), each model
with the configured retries and backoff on timeouts, 429 and 5xx. Structured output uses
tool calling with tool_choice auto; after two validation failures inside one run the run
is retried once in prompted mode (response_format json_object). The budget ledger admits
every run first and records its priced usage after.

Every attempt writes PROMPT_SENT and MODEL_RESPONDED trace steps, exactly one agent_runs
row with the full request and response (redacted like logs), and an llm_call_completed
log line carrying the run id (TRC-02). A switch to the next model is a PROVIDER_FALLBACK
step and a log line.
"""

import json
import math
import time
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any, TypeVar
from uuid import UUID

from pydantic import BaseModel
from pydantic_ai import Agent, PromptedOutput, ToolOutput, UsageLimits, capture_run_messages
from pydantic_ai.exceptions import (
    ModelAPIError,
    ModelConnectionError,
    ModelHTTPError,
    ModelNotFoundError,
    ModelRateLimitError,
    ModelRequestTimeout,
    ModelServerError,
    ModelUnavailableError,
    UnexpectedModelBehavior,
    UsageLimitExceeded,
)
from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelResponse,
    TextPart,
    ThinkingPart,
    ToolCallPart,
)
from qfr_core.correlation import bind, current
from qfr_core.ids import uuid7

from qfr_research import alerts as provider_alerts
from qfr_research.budget import BudgetExceeded
from qfr_research.env import ResearchEnv
from qfr_research.prompts import RenderedPrompt
from qfr_research.providers import CallPlan, ModelRef, NoPrice, ProviderUnavailable, TokenUsage
from qfr_research.store import Ctx, LlmAttribution, insert_agent_run
from qfr_research.tools import ToolDeps, llm_tools

T = TypeVar("T", bound=BaseModel)
OUTPUT_TOOL = "final_result"


class RoleFailed(RuntimeError):
    """Every model in the role's chain failed or was refused."""

    def __init__(self, role: str, errors: list[str]) -> None:
        super().__init__(f"{role}: every configured model failed ({'; '.join(errors)})")
        self.role, self.errors = role, errors


class _Transient(Exception):
    pass


class _Permanent(Exception):
    pass


@dataclass(frozen=True)
class RoleResult[T]:
    output: T
    run_id: UUID
    ref: ModelRef
    prompt: RenderedPrompt
    output_mode: str
    usage: TokenUsage
    cost: Decimal
    tool_calls: list[dict[str, Any]]

    @property
    def attribution(self) -> LlmAttribution:
        return LlmAttribution(
            self.ref.provider,
            self.ref.model_id,
            self.prompt.template_id,
            self.prompt.sha256,
            self.run_id,
        )


def role_limits(charter: dict[str, Any], role: str) -> tuple[int, int | None]:
    """Requests and tool calls per run, from the program's charter (Section 11.2)."""
    limits = charter.get("role_limits", {})
    budget = charter.get("budget", {})
    if role == "engineer":
        return int(budget["engineer_requests"]), int(budget["engineer_tool_calls"])
    key = {"interp_review": "critic"}.get(role, role)
    return int(limits[f"{key}_requests"]), None


class RoleRunner:
    def __init__(self, env: ResearchEnv) -> None:
        self.env = env
        request = env.config.providers.request
        self.retries = int(str(request["retries"]))
        backoff = request["backoff_s"]
        assert isinstance(backoff, list)
        self.backoff = [float(str(b)) for b in backoff]
        structured = request["structured_output"]
        assert isinstance(structured, dict)
        self.validation_failures = int(structured["fallback_after_failures"])  # type: ignore[arg-type]
        self.chars_per_token = env.config.service.estimate.chars_per_token

    async def run(
        self,
        role: str,
        prompt: RenderedPrompt,
        output_type: type[T],
        ctx: Ctx,
        charter: dict[str, Any],
        *,
        exclude_provider: str | None = None,
        inputs: dict[str, Any] | None = None,
    ) -> RoleResult[T]:
        chain = self.env.planner.chain(role, exclude_provider)
        errors: list[str] = []
        for index, ref in enumerate(chain):
            reason = await self._try_model(role, ref, prompt, output_type, ctx, charter, inputs)
            if isinstance(reason, RoleResult):
                return reason
            errors.append(f"{ref}: {reason}")
            if index + 1 < len(chain):
                self._fallback(role, ref, chain[index + 1], reason, ctx)
        raise RoleFailed(role, errors or ["no model left after the cross-provider rule"])

    async def _try_model(
        self,
        role: str,
        ref: ModelRef,
        prompt: RenderedPrompt,
        output_type: type[T],
        ctx: Ctx,
        charter: dict[str, Any],
        inputs: dict[str, Any] | None,
    ) -> "RoleResult[T] | str":
        missing = self.env.prices.missing(ref)
        if missing:
            self.env.logger.logger.error(
                "llm_model_refused",
                outcome="failed",
                error_code="NO_PRICE",
                payload={"role": role, "model": str(ref), "missing": missing},
                **ctx.log_ids(),
            )
            return "NO_PRICE"
        try:
            model = self.env.models.model(role, ref)
        except ProviderUnavailable as error:
            return f"PROVIDER_UNAVAILABLE {error}"
        plan = self.env.planner.plan(role, ref)
        for attempt in range(self.retries + 1):
            try:
                return await self._attempt(
                    role, ref, model, plan, prompt, output_type, ctx, charter, inputs
                )
            except BudgetExceeded:
                raise
            except _Transient as error:
                if attempt < self.retries:
                    await self.env.sleep(self.backoff[min(attempt, len(self.backoff) - 1)])
                    continue
                return f"TRANSIENT {error}"
            except _Permanent as error:
                return f"FAILED {error}"
        return "RETRIES_EXHAUSTED"

    async def _attempt(
        self,
        role: str,
        ref: ModelRef,
        model: Any,
        plan: CallPlan,
        prompt: RenderedPrompt,
        output_type: type[T],
        ctx: Ctx,
        charter: dict[str, Any],
        inputs: dict[str, Any] | None,
    ) -> RoleResult[T]:
        env = self.env
        run_id = uuid7()
        attribution = LlmAttribution(
            ref.provider, ref.model_id, prompt.template_id, prompt.sha256, run_id
        )
        now = env.clock.now()
        try:
            quote = env.prices.quote(ref, now)
        except NoPrice as error:
            raise _Permanent(str(error)) from error
        requests, tool_calls = role_limits(charter, role)
        prompt_tokens = math.ceil(len(prompt.text) / self.chars_per_token)
        bound = int(charter.get("context_tokens", 12000)) + plan.max_tokens
        with env.db.transaction() as conn:
            token_limit = env.ledger.admit(
                conn, ctx, now, quote, prompt_tokens, plan.max_tokens, bound
            )
            env.trace.step(
                conn,
                "PROMPT_SENT",
                ctx,
                actor_kind="llm",
                actor=role,
                llm=attribution,
                inputs=(inputs or {})
                | {"prompt_template_sha256": prompt.template_sha256, "truncated": prompt.truncated},
                payload={"prompt": prompt.text, "settings": _jsonable(plan.settings)},
            )
        limits = UsageLimits(
            request_limit=requests, tool_calls_limit=tool_calls, total_tokens_limit=token_limit
        )
        deps = ToolDeps(env, role, ctx)
        settings = _jsonable(plan.settings) | {
            "request_limit": requests,
            "tool_calls_limit": tool_calls,
            "total_tokens_limit": token_limit,
        }
        started = time.monotonic()
        messages: list[ModelMessage] = []
        mode, output, failure = "tool", None, None
        with bind(run_id=str(run_id), **ctx.log_ids()):
            try:
                output, messages = await self._run(
                    model, output_type, role, prompt, deps, limits, plan, "tool"
                )
            except UnexpectedModelBehavior as error:
                # Two validation failures inside the tool-mode run: retry once prompted.
                messages = list(getattr(error, "_qfr_messages", []))
                mode = "prompted"
                try:
                    output, more = await self._run(
                        model, output_type, role, prompt, deps, limits, plan, "prompted"
                    )
                    messages += more
                except Exception as second:  # noqa: BLE001 - classified below
                    messages += list(getattr(second, "_qfr_messages", []))
                    failure = second
            except Exception as error:  # noqa: BLE001 - classified below
                messages = list(getattr(error, "_qfr_messages", []))
                failure = error
            latency_ms = round((time.monotonic() - started) * 1000, 3)
            usage = _usage(messages, deps)
            status = "ok" if failure is None else "failed"
            response_json = None if output is None else output.model_dump(mode="json")
            finish = _finish_reason(messages)
            error_code = None if failure is None else _code(failure)
            with env.db.transaction() as conn:
                cost = env.ledger.record(
                    conn, ctx, env.clock.now(), run_id=run_id, role=role, quote=quote, usage=usage
                )
                step_id = env.trace.step(
                    conn,
                    "MODEL_RESPONDED",
                    ctx,
                    actor_kind="llm",
                    actor=role,
                    llm=attribution,
                    inputs={"prompt_sha256": prompt.sha256},
                    payload={
                        "output": response_json,
                        "output_mode": mode,
                        "finish_reason": finish,
                        "usage": _usage_view(usage, cost, quote.period),
                        "tool_calls": deps.calls,
                        "error_code": error_code,
                    },
                    outcome="ok" if failure is None else "failed",
                )
                redact = env.logger.redactor.scrub
                insert_agent_run(
                    conn,
                    env.clock,
                    ctx,
                    {
                        "run_id": run_id,
                        "step_id": step_id,
                        "role": role,
                        "provider": ref.provider,
                        "model_id": ref.model_id,
                        "prompt_template_id": prompt.template_id,
                        "prompt_sha256": prompt.sha256,
                        "request_messages": redact(
                            ModelMessagesTypeAdapter.dump_python(messages, mode="json")
                        )
                        or [{"kind": "request", "parts": [{"content": prompt.text}]}],
                        "response_text": redact(_response_text(messages)),
                        "response_json": response_json,
                        "usage": _usage_view(usage, cost, quote.period)
                        | {"finish_reason": finish, "provider_request_ids": _request_ids(messages)},
                        "settings": settings | {"output_mode": mode},
                        "status": status,
                        "latency_ms": latency_ms,
                    },
                )
            env.logger.logger.info(
                "llm_call_completed",
                outcome="ok" if failure is None else "failed",
                error_code=error_code,
                duration_ms=latency_ms,
                step_id=str(step_id),
                payload={
                    "role": role,
                    "provider": ref.provider,
                    "model": ref.model_id,
                    "prompt_template_id": prompt.template_id,
                    "prompt_sha256": prompt.sha256,
                    "tokens_in": usage.input_tokens,
                    "tokens_out": usage.output_tokens,
                    "tokens_cached": usage.cache_read_tokens,
                    "cost_cny": float(cost),
                    "price_period": quote.period,
                    "finish_reason": finish,
                    "output_mode": mode,
                },
            )
        if failure is not None:
            if isinstance(failure, UsageLimitExceeded):
                raise _Permanent(f"USAGE_LIMIT {failure}") from failure
            if _transient(failure):
                raise _Transient(_code(failure)) from failure
            raise _Permanent(_code(failure)) from failure
        assert output is not None
        return RoleResult(output, run_id, ref, prompt, mode, usage, cost, deps.calls)

    async def _run(
        self,
        model: Any,
        output_type: type[T],
        role: str,
        prompt: RenderedPrompt,
        deps: ToolDeps,
        limits: UsageLimits,
        plan: CallPlan,
        mode: str,
    ) -> tuple[T, list[ModelMessage]]:
        spec: Any = (
            ToolOutput(output_type, name=OUTPUT_TOOL)
            if mode == "tool"
            else PromptedOutput(output_type)
        )
        agent: Agent[ToolDeps, Any] = Agent(
            model,
            output_type=spec,
            deps_type=ToolDeps,
            tools=llm_tools(role),
            retries=self.validation_failures,
        )
        with capture_run_messages() as captured:
            try:
                result = await agent.run(
                    prompt.text,
                    deps=deps,
                    usage_limits=limits,
                    model_settings=plan.model_settings(),
                )
            except Exception as error:
                error._qfr_messages = list(captured)  # type: ignore[attr-defined]
                raise
        return result.output, list(result.all_messages())

    def _fallback(self, role: str, ref: ModelRef, nxt: ModelRef, reason: str, ctx: Ctx) -> None:
        self.env.logger.logger.warning(
            "llm_provider_fallback",
            outcome="fallback",
            error_code=reason.split(" ")[0],
            payload={"role": role, "from": str(ref), "to": str(nxt), "reason": reason[:300]},
            **ctx.log_ids(),
        )
        alerts = self.env.config.service.alerts
        with self.env.db.transaction() as conn:
            self.env.trace.step(
                conn,
                "PROVIDER_FALLBACK",
                ctx,
                actor=f"provider-layer:{role}",
                inputs={"from": str(ref), "to": str(nxt)},
                payload={"reason": reason[:500]},
                outcome="fallback",
            )
            # Repeated fallbacks away from one model raise a provider alert (17.4).
            provider_alerts.after_fallback(
                conn, str(ref), self.env.clock.now(), alerts.fallback_threshold,
                timedelta(minutes=alerts.fallback_window_minutes),
                current().get("request_id") or str(uuid7()), self.env.logger,
            )  # fmt: skip


def _transient(error: BaseException) -> bool:
    if isinstance(error, ModelNotFoundError):
        return False
    if isinstance(
        error,
        ModelRateLimitError
        | ModelUnavailableError
        | ModelServerError
        | ModelConnectionError
        | ModelRequestTimeout,
    ):
        return True
    if isinstance(error, ModelHTTPError):
        return error.status_code == 429 or error.status_code >= 500
    return isinstance(error, TimeoutError | ConnectionError)


def _code(error: BaseException) -> str:
    if isinstance(error, ModelNotFoundError):
        return "MODEL_NOT_FOUND"
    if isinstance(error, ModelHTTPError):
        return f"HTTP_{error.status_code}"
    if isinstance(error, UsageLimitExceeded):
        return "USAGE_LIMIT"
    if isinstance(error, UnexpectedModelBehavior):
        return "OUTPUT_INVALID"
    if isinstance(error, ModelAPIError):
        return type(error).__name__.upper()
    return type(error).__name__.upper()


def _usage(messages: list[ModelMessage], deps: ToolDeps) -> TokenUsage:
    responses = [m for m in messages if isinstance(m, ModelResponse)]
    return TokenUsage(
        input_tokens=sum(r.usage.input_tokens for r in responses),
        output_tokens=sum(r.usage.output_tokens for r in responses),
        cache_read_tokens=sum(r.usage.cache_read_tokens for r in responses),
        cache_write_tokens=sum(r.usage.cache_write_tokens for r in responses),
        requests=len(responses),
        tool_calls=len(deps.calls),
    )


def _usage_view(usage: TokenUsage, cost: Decimal, period: str) -> dict[str, Any]:
    return {
        "tokens_in": usage.input_tokens,
        "tokens_out": usage.output_tokens,
        "tokens_cached": usage.cache_read_tokens,
        "tokens_cache_write": usage.cache_write_tokens,
        "requests": usage.requests,
        "tool_calls": usage.tool_calls,
        "cost_cny": float(cost),
        "price_period": period,
    }


def _response_text(messages: list[ModelMessage]) -> str:
    """Every response part in order, reasoning included (stored, never forwarded)."""
    chunks: list[str] = []
    for message in messages:
        if not isinstance(message, ModelResponse):
            continue
        for part in message.parts:
            if isinstance(part, ThinkingPart):
                chunks.append(f"[reasoning]\n{part.content}")
            elif isinstance(part, TextPart):
                chunks.append(part.content)
            elif isinstance(part, ToolCallPart):
                args = json.dumps(part.args_as_dict(), sort_keys=True)
                chunks.append(f"[tool_call {part.tool_name}] {args}")
    return "\n".join(chunks)


def _finish_reason(messages: list[ModelMessage]) -> str | None:
    for message in reversed(messages):
        if isinstance(message, ModelResponse):
            return message.finish_reason
    return None


def _request_ids(messages: list[ModelMessage]) -> list[str]:
    return [
        m.provider_response_id
        for m in messages
        if isinstance(m, ModelResponse) and m.provider_response_id
    ]


def _jsonable(value: dict[str, Any]) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(json.dumps(value, default=str))
    return loaded
