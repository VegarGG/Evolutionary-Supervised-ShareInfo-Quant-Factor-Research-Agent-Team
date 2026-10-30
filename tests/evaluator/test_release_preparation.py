"""Synthetic immutable sources and real PostgreSQL; not financial acceptance."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from psycopg.types.json import Jsonb
from qfr_core.contracts.reports import WithheldRelease
from qfr_eval.protocols.store import activate_protocol, create_protocol
from qfr_eval.release.burn import summarize
from qfr_eval.release.models import PilotReleasePolicy
from qfr_eval.release.prepare import numeric_values, prepare_locked
from qfr_eval.release.store import activate_policy, create_policy, enqueue_source
from test_release_database import allocate, stock_policy, store_stock_record, subject
from test_release_projection import evidence

pytestmark = pytest.mark.database
ROOT = Path(__file__).resolve().parents[2]


def queue(conn, record, policy):
    key = enqueue_source(
        conn,
        "official_record",
        UUID(str(record.record_id)),
        policy.sha256,
        principal="synthetic-release-worker",
        request_id=uuid4(),
    )
    ready = conn.execute(
        "SELECT eligible_at FROM eval.release_queue WHERE id=%s", [key]
    ).fetchone()[0]
    return key, ready


def pilot_policy(conn, *, version=1):
    path = ROOT / "configs/evaluation/pilot_p0_p1_verification_v1.yaml"
    policy = PilotReleasePolicy.model_validate_json(
        (ROOT / f"configs/evaluation/release_pilot_v{version}.json").read_bytes()
    )
    sha = create_protocol(conn, path, principal="synthetic-owner", request_id=uuid4())
    from qfr_core.configuration import load_yaml
    from qfr_eval.protocols.models import FrozenProtocol

    protocol = load_yaml(path, FrozenProtocol)
    activate_protocol(
        conn,
        protocol.protocol_id,
        protocol.version,
        expected_hash=sha,
        principal="synthetic-owner",
        request_id=uuid4(),
    )
    create_policy(conn, policy, principal="synthetic-owner", request_id=uuid4())
    activate_policy(conn, policy.sha256, principal="synthetic-owner", request_id=uuid4())
    return policy


def store_pilot(
    conn,
    *,
    ordinal=1,
    score=0.5,
    failed=False,
    completed_at=None,
    evidence_store=None,
    source_case=None,
):
    # Explicit synthetic source clock; not actual elapsed-batch acceptance.
    completed_at = completed_at or datetime.now(UTC)
    record, request, measured, protocol = source_case or evidence(score)
    if source_case is None:
        request = request.model_copy(
            update={
                "program_id": str(uuid4()),
                "family_id": str(uuid4()),
                "generation_id": str(uuid4()),
                "epoch_id": str(uuid4()),
            }
        )
    if failed:
        measured = measured.model_copy(update={"status": "failed"})
    run, trial = uuid4(), uuid4()
    record = record.model_copy(
        update={
            "run_ids": [str(run)],
            "epoch_id": request.epoch_id,
            "request_hash": request.sha256,
            "results_hash": measured.results_hash,
            "status": "failed" if failed else "complete",
        }
    )
    snapshot = json.loads((ROOT / "contracts/examples/SnapshotManifest.valid.json").read_bytes())
    snapshot["snapshot_id"] = request.snapshot_id
    context = dict(
        request=request.model_dump(mode="json"),
        protocol=protocol.model_dump(mode="json"),
        snapshot=snapshot,
        frozen_prior=[],
    )
    body = dict(
        record=record.model_dump(mode="json"),
        request=request.model_dump(mode="json"),
        measurement=measured.model_dump(mode="json"),
    )
    if evidence_store is not None:
        from qfr_eval.persistence import receipt_hash
        from qfr_eval.records import MeasurementReceipt
        from qfr_eval.scheduler.dedup import digest

        sample = json.loads(
            (
                ROOT / "packages/qfr_eval/src/qfr_eval/private_contracts/"
                "MeasurementReceipt.valid.json"
            ).read_bytes()
        )
        sample.update(
            record_id=record.record_id,
            trial_id=str(trial),
            identity=record.identity.model_dump(),
            protocol_hash=protocol.sha256,
            request_hash=request.sha256,
            results_hash=record.results_hash,
            dataset_manifest_hash=digest(snapshot),
            image_digest=request.runtime.image_digest,
            implementation_sha256=request.runtime.implementation_sha256,
            files={
                "record": evidence_store.json(record.model_dump(mode="json")),
                "measurement": evidence_store.json(measured.model_dump(mode="json")),
                "context": evidence_store.json(context),
            },
        )
        receipt = MeasurementReceipt.model_validate(sample)
        body["receipt"] = receipt.model_copy(
            update={"receipt_hash": receipt_hash(receipt)}
        ).model_dump(mode="json")
    identity = record.identity
    with conn.transaction():
        conn.execute(
            "INSERT INTO eval.runs(id,payload,created_by,request_id,official_record_id) "
            "VALUES(%s,%s,'synthetic-fixture',%s,%s)",
            [run, Jsonb(context), uuid4(), UUID(record.record_id)],
        )
        conn.execute(
            "INSERT INTO eval.official_records(id,payload,created_by,request_id,"
            "artifact_version_id,content_hash,protocol_version,dataset_version_id,"
            "evaluator_version,trial_id,created_at) "
            "VALUES(%s,%s,'synthetic-fixture',%s,%s,%s,%s,%s,%s,%s,%s)",
            [
                UUID(record.record_id),
                Jsonb(body),
                uuid4(),
                request.artifact_version_id,
                identity.content_hash,
                identity.protocol_version,
                identity.dataset_version_id,
                identity.evaluator_version,
                trial,
                completed_at,
            ],
        )
        conn.execute(
            "INSERT INTO eval.trial_ledger(id,payload,created_by,request_id,official_record_id) "
            "VALUES(%s,%s,'synthetic-fixture',%s,%s)",
            [
                trial,
                Jsonb({"fixture": "synthetic_release_source"}),
                uuid4(),
                UUID(record.record_id),
            ],
        )
        conn.execute(
            "INSERT INTO eval.feedback_reservations(id,payload,program_id,lineage_id,generation_id,"
            "artifact_version_id,ordinal,created_by,request_id) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,'synthetic-fixture',%s)",
            [
                uuid4(),
                Jsonb({"fixture": "synthetic_source"}),
                request.program_id,
                request.economic_lineage_id,
                request.generation_id,
                request.artifact_version_id,
                ordinal,
                uuid4(),
            ],
        )
    return record, request


def test_pilot_preparation_is_due_only_and_cannot_publish_or_advance_ladder(eval_connect):
    with eval_connect() as conn:
        policy = pilot_policy(conn)
        record, request = store_pilot(conn)
        key, at = queue(conn, record, policy)
        with pytest.raises(ValueError, match="publication transaction"):
            prepare_locked(conn, key, control_time=at)
        with pytest.raises(ValueError, match="not due"), conn.transaction():
            prepare_locked(conn, key, control_time=at - timedelta(microseconds=1))
        with conn.transaction():
            prepared = prepare_locked(conn, key, control_time=at)
            assert prepared.visibility == "private_unsigned"
            assert prepared.content.scalar.measurement.value == 0.4945561368140035
            assert prepared.content.scalar.baseline_version_id is None
            assert prepared.content.scalar.cost_basis_ref.endswith(":primary_cost_bps_10")
            assert prepared.content.hurdle_flags.overall == "fail"
            assert prepared.numeric_values == 2  # single primary plus period count
            assert prepared.lineage_ids == [request.economic_lineage_id]
            assert prepared.ladder_updates
        assert conn.execute(
            "SELECT count(*) FROM eval.released_reports WHERE id=%s", [prepared.report_id]
        ).fetchone() == (0,)
        for update in prepared.ladder_updates.values():
            assert conn.execute(
                "SELECT count(*) FROM eval.ladder_state WHERE scope_sha256=%s",
                [update.scope_sha256],
            ).fetchone() == (0,)
    with eval_connect() as restarted, restarted.transaction():
        assert prepare_locked(restarted, key, control_time=at) == prepared


@pytest.mark.parametrize("score,failed", [(0.1, False), (0.9, False), (None, True)])
def test_excess_attempts_stay_counted_but_preparation_reveals_no_outcome(
    eval_connect, score, failed
):
    with eval_connect() as conn:
        policy = pilot_policy(conn)
        record, request = store_pilot(conn, ordinal=4, score=score, failed=failed)
        key, at = queue(conn, record, policy)
        with conn.transaction():
            result = prepare_locked(conn, key, control_time=at)
        assert result.content == WithheldRelease(type="withheld", reason="budget")
        assert not result.reason_codes and not result.flags and not result.ladder_updates
        assert result.numeric_values == 0
        burn = summarize(conn, policy.sha256, request.epoch_id, "validation")
        assert burn.trials == 1 and burn.queries_used == 1 and burn.released_values == 0
        assert burn.query_budget is None and burn.status == "unthresholded"


def test_missing_lineage_evidence_is_not_invented_for_builtin_records(eval_connect):
    with eval_connect() as conn:
        policy = pilot_policy(conn)
        record, request = store_pilot(conn)
        key, at = queue(conn, record, policy)
        # Independent scenario: the fixture's reservation exists, but prepare
        # must not accept a different generation merely because a name matches.
        from qfr_eval.release.prepare import reservations

        with pytest.raises(ValueError, match="authoritative lineage reservations"):
            reservations(conn, request.program_id, str(uuid4()), request.artifact_version_id)
        with pytest.raises(ValueError, match="batch is not due"), conn.transaction():
            prepare_locked(conn, key, control_time=at.replace(tzinfo=None))


@pytest.mark.parametrize("stage", ["w1", "w2"])
def test_stock_preparation_requires_original_quota_and_binds_its_scope(eval_connect, stage):
    from datetime import UTC, datetime

    with eval_connect() as conn:
        policy = stock_policy(conn)
        item = subject(stage=stage)
        record = store_stock_record(conn, item)
        key, at = queue(conn, record, policy)
        with pytest.raises(ValueError, match="matching evaluator quota"), conn.transaction():
            prepare_locked(conn, key, control_time=at)
        assert allocate(conn, item, policy, datetime.now(UTC)).state == "admitted"
        with pytest.raises(ValueError, match="matching evaluator quota"), conn.transaction():
            prepare_locked(conn, key, control_time=at)  # cannot backfill a missed admission
        record = store_stock_record(conn, item)
        key, at = queue(conn, record, policy)
        with conn.transaction():
            result = prepare_locked(conn, key, control_time=at)
        assert result.content.type == stage
        assert result.identity == record.identity
        if stage == "w2":
            assert result.content.scalar.measurement.value == 0.02
            assert result.ladder_updates[item.family_id].unrounded_score == 0.021
        else:
            assert result.content.rank_ic_mean.value == 0.02
        burn = summarize(conn, policy.sha256, item.epoch_id, stage.upper())
        assert burn.trials == 2 and burn.queries_used == 1 and burn.released_values == 0


def test_rel_05_burn_reader_has_no_confirmation_or_holdout_window(eval_connect):
    with eval_connect() as conn:
        policy = stock_policy(conn)
        with pytest.raises(ValueError, match="differs from release profile"):
            summarize(conn, policy.sha256, "synthetic-epoch", "W3")
    assert (
        numeric_values({"value": 0.5, "flags": [True, False, "pass"], "n": 10, "missing": None})
        == 2
    )


def test_intake_transition_is_frozen_and_unknown_private_reason_is_sanitized(eval_connect):
    from qfr_core.contracts.publication import PublishedArtifact
    from qfr_eval.records import RuntimeIdentity
    from qfr_eval.scheduler.dedup import digest
    from qfr_eval.scheduler.models import IntakeCampaign

    private = ROOT / "packages/qfr_eval/src/qfr_eval/private_contracts"
    runtime = RuntimeIdentity.model_validate_json(
        (private / "RuntimeIdentity.valid.json").read_bytes()
    )
    body = json.loads((ROOT / "contracts/examples/PublishedArtifact.valid.json").read_bytes())
    body["manifest"]["artifact_version_id"] = str(uuid4())
    body["manifest"]["family_id"] = str(uuid4())
    body["manifest"]["artifact_id"] = body["manifest"]["family_id"]
    body["manifest"]["provenance"]["program_id"] = str(uuid4())
    artifact = PublishedArtifact.model_validate(body)
    config = json.loads((private / "IntakeCampaign.valid.json").read_bytes())
    with eval_connect() as conn:
        policy = pilot_policy(conn)
        config.update(
            campaign_id=str(uuid4()),
            program_ids=[artifact.manifest.provenance.program_id],
            protocol_hash=policy.protocol_sha256,
            runtime_hash=digest(runtime.model_dump(mode="json")),
        )
        campaign = IntakeCampaign.model_validate(config)
        intake, transition = uuid4(), uuid4()
        with conn.transaction():
            conn.execute(
                "INSERT INTO eval.intake_campaigns(id,payload,sha256,created_by,request_id) "
                "VALUES(%s,%s,%s,'synthetic-fixture',%s)",
                [
                    campaign.campaign_id,
                    Jsonb(campaign.model_dump(mode="json")),
                    campaign.sha256,
                    uuid4(),
                ],
            )
            conn.execute(
                "INSERT INTO eval.intake(id,payload,created_by,request_id,campaign_id,"
                "artifact_version_id,published_seq,program_id,family_id,state) "
                "VALUES(%s,%s,'synthetic-fixture',%s,%s,%s,1,%s,%s,'deferred')",
                [
                    intake,
                    Jsonb({"artifact": artifact.model_dump(mode="json")}),
                    uuid4(),
                    campaign.campaign_id,
                    UUID(artifact.manifest.artifact_version_id),
                    artifact.manifest.provenance.program_id,
                    artifact.manifest.family_id,
                ],
            )
            conn.execute(
                "INSERT INTO eval.intake_transitions(id,intake_id,payload,created_by,request_id) "
                "VALUES(%s,%s,%s,'synthetic-fixture',%s)",
                [
                    transition,
                    intake,
                    Jsonb(
                        {
                            "from": "discovered",
                            "to": "deferred",
                            "reason": "PRIVATE-ERROR-SENTINEL",
                            "duplicate_of": None,
                        }
                    ),
                    uuid4(),
                ],
            )
        key = enqueue_source(
            conn,
            "intake_transition",
            transition,
            policy.sha256,
            principal="synthetic-worker",
            request_id=uuid4(),
        )
        at = conn.execute(
            "SELECT eligible_at FROM eval.release_queue WHERE id=%s", [key]
        ).fetchone()[0]
        with pytest.raises(ValueError, match="frozen campaign runtime"), conn.transaction():
            prepare_locked(conn, key, control_time=at)
        with conn.transaction():
            first = prepare_locked(conn, key, control_time=at, intake_runtime=runtime)
        conn.execute("UPDATE eval.intake SET state='queued' WHERE id=%s", [intake])
        with conn.transaction():
            assert prepare_locked(conn, key, control_time=at, intake_runtime=runtime) == first
        assert first.content.status == "withheld"
        assert first.reason_codes == ["QUOTA_DEFERRED"]
        assert first.lineage_ids == [] and not first.ladder_updates
        assert "PRIVATE-ERROR-SENTINEL" not in first.model_dump_json()


def test_inconsistent_source_is_rejected_before_queueing(eval_connect):
    with eval_connect() as conn:
        policy = pilot_policy(conn)
        record, _ = store_pilot(conn)
        # An immutable record cannot be edited; a malformed new producer write
        # must be detected rather than copying its header into public feedback.
        from unittest.mock import patch

        import qfr_eval.release.store as store

        original = store.source_payload

        def source(db, kind, identity):
            payload, at = original(db, kind, identity)
            payload["request"]["protocol_hash"] = "f" * 64
            return payload, at

        with (
            patch.object(store, "source_payload", source),
            pytest.raises(ValueError, match="pinned weekly validation"),
        ):
            queue(conn, record, policy)
