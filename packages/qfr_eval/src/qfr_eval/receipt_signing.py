"""Verify original private evidence before appending its signed wrapper."""

import json
from uuid import UUID, uuid5

from psycopg import Connection
from psycopg.types.json import Jsonb
from qfr_core.contracts.data import SnapshotManifest
from qfr_core.signatures import EvidenceVerifier

from qfr_eval.artifact_store import EvidenceStore
from qfr_eval.persistence import verify_receipt
from qfr_eval.protocols.models import FrozenProtocol
from qfr_eval.records import EvaluationRequest, Measurement, MeasurementReceipt, OfficialRecord
from qfr_eval.scheduler.dedup import digest
from qfr_eval.signed_receipts import SignedMeasurementReceipt
from qfr_eval.signing import EvaluatorSigner


def sign_measurement_receipt(
    conn: Connection,
    record_id: UUID,
    store: EvidenceStore,
    signer: EvaluatorSigner,
    verifier: EvidenceVerifier,
    *,
    principal: str,
    request_id: UUID,
) -> SignedMeasurementReceipt:
    if not principal.strip():
        raise ValueError("receipt author required")
    with conn.transaction():
        # Serialize even an absent wrapper without requesting UPDATE rights on
        # immutable official records. A hash collision only serializes more work.
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            ["qfr-receipt:" + str(record_id)],
        )
        row = conn.execute(
            "SELECT payload,trial_id FROM eval.official_records WHERE id=%s", [record_id]
        ).fetchone()
        if row is None:
            raise ValueError("measurement receipt source unavailable")
        record = OfficialRecord.model_validate(row[0]["record"])
        request = EvaluationRequest.model_validate(row[0]["request"])
        receipt = MeasurementReceipt.model_validate(row[0].get("receipt"))
        if (
            receipt.record_id != str(record_id)
            or receipt.identity != record.identity
            or receipt.protocol_hash != record.protocol_hash
            or receipt.request_hash != record.request_hash
            or receipt.results_hash != record.results_hash
            or receipt.trial_id != str(row[1])
            or request.sha256 != receipt.request_hash
            or receipt.implementation_sha256 != request.runtime.implementation_sha256
            or receipt.image_digest != request.runtime.image_digest
        ):
            raise ValueError("measurement receipt does not bind its official source")
        verify_receipt(receipt, store)
        if not {"context", "measurement", "record"} <= set(receipt.files):
            raise ValueError("measurement receipt lacks required original evidence")
        context = json.loads(store.read(receipt.files["context"]))
        snapshot = SnapshotManifest.model_validate(context["snapshot"])
        protocol = FrozenProtocol.model_validate(context["protocol"])
        if (
            EvaluationRequest.model_validate(context["request"]) != request
            or digest(snapshot.model_dump(mode="json")) != receipt.dataset_manifest_hash
            or snapshot.snapshot_id != request.snapshot_id
            or protocol.sha256 != receipt.protocol_hash
            or OfficialRecord.model_validate_json(store.read(receipt.files["record"])) != record
            or Measurement.model_validate_json(
                store.read(receipt.files["measurement"])
            ).results_hash
            != receipt.results_hash
        ):
            raise ValueError("measurement receipt evidence bindings differ")
        old = conn.execute(
            "SELECT payload,payload_sha256,original_receipt_hash "
            "FROM eval.signed_measurement_receipts WHERE official_record_id=%s",
            [record_id],
        ).fetchone()
        if old is not None:
            result = SignedMeasurementReceipt.model_validate(old[0])
            if (
                digest(old[0]) != old[1]
                or old[2] != receipt.receipt_hash
                or result.receipt != receipt
            ):
                raise ValueError("signed receipt identity differs")
        else:
            clock = conn.execute("SELECT clock_timestamp()").fetchone()
            assert clock is not None
            result = signer.seal(
                SignedMeasurementReceipt,
                "measurement_receipt",
                dict(
                    schema_version="1",
                    kind="private_signed_measurement_receipt",
                    authenticity="signed_wrapper",
                    receipt=receipt,
                    signed_at=clock[0],
                ),
            )
        verifier.verify_payload(
            "measurement_receipt",
            result.model_dump(mode="json", exclude={"signature"}),
            result.signature,
        )
        if old is None:
            body = result.model_dump(mode="json")
            conn.execute(
                "INSERT INTO eval.signed_measurement_receipts(id,official_record_id,"
                "original_receipt_hash,payload_sha256,payload,created_by,request_id) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s)",
                [
                    uuid5(record_id, "signed-measurement-receipt"),
                    record_id,
                    receipt.receipt_hash,
                    digest(body),
                    Jsonb(body),
                    principal,
                    request_id,
                ],
            )
        return result
