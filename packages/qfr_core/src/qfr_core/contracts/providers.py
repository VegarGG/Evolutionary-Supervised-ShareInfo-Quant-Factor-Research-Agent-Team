"""Offline configuration contracts. No secret resolution or provider requests."""

from typing import Literal, Self

from pydantic import Field, NonNegativeFloat, PositiveFloat, PositiveInt, model_validator

from qfr_core.contracts.base import Contract, SecretRef, Sha256, Text


class Timeouts(Contract):
    connect_seconds: PositiveFloat
    read_seconds: PositiveFloat
    idle_seconds: PositiveFloat | None = None


class RetryPolicy(Contract):
    max_attempts: PositiveInt
    backoff: Literal["exponential_with_jitter", "fixed", "none"]
    ambiguous_outcome: Literal["persist_before_retry"]
    backoff_seconds: NonNegativeFloat | None = None


class ProviderEndpoint(Contract):
    vendor: Text
    enabled: bool = True
    base_url_ref: SecretRef
    api_dialect: Literal["openai_chat_completions", "openai_responses"]
    api_key_ref: SecretRef
    region: Text | None = None
    account_label: Text | None = None
    timeouts: Timeouts | None = None
    retry_policy: RetryPolicy | None = None
    concurrency: PositiveInt | None = None
    requests_per_minute: PositiveInt | None = None
    tokens_per_minute: PositiveInt | None = None


class ModelCapabilities(Contract):
    input_modalities: list[Literal["text", "image", "audio", "video"]] | None = None
    tool_calling: bool | None = None
    structured_output: Literal["json_schema", "json_object", "local_only"] | None = None
    streaming: bool | None = None
    reasoning_efforts: list[Text] | None = None
    thinking_budget_tokens: bool | None = None
    sampling_parameters: list[Literal["temperature", "top_p"]] | None = None
    batch: bool | None = None
    cache: bool | None = None
    hosted_tools: bool | None = None
    server_conversation_state: bool | None = None
    knowledge_cutoff: Text | None = None


class ModelProfile(Contract):
    endpoint_ref: Text
    exact_model_id_ref: SecretRef | None = None
    exact_model_id: Text | None = None
    verified_capabilities_ref: Text | None
    context_limit_tokens: PositiveInt | None
    output_limit_tokens: PositiveInt | None
    capabilities: ModelCapabilities | None = None


class RequestedSettings(Contract):
    temperature: NonNegativeFloat | None = None
    top_p: float | None = Field(default=None, ge=0, le=1)
    reasoning_effort: Text | None = None
    thinking_budget_tokens: PositiveInt | None = None
    max_output_tokens: PositiveInt | None = None


class PricingSnapshot(Contract):
    snapshot_ref: Text | None
    currency: Text | None
    input_per_million: NonNegativeFloat | None
    output_per_million: NonNegativeFloat | None
    cached_input_per_million: NonNegativeFloat | None


class RoleProfile(Contract):
    model_profile: Text
    prompt_template_ref: Text
    tool_policy_ref: Text
    tool_allowlist: list[Text] = Field(default_factory=list)
    requested_settings: RequestedSettings
    max_tool_turns: PositiveInt
    context_policy_ref: Text
    per_call_timeouts: Timeouts
    retry_policy: RetryPolicy
    pricing_snapshot: PricingSnapshot | None = None
    budget_reservation_usd: PositiveFloat | None = None
    fallback_allowlist: list[Text] = Field(default_factory=list)


class TaskOverride(Contract):
    task_id: Text
    role_profile: Text
    model_profile: Text | None = None
    prompt_template_ref: Text | None = None
    requested_settings: RequestedSettings | None = None
    max_tool_turns: PositiveInt | None = None
    context_policy_ref: Text | None = None
    per_call_timeouts: Timeouts | None = None
    retry_policy: RetryPolicy | None = None
    fallback_allowlist: list[Text] = Field(default_factory=list)
    override_source: Text


