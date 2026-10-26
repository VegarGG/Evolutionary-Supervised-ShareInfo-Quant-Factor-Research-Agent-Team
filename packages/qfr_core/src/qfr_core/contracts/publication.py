"""Publication and declared-runner contracts; no private evaluator information."""

from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, NonNegativeInt, PositiveInt, model_validator

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


class ArtifactPage(Contract):
    items: list[PublishedArtifact]
    next_cursor: NonNegativeInt
    has_more: bool

    @model_validator(mode="after")
    def ordered_cursor(self) -> Self:
        sequences = [item.published_seq for item in self.items]
        if sequences != sorted(set(sequences)):
            raise ValueError("page sequences must be strictly increasing")
        if sequences and self.next_cursor != sequences[-1]:
            raise ValueError("page cursor must identify its last publication")
        if not sequences and self.has_more:
            raise ValueError("an empty page cannot advance to more publications")
        return self


class FamilyPage(Contract):
    family_id: Text
    program_id: Text
    kind: ArtifactKind
    name: Text
    created_by: Text
    created_at: AwareDatetime
    versions: ArtifactPage


class LineageNode(Contract):
    artifact_version_id: Text
    content_hash: Sha256
    family_id: Text
    kind: ArtifactKind
    version_no: PositiveInt


class LineageEdge(Contract):
    version_id: Text
    parent_version_id: Text
    relation: Literal["seed", "mutation", "crossover", "revision", "repair", "human_seed", "import"]


class ArtifactLineage(Contract):
    root_version_id: Text
    depth: NonNegativeInt
    nodes: list[LineageNode]
    edges: list[LineageEdge]
    truncated_at_depth: bool

    @model_validator(mode="after")
    def connected_references(self) -> Self:
        identities = {node.artifact_version_id for node in self.nodes}
        if self.root_version_id not in identities or len(identities) != len(self.nodes):
            raise ValueError("lineage must include its root and unique nodes")
        pairs = {(edge.version_id, edge.parent_version_id) for edge in self.edges}
        if len(pairs) != len(self.edges):
            raise ValueError("lineage edges must be unique")
        if any(child == parent or {child, parent} - identities for child, parent in pairs):
            raise ValueError("lineage edges must reference distinct included nodes")
        reached = {self.root_version_id}
        for _ in range(self.depth):
            neighbors = {value for pair in pairs if reached.intersection(pair) for value in pair}
            reached |= neighbors
        if reached != identities:
            raise ValueError("lineage nodes must be reachable within its depth")
        return self


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
