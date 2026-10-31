"""The provider layer without a provider (P4.2): model references, the price table with
peak and off-peak rates, the no-price-no-run rule, per-role call plans and the model
classes. Every price here is a test price."""

import asyncio
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import httpx
import pydantic_ai.models
import pytest
from pydantic_ai import Agent, PromptedOutput, ToolOutput
from pydantic_ai.models import override_allow_model_requests
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.models.zai import ZaiModel
from qfr_core.config import ProvidersConfig
from qfr_research.probe import Ping
from qfr_research.providers import (
    ModelRef,
    NoPrice,
    Planner,
    PriceTable,
    ProviderModels,
    ProviderUnavailable,
    TokenUsage,
)
from qfr_research.settings import ResearchConfig

from tests.research.scripted import priced

SHIPPED = ResearchConfig.load(Path("configs"))
PRICED = priced(SHIPPED)
DEEPSEEK = ModelRef("deepseek", "deepseek-v4-pro")
KIMI = ModelRef("kimi", "kimi-k3")
MONDAY_PEAK = datetime(2026, 1, 5, 2, 0, tzinfo=UTC)  # inside 01:00-04:00 UTC
MONDAY_OFFPEAK = datetime(2026, 1, 5, 5, 0, tzinfo=UTC)
SATURDAY_PEAK_HOUR = datetime(2026, 1, 10, 2, 0, tzinfo=UTC)
# The endpoints the shipped providers.yaml configures.
DS, MS, ZAI = (
    "https://api.deepseek.com",
    "https://api.moonshot.cn/v1",
    "https://open.bigmodel.cn/api/paas/v4",
)


def test_real_model_requests_are_disabled_in_the_test_session():
    assert pydantic_ai.models.ALLOW_MODEL_REQUESTS is False


def test_model_references_name_a_known_provider():
    assert ModelRef.parse("glm/glm-5.3") == ModelRef("glm", "glm-5.3")
    assert str(ModelRef.parse("kimi/kimi-k3")) == "kimi/kimi-k3"
    for bad in ("openai/gpt", "deepseek", "deepseek/"):
        with pytest.raises(ValueError):
            ModelRef.parse(bad)


def test_the_shipped_configuration_has_no_price_so_no_model_may_run():
    table = PriceTable(SHIPPED.providers)
    for provider in SHIPPED.providers.providers.values():
        assert provider.models
    assert table.missing(DEEPSEEK) == ["in_hit", "in_miss", "out"]
    assert table.missing(ModelRef("deepseek", "not-configured")) == ["model"]
    with pytest.raises(NoPrice):
        table.quote(DEEPSEEK, MONDAY_PEAK)


def test_peak_and_off_peak_rates_follow_the_pricing_calendar():
    table = PriceTable(PRICED.providers)
    peak = table.quote(DEEPSEEK, MONDAY_PEAK)
    assert peak.period == "peak" and peak.in_miss == Decimal(2) and peak.out == Decimal(8)
    offpeak = table.quote(DEEPSEEK, MONDAY_OFFPEAK)
    assert offpeak.period == "offpeak" and offpeak.in_miss == Decimal(1)
    assert offpeak.out == Decimal(4)
    assert table.quote(DEEPSEEK, SATURDAY_PEAK_HOUR).period == "offpeak"
    # A listed public holiday is off-peak all day.
    raw = PRICED.providers.model_dump(mode="json")
    raw["providers"]["deepseek"]["pricing_calendar"]["holidays"] = ["2026-01-05"]
    holiday = PriceTable(ProvidersConfig.model_validate(raw))
    assert holiday.quote(DEEPSEEK, MONDAY_PEAK).period == "offpeak"
    assert date(2026, 1, 5).weekday() == 0
    # Moonshot has one flat rate.
    flat = table.quote(KIMI, MONDAY_PEAK)
    assert flat.period == "flat" and flat.in_miss == Decimal(2)


def test_usage_converts_to_cny_by_token_class():
    quote = PriceTable(PRICED.providers).quote(KIMI, MONDAY_PEAK)
    usage = TokenUsage(
        input_tokens=10_000, output_tokens=2_000, cache_read_tokens=6_000, cache_write_tokens=1_000
    )
    # miss 3,000 x 2 + hit 6,000 x 0.5 + write 1,000 x 2 + out 2,000 x 8, per million.
    assert usage.miss_tokens == 3_000
    assert quote.cost(usage) == Decimal("0.027000")
    # Before a call: the whole prompt at the miss rate plus the full output budget.
    assert quote.estimate(1_000, 4_096) == Decimal("0.034768")


def test_usd_prices_need_a_conversion_rate():
    raw = PRICED.providers.model_dump(mode="json")
    model = raw["providers"]["glm"]["models"]["glm-5.3"]
    model["price_usd_per_mtok"] = {"in_miss": 0.5, "in_hit": 0.1, "out": 2.0}
    model["price_cny_per_mtok"] = None
    glm = ModelRef("glm", "glm-5.3")
    assert PriceTable(ProvidersConfig.model_validate(raw)).missing(glm) == ["usd_to_cny"]
    raw["budget"]["usd_to_cny"] = 7.0
    quote = PriceTable(ProvidersConfig.model_validate(raw)).quote(glm, MONDAY_PEAK)
    assert quote.in_miss == Decimal("3.5") and quote.out == Decimal("14.0")


