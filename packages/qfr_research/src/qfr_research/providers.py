"""The provider layer (P4.2, PLAN Section 11.8).

One adapter interface over PydanticAI's DeepSeekProvider, MoonshotAIProvider and
ZaiProvider (with ZaiModel). The library encodes each provider's thinking switch,
reasoning pass-back and tool-choice rules; QFR adds configuration, prices, the thinking
policy, explicit max tokens, timeouts and the fallback chain. Profile changes come from
providers.yaml only.

Nothing here hard-codes a model id or a price: every id and price is configuration that
the probe verifies. A model without a configured price refuses to run.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, time
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal, Protocol

import pydantic_ai
from pydantic_ai.models import Model
from pydantic_ai.settings import ModelSettings
from qfr_core.config import ProviderModel, ProviderProfile, ProvidersConfig, RolesConfig

# The services and the CLI own their output (JSON log lines and probe reports), so the
# library's first-run banner is never printed.
pydantic_ai.BANNER_ENABLED = False

ProviderKey = Literal["deepseek", "kimi", "glm"]
PROVIDER_KEYS: tuple[ProviderKey, ...] = ("deepseek", "kimi", "glm")
PricePeriod = Literal["peak", "offpeak", "flat"]
# The token class each role's output budget comes from (providers.yaml max_completion_tokens).
OUTPUT_CLASS = {
    "supervisor": "plan",
    "hypothesis": "draft",
    "engineer": "draft",
    "critic": "review",
    "analyst": "interpretation",
    "interp_review": "review",
}
# Accepted temperature ranges; GLM documents (0, 1] on its China endpoint.
TEMPERATURE_RANGE: dict[ProviderKey, tuple[float, float]] = {
    "deepseek": (0.0, 2.0),
    "kimi": (0.0, 1.0),
    "glm": (0.01, 1.0),
}
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
MILLION = Decimal(1_000_000)
CENT_MICROS = Decimal("0.000001")


class NoPrice(RuntimeError):
    """A role's model has no complete price: it must not run (Section 11.7)."""


class ProviderUnavailable(RuntimeError):
    """The provider's key is not in this process's environment."""


@dataclass(frozen=True)
class ModelRef:
    provider: ProviderKey
    model_id: str

    @classmethod
    def parse(cls, ref: str) -> "ModelRef":
        provider, _, model_id = ref.partition("/")
        if provider not in PROVIDER_KEYS or not model_id:
            raise ValueError(f"model references are provider/model_id, got {ref!r}")
        return cls(provider, model_id)

    def __str__(self) -> str:
        return f"{self.provider}/{self.model_id}"


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    requests: int = 0
    tool_calls: int = 0

    @property
    def miss_tokens(self) -> int:
        return max(0, self.input_tokens - self.cache_read_tokens - self.cache_write_tokens)


@dataclass(frozen=True)
class PriceQuote:
    """CNY per million tokens for each class, at the rate in force at one instant."""

    ref: ModelRef
    period: PricePeriod
    in_miss: Decimal
    in_hit: Decimal
    cache_write: Decimal
    out: Decimal

    def cost(self, usage: TokenUsage) -> Decimal:
        total = (
            self.in_miss * usage.miss_tokens
            + self.in_hit * usage.cache_read_tokens
            + self.cache_write * usage.cache_write_tokens
            + self.out * usage.output_tokens
        ) / MILLION
        return total.quantize(CENT_MICROS, rounding=ROUND_HALF_UP)

    def estimate(self, prompt_tokens: int, max_output_tokens: int) -> Decimal:
        """Before a call: the whole prompt at the miss rate plus the full output budget."""
        return self.cost(TokenUsage(prompt_tokens, max_output_tokens))


