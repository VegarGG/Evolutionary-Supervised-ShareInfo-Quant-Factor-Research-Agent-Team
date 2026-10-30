"""Versioned YAML configuration and environment-only runtime secrets."""

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, JsonValue, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ConfigKind = Literal[
    "protocol",
    "policy",
    "quotas",
    "charter",
    "providers",
    "roles",
    "epoch",
    "logging",
    "mcp",
    "registry",
]
CONFIG_FILES: dict[ConfigKind, str] = {
    "protocol": "protocols/cn_csi300_daily_v1.yaml",
    "policy": "release_policies/default_v1.yaml",
    "quotas": "quotas/default_v1.yaml",
    "charter": "research/charter_default.yaml",
    "providers": "research/providers.yaml",
    "roles": "research/roles.yaml",
    "epoch": "epochs/epoch_001.yaml",
    "logging": "logging.yaml",
    "mcp": "mcp.yaml",
    "registry": "registry.yaml",
}
PUBLIC_CARDS_FILE = "public_cards.json"


class RuntimeSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="QFR_", extra="ignore")
    config_dir: Path = Path("configs")
    log_dir: Path = Path("logs")
    log_level: str | None = None
    env: Literal["dev", "test", "prod"] = "dev"
    service: str = "cli"
    zone: Literal["control", "research", "registry", "eval"] = "control"
    mcp_token: SecretStr | None = None
    mcp_bind: str | None = None
    control_db_url: SecretStr | None = Field(default=None, validation_alias="CONTROL_DB_URL")


class LoggingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    rotate_bytes: int = Field(gt=0)
    compress_after_days: int = Field(gt=0)
    delete_after_days: int = Field(gt=0)
    disk_warning_bytes: int = Field(gt=0)
    sensitive_field_pattern: str
    secret_value_patterns: list[str]
    excluded_text_fields: list[str]
    default_search_hours: int = Field(gt=0)
    implicit_range_max_days: int = Field(gt=0)
    tail_default: int = Field(gt=0)

    @model_validator(mode="after")
    def retention_order(self) -> "LoggingConfig":
        if self.delete_after_days <= self.compress_after_days:
            raise ValueError("deletion must follow compression")
        return self


class MCPConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str
    bind: str
    port: int = Field(gt=0, le=65535)
    path: Literal["/mcp"]
    request_body_bytes: int = Field(gt=0)
    long_poll_seconds: int = Field(gt=0)
    list_default: int = Field(gt=0)
    list_max: int = Field(gt=0)
    approval_concurrency: Literal[1]
    confirmation_pattern: str
    downstream_timeout_seconds: float = Field(gt=0)
    import_max_bytes: int = Field(gt=0)
    import_max_entries: int = Field(gt=0)

    @model_validator(mode="after")
    def limits(self) -> "MCPConfig":
        if self.bind not in {"127.0.0.1", "::1"}:
            raise ValueError("MCP host publication must be loopback")
        if self.list_default > self.list_max:
            raise ValueError("default list size exceeds maximum")
        return self


class RegistryConfig(BaseModel):
    """registry-api listener and read limits (PLAN Section 16.5)."""

    model_config = ConfigDict(extra="forbid")
    version: str
    bind: str
    port: int = Field(gt=0, le=65535)
    request_body_bytes: int = Field(gt=0)
    list_default: int = Field(gt=0)
    list_max: int = Field(gt=0)
    lineage_depth_default: int = Field(ge=0)
    lineage_depth_max: int = Field(ge=0)

    @model_validator(mode="after")
    def limits(self) -> "RegistryConfig":
        if self.list_default > self.list_max:
            raise ValueError("default list size exceeds maximum")
        if self.lineage_depth_default > self.lineage_depth_max:
            raise ValueError("default lineage depth exceeds maximum")
        return self


class ConfigDocument(BaseModel):
    """Validated JSON-compatible YAML, with a content identity for startup logs."""

    model_config = ConfigDict(extra="forbid")
    kind: ConfigKind
    values: dict[str, JsonValue]
    sha256: str


class ProtocolConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    protocol_id: str
    version: str
    epoch_ref: str
    supported_kinds: list[Literal["factor", "strategy"]]
    universe: dict[str, JsonValue]
    eligibility: dict[str, JsonValue]
    label: dict[str, JsonValue]
    preprocessing: dict[str, JsonValue]
    quantiles: int = Field(gt=0)
    costs: dict[str, JsonValue]
    reference_strategy: dict[str, JsonValue]
    strategy_bounds: dict[str, JsonValue]
    fingerprint: dict[str, JsonValue]
    dsl: dict[str, JsonValue]
    screening: dict[str, JsonValue]
    dedup: dict[str, JsonValue]
    gates: dict[str, dict[str, JsonValue]]
    simulation: dict[str, JsonValue]
    monitoring: dict[str, JsonValue]


class PolicyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    policy_id: str
    version: str
    batching: dict[str, JsonValue]
    rounding: dict[str, float]
    t_buckets: list[float]
    ladder: dict[str, float]
    release_w3_metrics: Literal[False]
    flags: dict[
        Literal[
            "high_turnover_above",
            "low_monotonicity_below",
            "crowded_library_correlation_above",
            "decays_fast_h5_over_h1_below",
            "weak_signal_rankic_below",
            "weak_signal_nw_t_below",
            "cost_dominated_net_over_gross_below",
        ],
        float,
    ]

    @model_validator(mode="after")
    def complete(self) -> "PolicyConfig":
        required = {"rankic", "ir", "sharpe", "shares", "correlations"}
        if not required <= set(self.rounding) or any(v <= 0 for v in self.rounding.values()):
            raise ValueError("rounding needs positive rankic, ir, sharpe, shares, correlations")
        if len(self.flags) != 7:
            raise ValueError("every diagnostic flag rule needs a threshold")
        if list(self.t_buckets) != sorted(set(self.t_buckets)):
            raise ValueError("t buckets must be strictly increasing")
        return self


class QuotaConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    quota_id: str
    version: str
    family: dict[str, int]
    program: dict[str, int]
    global_limits: dict[str, int] = Field(alias="global")
    deferral_expiry_days: int = Field(gt=0)
    burn: dict[str, int]


class WindowConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: date
    end: date | None
    end_rule: Literal["last_full_month_before_epoch_activation"] | None = None

    @model_validator(mode="after")
    def ordered(self) -> "WindowConfig":
        if self.end is None and self.end_rule is None:
            raise ValueError("unresolved windows require an explicit end rule")
        if self.end is not None and self.end <= self.start:
            raise ValueError("window end must follow start")
        return self


class EpochConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    epoch_id: str
    version: str
    W0: WindowConfig
    W1: WindowConfig
    W2: WindowConfig
    W3: WindowConfig
    embargo_trading_days: int = Field(gt=0)

    @model_validator(mode="after")
    def disjoint(self) -> "EpochConfig":
        for earlier, later in ((self.W0, self.W1), (self.W1, self.W2), (self.W2, self.W3)):
            if earlier.end is None or earlier.end >= later.start:
                raise ValueError("historical windows must be resolved and disjoint")
        return self


class CharterConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    charter_id: str
    version: str
    cadence: dict[str, JsonValue]
    throughput: dict[str, int]
    budget: dict[str, JsonValue]
    context_tokens: int = Field(gt=0)
    role_limits: dict[str, JsonValue]
    population: dict[str, JsonValue]
    selection: dict[str, JsonValue]
    operator_mix: dict[str, float]
    improve_mix: dict[str, float]
    prescreen: dict[str, JsonValue]
    bandit: dict[str, JsonValue]
    job: dict[str, JsonValue]


class ProviderModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tier: Literal["strong", "fast"]
    thinking: Literal["on", "off", "always"]
    effort: Literal["low", "high", "max"] | None = None
    price_cny_per_mtok: dict[str, float | None]


class ProviderProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_url: str
    api_key_env: Literal["DEEPSEEK_API_KEY", "MOONSHOT_API_KEY", "ZHIPU_API_KEY"]
    pydantic_ai_provider: Literal["deepseek", "moonshotai", "zai"]
    models: dict[str, ProviderModel]


class ProvidersConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    providers: dict[Literal["deepseek", "kimi", "glm"], ProviderProfile]
    request: dict[str, JsonValue]
    budget: dict[str, JsonValue]
    probe: dict[str, list[str]]


class RoleProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    primary: str
    fallbacks: list[str]
    temperature: float = Field(ge=0, le=1)
    must_differ_from: Literal["engineer"] | None = None


class RolesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    roles: dict[
        Literal["supervisor", "hypothesis", "engineer", "critic", "analyst", "interp_review"],
        RoleProfile,
    ]


def canonical_json(value: JsonValue) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def load_config(kind: ConfigKind, root: Path) -> ConfigDocument:
    raw = yaml.safe_load((root / CONFIG_FILES[kind]).read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not raw:
        raise ValueError("configuration must be a nonempty mapping")
    # Pydantic rejects arbitrary Python objects, including unquoted YAML dates.
    doc = ConfigDocument(kind=kind, values=raw, sha256="pending")
    validators: dict[str, type[BaseModel]] = {
        "protocol": ProtocolConfig,
        "policy": PolicyConfig,
        "quotas": QuotaConfig,
        "epoch": EpochConfig,
        "charter": CharterConfig,
        "providers": ProvidersConfig,
        "roles": RolesConfig,
        "registry": RegistryConfig,
    }
    if kind in validators:
        validators[kind].model_validate(raw)
    if kind == "logging":
        LoggingConfig.model_validate(doc.values)
    elif kind == "mcp":
        MCPConfig.model_validate(doc.values)
    elif kind == "providers":
        providers = raw.get("providers", {})
        if set(providers) != {"deepseek", "kimi", "glm"}:
            raise ValueError("exactly the three owner-selected providers are required")
        for profile in providers.values():
            if "api_key" in profile or not profile.get("api_key_env"):
                raise ValueError("provider keys must be referenced by environment name only")
    return doc.model_copy(
        update={"sha256": hashlib.sha256(canonical_json(doc.values).encode()).hexdigest()}
    )


def logging_config(root: Path) -> LoggingConfig:
    return LoggingConfig.model_validate(load_config("logging", root).values)


def mcp_config(root: Path) -> MCPConfig:
    return MCPConfig.model_validate(load_config("mcp", root).values)


def registry_config(root: Path) -> RegistryConfig:
    return RegistryConfig.model_validate(load_config("registry", root).values)


def public_cards(root: Path) -> dict[str, JsonValue]:
    """The whitelist-built public protocol and policy cards (scripts/build_public_cards.py).

    They are the only protocol content outside the evaluation zone, so the registry
    and the front door take the DSL limits from here.
    """
    cards = json.loads((root / PUBLIC_CARDS_FILE).read_text(encoding="utf-8"))
    if not isinstance(cards, dict) or not isinstance(cards.get("protocol"), dict):
        raise ValueError("public cards must hold a protocol card")
    return cards


def public_protocol_section(root: Path, section: str) -> dict[str, JsonValue]:
    protocol = public_cards(root)["protocol"]
    value = protocol.get(section) if isinstance(protocol, dict) else None
    if not isinstance(value, dict):
        raise ValueError(f"the public protocol card has no {section} section")
    return value
