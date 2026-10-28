"""Explicit trusted one-shot pull; no evaluation-control HTTP or research trigger."""

from collections.abc import Mapping
from uuid import UUID

from psycopg import Connection
from pydantic import ValidationError
from qfr_core.contracts.delivery import DeliveryCandidate, DeliveryReceipt
from qfr_core.registry_client import RegistryClient
from qfr_core.service_client import PublicServiceClient, ServiceTransportError
from qfr_core.signatures import EvidenceVerifier

from qfr_eval.artifact_store import EvidenceStore
from qfr_eval.delivery.models import DeliveryWorkerConfiguration
from qfr_eval.delivery.store import persist_delivery
from qfr_eval.signing import EvaluatorSigner


def pull_and_check(
    conn: Connection,
    configuration: DeliveryWorkerConfiguration,
    environment: Mapping[str, str],
    job_id: UUID,
    proposal_id: UUID,
    signer: EvaluatorSigner,
    verifier: EvidenceVerifier,
    evidence_store: EvidenceStore,
    *,
    principal: str,
    request_id: UUID,
) -> DeliveryReceipt:
    client = PublicServiceClient.from_environment(configuration.research_client, environment)
    _, raw = client.request(
        "GET", f"v1/jobs/{job_id}/delivery-proposals/{proposal_id}", request_id=request_id
    )
    try:
        candidate = DeliveryCandidate.model_validate_json(raw)
    except ValidationError:
        raise ServiceTransportError("invalid admitted delivery candidate") from None
    if (
        candidate.context.job.project_id != configuration.program_id
        or candidate.context.job.job_id != str(job_id)
        or candidate.proposal.proposal_id != str(proposal_id)
    ):
        raise ValueError("delivery source differs from authorized job and program")
    registry = RegistryClient.from_environment(configuration.registry_client, environment)
    return persist_delivery(
        conn,
        candidate.context,
        candidate.proposal,
        registry,
        configuration.policy,
        verifier,
        signer,
        evidence_store,
        principal=principal,
        request_id=request_id,
    )
