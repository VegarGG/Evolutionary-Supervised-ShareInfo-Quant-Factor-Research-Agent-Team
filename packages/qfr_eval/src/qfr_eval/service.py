"""Private execution boundary for frozen built-ins and screened Registry artifacts."""

import hashlib
from uuid import UUID

import polars as pl
from psycopg import Connection
from qfr_core.contracts.enums import ReasonCode
from qfr_core.data_layer.snapshots import Snapshot, canonical_json

from qfr_eval.artifact_store import EvidenceStore
from qfr_eval.backtest.fingerprint import pilot_fingerprint
from qfr_eval.cohorts import cohort_scope, read_cohort, read_fingerprints
from qfr_eval.measurement import failed_measurement, measure_pilot
from qfr_eval.persistence import ids_for_request, persist_run, verify_receipt
from qfr_eval.protocols.store import get_active
from qfr_eval.records import EvaluationRequest, MeasurementReceipt, OfficialRecord, TrialLedgerEntry
from qfr_eval.registry_execution import RegistryExecutionFailure, load_registry_execution
from qfr_eval.runtime import builtin_definition, verify_runtime
from qfr_eval.statistics.clustering import cluster_trials


def evaluate(
    conn: Connection,
    request: EvaluationRequest,
    snapshot: Snapshot,
    store: EvidenceStore,
    *,
    principal: str,
    request_id: UUID,
) -> tuple[OfficialRecord, MeasurementReceipt]:
    request = EvaluationRequest.model_validate(request.model_dump(mode="json"))
    verify_runtime(request.runtime)
    protocol = get_active(conn, request.protocol_id, request.protocol_version)
    if request.protocol_hash != protocol.sha256:
        raise ValueError("active protocol hash differs from request")
    if request.variant != "registry":
        artifact, content, _ = builtin_definition(request.variant)
        if request.artifact_version_id != artifact or request.content_hash != content:
            raise ValueError("trusted built-in identity differs from request")
    if (
        snapshot.manifest.snapshot_id != request.snapshot_id
        or snapshot.manifest.zone != "full"
        or snapshot.manifest.profile != protocol.profile
        or snapshot.manifest.as_of < protocol.windows[request.window].end
    ):
        raise ValueError("verified full snapshot does not satisfy the requested window")
    record_id, trial_id, _ = ids_for_request(request_id)
    cohort = cohort_scope(request)
    lock = int.from_bytes(hashlib.sha256(canonical_json(cohort)).digest()[:8], "big", signed=True)
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(%s)", [lock])
        existing = conn.execute(
            "SELECT payload FROM eval.official_records WHERE id=%s", [record_id]
        ).fetchone()
        if existing:
            record = OfficialRecord.model_validate(existing[0]["record"])
            if record.request_hash != request.sha256:
                raise ValueError("request id reused with different inputs")
            receipt = MeasurementReceipt.model_validate(existing[0]["receipt"])
            verify_receipt(receipt, store)
            return record, receipt
        registry = (
            load_registry_execution(conn, request, protocol, store)
            if request.variant == "registry"
            else None
        )
        candidate_history = registry.history if registry else None
        rows = read_cohort(conn, request)
        prior = [TrialLedgerEntry.model_validate(t).observation for t, _ in rows]
        prior_deltas = {
            t.trial_id: r["primary_deltas"] for t, (_, r) in zip(prior, rows, strict=True)
        }
        frozen_fingerprints = read_fingerprints(rows, store)
        fingerprint = None
        measured = failed_measurement(request, str(trial_id), ReasonCode.LOW_COVERAGE)
        clusters = cluster_trials(
            [*prior, measured.summary.observation],
            {**frozen_fingerprints, str(trial_id): None},
            protocol.diagnostics,
        )
        try:
            tables = {table.name: snapshot.read(table.name) for table in snapshot.manifest.tables}
            try:
                fingerprint = pilot_fingerprint(
                    request, protocol, tables, candidate_history=candidate_history
                )
            except RegistryExecutionFailure:
                raise
            except (ValueError, KeyError, pl.exceptions.PolarsError):
                fingerprint = None
            clusters = cluster_trials(
                [*prior, measured.summary.observation],
                {**frozen_fingerprints, str(trial_id): fingerprint},
                protocol.diagnostics,
            )
            measured = measure_pilot(
                request,
                protocol,
                tables,
                trial_id=str(trial_id),
                prior=prior,
                prior_deltas=prior_deltas,
                effective_trials=clusters.effective_trials,
                candidate_history=candidate_history,
            )
        except RegistryExecutionFailure as exc:
            measured = failed_measurement(request, str(trial_id), exc.reason)
        except (ValueError, KeyError, pl.exceptions.PolarsError):
            # A measured data/shape failure is counted. No fallback scores or
            # success state; arbitrary exception text never enters the record.
            measured = failed_measurement(request, str(trial_id), ReasonCode.LOW_COVERAGE)
        return persist_run(
            conn,
            request,
            protocol,
            snapshot.manifest,
            measured,
            prior,
            prior_deltas,
            store,
            principal=principal,
            request_id=request_id,
            fingerprint=fingerprint,
            clusters=clusters,
            frozen_fingerprints=frozen_fingerprints,
            execution_files=registry.evidence_files() if registry else None,
        )
