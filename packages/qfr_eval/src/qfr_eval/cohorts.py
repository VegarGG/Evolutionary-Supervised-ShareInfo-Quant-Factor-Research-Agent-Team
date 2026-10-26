"""Read a private frozen all-attempt cohort; never discard failed versions."""

import json
from typing import Any

from psycopg import Connection

from qfr_eval.artifact_store import EvidenceStore
from qfr_eval.persistence import verify_receipt
from qfr_eval.records import EvaluationRequest, MeasurementReceipt, TrialLedgerEntry
from qfr_eval.statistics.clustering import BehavioralFingerprint

COHORT_FIELDS = (
    "program_id",
    "protocol_hash",
    "snapshot_id",
    "epoch_id",
    "window",
    "cycle",
    "cohort_id",
)


def cohort_scope(request: EvaluationRequest) -> list[str]:
    return [getattr(request, name) for name in COHORT_FIELDS]


def read_cohort(
    conn: Connection, request: EvaluationRequest
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    # Field names are source constants, never interpolated user input.
    conditions = " AND ".join(f"r.payload->'request'->>'{name}'=%s" for name in COHORT_FIELDS)
    return conn.execute(
        "SELECT t.payload,r.payload FROM eval.trial_ledger t "
        "JOIN eval.official_records r ON r.id=t.official_record_id WHERE "
        + conditions
        + " ORDER BY t.created_at,t.id",
        cohort_scope(request),
    ).fetchall()


def read_fingerprints(
    rows: list[tuple[dict[str, Any], dict[str, Any]]], store: EvidenceStore
) -> dict[str, BehavioralFingerprint | None]:
    fingerprints = {}
    for payload, record in rows:
        trial = TrialLedgerEntry.model_validate(payload)
        value = None
        if trial.fingerprint_ref is not None:
            try:
                receipt = MeasurementReceipt.model_validate(record["receipt"])
                verify_receipt(receipt, store)
                item = receipt.files["fingerprint"]
                if item.relative_path != trial.fingerprint_ref:
                    raise ValueError("fingerprint receipt reference differs")
                value = BehavioralFingerprint.model_validate(json.loads(store.read(item)))
                request = EvaluationRequest.model_validate(record["request"])
                if value.content_hash != request.content_hash or value.epoch_id != request.epoch_id:
                    raise ValueError("fingerprint source identity differs")
            except (ValueError, KeyError, OSError):
                # ClusterSnapshot explicitly records this missing trial and no
                # behavioral N_eff; never substitute an independent singleton.
                value = None
        fingerprints[trial.trial_id] = value
    return fingerprints