class PriceTable:
    def __init__(self, providers: ProvidersConfig) -> None:
        self.providers = providers
        rate = providers.budget.get("usd_to_cny")
        self.usd_to_cny = None if rate is None else Decimal(str(rate))

    def model(self, ref: ModelRef) -> ProviderModel:
        profile = self.providers.providers.get(ref.provider)
        if profile is None or ref.model_id not in profile.models:
            raise NoPrice(f"{ref} is not configured in providers.yaml")
        return profile.models[ref.model_id]

    def missing(self, ref: ModelRef) -> list[str]:
        """The price classes a model lacks; empty when the model may run."""
        try:
            model = self.model(ref)
        except NoPrice:
            return ["model"]
        prices = model.price_cny_per_mtok or model.price_usd_per_mtok or {}
        missing: list[str] = [k for k, v in prices.items() if v is None]
        for required in ("in_miss", "out"):
            if required not in prices:
                missing.append(required)
        if model.price_usd_per_mtok is not None and self.usd_to_cny is None:
            missing.append("usd_to_cny")
        return sorted(set(missing))

    def quote(self, ref: ModelRef, at: datetime) -> PriceQuote:
        missing = self.missing(ref)
        if missing:
            raise NoPrice(f"{ref} has no price for {', '.join(missing)}")
        model = self.model(ref)
        raw = model.price_cny_per_mtok or model.price_usd_per_mtok or {}
        factor = Decimal(1) if model.price_cny_per_mtok is not None else self.usd_to_cny
        assert factor is not None
        prices = {
            k: Decimal(str(v)) * factor
            for k, v in raw.items()
            if v is not None and k != "offpeak_factor"
        }
        period = self.period(ref.provider, at)
        scale = Decimal(1)
        if period == "offpeak" and raw.get("offpeak_factor") is not None:
            scale = Decimal(str(raw["offpeak_factor"]))
        miss = prices["in_miss"] * scale
        return PriceQuote(
            ref,
            period if "offpeak_factor" in raw else "flat",
            miss,
            prices.get("in_hit", prices["in_miss"]) * scale,
            prices.get("cache_write", prices["in_miss"]) * scale,
            prices["out"] * scale,
        )

    def period(self, provider: ProviderKey, at: datetime) -> PricePeriod:
        calendar = self.providers.providers[provider].pricing_calendar
        if calendar is None:
            return "flat"
        if WEEKDAYS[at.weekday()] not in calendar.weekdays or at.date() in calendar.holidays:
            return "offpeak"
        now = at.time().replace(second=0, microsecond=0)
        for window in calendar.peak_utc:
            start, _, end = window.partition("-")
            if time.fromisoformat(start) <= now < time.fromisoformat(end):
                return "peak"
        return "offpeak"


@dataclass(frozen=True)
class CallPlan:
    """How one role calls one model: settings, limits, timeout and the thinking policy."""

    ref: ModelRef
    settings: dict[str, Any]
    thinking: bool | str
    max_tokens: int
    timeout_s: float

    def model_settings(self) -> ModelSettings:
        settings: ModelSettings = ModelSettings(**self.settings)  # type: ignore[typeddict-item]
        return settings


class Planner:
    """Per-role settings from providers.yaml and roles.yaml."""

    def __init__(self, providers: ProvidersConfig, roles: RolesConfig) -> None:
        self.providers, self.roles = providers, roles
        request = providers.request
        self.max_tokens = _int_map(request["max_completion_tokens"])
        self.timeouts = _int_map(request["timeout_s"])

    def chain(self, role: str, exclude_provider: str | None = None) -> list[ModelRef]:
        profile = self.roles.roles[role]  # type: ignore[index]
        refs = [ModelRef.parse(r) for r in [profile.primary, *profile.fallbacks]]
        return [r for r in refs if r.provider != exclude_provider]

    def plan(self, role: str, ref: ModelRef) -> CallPlan:
        model = self.providers.providers[ref.provider].models[ref.model_id]
        temperature = self.roles.roles[role].temperature  # type: ignore[index]
        # Strong models think at their configured effort; fast models think as little as
        # the model allows (PydanticAI maps False to the lowest effort on always-on models).
        thinking: bool | str = (model.effort or True) if model.tier == "strong" else False
        if model.thinking == "off":
            thinking = False
        thinks = thinking is not False or model.thinking == "always"
        max_tokens = self.max_tokens[OUTPUT_CLASS[role]]
        timeout = float(self.timeouts["thinking" if thinks else "fast"])
        settings: dict[str, Any] = {
            "max_tokens": max_tokens,
            "timeout": timeout,
            "thinking": thinking,
        }
        if not thinks:
            low, high = TEMPERATURE_RANGE[ref.provider]
            settings["temperature"] = min(high, max(low, temperature))
        return CallPlan(ref, settings, thinking, max_tokens, timeout)


