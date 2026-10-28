"""Private policy freeze and durable source scheduling. No unsigned publication."""

from datetime import datetime
from typing import Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from psycopg import Connection
from psycopg.pq import TransactionStatus
from psycopg.types.json import Jsonb
from pydantic import TypeAdapter
from qfr_core.contracts.publication import PublishedArtifact

from qfr_eval.protocols.models import FrozenProtocol
from qfr_eval.records import EvaluationRequest, Measurement, OfficialRecord
from qfr_eval.release.models import (
    PilotReleasePolicy,
    ReleasePolicy,
    ReleaseSource,
    StockReleasePolicy,
    StockReleaseRecord,
)
from qfr_eval.release.policy import eligible_at
from qfr_eval.scheduler.dedup import digest
from qfr_eval.scheduler.models import IntakeCampaign
from qfr_eval.screening.records import ScreeningRecord

POLICY = TypeAdapter(ReleasePolicy)


def create_policy(
    conn: Connection,
    policy: PilotReleasePolicy | StockReleasePolicy,
    *,
    principal: str,
    request_id: UUID,
) -> str:
    if not principal.strip():
        raise ValueError("policy author required")
    policy = POLICY.validate_python(policy.model_dump())
    with conn.transaction():
        row = conn.execute(
            "INSERT INTO eval.release_policies(id,payload,created_by,request_id,"
            "policy_id,version,sha256,status) VALUES(%s,%s,%s,%s,%s,%s,%s,'draft') "
            "ON CONFLICT(policy_id,version) DO NOTHING RETURNING sha256",
            [
                uuid4(),
                Jsonb(policy.model_dump(mode="json")),
                principal,
                request_id,
                policy.policy_id,
                policy.version,
                policy.sha256,
            ],
        ).fetchone()
        if row is None:
            row = conn.execute(
                "SELECT sha256 FROM eval.release_policies WHERE policy_id=%s AND version=%s",
                [policy.policy_id, policy.version],
            ).fetchone()
            if row is None or row[0] != policy.sha256:
                raise ValueError("release policy revision already has different content")
    return policy.sha256


def active_policy(conn: Connection, sha256: str) -> PilotReleasePolicy | StockReleasePolicy:
    row = conn.execute(
        "SELECT payload FROM eval.release_policies WHERE sha256=%s AND status='active'", [sha256]
    ).fetchone()
    if row is None:
        raise ValueError("release policy is not active")
    policy = POLICY.validate_python(row[0])
    if policy.sha256 != sha256:
        raise ValueError("release policy content hash differs")
    return policy


def activate_policy(conn: Connection, sha256: str, *, principal: str, request_id: UUID) -> str:
    if not principal.strip():
        raise ValueError("policy owner required")
    with conn.transaction():
        row = conn.execute(
            "SELECT id,payload,status FROM eval.release_policies WHERE sha256=%s FOR UPDATE",
            [sha256],
        ).fetchone()
        if row is None:
            raise ValueError("unknown release policy hash")
        policy = POLICY.validate_python(row[1])
        if policy.sha256 != sha256:
            raise ValueError("release policy content hash differs")
        if isinstance(policy, PilotReleasePolicy):
            protocol_row = conn.execute(
                "SELECT payload FROM eval.protocols WHERE sha256=%s AND status='active'",
                [policy.protocol_sha256],
            ).fetchone()
            if protocol_row is None:
                raise ValueError("pilot policy requires its active frozen protocol")
            protocol = FrozenProtocol.model_validate(protocol_row[0])
            intent = protocol.release_intent
            if (
                intent is None
                or protocol.sha256 != policy.protocol_sha256
                or policy.ladder_step != intent.ladder_step
                or policy.feedback_versions_per_lineage_generation
                != intent.feedback_versions_per_lineage_generation
                or policy.confirmation_queries_per_protocol
                != intent.confirmation_queries_per_protocol
            ):
                raise ValueError("release policy differs from approved pilot intent")
        if row[2] == "active":
            return sha256
        if row[2] != "draft":
            raise ValueError("release policy cannot be activated")
        conn.execute(
            "UPDATE eval.release_policies SET status='active',created_by=%s,request_id=%s "
            "WHERE id=%s",
            [principal, request_id, row[0]],
        )
    return sha256


def source_payload(
    conn: Connection, kind: Literal["official_record", "intake_transition"], identity: UUID
) -> tuple[dict[str, Any], datetime]:
    if kind == "official_record":
        row = conn.execute(
            "SELECT payload,created_at,artifact_version_id,content_hash,protocol_version,"
            "dataset_version_id,evaluator_version FROM eval.official_records WHERE id=%s",
            [identity],
        ).fetchone()
        if row is None:
            raise ValueError("unknown official record")
        body = row[0].get("record", {})
        fields = (
            "artifact_version_id",
            "content_hash",
            "protocol_version",
            "dataset_version_id",
            "evaluator_version",
        )
        if str(body.get("record_id")) != str(identity) or tuple(
            str(body.get("identity", {}).get(key)) for key in fields
        ) != tuple(str(value) for value in row[2:]):
            raise ValueError("official record header differs from its database identity")
        return row[0], row[1]
    if kind != "intake_transition":
        raise ValueError("unsupported release source")
    row = conn.execute(
        "SELECT t.payload,t.created_at,i.payload,c.payload FROM eval.intake_transitions t "
        "JOIN eval.intake i ON i.id=t.intake_id JOIN eval.intake_campaigns c ON c.id=i.campaign_id "
        "WHERE t.id=%s",
        [identity],
    ).fetchone()
    if row is None:
        raise ValueError("unknown intake transition")
    # Intake state is mutable; only its frozen publication and campaign plus an
    # append-only transition can be a durable release source.
    return {"transition": row[0], "artifact": row[2]["artifact"], "campaign": row[3]}, row[1]


