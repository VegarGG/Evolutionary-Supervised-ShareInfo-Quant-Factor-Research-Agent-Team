"""Publication and declared-runner contracts; no private evaluator information."""

from typing import Annotated, Literal

from pydantic import Field, NonNegativeInt, PositiveInt

from qfr_core.contracts.artifacts import ArtifactDefinition, ArtifactManifest
from qfr_core.contracts.base import Contract, Sha256, Text
from qfr_core.contracts.enums import ArtifactKind


class EncodedPayload(Contract):
    asset_id: Text
    data_base64: str


class PublicationRequest(Contract):
    publish_key: Annotated[str, Field(min_length=1, max_length=200)]
    profile: Literal["pilot_industry_v1", "stock_daily_v1", "generic"]
    manifest: ArtifactDefinition
    files: list[EncodedPayload]
    # Accepted for compatibility with clients that precompute a hash. Never trusted.
    content_hash: Sha256 | None = None


class PublishedArtifact(Contract):
    manifest: ArtifactManifest
    profile: Literal["pilot_industry_v1", "stock_daily_v1", "generic"]
    version_no: PositiveInt
    published_seq: PositiveInt
    dsl_policy_hash: Sha256 | None
    payload_digest: Sha256


class PublicationResponse(Contract):
    artifact: PublishedArtifact
    created: bool


class RunnerPackage(Contract):
    """Metadata is inspected without importing or executing package source."""

    format: Literal["qfr-json-runner/1"]
    kind: ArtifactKind
    entrypoint: Text
    input_schema_ref: Text
    output_schema_ref: Text
    dependency_lock_sha256: Sha256
    fields_used: list[Text]
    max_lookback_days: NonNegativeInt
    weight_files: list[Text]
