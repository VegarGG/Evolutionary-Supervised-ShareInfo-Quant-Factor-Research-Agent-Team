"""Read authorized public services over HTTP; verify before using official labels."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlencode
from uuid import UUID

from qfr_core.contracts.artifacts import ArtifactDefinition, ArtifactReference
from qfr_core.contracts.data import SourceAsset
from qfr_core.contracts.delivery import DeliveryReceipt
from qfr_core.contracts.feedback import PublicCards
from qfr_core.contracts.publication import PublishedArtifact
from qfr_core.contracts.reports import PublicProtocolCard, ReleasedReport
from qfr_core.delivery_rules import content_sha256
from qfr_core.registry_client import RegistryClient
from qfr_core.service_client import PublicServiceClient
from qfr_core.signatures import EvidenceVerifier

from qfr_research.api.errors import InvalidResearchRequest, ResearchNotFound, ResearchUnavailable


@dataclass(frozen=True)
class ProgramServices:
    registry: RegistryClient
    feedback: PublicServiceClient
    intake: PublicServiceClient | None = None


class EvidenceGateway:
    def __init__(self, clients: Mapping[UUID, ProgramServices], verifier: EvidenceVerifier):
        self.clients, self.verifier = dict(clients), verifier

    def services(self, program: UUID) -> ProgramServices:
        if program not in self.clients:
            raise ResearchUnavailable("program public services are not configured")
        return self.clients[program]

    def artifact(self, program: UUID, reference: ArtifactReference) -> PublishedArtifact:
        value = self.services(program).registry.get(UUID(reference.artifact_version_id))
        manifest = value.manifest
        definition = {
            k: v
            for k, v in manifest.model_dump(mode="json").items()
            if k in ArtifactDefinition.model_fields and k != "family_id"
        }
        expected = content_sha256(
            dict(
                hash_spec="qfr-publication/1",
                profile=value.profile,
                dsl_policy_hash=value.dsl_policy_hash,
                manifest=definition,
            )
        )
        if manifest.provenance.program_id != str(program):
            raise ResearchNotFound("artifact unavailable")
        if (
            manifest.content_hash != reference.content_hash
            or value.payload_digest != expected
            or manifest.content_hash != expected
        ):
            raise InvalidResearchRequest("artifact identity differs")
        return value

    def report(self, program: UUID, identity: UUID) -> ReleasedReport:
        _, raw = self.services(program).feedback.request("GET", f"v1/reports/{identity}")
        value = self.verifier.report(raw)
        if value.program_id != str(program):
            raise ResearchNotFound("released report unavailable")
        if value.report_id != str(identity) or value.released_at > datetime.now(UTC):
            raise InvalidResearchRequest("released report binding differs")
        return value

    def payload(self, program: UUID, artifact: PublishedArtifact, asset_id: str) -> bytes:
        if artifact.manifest.provenance.program_id != str(program):
            raise ResearchNotFound("artifact unavailable")
        return self.services(program).registry.payload(artifact, asset_id)

    def protocol_card(self, program: UUID, reference: str) -> PublicProtocolCard:
        _, raw = self.services(program).feedback.request(
            "GET", "v1/cards/protocol?" + urlencode({"ref": reference})
        )
        cards = PublicCards.model_validate_json(raw)
        if (
            len(cards.protocols) != 1
            or cards.policies
            or (cards.protocols[0].card_ref or cards.protocols[0].protocol_version) != reference
        ):
            raise InvalidResearchRequest("public protocol card unavailable")
        return cards.protocols[0]

    def protocol_exists(self, program: UUID, version: str) -> None:
        _, raw = self.services(program).feedback.request("GET", "v1/cards/protocol")
        cards = PublicCards.model_validate_json(raw)
        if cards.policies or not any(card.protocol_version == version for card in cards.protocols):
            raise InvalidResearchRequest("declared public protocol version unavailable")

    def receipt(self, program: UUID, identity: UUID) -> DeliveryReceipt:
        _, raw = self.services(program).feedback.request("GET", f"v1/delivery-receipts/{identity}")
        value = self.verifier.delivery(raw)
        if value.receipt_id != str(identity) or value.created_at > datetime.now(UTC):
            raise InvalidResearchRequest("delivery receipt binding differs")
        return value

    def source(self, program: UUID, value: SourceAsset) -> None:
        client = self.services(program).intake
        if client is None:
            raise ResearchUnavailable("quarantine verification service not configured")
        _, raw = client.request(
            "POST", f"v1/programs/{program}/assets/verify", body=value.model_dump_json().encode()
        )
        if SourceAsset.model_validate_json(raw) != value:
            raise InvalidResearchRequest("source asset verification differs")
