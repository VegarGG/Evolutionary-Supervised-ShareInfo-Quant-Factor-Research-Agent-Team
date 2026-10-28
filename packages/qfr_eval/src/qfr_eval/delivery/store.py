"""An independent worker freezes each checked proposal once, including failures."""

from uuid import UUID, uuid4

from psycopg import Connection
from psycopg.types.json import Jsonb
from qfr_core.contracts.delivery import AdmittedDeliveryContext, DeliveryProposal, DeliveryReceipt
from qfr_core.delivery_rules import admission_hash
from qfr_core.signatures import EvidenceVerifier

from qfr_eval.artifact_store import EvidenceStore
from qfr_eval.delivery.checker import RegistryEvidence, check_delivery
from qfr_eval.delivery.models import PilotDeliveryPolicy
from qfr_eval.scheduler.dedup import digest
from qfr_eval.signing import EvaluatorSigner


class DeliveryConflict(ValueError):
    pass


def persist_delivery(
    conn: Connection,
    context: AdmittedDeliveryContext,
    proposal: DeliveryProposal,
    registry: RegistryEvidence,
    policy: PilotDeliveryPolicy,
    verifier: EvidenceVerifier,
    signer: EvaluatorSigner,
    evidence_store: EvidenceStore,
    *,
    principal: str,
    request_id: UUID,
) -> DeliveryReceipt:
    """Internal evaluator operation, never a Research API/evaluation-control route.

    The caller independently reads admitted context and immutable proposals. A
    retry cannot replace an earlier failure with success: changed evidence must
    be submitted under a new proposal ID and retains the failed receipt.
    """
    if not principal.strip() or conn.execute(
        "SELECT current_user,current_database()"
    ).fetchone() != ("eval_rw", "eval_db"):
        raise PermissionError("independent delivery requires evaluator authority")
    context = AdmittedDeliveryContext.model_validate(context.model_dump())
    proposal = DeliveryProposal.model_validate(proposal.model_dump())
    policy = PilotDeliveryPolicy.model_validate(policy.model_dump())
    identity = dict(
        program=context.job.project_id, job=context.job.job_id, proposal=proposal.proposal_id
    )
    attempt_sha = digest(
        dict(
            identity=identity,
            admission_sha256=context.job.payload_hash,
            observed_admission_sha256=admission_hash(context.input_bundle, context.brief),
            job_config_sha256=context.job.config_hash,
            job_gate_sha256=context.job.exit_gate.spec_hash,
            proposal=proposal.model_dump(mode="json"),
            policy=policy.model_dump(mode="json"),
            human_approval=context.human_approval.model_dump(mode="json")
            if context.human_approval
            else None,
        )
    )
    with conn.transaction():
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ["delivery:" + digest(identity)]
        )
        row = conn.execute(
            "SELECT a.attempt_sha256,a.receipt_sha256,r.payload FROM eval.delivery_attempts a "
            "JOIN eval.delivery_receipts r ON r.id=a.receipt_id "
            "WHERE a.program_id=%s AND a.job_id=%s AND a.proposal_id=%s",
            [identity["program"], identity["job"], identity["proposal"]],
        ).fetchone()
        if row is not None:
            if row[0] != attempt_sha:
                raise DeliveryConflict("delivery proposal identity already has different content")
            result = verifier.delivery(DeliveryReceipt.model_validate(row[2]))
            if digest(row[2]) != row[1] or result.job_id != context.job.job_id:
                raise ValueError("stored delivery receipt binding differs")
            return result
        clock = conn.execute("SELECT clock_timestamp()").fetchone()
        assert clock is not None
        receipt_id = uuid4()
        result = check_delivery(
            conn,
            context,
            proposal,
            registry,
            policy,
            verifier,
            signer,
            evidence_store,
            receipt_id=receipt_id,
            at=clock[0],
        )
        body = result.model_dump(mode="json")
        conn.execute(
            "INSERT INTO eval.delivery_receipts(id,payload,created_by,request_id) "
            "VALUES(%s,%s,%s,%s)",
            [receipt_id, Jsonb(body), principal, request_id],
        )
        conn.execute(
            "INSERT INTO eval.delivery_attempts(id,job_id,program_id,proposal_id,attempt_sha256,"
            "receipt_id,receipt_sha256,payload,created_by,request_id) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            [
                uuid4(),
                identity["job"],
                identity["program"],
                identity["proposal"],
                attempt_sha,
                receipt_id,
                digest(body),
                Jsonb(
                    dict(
                        context=context.model_dump(mode="json"),
                        proposal=proposal.model_dump(mode="json"),
                        policy=policy.model_dump(mode="json"),
                    )
                ),
                principal,
                request_id,
            ],
        )
        return result
