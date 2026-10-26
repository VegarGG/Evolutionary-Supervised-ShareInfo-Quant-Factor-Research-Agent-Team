"""Atomic private run/metric/series/record/trial persistence with audited writes."""

import hashlib
from datetime import UTC
from uuid import NAMESPACE_URL, UUID, uuid5

import numpy as np
import psycopg
from psycopg.types.json import Jsonb
from qfr_core.contracts.data import SnapshotManifest
from qfr_core.contracts.reports import EvidenceIdentity
from qfr_core.data_layer.snapshots import canonical_json
from qfr_core.metrics.core import measurement
from qfr_core.metrics.statistics import StatisticsConfig, sharpe_moments

from qfr_eval.artifact_store import EvidenceStore
from qfr_eval.measurement import MeasuredRun
from qfr_eval.protocols.models import FrozenProtocol
from qfr_eval.records import EvaluationRequest, MeasurementReceipt, OfficialRecord, TrialLedgerEntry
from qfr_eval.statistics.clustering import BehavioralFingerprint, ClusterSnapshot
from qfr_eval.statistics.family import TrialObservation


def ids_for_request(request_id: UUID) -> tuple[UUID, UUID, UUID]:
    record = uuid5(NAMESPACE_URL, "qfr-official-request:" + str(request_id))
    return record, uuid5(record, "trial"), uuid5(record, "run")


def receipt_hash(receipt: MeasurementReceipt) -> str:
    return hashlib.sha256(
        canonical_json(receipt.model_dump(mode="json", exclude={"receipt_hash"}))
    ).hexdigest()


def render_record(record: OfficialRecord) -> str:
    rows = [
        "# Private measurement record",
        "",
        f"Record: {record.record_id}",
        f"Status: {record.status}",
        f"Artifact: {record.identity.artifact_version_id}",
        f"Content SHA256: {record.identity.content_hash}",
        f"Protocol: {record.identity.protocol_version}",
        f"Snapshot: {record.identity.dataset_version_id}",
        f"Evaluator: {record.identity.evaluator_version}",
        f"Results SHA256: {record.results_hash}",
        "",
        "Internal measurement only. Not a released report, signed receipt, "
        "delivery decision or promotion.",
        "",
        "| Metric | Value / missing reason |",
        "| --- | --- |",
    ]
    rows.extend(
        f"| {name} | {value.value if value.value is not None else value.missing_reason} |"
        for name, value in sorted(record.metrics.items())
    )
    return "\n".join(rows) + "\n"


