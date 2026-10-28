"""Prepare releases from immutable sources under the publication transaction.

This module cannot publish unsigned content or mutate a Ladder. The signing
worker must keep these locks through signing and atomic publication, or discard
this preparation and start again; a saved preparation is never authoritative.
"""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid5

from psycopg import Connection
from psycopg.pq import TransactionStatus
from qfr_core.contracts.data import SnapshotManifest
from qfr_core.contracts.enums import ReasonCode
from qfr_core.contracts.publication import PublishedArtifact
from qfr_core.contracts.reports import (
    EvidenceIdentity,
    MetricValue,
    ReleasedContent,
    ReleasedScalar,
    StatusRelease,
    WithheldRelease,
)

from qfr_eval.protocols.models import FrozenProtocol
from qfr_eval.records import EvaluationRequest, Measurement, OfficialRecord, RuntimeIdentity
from qfr_eval.release.models import (
    LadderBest,
    PilotReleasePolicy,
    PreparedRelease,
    ReleaseSource,
    StockReleasePolicy,
    StockReleaseRecord,
)
from qfr_eval.release.pilot import project_pilot, scope_hash
from qfr_eval.release.policy import eligible_at
from qfr_eval.release.stock import project_w1, project_w2
from qfr_eval.release.store import active_policy, source_payload
from qfr_eval.scheduler.dedup import digest
from qfr_eval.scheduler.models import IntakeCampaign
from qfr_eval.screening.records import ScreeningRecord


def numeric_values(value: Any) -> int:
    """Count emitted numeric leaves, including counts, never enum bits or IDs."""
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return 1
    if isinstance(value, dict):
        return sum(numeric_values(v) for v in value.values())
    if isinstance(value, list):
        return sum(numeric_values(v) for v in value)
    return 0


def load_best(conn: Connection, scope: str) -> LadderBest | None:
    row = conn.execute(
        "SELECT payload FROM eval.ladder_state WHERE scope_sha256=%s FOR UPDATE", [scope]
    ).fetchone()
    if row is None:
        return None
    best = LadderBest.model_validate(row[0])
    if best.scope_sha256 != scope:
        raise ValueError("Ladder state has a different scope")
    return best


def reservations(conn: Connection, program: str, generation: str, artifact: UUID) -> dict[str, int]:
    rows = conn.execute(
        "SELECT lineage_id,ordinal FROM eval.feedback_reservations WHERE program_id=%s "
        "AND generation_id=%s AND artifact_version_id=%s ORDER BY lineage_id",
        [program, generation, artifact],
    ).fetchall()
    if not rows:
        raise ValueError("measured feedback requires authoritative lineage reservations")
    return dict(rows)


def frozen_family_scores(
    conn: Connection, request: EvaluationRequest, context: dict[str, Any]
) -> list[float | None]:
    """Only the cohort frozen before this measurement; never later trial data."""
    scores = []
    for observation in context["frozen_prior"]:
        row = conn.execute(
            "SELECT o.payload FROM eval.trial_ledger t JOIN eval.official_records o "
            "ON t.official_record_id=o.id WHERE t.id=%s",
            [UUID(observation["trial_id"])],
        ).fetchone()
        if row is None:
            raise ValueError("frozen family cohort has missing immutable evidence")
        payload = row[0]
        prior = EvaluationRequest.model_validate(payload["request"])
        if (
            prior.program_id,
            prior.family_id,
            prior.protocol_hash,
            prior.snapshot_id,
            prior.epoch_id,
            prior.window,
            prior.cycle,
        ) != (
            request.program_id,
            request.family_id,
            request.protocol_hash,
            request.snapshot_id,
            request.epoch_id,
            request.window,
            request.cycle,
        ):
            continue
        if prior.intent == "diagnostic":
            continue
        record = OfficialRecord.model_validate(payload["record"])
        measured = Measurement.model_validate(payload["measurement"])
        if record.request_hash != prior.sha256 or record.results_hash != measured.results_hash:
            raise ValueError("frozen family evidence hash differs")
        metric = measured.metrics.get("extreme_macro_recall")
        scores.append(
            metric.value if measured.status == "complete" and metric is not None else None
        )
    return scores


