"""On-demand evaluator-owner trial clustering, with immutable audited snapshots."""

from uuid import NAMESPACE_URL, UUID, uuid5

from psycopg import Connection
from psycopg.types.json import Jsonb

from qfr_eval.artifact_store import EvidenceStore
from qfr_eval.cohorts import cohort_scope, read_cohort, read_fingerprints
from qfr_eval.protocols.store import get_active
from qfr_eval.records import EvaluationRequest, TrialLedgerEntry
from qfr_eval.statistics.clustering import ClusterSnapshot, cluster_trials


def cluster_job(
    conn: Connection,
    request: EvaluationRequest,
    store: EvidenceStore,
    *,
    principal: str,
    request_id: UUID,
) -> ClusterSnapshot:
    if not principal:
        raise ValueError("cluster job requires an audit principal")
    protocol = get_active(conn, request.protocol_id, request.protocol_version)
    if protocol.sha256 != request.protocol_hash:
        raise ValueError("cluster protocol identity differs")
    identity = uuid5(NAMESPACE_URL, "qfr-cluster-job:" + str(request_id))
    with conn.transaction():
        # One SQL statement supplies the immutable high-water cohort. Later
        # arrivals enter a later job; they cannot revise this snapshot.
        previous = conn.execute(
            "SELECT payload FROM eval.trial_clusters WHERE id=%s", [identity]
        ).fetchone()
        if previous:
            if previous[0]["cohort"] != cohort_scope(request):
                raise ValueError("cluster job request id reused for another cohort")
            return ClusterSnapshot.model_validate(previous[0]["evidence"])
        rows = read_cohort(conn, request)
        trials = [TrialLedgerEntry.model_validate(t).observation for t, _ in rows]
        result = cluster_trials(trials, read_fingerprints(rows, store), protocol.diagnostics)
        conn.execute(
            "INSERT INTO eval.trial_clusters(id,payload,created_by,request_id) VALUES(%s,%s,%s,%s)",
            [
                identity,
                Jsonb(
                    {
                        "cohort": cohort_scope(request),
                        "evidence": result.model_dump(mode="json"),
                        "source_record_ids": [t["official_record_id"] for t, _ in rows],
                    }
                ),
                principal,
                request_id,
            ],
        )
    return result