class ModelSource(Protocol):
    """Builds the PydanticAI model for one role and model reference; the probe also lists
    a provider's models and reads an account balance where the provider offers one."""

    def model(self, role: str, ref: ModelRef) -> Model: ...

    async def list_models(self, provider: ProviderKey) -> list[str]: ...

    async def balance(self, provider: ProviderKey) -> dict[str, Any]: ...


class ProviderModels:
    """Real providers: PydanticAI provider classes with the configured base URL and key.

    Keys are read from this process's environment by the variable name that
    providers.yaml gives; only research-worker has them (BND-07).
    """

    def __init__(
        self, providers: ProvidersConfig, environ: Mapping[str, str], http_client: Any = None
    ) -> None:
        self.providers, self.environ, self.http_client = providers, environ, http_client
        self.cache: dict[ModelRef, Model] = {}

    def model(self, role: str, ref: ModelRef) -> Model:
        if ref not in self.cache:
            self.cache[ref] = build_model(
                self.providers.providers[ref.provider], ref, self.environ, self.http_client
            )
        return self.cache[ref]

    def _key(self, provider: ProviderKey) -> tuple[ProviderProfile, str]:
        profile = self.providers.providers[provider]
        key = self.environ.get(profile.api_key_env)
        if not key:
            raise ProviderUnavailable(f"{profile.api_key_env} is not set in this service")
        return profile, key

    async def list_models(self, provider: ProviderKey) -> list[str]:
        """The provider's model list (GET /models, OpenAI-compatible on all three)."""
        from openai import AsyncOpenAI

        profile, key = self._key(provider)
        client = AsyncOpenAI(
            base_url=profile.base_url, api_key=key, max_retries=0, http_client=self.http_client
        )
        page = await client.models.list()
        return [m.id for m in page.data]

    async def balance(self, provider: ProviderKey) -> dict[str, Any]:
        """Moonshot's account balance (GET /users/me/balance); other providers: empty."""
        import httpx

        if provider != "kimi":
            return {}
        profile, key = self._key(provider)
        async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
            response = await client.get(
                profile.base_url.rstrip("/") + "/users/me/balance",
                headers={"Authorization": f"Bearer {key}"},
            )
        response.raise_for_status()
        data = response.json()
        return dict(data.get("data") or {}) if isinstance(data, dict) else {}


def build_model(
    profile: ProviderProfile, ref: ModelRef, environ: Mapping[str, str], http_client: Any = None
) -> Model:
    from openai import AsyncOpenAI
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.models.zai import ZaiModel
    from pydantic_ai.providers.deepseek import DeepSeekProvider
    from pydantic_ai.providers.moonshotai import MoonshotAIProvider
    from pydantic_ai.providers.zai import ZaiProvider

    key = environ.get(profile.api_key_env)
    if not key:
        raise ProviderUnavailable(f"{profile.api_key_env} is not set in this service")
    # The SDK's own retries are off: QFR retries with its configured backoff, and on a
    # small Moonshot tier the SDK's retries alone can exhaust the request rate.
    client = AsyncOpenAI(
        base_url=profile.base_url, api_key=key, max_retries=0, http_client=http_client
    )
    provider: Any
    if profile.pydantic_ai_provider == "deepseek":
        provider = DeepSeekProvider(openai_client=client)
    elif profile.pydantic_ai_provider == "moonshotai":
        provider = MoonshotAIProvider(openai_client=client)
    else:
        provider = ZaiProvider(openai_client=client)
    base = provider.model_profile(ref.model_id) or {}
    merged = dict(base) | dict(profile.profile_overrides)
    if profile.pydantic_ai_provider == "zai":
        return ZaiModel(ref.model_id, provider=provider, profile=merged)  # type: ignore[arg-type]
    return OpenAIChatModel(ref.model_id, provider=provider, profile=merged)  # type: ignore[arg-type]


def _int_map(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        raise ValueError("expected a mapping in providers.yaml request")
    return {str(k): int(v) for k, v in value.items()}