def enqueue_source(
    conn: Connection,
    kind: Literal["official_record", "intake_transition"],
    identity: UUID,
    policy_hash: str,
    *,
    principal: str,
    request_id: UUID,
) -> UUID:
    if not principal.strip():
        raise ValueError("release worker principal required")
    with conn.transaction():
        policy = active_policy(conn, policy_hash)
        payload, at = source_payload(conn, kind, identity)
        if kind == "intake_transition":
            artifact = PublishedArtifact.model_validate(payload["artifact"])
            campaign = IntakeCampaign.model_validate(payload["campaign"])
            if (
                isinstance(policy, PilotReleasePolicy)
                and campaign.protocol_hash != policy.protocol_sha256
            ):
                raise ValueError("intake protocol differs from release policy")
            if payload["transition"]["to"] not in {"queued", "duplicate", "rejected", "deferred"}:
                raise ValueError("internal progress is not an intake release decision")
            program, family = artifact.manifest.provenance.program_id, artifact.manifest.family_id
            epoch, stage = campaign.protocol_ref, "intake"
        else:
            stage = payload["record"].get("stage")
            if stage == "screening":
                screening = ScreeningRecord.model_validate(payload["record"])
                if (
                    not isinstance(policy, PilotReleasePolicy)
                    or screening.request.protocol_hash != policy.protocol_sha256
                ):
                    raise ValueError("screening protocol differs from release policy")
                program, family = screening.request.program_id, screening.request.family_id
                epoch = screening.identity.protocol_version
            elif stage == "measurement":
                if not isinstance(policy, PilotReleasePolicy):
                    raise ValueError("pilot record requires pilot release policy")
                record = OfficialRecord.model_validate(payload["record"])
                request = EvaluationRequest.model_validate(payload["request"])
                measured = Measurement.model_validate(payload["measurement"])
                if (
                    record.request_hash != request.sha256
                    or record.results_hash != measured.results_hash
                    or record.protocol_hash != policy.protocol_sha256
                    or request.protocol_hash != policy.protocol_sha256
                    or request.window != policy.release_window
                    or request.cycle != policy.release_cycle
                ):
                    raise ValueError("official record is not the pinned weekly validation evidence")
                program, family, epoch, stage = (
                    request.program_id,
                    request.family_id,
                    request.epoch_id,
                    "pilot",
                )
            elif stage == "stock_measurement":
                if not isinstance(policy, StockReleasePolicy):
                    raise ValueError("stock record requires stock release policy")
                stock = StockReleaseRecord.model_validate(payload["record"])
                if stock.record_id != identity:
                    raise ValueError("stock source identity mismatch")
                program, family, epoch, stage = (
                    stock.program_id,
                    stock.family_id,
                    stock.epoch_id,
                    stock.window.lower(),
                )
            else:
                raise ValueError("no projection for this official record stage")
        source = ReleaseSource.model_validate(
            dict(
                schema_version="1",
                source_kind=kind,
                source_id=identity,
                source_sha256=digest(payload),
                policy_sha256=policy_hash,
                program_id=program,
                family_id=family,
                epoch_id=epoch,
                stage=stage,
                completed_at=at,
                eligible_at=eligible_at(policy, stage, at),
            )
        )
        queue_id = uuid5(
            NAMESPACE_URL, "qfr-release:" + kind + ":" + str(identity) + ":" + policy_hash
        )
        row = conn.execute(
            "INSERT INTO eval.release_queue(id,payload,created_by,request_id,source_kind,source_id,"
            "official_record_id,intake_transition_id,source_sha256,policy_sha256,program_id,family_id,"
            "epoch_id,eligible_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT(source_kind,source_id,policy_sha256) DO NOTHING RETURNING id",
            [
                queue_id,
                Jsonb(source.model_dump(mode="json")),
                principal,
                request_id,
                kind,
                identity,
                identity if kind == "official_record" else None,
                identity if kind == "intake_transition" else None,
                source.source_sha256,
                policy_hash,
                program,
                family,
                epoch,
                source.eligible_at,
            ],
        ).fetchone()
        if row is None:
            previous = conn.execute(
                "SELECT payload FROM eval.release_queue WHERE id=%s", [queue_id]
            ).fetchone()
            if previous is None or ReleaseSource.model_validate(previous[0]) != source:
                raise ValueError("release source changed after scheduling")
        return queue_id


def locked_ready(
    conn: Connection, *, limit: int, control_time: datetime | None = None
) -> list[tuple[UUID, ReleaseSource]]:
    """Within the publication transaction only; never visible through feedback."""
    if conn.info.transaction_status != TransactionStatus.INTRANS or not 1 <= limit <= 100:
        raise ValueError("bounded release batch requires an active transaction")
    if control_time is not None and control_time.utcoffset() is None:
        raise ValueError("aware control time required")
    # Same order as prepare_locked: missing Ladder scopes need serialization too.
    conn.execute("SELECT pg_advisory_xact_lock(72460406)")
    if control_time is None:
        row = conn.execute("SELECT clock_timestamp()").fetchone()
        assert row is not None
        control_time = row[0]
    rows = conn.execute(
        "SELECT id,payload FROM eval.release_queue WHERE state='pending' AND eligible_at<=%s "
        "ORDER BY eligible_at,id FOR UPDATE SKIP LOCKED LIMIT %s",
        [control_time, limit],
    ).fetchall()
    return [(UUID(str(row[0])), ReleaseSource.model_validate(row[1])) for row in rows]
