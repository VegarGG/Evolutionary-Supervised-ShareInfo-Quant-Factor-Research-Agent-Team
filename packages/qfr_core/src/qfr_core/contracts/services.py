"""Explicit launch configuration; references never grant or generate credentials."""

from pathlib import Path
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, PositiveInt, model_validator

from qfr_core.contracts.access import PublicServiceClientConfiguration, ServiceAuthentication
from qfr_core.contracts.base import Contract, SecretRef, Text
from qfr_core.contracts.feedback import FeedbackReadPolicy
from qfr_core.contracts.mcp import MCPBackendBinding, MCPPolicy
from qfr_core.contracts.publication import (
    RegistryAuthenticationConfiguration,
    RegistryClientConfiguration,
)
from qfr_core.contracts.research import ResearchApiPolicy
from qfr_core.contracts.signing import VerificationPolicy
from qfr_core.contracts.transfers import IntakeTransportPolicy


class HTTPServerConfiguration(Contract):
    revision: Literal[1]
    host: Literal["127.0.0.1", "::1", "0.0.0.0", "::"]
    port: int = Field(ge=1, le=65535)
    limit_concurrency: PositiveInt
    timeout_keep_alive: PositiveInt
    timeout_graceful_shutdown: PositiveInt
    access_log: Literal[False]
    proxy_headers: Literal[False]
    log_level: Literal["info", "warning", "error"]


class ServiceDatabaseConfiguration(Contract):
    """Role/database are selected by service code, never this public config."""

    revision: Literal[1]
    host: Text
    port: int = Field(ge=1, le=65535)
    password_ref: SecretRef
    connect_timeout_seconds: PositiveInt = Field(le=30)


class ResearchBackendBinding(Contract):
    program_id: UUID
    registry: RegistryClientConfiguration
    feedback: PublicServiceClientConfiguration
    intake: PublicServiceClientConfiguration


class ResearchServiceConfiguration(Contract):
    schema_version: Literal["1"]
    server: HTTPServerConfiguration
    database: ServiceDatabaseConfiguration
    authentication: ServiceAuthentication
    policy: ResearchApiPolicy
    verification: VerificationPolicy
    research_root: Path
    backends: list[ResearchBackendBinding] = Field(min_length=1)

    @model_validator(mode="after")
    def scoped(self) -> Self:
        ids = [entry.program_id for entry in self.backends]
        if self.authentication.audience != "research" or len(ids) != len(set(ids)):
            raise ValueError("research audience and unique backends required")
        configured = {str(value) for value in ids}
        if any(not set(b.programs) <= configured for b in self.authentication.bindings):
            raise ValueError("research authentication has an unconfigured program")
        return self


class MCPServiceConfiguration(Contract):
    schema_version: Literal["1"]
    server: HTTPServerConfiguration
    authentication: ServiceAuthentication
    policy: MCPPolicy
    export_policy: ResearchApiPolicy
    verification: VerificationPolicy
    backends: list[MCPBackendBinding] = Field(min_length=1)

    @model_validator(mode="after")
    def audience(self) -> Self:
        if self.authentication.audience != "mcp":
            raise ValueError("MCP audience required")
        return self


class IntakeServiceConfiguration(Contract):
    schema_version: Literal["1"]
    server: HTTPServerConfiguration
    authentication: ServiceAuthentication
    policy: IntakeTransportPolicy
    quarantine_root: Path
    readonly_import_mounts: dict[Text, Path]

    @model_validator(mode="after")
    def audience(self) -> Self:
        if self.authentication.audience != "intake":
            raise ValueError("intake audience required")
        return self


class FeedbackServiceConfiguration(Contract):
    schema_version: Literal["1"]
    server: HTTPServerConfiguration
    database: ServiceDatabaseConfiguration
    authentication: ServiceAuthentication
    policy: FeedbackReadPolicy
    verification: VerificationPolicy

    @model_validator(mode="after")
    def audience(self) -> Self:
        if self.authentication.audience != "feedback":
            raise ValueError("feedback audience required")
        return self


class RegistryServiceConfiguration(Contract):
    schema_version: Literal["1"]
    server: HTTPServerConfiguration
    database: ServiceDatabaseConfiguration
    authentication: RegistryAuthenticationConfiguration
    publication_policy_file: Path
    read_policy_file: Path
    dsl_policy_files: dict[Text, Path]
    payload_root: Path

    @model_validator(mode="after")
    def explicitly_enabled(self) -> Self:
        if not self.authentication.enabled:
            raise ValueError("registry service launch requires explicit authentication")
        return self