def test_call_plans_follow_the_role_and_the_model_tier():
    env_planner = _planner()
    supervisor = env_planner.plan("supervisor", DEEPSEEK)
    assert supervisor.thinking == "high" and "temperature" not in supervisor.settings
    assert supervisor.max_tokens == 16384 and supervisor.timeout_s == 600
    fast = env_planner.plan("engineer", ModelRef("deepseek", "deepseek-flash"))
    assert fast.thinking is False and fast.settings["temperature"] == 0.2
    assert fast.max_tokens == 4096 and fast.timeout_s == 120
    # A fast model that always thinks gets the lowest effort and no temperature.
    glm_flash = env_planner.plan("engineer", ModelRef("glm", "glm-5.3-flash"))
    assert glm_flash.thinking is False and "temperature" not in glm_flash.settings
    assert glm_flash.timeout_s == 600


def test_the_critic_chain_excludes_the_engineers_provider():
    planner = _planner()
    assert [str(r) for r in planner.chain("critic")] == ["deepseek/deepseek-v4-pro", "kimi/kimi-k3"]
    assert [str(r) for r in planner.chain("critic", exclude_provider="deepseek")] == [
        "kimi/kimi-k3"
    ]


def test_models_are_built_with_the_configured_endpoint_and_no_sdk_retries():
    environ = {"DEEPSEEK_API_KEY": "k1", "MOONSHOT_API_KEY": "k2", "ZHIPU_API_KEY": "k3"}
    source = ProviderModels(PRICED.providers, environ)
    deepseek = source.model("critic", DEEPSEEK)
    assert isinstance(deepseek, OpenAIChatModel)
    assert str(deepseek.client.base_url).rstrip("/") == "https://api.deepseek.com"
    assert deepseek.client.max_retries == 0
    assert deepseek.profile["supports_forced_tool_choice"] is False  # tool_choice auto
    glm = source.model("engineer", ModelRef("glm", "glm-5.3-flash"))
    assert isinstance(glm, ZaiModel)
    assert source.model("critic", DEEPSEEK) is deepseek  # one model object per reference
    with pytest.raises(ProviderUnavailable):
        ProviderModels(PRICED.providers, {}).model("critic", DEEPSEEK)


def _planner():
    return Planner(PRICED.providers, PRICED.roles)


def _completion(request: httpx.Request) -> httpx.Response:
    """An OpenAI-compatible answer: the output tool call, or JSON text in prompted mode."""
    body = json.loads(request.content)
    answer = json.dumps({"ok": True, "token": "qfr"})
    tools = body.get("tools") or []
    message: dict[str, object] = {"role": "assistant", "content": answer}
    if tools:
        name = tools[0]["function"]["name"]
        message = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": name, "arguments": answer}}
            ],
        }
    return httpx.Response(
        200,
        json={
            "id": "r1",
            "object": "chat.completion",
            "created": 0,
            "model": body["model"],
            "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        },
    )


@pytest.mark.parametrize(
    ("role", "ref", "endpoint", "thinking"),
    [
        ("supervisor", "deepseek/deepseek-v4-pro", DS, {"reasoning_effort": "high"}),
        ("engineer", "deepseek/deepseek-flash", DS, {"reasoning_effort": "none"}),
        ("hypothesis", "kimi/kimi-k3", MS, {"reasoning_effort": "high"}),
        ("engineer", "kimi/kimi-k2.6", MS, {"thinking": {"type": "disabled"}}),
        ("interp_review", "glm/glm-5.3", ZAI, {"reasoning_effort": "high"}),
        ("engineer", "glm/glm-5.3-flash", ZAI, {"reasoning_effort": "low"}),
    ],
)  # fmt: skip
def test_each_provider_receives_its_request_shape(role, ref, endpoint, thinking):
    """The request each configured model gets, over a mock transport (no network): the
    configured endpoint, explicit max tokens, tool_choice auto (never forced), the
    thinking control, a temperature only without thinking, and json_object in prompted
    mode. The probe confirms on the owner's machine that each provider accepts it."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _completion(request)

    environ = {"DEEPSEEK_API_KEY": "k1", "MOONSHOT_API_KEY": "k2", "ZHIPU_API_KEY": "k3"}
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    model_ref = ModelRef.parse(ref)
    model = ProviderModels(PRICED.providers, environ, client).model(role, model_ref)
    plan = _planner().plan(role, model_ref)
    bodies = []

    async def both() -> None:
        for spec in (ToolOutput(Ping, name="final_result"), PromptedOutput(Ping)):
            run = await Agent(model, output_type=spec).run(
                "ping", model_settings=plan.model_settings()
            )
            assert run.output == Ping(ok=True, token="qfr")
            bodies.append(json.loads(seen[-1].content))

    with override_allow_model_requests(True):
        asyncio.run(both())
    assert all(str(r.url) == f"{endpoint}/chat/completions" for r in seen)
    tool, prompted = bodies
    for body in bodies:
        assert body["model"] == model_ref.model_id
        assert body["max_completion_tokens"] == plan.max_tokens
        assert thinking.items() <= body.items(), body
        assert ("temperature" in body) == ("temperature" in plan.settings)
    assert tool["tool_choice"] == "auto" and "response_format" not in tool
    assert prompted["response_format"] == {"type": "json_object"} and "tools" not in prompted
