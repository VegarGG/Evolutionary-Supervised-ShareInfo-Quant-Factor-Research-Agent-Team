"""Recompute one counted record from its exact frozen inputs, without new feedback."""

import argparse
import hashlib
import json
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb
from qfr_core.contracts.data import SnapshotManifest
from qfr_core.data_layer.snapshots import Snapshot, canonical_json, logical_hash

from qfr_eval.artifact_store import EvidenceStore
from qfr_eval.backtest.fingerprint import pilot_fingerprint
from qfr_eval.measurement import measure_pilot
from qfr_eval.persistence import verify_receipt
from qfr_eval.protocols.models import FrozenProtocol
from qfr_eval.records import (
    EvaluationRequest,
    Measurement,
    MeasurementReceipt,
    OfficialRecord,
    ReproductionResult,
)
from qfr_eval.runtime import verify_runtime
from qfr_eval.statistics.clustering import BehavioralFingerprint, ClusterSnapshot, cluster_trials
from qfr_eval.statistics.family import TrialObservation


def reproduce(
    conn: psycopg.Connection,
    record_id: UUID,
    snapshot: Snapshot,
    store: EvidenceStore,
    *,
    principal: str,
    request_id: UUID,
) -> ReproductionResult:
    row = conn.execute(
        "SELECT payload FROM eval.official_records WHERE id=%s", [record_id]
    ).fetchone()
    if row is None:
        raise ValueError("unknown official record")
    payload = row[0]
    record = OfficialRecord.model_validate(payload["record"])
    receipt = MeasurementReceipt.model_validate(payload["receipt"])
    old = Measurement.model_validate(payload["measurement"])
    if old.status != "complete":
        raise ValueError("failed attempt has no completed measurement to reproduce")
    verify_receipt(receipt, store)
    context = json.loads(store.read(receipt.files["context"]))
    request = EvaluationRequest.model_validate(context["request"])
    protocol = FrozenProtocol.model_validate(context["protocol"])
    pinned_snapshot = SnapshotManifest.model_validate(context["snapshot"])
    if (
        str(record_id) != record.record_id
        or receipt.record_id != record.record_id
        or request.sha256 != record.request_hash
        or receipt.request_hash != request.sha256
        or protocol.sha256 != receipt.protocol_hash
        or record.protocol_hash != protocol.sha256
        or record.identity != receipt.identity
        or old.results_hash != record.results_hash
        or receipt.results_hash != record.results_hash
        or snapshot.manifest != pinned_snapshot
        or request.snapshot_id != snapshot.manifest.snapshot_id
        or hashlib.sha256(canonical_json(pinned_snapshot.model_dump(mode="json"))).hexdigest()
        != receipt.dataset_manifest_hash
        or json.loads(store.read(receipt.files["record"])) != record.model_dump(mode="json")
        or json.loads(store.read(receipt.files["measurement"])) != old.model_dump(mode="json")
    ):
        raise ValueError("record, receipt or frozen input identity mismatch")
    verify_runtime(request.runtime)
    prior = [TrialObservation.model_validate(t) for t in context["frozen_prior"]]
    tables = {table.name: snapshot.read(table.name) for table in snapshot.manifest.tables}
    frozen_fingerprints = {
        key: BehavioralFingerprint.model_validate(value) if value else None
        for key, value in context["frozen_fingerprints"].items()
    }
    pinned_clusters = ClusterSnapshot.model_validate(context["clusters"])
    try:
        fingerprint = pilot_fingerprint(request, protocol, tables)
    except (ValueError, KeyError):
        fingerprint = None
    fingerprint_match = (fingerprint is None and "fingerprint" not in receipt.files) or (
        fingerprint is not None
        and "fingerprint" in receipt.files
        and fingerprint
        == BehavioralFingerprint.model_validate_json(store.read(receipt.files["fingerprint"]))
    )
    clusters = cluster_trials(
        [*prior, old.observation],
        {**frozen_fingerprints, receipt.trial_id: fingerprint},
        protocol.diagnostics,
    )
    clusters_match = (
        clusters == pinned_clusters
        and context["effective_trials"] == clusters.effective_trials
        and pinned_clusters
        == ClusterSnapshot.model_validate_json(store.read(receipt.files["clusters"]))
    )
    actual = measure_pilot(
        request,
        protocol,
        tables,
        trial_id=receipt.trial_id,
        prior=prior,
        prior_deltas=context["prior_deltas"],
        effective_trials=context["effective_trials"],
    )
    expected_tables = {
        name
        for name, item in receipt.files.items()
        if item.media_type == "application/vnd.apache.parquet"
    }
    series_match = set(actual.tables) == expected_tables and all(
        logical_hash(frame, grain) == receipt.files[name].logical_sha256
        for name, (frame, grain) in actual.tables.items()
    )
    result = ReproductionResult(
        record_id=record.record_id,
        status="match"
        if actual.summary.results_hash == record.results_hash
        and series_match
        and fingerprint_match
        and clusters_match
        else "mismatch",
        expected_results_hash=record.results_hash,
        actual_results_hash=actual.summary.results_hash,
        series_match=series_match,
        fingerprint_match=fingerprint_match,
        clusters_match=clusters_match,
        checked_files=len(receipt.files),
        verification_only=True,
    )
    # Exact semantic replay verifies an existing counted attempt. It does not
    # publish a new version, consume a feedback query, or create a duplicate trial.
    with conn.transaction():
        conn.execute(
            "INSERT INTO eval.events(id,payload,created_by,request_id) VALUES(%s,%s,%s,%s)",
            [
                uuid4(),
                Jsonb(
                    {
                        "action": "reproduction_" + result.status,
                        "entity_type": "official_records",
                        "entity_id": str(record_id),
                        "results_hash": result.actual_results_hash,
                    }
                ),
                principal,
                request_id,
            ],
        )
    return result


def main(arguments: list[str] | None = None) -> None:
    from qfr_eval.admin.cli import connection_dsn

    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    command = commands.add_parser("reproduce")
    command.add_argument("record_id", type=UUID)
    command.add_argument("--snapshot", type=Path, required=True)
    command.add_argument("--evidence-root", type=Path, required=True)
    command.add_argument("--principal", required=True)
    command.add_argument("--request-id", type=UUID, required=True)
    args = parser.parse_args(arguments)
    try:
        with psycopg.connect(connection_dsn(), autocommit=True) as conn:
            result = reproduce(
                conn,
                args.record_id,
                Snapshot.load(args.snapshot),
                EvidenceStore(args.evidence_root),
                principal=args.principal,
                request_id=args.request_id,
            )
        print(result.model_dump_json())
        if result.status != "match":
            parser.exit(1)
    except (psycopg.Error, OSError, KeyError, ValueError) as error:
        parser.exit(1, f"reproduction refused: {type(error).__name__}\n")
