"""Atomic evaluator publication: signed report, Ladder and disclosure ledger."""

from uuid import NAMESPACE_URL, UUID, uuid5

from psycopg import Connection
from psycopg.types.json import Jsonb
from qfr_core.contracts.reports import ReleasedReport
from qfr_core.signatures import EvidenceVerifier

from qfr_eval.artifact_store import EvidenceStore
from qfr_eval.receipt_signing import sign_measurement_receipt
from qfr_eval.records import RuntimeIdentity
from qfr_eval.release.cards import publish_policy_cards
from qfr_eval.release.models import PilotReleasePolicy, ReleaseSource
from qfr_eval.release.prepare import prepare_locked
from qfr_eval.release.store import active_policy, locked_ready
from qfr_eval.scheduler.dedup import digest
from qfr_eval.signing import EvaluatorSigner


def publish_one(
    conn: Connection,
    queue_id: UUID,
    signer: EvaluatorSigner,
    verifier: EvidenceVerifier,
    *,
    principal: str,
    request_id: UUID,
    evidence_store: EvidenceStore | None = None,
    intake_runtime: RuntimeIdentity | None = None,
) -> ReleasedReport:
    """No caller-provided clock or prepared payload can bypass the actual batch."""
    if not principal.strip():
        raise ValueError("publication principal required")
    with conn.transaction():
        if conn.execute("SELECT current_user,current_database()").fetchone() != (
            "eval_rw",
            "eval_db",
        ):
            raise ValueError("publication requires the evaluator service role")
        conn.execute("SELECT pg_advisory_xact_lock(72460406)")
        row = conn.execute(
            "SELECT payload,state,published_report_id FROM eval.release_queue "
            "WHERE id=%s FOR UPDATE",
            [queue_id],
        ).fetchone()
        if row is None:
            raise ValueError("unknown release source")
        source = ReleaseSource.model_validate(row[0])
        if row[1] == "published":
            old = conn.execute(
                "SELECT r.payload,p.payload FROM eval.released_reports r "
                "JOIN eval.release_publications p ON p.id=r.id WHERE r.id=%s AND p.queue_id=%s",
                [row[2], queue_id],
            ).fetchone()
            if old is None or old[1].get("report_sha256") != digest(old[0]):
                raise ValueError("published report integrity differs")
            return verifier.report(ReleasedReport.model_validate(old[0]))
        prepared = prepare_locked(conn, queue_id, intake_runtime=intake_runtime)
        policy = active_policy(conn, source.policy_sha256)
        if isinstance(policy, PilotReleasePolicy) and policy.planning_detectability is None:
            raise ValueError("new pilot publication requires planning policy revision 2")
        publish_policy_cards(conn, source.policy_sha256, principal=principal, request_id=request_id)
        if source.stage == "pilot":
            if evidence_store is None:
                raise ValueError("pilot publication requires verified private receipt evidence")
            sign_measurement_receipt(
                conn,
                source.source_id,
                evidence_store,
                signer,
                verifier,
                principal=principal,
                request_id=request_id,
            )
        clock = conn.execute("SELECT clock_timestamp()").fetchone()
        assert clock is not None
        report = signer.seal(
            ReleasedReport,
            "released_report",
            dict(
                schema_version="1",
                report_id=str(prepared.report_id),
                identity=prepared.identity,
                family_id=prepared.family_id,
                program_id=prepared.program_id,
                release_policy_ref=prepared.release_policy_ref,
                protocol_card_ref=prepared.protocol_card_ref,
                profile=prepared.profile,
                content=prepared.content,
                reason_codes=prepared.reason_codes,
                flags=prepared.flags,
                released_at=clock[0],
            ),
        )
        verifier.report(report)
        body = report.model_dump(mode="json")
        identity = report.identity
        conn.execute(
            "INSERT INTO eval.released_reports(id,payload,created_by,request_id,"
            "artifact_version_id,"
            "content_hash,protocol_version,dataset_version_id,evaluator_version) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            [
                prepared.report_id,
                Jsonb(body),
                principal,
                request_id,
                UUID(identity.artifact_version_id),
                identity.content_hash,
                identity.protocol_version,
                identity.dataset_version_id,
                identity.evaluator_version,
            ],
        )
        for best in prepared.ladder_updates.values():
            conn.execute(
                "INSERT INTO eval.ladder_state(id,payload,created_by,request_id,scope_sha256) "
                "VALUES(%s,%s,%s,%s,%s) ON CONFLICT(scope_sha256) DO UPDATE "
                "SET payload=EXCLUDED.payload,created_by=EXCLUDED.created_by,"
                "request_id=EXCLUDED.request_id",
                [
                    uuid5(NAMESPACE_URL, "qfr-ladder:" + best.scope_sha256),
                    Jsonb(best.model_dump(mode="json")),
                    principal,
                    request_id,
                    best.scope_sha256,
                ],
            )
        conn.execute(
            "INSERT INTO eval.release_publications(id,queue_id,payload,created_by,request_id,"
            "numeric_values) VALUES(%s,%s,%s,%s,%s,%s)",
            [
                prepared.report_id,
                queue_id,
                Jsonb(
                    dict(
                        report_sha256=digest(body),
                        policy_sha256=source.policy_sha256,
                        source_sha256=source.source_sha256,
                    )
                ),
                principal,
                request_id,
                prepared.numeric_values,
            ],
        )
        conn.execute(
            "UPDATE eval.release_queue SET state='published',published_report_id=%s,"
            "created_by=%s,request_id=%s WHERE id=%s",
            [prepared.report_id, principal, request_id, queue_id],
        )
        return report


def publish_ready(
    conn: Connection,
    signer: EvaluatorSigner,
    verifier: EvidenceVerifier,
    *,
    limit: int,
    policy_hash: str,
    program_id: str,
    principal: str,
    request_id: UUID,
    evidence_store: EvidenceStore | None = None,
    intake_runtime: RuntimeIdentity | None = None,
) -> list[ReleasedReport]:
    if not program_id.strip() or not principal.strip():
        raise ValueError("publication requires an explicit program and principal")
    with conn.transaction():
        active_policy(conn, policy_hash)
        sources = locked_ready(conn, limit=limit, policy_hash=policy_hash, program_id=program_id)
        return [
            publish_one(
                conn,
                identity,
                signer,
                verifier,
                principal=principal,
                request_id=request_id,
                evidence_store=evidence_store,
                intake_runtime=intake_runtime,
            )
            for identity, _ in sources
        ]