def _pilot(
    conn: Connection, payload: dict[str, Any], policy: PilotReleasePolicy
) -> tuple[ReleasedContent, dict[str, LadderBest], dict[str, int]]:
    request = EvaluationRequest.model_validate(payload["request"])
    record = OfficialRecord.model_validate(payload["record"])
    measured = Measurement.model_validate(payload["measurement"])
    contexts = conn.execute(
        "SELECT id,payload FROM eval.runs WHERE official_record_id=%s", [UUID(record.record_id)]
    ).fetchall()
    if len(contexts) != 1 or [str(contexts[0][0])] != record.run_ids:
        raise ValueError("pilot release requires its exact frozen run context")
    context = contexts[0][1]
    protocol = FrozenProtocol.model_validate(context["protocol"])
    snapshot = SnapshotManifest.model_validate(context["snapshot"])
    if context["request"] != request.model_dump(mode="json"):
        raise ValueError("run context differs from release request")
    if snapshot.snapshot_id != request.snapshot_id:
        raise ValueError("run context differs from the frozen dataset")
    ordinals = reservations(
        conn, request.program_id, request.generation_id, request.artifact_version_id
    )
    bests = {}
    for lineage in ordinals:
        best = load_best(conn, scope_hash(request, policy, lineage))
        if best is not None:
            bests[lineage] = best
    content, updates = project_pilot(
        record,
        request,
        measured,
        protocol,
        policy,
        ordinals=ordinals,
        bests=bests,
        frozen_family_scores=frozen_family_scores(conn, request, context),
        # Absolute recall is not baseline-adjusted. The frozen protocol pins the
        # paired P1 comparator; do not invent a Registry version for that builtin.
        baseline_version_id=None,
        cost_basis_ref=f"{protocol.protocol_id}@{protocol.version}:primary_cost_bps_10",
        pit_grade_downgrade=any(
            quality.timing_grade != "A"
            or quality.vintage_status != "verified"
            or quality.membership_grade not in (None, "A")
            or quality.membership_status == "unknown"
            for quality in [snapshot.exposure.quality, *(t.quality for t in snapshot.tables)]
        ),
    )
    return content, updates, ordinals


def stock_scope(record: StockReleaseRecord, policy: StockReleasePolicy) -> str:
    return digest(
        dict(
            program=record.program_id,
            family=record.economic_lineage_id,
            protocol=record.identity.protocol_version,
            snapshot=record.identity.dataset_version_id,
            epoch=record.epoch_id,
            window=record.window,
            policy=policy.sha256,
        )
    )


def _stock(
    conn: Connection, record: StockReleaseRecord, policy: StockReleasePolicy
) -> tuple[ReleasedContent, dict[str, LadderBest]]:
    # An actual evaluator producer must reserve capacity before its measurement.
    row = conn.execute(
        "SELECT family_id,policy_sha256,admitted_at FROM eval.quota_usage WHERE program_id=%s "
        "AND epoch_id=%s AND stage=%s AND artifact_version_id=%s",
        [
            record.program_id,
            record.epoch_id,
            record.window.lower(),
            record.identity.artifact_version_id,
        ],
    ).fetchone()
    if (
        row is None
        or row[:2] != (record.economic_lineage_id, policy.sha256)
        or row[2] > record.created_at
    ):
        raise ValueError("stock source has no matching evaluator quota admission")
    if record.status == "withheld":
        return WithheldRelease(type="withheld", reason="budget"), {}
    if record.status == "failed":
        return StatusRelease(type="screening", status="failed"), {}
    if record.window == "W1":
        return project_w1(
            record.metrics,
            window=record.window,
            policy=policy,
            yearly=record.yearly_rank_ic,
            decay=record.decay_profile,
            library_artifact_version_id=record.library_artifact_version_id,
            coverage_bucket=record.coverage_bucket,
            complexity=record.complexity,
        ), {}
    scope = stock_scope(record, policy)
    current = ReleasedScalar(
        metric="RankIC_mean",
        sampling_unit="trading_date",
        period_count=record.period_count,
        cost_basis_ref=record.cost_basis_ref,
        baseline_version_id=record.baseline_version_id,
        measurement=record.metrics.get(
            "rank_ic_mean", MetricValue(value=None, missing_reason="insufficient_data")
        ),
        origin_artifact_version_id=record.identity.artifact_version_id,
        attribution="current_version",
    )
    content, best = project_w2(
        current,
        window="W2",
        policy=policy,
        passed=record.gate_passed,
        scope_sha256=scope,
        prior=load_best(conn, scope),
    )
    return content, {record.economic_lineage_id: best} if best is not None else {}


