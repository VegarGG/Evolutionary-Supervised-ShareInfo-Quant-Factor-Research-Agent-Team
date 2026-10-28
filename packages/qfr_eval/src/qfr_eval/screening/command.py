"""Explicit one-shot evaluator-owner commands; idle startup does not invoke them."""

import os
from pathlib import Path

import psycopg
from qfr_core.data_layer.snapshots import Snapshot
from qfr_core.registry_client import RegistryClient

from qfr_eval.artifact_store import EvidenceStore
from qfr_eval.protocols.store import get_active
from qfr_eval.sandbox.client import configured_runner
from qfr_eval.scheduler.intake import IntakeScheduler
from qfr_eval.screening.documents import ReleasedEvidence
from qfr_eval.screening.models import ScreeningSessionConfiguration
from qfr_eval.screening.worker import InputSlices, ScreeningWorker


def run_command(
    action: str,
    configuration: Path,
    dsn: str,
    *,
    principal: str,
    snapshot: Path | None,
    evidence_root: Path | None,
) -> dict[str, object]:
    config = ScreeningSessionConfiguration.model_validate_json(configuration.read_bytes())
    client = RegistryClient.from_environment(config.registry_client, os.environ)

    def connect() -> psycopg.Connection:
        return psycopg.connect(
            dsn,
            autocommit=True,
            connect_timeout=10,
            options="-c statement_timeout=30000 -c lock_timeout=30000",
        )

    scheduler = IntakeScheduler(
        client,
        connect,
        config.campaign,
        config.intake_policy,
        config.screening_policy,
        {str(k): v for k, v in config.dsl_configs.items()},
        principal=principal,
    )
    if action == "intake-poll":
        return dict(scheduler.poll_once())
    if action != "screen-one" or snapshot is None or evidence_root is None:
        raise ValueError("screening requires explicit snapshot and private evidence destinations")
    with connect() as conn:
        protocol = get_active(conn, config.campaign.protocol_ref, config.protocol_version)
    sandbox = (
        configured_runner(config.sandbox_profile, "sha256:" + config.sandbox_image_digest)
        if config.sandbox_profile is not None and config.sandbox_image_digest is not None
        else None
    )
    worker = ScreeningWorker(
        scheduler,
        protocol,
        config.runtime,
        InputSlices.from_snapshot(Snapshot.load(snapshot)),
        EvidenceStore(evidence_root),
        config.execution_policy,
        {str(k): v for k, v in config.adapter_profiles.items()},
        sandbox,
        worker=principal,
        # There is no Stage 4 release policy implementation yet. Unresolvable
        # numeric claim precision fails explicitly; no unpublished value lookup.
        released=ReleasedEvidence({}, {}, frozenset()),
    )
    result = worker.run_once()
    return {
        "status": result.status,
        "reason": result.reason,
        "intake_id": str(result.intake_id) if result.intake_id else None,
        "record_id": str(result.receipt.record_id) if result.receipt else None,
        "receipt_hash": result.receipt.receipt_hash if result.receipt else None,
    }
