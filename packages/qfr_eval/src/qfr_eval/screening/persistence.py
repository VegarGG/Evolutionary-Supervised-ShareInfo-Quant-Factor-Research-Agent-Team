"""Atomic all-attempt screening evidence, budget reservation and fenced completion."""

from datetime import UTC
from uuid import UUID, uuid5

from psycopg import Connection
from psycopg.pq import TransactionStatus
from psycopg.types.json import Jsonb
from qfr_core.contracts.artifacts import (
    DocumentImplementation,
    DSLImplementation,
    PackageImplementation,
    PythonImplementation,
)
from qfr_core.contracts.execution import RunnerInput, RunnerOutput
from qfr_core.contracts.publication import PublishedArtifact
from qfr_core.contracts.reports import EvidenceIdentity

from qfr_eval.artifact_store import EvidenceStore
from qfr_eval.db.queue import finish
from qfr_eval.execution_bundle import ArtifactExecutionBundle
from qfr_eval.protocols.store import get_active
from qfr_eval.runtime import verify_runtime
from qfr_eval.scheduler.dedup import digest
from qfr_eval.scheduler.intake import IntakeScheduler, transition
from qfr_eval.scheduler.models import DevelopmentBehavior
from qfr_eval.screening.models import KindAdapterProfile, ScreeningExecutionPolicy
from qfr_eval.screening.records import (
    ScreeningOutcome,
    ScreeningReceipt,
    ScreeningRecord,
    ScreeningRequest,
    ScreeningTrial,
)


def screening_receipt_hash(receipt: ScreeningReceipt) -> str:
    return digest(receipt.model_dump(mode="json", exclude={"receipt_hash"}))


def verify_screening_receipt(receipt: ScreeningReceipt, store: EvidenceStore) -> None:
    if receipt.receipt_hash != screening_receipt_hash(receipt):
        raise ValueError("screening receipt hash differs")
    for item in receipt.files.values():
        store.read(item)


def lock_semantics(conn: Connection, semantic_scope: str) -> None:
    if conn.info.transaction_status != TransactionStatus.INTRANS:
        raise ValueError("screening requires an explicit caller transaction")
    value = int.from_bytes(bytes.fromhex(semantic_scope)[:8], "big", signed=True)
    conn.execute("SELECT pg_advisory_xact_lock(%s)", [value])


def finish_duplicate(
    conn: Connection,
    scheduler: IntakeScheduler,
    *,
    intake_id: UUID,
    duplicate_of: UUID,
    job_id: UUID,
    worker: str,
    fence: int,
    request_id: UUID,
) -> None:
    """Called under the semantic lock, before any non-development computation."""
    if conn.info.transaction_status != TransactionStatus.INTRANS:
        raise ValueError("duplicate completion requires an explicit caller transaction")
    rows = conn.execute(
        "SELECT id,campaign_id,semantic_scope_sha256,state,job_id FROM eval.intake "
        "WHERE id=ANY(%s)",
        [[intake_id, duplicate_of]],
    ).fetchall()
    by_id = {row[0]: row for row in rows}
    if (
        intake_id not in by_id
        or duplicate_of not in by_id
        or by_id[intake_id][1] != scheduler.campaign.campaign_id
        or by_id[intake_id][2] != by_id[duplicate_of][2]
        or by_id[intake_id][3] != "screening"
        or by_id[duplicate_of][3] != "screen_passed"
        or by_id[intake_id][4] != job_id
    ):
        raise ValueError("duplicate completion lacks a compatible passing reference")
    transition(
        conn,
        intake_id,
        "duplicate",
        reason="DUPLICATE_OF",
        principal=worker,
        request_id=request_id,
        duplicate_of=duplicate_of,
    )
    finish(conn, job_id, worker=worker, fence=fence, request_id=request_id)


