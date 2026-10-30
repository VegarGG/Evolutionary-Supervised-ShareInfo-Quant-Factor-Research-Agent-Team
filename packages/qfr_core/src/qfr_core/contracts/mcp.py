"""Portable MCP front-door policy and bounded structured replies."""

from typing import Literal
from uuid import UUID

from pydantic import Field, JsonValue, NonNegativeInt, PositiveInt

from qfr_core.contracts.access import PublicServiceClientConfiguration, ServiceRole
from qfr_core.contracts.base import Contract, Sha256, Text
from qfr_core.contracts.publication import RegistryClientConfiguration


class MCPPolicy(Contract):
    revision: PositiveInt
    max_request_bytes: PositiveInt
    request_body_timeout_seconds: PositiveInt
    max_inline_result_bytes: PositiveInt
    resource_page_characters: PositiveInt
    default_page_size: PositiveInt
    max_page_size: PositiveInt
    upload_chunk_bytes: PositiveInt
    allowed_hosts: list[Text] = Field(min_length=1)
    allowed_origins: list[Text]
    dns_rebinding_protection: Literal[True]
    stateless_transport: Literal[True]


class MCPBackendBinding(Contract):
    principal: Text
    program_id: UUID
    roles: list[ServiceRole] = Field(min_length=1)
    research: PublicServiceClientConfiguration
    registry: RegistryClientConfiguration
    feedback: PublicServiceClientConfiguration
    intake: PublicServiceClientConfiguration


class MCPReply(Contract):
    summary: Text
    data: dict[str, JsonValue]
    resource_uri: Text | None
    document_sha256: Sha256 | None
    official_signature_verified: bool


class ResourceDocumentPage(Contract):
    uri: Text
    page: NonNegativeInt
    pages: PositiveInt
    document_sha256: Sha256
    text: str
    official_signature_verified: bool