def persist_run(
    conn: psycopg.Connection,
    request: EvaluationRequest,
    protocol: FrozenProtocol,
    snapshot: SnapshotManifest,
    measured: MeasuredRun,
    frozen_prior: list[TrialObservation],
    prior_deltas: dict[str, list[float | None]],
    store: EvidenceStore,
    *,
    principal: str,
    request_id: UUID,
    fingerprint: BehavioralFingerprint | None = None,
    clusters: ClusterSnapshot | None = None,
    frozen_fingerprints: dict[str, BehavioralFingerprint | None] | None = None,
) -> tuple[OfficialRecord, MeasurementReceipt]:
    record_id, trial_id, run_id = ids_for_request(request_id)
    summary = measured.summary
    if not principal or summary.observation.trial_id != str(trial_id):
        raise ValueError("record principal or trial identity differs")
    if request.snapshot_id != snapshot.snapshot_id or request.protocol_hash != protocol.sha256:
        raise ValueError("record inputs do not match pinned identities")
    if fingerprint is not None and (
        fingerprint.artifact_version_id != str(request.artifact_version_id)
        or fingerprint.content_hash != request.content_hash
        or fingerprint.protocol_hash != request.protocol_hash
        or fingerprint.snapshot_id != request.snapshot_id
        or fingerprint.epoch_id != request.epoch_id
    ):
        raise ValueError("fingerprint identity differs from its record")
    identity = EvidenceIdentity(
        artifact_version_id=str(request.artifact_version_id),
        content_hash=request.content_hash,
        protocol_version=f"{protocol.protocol_id}@{protocol.version}",
        dataset_version_id=request.snapshot_id,
        evaluator_version=request.runtime.evaluator_git_sha,
    )
    with conn.transaction():
        row = conn.execute("SELECT transaction_timestamp()").fetchone()
        assert row is not None
        timestamp = row[0].astimezone(UTC)
        existing = conn.execute(
            "SELECT payload FROM eval.official_records WHERE id=%s", [record_id]
        ).fetchone()
        if existing is not None:
            old = OfficialRecord.model_validate(existing[0]["record"])
            if old.request_hash != request.sha256 or old.results_hash != summary.results_hash:
                raise ValueError("request id reused with different inputs or results")
            receipt = MeasurementReceipt.model_validate(existing[0]["receipt"])
            verify_receipt(receipt, store)
            return old, receipt
        files = {
            name: store.table(frame, grain) for name, (frame, grain) in measured.tables.items()
        }
        if fingerprint is not None:
            files["fingerprint"] = store.json(fingerprint.model_dump(mode="json"))
        if clusters is not None:
            if clusters.trial_ids != sorted([str(trial_id), *(t.trial_id for t in frozen_prior)]):
                raise ValueError("cluster snapshot does not cover the frozen trial cohort")
            evidence_fingerprints = {**(frozen_fingerprints or {}), str(trial_id): fingerprint}
            if clusters.fingerprint_hashes != {
                identity: value.sha256 if value else None
                for identity, value in evidence_fingerprints.items()
            }:
                raise ValueError("cluster snapshot does not pin its fingerprint evidence")
            if summary.family_statistics is not None and (
                summary.family_statistics.effective_trials != clusters.effective_trials
            ):
                raise ValueError("record effective count differs from its cluster evidence")
            files["clusters"] = store.json(clusters.model_dump(mode="json"))
        record = OfficialRecord(
            schema_version="1",
            record_id=str(record_id),
            identity=identity,
            epoch_id=request.epoch_id,
            window=request.window,
            stage="measurement",
            run_ids=[str(run_id)],
            image_digest=request.runtime.image_digest,
            protocol_hash=protocol.sha256,
            request_hash=request.sha256,
            sampling_unit="mature_matched_decision",
            cycle=request.cycle,
            seed=protocol.bootstrap.seed,
            status="failed"
            if summary.status == "failed"
            else "withheld"
            if request.intent == "withheld"
            else "complete",
            metrics=summary.metrics,
            series_refs=[files[n].relative_path for n in sorted(measured.tables)],
            results_hash=summary.results_hash,
            reason_codes=summary.reason_codes,
            created_by=principal,
            request_id=str(request_id),
            created_at=timestamp,
        )
        config = StatisticsConfig(
            revision=1,
            min_observations=protocol.bootstrap.minimum_periods,
            min_pbo_candidates=protocol.diagnostics.minimum_pbo_candidates,
            pbo_blocks=protocol.diagnostics.pbo_blocks,
            zero_epsilon=protocol.metrics.zero_epsilon,
        )
        moments = sharpe_moments(np.asarray(summary.observation.returns, dtype=float), config)
        trial = TrialLedgerEntry(
            schema_version="1",
            trial_id=str(trial_id),
            official_record_id=str(record_id),
            identity=identity,
            window=request.window,
            epoch_id=request.epoch_id,
            family_id=request.family_id,
            program_id=request.program_id,
            status=summary.observation.status,
            selectable=summary.observation.selectable,
            sampling_unit="mature_matched_decision",
            sharpe_per_period=measurement(moments.sharpe if moments else None),
            n_obs=summary.period_count,
            skew=measurement(moments.skewness if moments else None),
            kurt_raw=measurement(moments.pearson_kurtosis if moments else None),
            fingerprint_ref=files["fingerprint"].relative_path if fingerprint else None,
            observation=summary.observation,
            counted_at=timestamp,
        )
        context = dict(
            request=request.model_dump(mode="json"),
            protocol=protocol.model_dump(mode="json"),
            snapshot=snapshot.model_dump(mode="json"),
            frozen_prior=[t.model_dump(mode="json") for t in frozen_prior],
            prior_deltas=prior_deltas,
            effective_trials=summary.family_statistics.effective_trials
            if summary.family_statistics
            else None,
            clusters=clusters.model_dump(mode="json") if clusters else None,
            frozen_fingerprints={
                key: value.model_dump(mode="json") if value else None
                for key, value in (frozen_fingerprints or {}).items()
            },
        )
        files["context"] = store.json(context)
        files["measurement"] = store.json(summary.model_dump(mode="json"))
        files["record"] = store.json(record.model_dump(mode="json"))
        files["markdown"] = store.put(render_record(record).encode(), suffix="md")
        receipt = MeasurementReceipt(
            schema_version="1",
            kind="private_measurement",
            authenticity="internal_unsigned",
            record_id=str(record_id),
            trial_id=str(trial_id),
            identity=identity,
            protocol_hash=protocol.sha256,
            dataset_manifest_hash=hashlib.sha256(
                canonical_json(snapshot.model_dump(mode="json"))
            ).hexdigest(),
            implementation_sha256=request.runtime.implementation_sha256,
            image_digest=request.runtime.image_digest,
            request_hash=request.sha256,
            results_hash=summary.results_hash,
            files=files,
            receipt_hash="0" * 64,
        )
        receipt = receipt.model_copy(update={"receipt_hash": receipt_hash(receipt)})
        receipt_file = store.json(receipt.model_dump(mode="json"))
        for name, cluster_evidence in [("fingerprints", fingerprint), ("trial_clusters", clusters)]:
            if cluster_evidence is not None:
                conn.execute(
                    "INSERT INTO eval." + name + "(id,payload,created_by,request_id) "
                    "VALUES(%s,%s,%s,%s)",
                    [
                        uuid5(run_id, name),
                        Jsonb(
                            {
                                "official_record_id": str(record_id),
                                "request": request.model_dump(mode="json"),
                                "evidence": cluster_evidence.model_dump(mode="json"),
                            }
                        ),
                        principal,
                        request_id,
                    ],
                )
        conn.execute(
            "INSERT INTO eval.runs(id,payload,created_by,request_id,official_record_id) "
            "VALUES(%s,%s,%s,%s,%s)",
            [run_id, Jsonb(context), principal, request_id, record_id],
        )
        for name, value in summary.metrics.items():
            conn.execute(
                "INSERT INTO eval.metrics(id,payload,created_by,request_id,run_id) "
                "VALUES(%s,%s,%s,%s,%s)",
                [
                    uuid5(run_id, "metric:" + name),
                    Jsonb({"name": name, "measurement": value.model_dump(mode="json")}),
                    principal,
                    request_id,
                    run_id,
                ],
            )
        for name, (_, grain) in measured.tables.items():
            conn.execute(
                "INSERT INTO eval.series_files(id,payload,created_by,request_id,run_id) "
                "VALUES(%s,%s,%s,%s,%s)",
                [
                    uuid5(run_id, "series:" + name),
                    Jsonb(
                        {"name": name, "file": files[name].model_dump(mode="json"), "grain": grain}
                    ),
                    principal,
                    request_id,
                    run_id,
                ],
            )
        payload = dict(
            record=record.model_dump(mode="json"),
            request=request.model_dump(mode="json"),
            measurement=summary.model_dump(mode="json"),
            receipt=receipt.model_dump(mode="json"),
            receipt_file=receipt_file.model_dump(mode="json"),
            primary_deltas=measured.primary_deltas,
        )
        conn.execute(
            "INSERT INTO eval.official_records(id,payload,created_by,request_id,"
            "artifact_version_id,content_hash,protocol_version,dataset_version_id,"
            "evaluator_version,trial_id) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            [
                record_id,
                Jsonb(payload),
                principal,
                request_id,
                request.artifact_version_id,
                request.content_hash,
                identity.protocol_version,
                request.snapshot_id,
                request.runtime.evaluator_git_sha,
                trial_id,
            ],
        )
        conn.execute(
            "INSERT INTO eval.trial_ledger(id,payload,created_by,request_id,official_record_id) "
            "VALUES(%s,%s,%s,%s,%s)",
            [trial_id, Jsonb(trial.model_dump(mode="json")), principal, request_id, record_id],
        )
    return record, receipt


def verify_receipt(receipt: MeasurementReceipt, store: EvidenceStore) -> None:
    if receipt.receipt_hash != receipt_hash(receipt):
        raise ValueError("measurement receipt hash mismatch")
    for item in receipt.files.values():
        store.read(item)