def persist_screening(
    conn: Connection,
    scheduler: IntakeScheduler,
    request: ScreeningRequest,
    outcome: ScreeningOutcome,
    store: EvidenceStore,
    *,
    execution_policy: ScreeningExecutionPolicy,
    adapter_profile: KindAdapterProfile,
    development_input: RunnerInput,
    probe_input: RunnerInput | None,
    output: RunnerOutput | None,
    behavior: DevelopmentBehavior | None,
    job_id: UUID,
    worker: str,
    fence: int,
    request_id: UUID,
    execution_bundle: ArtifactExecutionBundle | None = None,
) -> tuple[ScreeningRecord, ScreeningReceipt]:
    """Caller holds the semantic lock across dedup and subsequent computation.

    An expired fence rolls back every database write, including the budget slot.
    Content-addressed files can remain unreferenced after rollback; no partial
    official record or feedback is visible. This function never releases feedback.
    """
    if conn.info.transaction_status != TransactionStatus.INTRANS:
        raise ValueError("screening persistence requires the caller's active transaction")
    verify_runtime(request.runtime)
    if request.execution_policy_hash != digest(execution_policy.model_dump(mode="json")):
        raise ValueError("screening execution policy differs from pinned request")
    if (
        request.adapter_profile_hash != digest(adapter_profile.model_dump(mode="json"))
        or request.development_input_sha256 != digest(development_input.model_dump(mode="json"))
        or request.probe_input_sha256
        != (digest(probe_input.model_dump(mode="json")) if probe_input else None)
    ):
        raise ValueError("screening adapter or exact input slices differ from pinned request")
    campaign = scheduler.campaign
    if (
        request.campaign_id != campaign.campaign_id
        or request.protocol_id != campaign.protocol_ref
        or request.protocol_hash != campaign.protocol_hash
        or request.snapshot_id != campaign.snapshot_id
        or request.screening_policy_hash != campaign.screening_policy_hash
        or digest(request.runtime.model_dump(mode="json")) != campaign.runtime_hash
        or request.generation_id != campaign.server_generation_id
    ):
        raise ValueError("screening request differs from the frozen campaign")
    protocol = get_active(conn, request.protocol_id, request.protocol_version)
    if protocol.sha256 != request.protocol_hash:
        raise ValueError("screening requires its active frozen protocol")
    row = conn.execute(
        "SELECT payload,semantic_scope_sha256,job_id FROM eval.intake WHERE id=%s",
        [request.intake_id],
    ).fetchone()
    if row is None or row[2] != job_id:
        raise ValueError("screening intake or durable job differs")
    artifact = PublishedArtifact.model_validate(row[0]["artifact"])
    manifest = artifact.manifest
    implementation = manifest.implementation
    if isinstance(implementation, (PackageImplementation, PythonImplementation)):
        if (
            outcome.execution != "sandbox"
            or request.runner_image_digest
            != implementation.execution_contract.image_digest.removeprefix("sha256:")
        ):
            raise ValueError("screening runner differs from immutable execution contract")
    elif isinstance(implementation, DSLImplementation):
        if outcome.execution != "dsl" or request.runner_image_digest is not None:
            raise ValueError("DSL screening cannot claim a sandbox runner")
    elif isinstance(implementation, DocumentImplementation):
        if outcome.execution != "document" or request.runner_image_digest is not None:
            raise ValueError("document screening cannot claim executable inference")
    else:
        raise ValueError("unsupported screening implementation")
    if (
        request.artifact_version_id != UUID(manifest.artifact_version_id)
        or request.content_hash != manifest.content_hash
        or request.program_id != manifest.provenance.program_id
        or request.family_id != manifest.family_id
        or outcome.kind != manifest.kind
    ):
        raise ValueError("screening identity differs from immutable publication")
    lock_semantics(conn, row[1])
    record_id = uuid5(request.intake_id, "official-screening")
    trial_id = uuid5(record_id, "trial")
    old = conn.execute(
        "SELECT payload FROM eval.official_records WHERE id=%s", [record_id]
    ).fetchone()
    if old is not None:
        record = ScreeningRecord.model_validate(old[0]["record"])
        if record.request_hash != request.sha256 or record.results_hash != outcome.sha256:
            raise ValueError("screening retry differs from immutable completed evidence")
        receipt = ScreeningReceipt.model_validate(old[0]["receipt"])
        verify_screening_receipt(receipt, store)
        return record, receipt
    if (output is None) != (outcome.output_sha256 is None):
        raise ValueError("screening output presence differs from its evidence")
    if output is not None and (
        output.kind != outcome.kind
        or digest(output.model_dump(mode="json")) != outcome.output_sha256
    ):
        raise ValueError("screening output hash differs from measured evidence")
    if behavior is not None and (
        outcome.status != "passed" or behavior.semantic_scope_sha256 != row[1]
    ):
        raise ValueError("behavior evidence requires a passing compatible screen")
    disposition = scheduler.reserve_feedback(conn, request.intake_id, request_id=request_id)
    timestamp_row = conn.execute("SELECT transaction_timestamp()").fetchone()
    assert timestamp_row is not None
    timestamp = timestamp_row[0].astimezone(UTC)
    identity = EvidenceIdentity(
        artifact_version_id=str(request.artifact_version_id),
        content_hash=request.content_hash,
        protocol_version=f"{request.protocol_id}@{request.protocol_version}",
        dataset_version_id=request.snapshot_id,
        evaluator_version=request.runtime.evaluator_git_sha,
    )
    record = ScreeningRecord(
        schema_version="1",
        stage="screening",
        record_id=record_id,
        trial_id=trial_id,
        identity=identity,
        request=request,
        request_hash=request.sha256,
        outcome=outcome,
        results_hash=outcome.sha256,
        feedback_disposition=disposition,
        created_by=worker,
        request_id=request_id,
        created_at=timestamp,
    )
    coverage = outcome.coverage
    trial = ScreeningTrial(
        schema_version="1",
        stage="screening",
        trial_id=trial_id,
        official_record_id=record_id,
        identity=identity,
        program_id=request.program_id,
        family_id=request.family_id,
        generation_id=request.generation_id,
        window="development",
        status="failed"
        if outcome.status != "passed"
        else "withheld"
        if disposition == "withheld:budget"
        else "evaluated",
        sampling_unit="document" if outcome.execution == "document" else "eligible_observation",
        required_observations=coverage.required_observations if coverage else 0,
        complete_observations=coverage.complete_observations if coverage else 0,
        results_hash=outcome.sha256,
        counted_at=timestamp,
    )
    files = {
        "record": store.json(record.model_dump(mode="json")),
        "trial": store.json(trial.model_dump(mode="json")),
        "adapter_profile": store.json(adapter_profile.model_dump(mode="json")),
        "execution_policy": store.json(execution_policy.model_dump(mode="json")),
        "development_input": store.json(development_input.model_dump(mode="json")),
    }
    if execution_bundle is not None:
        if (
            execution_bundle.artifact != artifact
            or outcome.status != "passed"
            or execution_bundle.execution_policy != execution_policy
            or execution_bundle.adapter_profile != adapter_profile
        ):
            raise ValueError("execution bundle differs from successful screening")
        files["execution_bundle"] = store.json(execution_bundle.model_dump(mode="json"))
    if probe_input is not None:
        files["probe_input"] = store.json(probe_input.model_dump(mode="json"))
    if output is not None:
        files["output"] = store.json(output.model_dump(mode="json"))
    if behavior is not None:
        files["behavior"] = store.json(behavior.model_dump(mode="json"))
    receipt = ScreeningReceipt(
        schema_version="1",
        kind="private_screening",
        authenticity="internal_unsigned",
        record_id=record_id,
        trial_id=trial_id,
        identity=identity,
        request_hash=request.sha256,
        results_hash=outcome.sha256,
        files=files,
        receipt_hash="0" * 64,
    )
    receipt = receipt.model_copy(update={"receipt_hash": screening_receipt_hash(receipt)})
    receipt_file = store.json(receipt.model_dump(mode="json"))
    conn.execute(
        "INSERT INTO eval.official_records(id,payload,created_by,request_id,"
        "artifact_version_id,content_hash,protocol_version,dataset_version_id,"
        "evaluator_version,trial_id) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        [
            record_id,
            Jsonb(
                {
                    "record": record.model_dump(mode="json"),
                    "request": request.model_dump(mode="json"),
                    "receipt": receipt.model_dump(mode="json"),
                    "receipt_file": receipt_file.model_dump(mode="json"),
                }
            ),
            worker,
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
        [trial_id, Jsonb(trial.model_dump(mode="json")), worker, request_id, record_id],
    )
    if behavior is not None:
        conn.execute(
            "INSERT INTO eval.intake_behavior(id,intake_id,semantic_scope_sha256,"
            "payload,created_by,request_id) "
            "VALUES(%s,%s,%s,%s,%s,%s)",
            [
                uuid5(record_id, "behavior"),
                request.intake_id,
                row[1],
                Jsonb(files["behavior"].model_dump(mode="json")),
                worker,
                request_id,
            ],
        )
    transition(
        conn,
        request.intake_id,
        "screen_passed" if outcome.status == "passed" else "screen_failed",
        reason="SCREEN_COMPLETE" if outcome.status == "passed" else "SCREEN_FAILED",
        principal=worker,
        request_id=request_id,
    )
    finish(
        conn,
        job_id,
        worker=worker,
        fence=fence,
        request_id=request_id,
        failed=outcome.status != "passed",
    )
    return record, receipt