def prepare_locked(
    conn: Connection,
    queue_id: UUID,
    *,
    control_time: datetime | None = None,
    intake_runtime: RuntimeIdentity | None = None,
) -> PreparedRelease:
    if conn.info.transaction_status != TransactionStatus.INTRANS:
        raise ValueError("release preparation requires its publication transaction")
    # Serialize missing as well as existing Ladder rows. Acquire before queue
    # locks in the worker, so two first releases cannot both win the same scope.
    conn.execute("SELECT pg_advisory_xact_lock(72460406)")
    row = conn.execute(
        "SELECT payload,state,eligible_at FROM eval.release_queue WHERE id=%s FOR UPDATE",
        [queue_id],
    ).fetchone()
    if row is None or row[1] != "pending":
        raise ValueError("release source is not pending")
    now = control_time
    if now is None:
        clock = conn.execute("SELECT clock_timestamp()").fetchone()
        assert clock is not None
        now = clock[0]
    assert now is not None
    if now.utcoffset() is None or now < row[2]:
        raise ValueError("release batch is not due")
    source = ReleaseSource.model_validate(row[0])
    policy = active_policy(conn, source.policy_sha256)
    payload, completed = source_payload(conn, source.source_kind, source.source_id)
    if (
        digest(payload) != source.source_sha256
        or source.completed_at != completed
        or source.eligible_at != row[2]
        or source.eligible_at != eligible_at(policy, source.stage, completed)
    ):
        raise ValueError("release source or batch binding differs")
    updates: dict[str, LadderBest] = {}
    reasons: list[ReasonCode] = []
    flags = []
    lineages: list[str] = []
    if source.source_kind == "intake_transition":
        artifact = PublishedArtifact.model_validate(payload["artifact"])
        campaign = IntakeCampaign.model_validate(payload["campaign"])
        if (
            intake_runtime is None
            or digest(intake_runtime.model_dump(mode="json")) != campaign.runtime_hash
        ):
            raise ValueError("intake release requires its frozen campaign runtime")
        identity = EvidenceIdentity(
            artifact_version_id=artifact.manifest.artifact_version_id,
            content_hash=artifact.manifest.content_hash,
            protocol_version=campaign.protocol_ref,
            dataset_version_id=campaign.snapshot_id,
            evaluator_version=intake_runtime.evaluator_git_sha,
        )
        generation = campaign.server_generation_id
        transition = payload["transition"]
        status = {
            "queued": "queued",
            "duplicate": "failed",
            "rejected": "failed",
            "deferred": "withheld",
        }
        content: ReleasedContent = StatusRelease.model_validate(
            dict(type="intake", status=status[transition["to"]])
        )
        if transition["reason"] in ReasonCode:
            reasons = [ReasonCode(transition["reason"])]
        elif transition["to"] != "queued":
            reasons = [
                ReasonCode.QUOTA_DEFERRED
                if transition["to"] == "deferred"
                else ReasonCode.DECLARATION_MISMATCH
            ]
    elif source.stage == "screening":
        screen = ScreeningRecord.model_validate(payload["record"])
        if (
            not isinstance(policy, PilotReleasePolicy)
            or screen.request.protocol_hash != policy.protocol_sha256
        ):
            raise ValueError("screening source differs from release policy")
        ordinals = reservations(
            conn,
            screen.request.program_id,
            screen.request.generation_id,
            screen.request.artifact_version_id,
        )
        identity, generation = screen.identity, screen.request.generation_id
        lineages = sorted(ordinals)
        if (
            screen.feedback_disposition == "withheld:budget"
            or max(ordinals.values()) > policy.feedback_versions_per_lineage_generation
        ):
            content = WithheldRelease(type="withheld", reason="budget")
        else:
            content = StatusRelease(
                type="screening", status="pass" if screen.outcome.status == "passed" else "failed"
            )
            reasons = screen.outcome.reason_codes
    elif source.stage == "pilot":
        if not isinstance(policy, PilotReleasePolicy):
            raise ValueError("pilot source requires its matching policy")
        request = EvaluationRequest.model_validate(payload["request"])
        record = OfficialRecord.model_validate(payload["record"])
        identity, generation = record.identity, request.generation_id
        content, updates, ordinals = _pilot(conn, payload, policy)
        lineages = sorted(ordinals)
        reasons = record.reason_codes
    elif source.stage in ("w1", "w2"):
        if not isinstance(policy, StockReleasePolicy):
            raise ValueError("stock source requires its matching policy")
        stock = StockReleaseRecord.model_validate(payload["record"])
        identity, generation = stock.identity, stock.generation_id
        content, updates = _stock(conn, stock, policy)
        reasons, flags = stock.reason_codes, stock.flags
        lineages = [stock.economic_lineage_id]
    else:
        raise ValueError("unsupported private source stage")
    if isinstance(content, WithheldRelease):
        # No outcome-dependent codes may bypass a withheld content payload.
        reasons, flags, updates = [], [], {}
    return PreparedRelease(
        schema_version="1",
        visibility="private_unsigned",
        report_id=uuid5(queue_id, "released-report"),
        source_id=source.source_id,
        source_kind=source.source_kind,
        identity=identity,
        family_id=source.family_id,
        program_id=source.program_id,
        epoch_id=source.epoch_id,
        generation_id=generation,
        lineage_ids=lineages,
        release_policy_ref=f"{policy.policy_id}@{policy.version}",
        release_policy_sha256=policy.sha256,
        protocol_card_ref=identity.protocol_version,
        profile=policy.profile,
        content=content,
        reason_codes=reasons,
        flags=flags,
        eligible_at=source.eligible_at,
        numeric_values=numeric_values(content.model_dump(mode="json")),
        ladder_updates=updates,
    )