class CapabilityPreflight(Contract):
    required: Literal[True]
    unsupported_parameter_policy: Literal["reject_with_field_reason"]
    local_schema_validation: Literal[True]
    preserve_provider_continuation: Literal[True]
    pricing_snapshot_ref: Text | None
    audit_requested_and_effective_settings: Literal[True]


class JobPolicy(Contract):
    max_wall_clock_seconds: PositiveInt | None
    max_generations: PositiveInt | None
    authorized_spend_ref: Text | None
    exit_gate_spec_ref: Text | None
    fallback_allowlist: list[Text]
    on_budget_exhaustion: Literal["budget_paused"]
    completion_requires_independent_receipt: Literal[True]


class ProviderProfiles(Contract):
    schema_version: Literal["1"]
    status: Text
    notes: list[Text]
    provider_endpoints: dict[Text, ProviderEndpoint]
    model_profiles: dict[Text, ModelProfile]
    role_profiles: dict[Text, RoleProfile]
    task_overrides: list[TaskOverride] = Field(default_factory=list)
    task_override_fields: list[
        Literal[
            "model_profile",
            "prompt_template_ref",
            "requested_settings",
            "max_tool_turns",
            "context_policy_ref",
            "per_call_timeouts",
            "retry_policy",
            "fallback_allowlist",
        ]
    ]
    capability_preflight: CapabilityPreflight
    job_policy: JobPolicy

    @model_validator(mode="after")
    def references_exist(self) -> Self:
        for name, model in self.model_profiles.items():
            if model.endpoint_ref not in self.provider_endpoints:
                raise ValueError(f"model_profiles.{name}.endpoint_ref is unresolved")
        for name, role in self.role_profiles.items():
            if role.model_profile not in self.model_profiles:
                raise ValueError(f"role_profiles.{name}.model_profile is unresolved")
            if not set(role.fallback_allowlist) <= self.model_profiles.keys():
                raise ValueError(f"role_profiles.{name}.fallback_allowlist is unresolved")
            model = self.model_profiles[role.model_profile]
            settings = role.requested_settings
            if (
                model.output_limit_tokens is not None
                and settings.max_output_tokens is not None
                and settings.max_output_tokens > model.output_limit_tokens
            ):
                raise ValueError(f"role_profiles.{name}.max_output_tokens exceeds model limit")
            if model.capabilities and model.capabilities.sampling_parameters is not None:
                for field in ("temperature", "top_p"):
                    if (
                        getattr(settings, field) is not None
                        and field not in model.capabilities.sampling_parameters
                    ):
                        raise ValueError(f"role_profiles.{name}.{field} is unsupported")
        for task in self.task_overrides:
            if task.role_profile not in self.role_profiles:
                raise ValueError("task_overrides.role_profile is unresolved")
            if task.model_profile is not None and task.model_profile not in self.model_profiles:
                raise ValueError("task_overrides.model_profile is unresolved")
            if not set(task.fallback_allowlist) <= self.model_profiles.keys():
                raise ValueError("task_overrides.fallback_allowlist is unresolved")
        return self


class EffectiveTaskConfiguration(Contract):
    status: Literal["unresolved", "frozen"]
    task_id: Text
    revision: PositiveInt
    provider_vendor: Text
    endpoint_id: Text
    exact_model_id: Text | None
    role_profile: Text
    requested_settings: RequestedSettings
    effective_settings: RequestedSettings
    override_sources: list[Text]
    capability_test_revision: Text | None
    prompt_hash: Sha256
    config_hash: Sha256
    pricing_snapshot: PricingSnapshot
    budget_reservation_usd: PositiveFloat | None

    @model_validator(mode="after")
    def frozen_requires_verified_identity(self) -> Self:
        if self.status == "frozen" and (
            self.exact_model_id is None
            or self.capability_test_revision is None
            or self.budget_reservation_usd is None
        ):
            raise ValueError("frozen task requires model identity, capability evidence and budget")
        return self
