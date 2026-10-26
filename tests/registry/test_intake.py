"""P3.2 real HTTP/DB scheduling; synthetic outputs are not sandbox acceptance."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from uuid import UUID, uuid4, uuid5

import psycopg
import pytest
from psycopg.types.json import Jsonb
from qfr_core.configuration import load_yaml
from qfr_core.contracts.publication import PublicationRequest
from qfr_core.dsl.language import DSLConfig
from qfr_core.registry_client import RegistryClient, RegistryTransportError
from qfr_eval.artifact_store import EvidenceStore
from qfr_eval.db.queue import finish
from qfr_eval.protocols.models import FrozenProtocol
from qfr_eval.scheduler.dedup import equivalent, semantic_scope, verify_publication
from qfr_eval.scheduler.intake import IntakeScheduler, transition
from qfr_eval.scheduler.models import (
    DevelopmentBehavior,
    IntakeCampaign,
    IntakePolicy,
    PilotScreeningPolicy,
)

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def screening_policy():
    return PilotScreeningPolicy.model_validate_json(
        (ROOT / "configs/evaluation/pilot_screening_v1.json").read_bytes()
    )


@pytest.fixture
def intake_publication(registry_http, draft):
    def publish(offset=0, parent=None, branch=False):
        request = draft(f"Ref($close,1)+{offset}")
        body = request.model_dump(mode="json")
        body["manifest"]["eligible_protocols"] = ["pilot_p0_p1_verification_v1"]
        if parent:
            body["manifest"]["parent_version_ids"] = [parent.manifest.artifact_version_id]
            body["manifest"]["rationale"]["change_summary"] = "Synthetic scheduling revision"
            if not branch:
                body["manifest"]["family_id"] = parent.manifest.family_id
                body["manifest"]["name"] = parent.manifest.name
        return registry_http.publish(PublicationRequest.model_validate(body)).artifact

    return publish


@pytest.fixture
def scheduler_factory(registry_http, eval_connect, program, screening_policy):
    def make(roots, active=True, generation=None, campaign_id=None, policy=None):
        campaign = IntakeCampaign(
            schema_version="1",
            campaign_id=campaign_id or uuid4(),
            active=active,
            owner_authorization_ref="synthetic-test-owner",
            program_ids=[program],
            protocol_ref="pilot_p0_p1_verification_v1",
            protocol_hash=screening_policy.protocol_sha256,
            snapshot_id="1" * 64,
            runtime_hash="2" * 64,
            screening_policy_hash=screening_policy.sha256,
            server_generation_id=generation or uuid4().hex,
            allowed_kinds=["factor", "model", "strategy", "research_note", "data_product"],
            root_lineages={UUID(family): lineage for family, lineage in roots.items()},
        )
        return IntakeScheduler(
            registry_http,
            eval_connect,
            campaign,
            policy
            or IntakePolicy.model_validate_json(
                (ROOT / "configs/evaluation/intake_v1.json").read_bytes()
            ),
            screening_policy,
            {"pilot_industry_v1": DSLConfig.load(ROOT / "configs/dsl/pilot_industry_v1.json")},
            principal="private-intake-test",
        )

    return make


def identity(scheduler, artifact):
    return uuid5(scheduler.campaign.campaign_id, artifact.manifest.artifact_version_id)


def queue_only_finish(scheduler, eval_connect):
    """A queue plumbing fixture; it never executes or claims to measure an artifact."""
    request = uuid4()
    job = scheduler.claim(worker="queue-test", lease_seconds=60, request_id=request)
    assert job is not None
    with eval_connect() as conn, conn.transaction():
        finish(
            conn,
            job["id"],
            worker="queue-test",
            fence=job["fence"],
            request_id=request,
            failed=True,
        )
        transition(
            conn,
            job["intake"]["id"],
            "rejected",
            reason="TEST_QUEUE_ONLY",
            principal="queue-test",
            request_id=request,
        )
    return job


@pytest.mark.database
def test_evl01_idle_does_not_poll_and_public_registry_has_no_trigger(
    scheduler_factory, monkeypatch
):
    def forbidden(*args, **kwargs):
        raise AssertionError("an idle campaign cannot access the registry")

    monkeypatch.setattr(RegistryClient, "page", forbidden)
    scheduler = scheduler_factory({}, active=False)
    assert scheduler.poll_once() == {"active": False, "discovered": 0, "queued": 0}
    assert scheduler.claim(worker="unused", lease_seconds=1, request_id=uuid4()) is None
    source = (ROOT / "packages/qfr_eval/src/qfr_eval/scheduler/intake.py").read_text()
    assert "FastAPI" not in source and "uvicorn" not in source


@pytest.mark.database
def test_cursor_polling_is_concurrent_idempotent_and_audited(
    intake_publication, scheduler_factory, eval_connect
):
    artifacts = [intake_publication(i) for i in range(3)]
    roots = {a.manifest.family_id: "lineage-" + str(i) for i, a in enumerate(artifacts)}
    scheduler = scheduler_factory(roots)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: scheduler.poll_once(), range(2)))
    assert sum(r["discovered"] for r in results) == 3
    assert sum(r["queued"] for r in results) == 1
    with eval_connect() as conn:
        assert conn.execute(
            "SELECT published_seq FROM eval.intake_cursor WHERE campaign_id=%s",
            [scheduler.campaign.campaign_id],
        ).fetchone() == (artifacts[-1].published_seq,)
        assert conn.execute(
            "SELECT count(*) FROM eval.intake WHERE campaign_id=%s",
            [scheduler.campaign.campaign_id],
        ).fetchone() == (3,)
        events = conn.execute(
            "SELECT created_by,request_id,created_at FROM eval.events WHERE "
            "payload->>'entity_id'=%s",
            [str(identity(scheduler, artifacts[0]))],
        ).fetchall()
        assert events and all(all(row) for row in events)
    # Reconstructing the scheduler uses the persisted cursor, not process memory.
    resumed = IntakeScheduler(
        scheduler.client,
        scheduler.connect,
        scheduler.campaign,
        scheduler.policy,
        scheduler.screening,
        scheduler.dsl_configs,
        principal=scheduler.principal,
    )
    assert resumed.poll_once()["discovered"] == 0


@pytest.mark.database
def test_registry_failure_keeps_cursor_and_no_silent_empty_success(
    intake_publication, scheduler_factory, eval_connect, monkeypatch
):
    artifact = intake_publication()
    scheduler = scheduler_factory({artifact.manifest.family_id: "root"})
    scheduler.poll_once()

    def unavailable(*args, **kwargs):
        raise RegistryTransportError("registry connection unavailable")

    monkeypatch.setattr(RegistryClient, "page", unavailable)
    with pytest.raises(RegistryTransportError):
        scheduler.poll_once()
    with eval_connect() as conn:
        assert conn.execute(
            "SELECT published_seq FROM eval.intake_cursor WHERE campaign_id=%s",
            [scheduler.campaign.campaign_id],
        ).fetchone() == (artifact.published_seq,)


@pytest.mark.database
def test_round_robin_family_fifo_and_capacity_deferral(
    intake_publication, scheduler_factory, eval_connect
):
    a1 = intake_publication(1)
    a2 = intake_publication(2, parent=a1)
    b1 = intake_publication(3)
    b2 = intake_publication(4, parent=b1)
    scheduler = scheduler_factory({a1.manifest.family_id: "a", b1.manifest.family_id: "b"})
    order = []
    for _ in range(4):
        result = scheduler.poll_once()
        assert result["queued"] == 1
        assert scheduler.poll_once()["queued"] == 0
        job = queue_only_finish(scheduler, eval_connect)
        order.append(job["intake"]["artifact_version_id"])
    assert order == [UUID(a.manifest.artifact_version_id) for a in [a1, b1, a2, b2]]


@pytest.mark.database
def test_evl05_canonical_duplicate_never_queued_reserved_or_counted(
    intake_publication, scheduler_factory, eval_connect
):
    original, renamed = intake_publication(1), intake_publication(1)
    scheduler = scheduler_factory({original.manifest.family_id: "root"})
    result = scheduler.poll_once()
    assert result["discovered"] == 2 and result["queued"] == 1
    with eval_connect() as conn:
        row = conn.execute(
            "SELECT state,duplicate_of,job_id,feedback_disposition FROM eval.intake WHERE id=%s",
            [identity(scheduler, renamed)],
        ).fetchone()
        assert row == ("duplicate", identity(scheduler, original), None, None)
        assert conn.execute(
            "SELECT count(*) FROM eval.official_records WHERE artifact_version_id=%s",
            [UUID(renamed.manifest.artifact_version_id)],
        ).fetchone() == (0,)
        assert conn.execute(
            "SELECT count(*) FROM eval.feedback_reservations WHERE artifact_version_id=%s",
            [UUID(renamed.manifest.artifact_version_id)],
        ).fetchone() == (0,)
        assert conn.execute(
            "SELECT lineage_id FROM eval.intake_lineages WHERE family_id=%s",
            [renamed.manifest.family_id],
        ).fetchone() == ("root",)


@pytest.mark.database
def test_missing_owner_lineage_waits_and_manifest_generation_is_not_authority(
    intake_publication, scheduler_factory, eval_connect
):
    artifact = intake_publication()
    scheduler = scheduler_factory({})
    assert scheduler.poll_once()["queued"] == 0
    assert scheduler.poll_once()["queued"] == 0
    with eval_connect() as conn:
        assert conn.execute(
            "SELECT state FROM eval.intake WHERE id=%s", [identity(scheduler, artifact)]
        ).fetchone() == ("deferred",)
        reason = conn.execute(
            "SELECT payload->>'reason' FROM eval.intake_transitions WHERE intake_id=%s",
            [identity(scheduler, artifact)],
        ).fetchone()
        assert reason == ("LINEAGE_OWNER_INPUT",)
        assert conn.execute(
            "SELECT count(*) FROM eval.feedback_reservations WHERE artifact_version_id=%s",
            [UUID(artifact.manifest.artifact_version_id)],
        ).fetchone() == (0,)


@pytest.mark.database
def test_three_feedback_versions_and_branches_do_not_reset_budget(
    intake_publication, scheduler_factory, eval_connect
):
    original = intake_publication(0)
    artifacts = [original] + [
        intake_publication(i, parent=original, branch=True) for i in range(1, 4)
    ]
    scheduler = scheduler_factory({original.manifest.family_id: "economic-root"})
    dispositions = []
    for _ in artifacts:
        scheduler.poll_once()
        job = scheduler.claim(worker="budget-test", lease_seconds=60, request_id=uuid4())
        assert job is not None
        with eval_connect() as conn, conn.transaction():
            request_id = uuid4()
            disposition = scheduler.reserve_feedback(
                conn, job["intake"]["id"], request_id=request_id
            )
            assert (
                scheduler.reserve_feedback(conn, job["intake"]["id"], request_id=request_id)
                == disposition
            )
            dispositions.append(disposition)
            finish(
                conn,
                job["id"],
                worker="budget-test",
                fence=job["fence"],
                request_id=request_id,
                failed=True,
            )
            transition(
                conn,
                job["intake"]["id"],
                "rejected",
                reason="TEST_RESERVATION_ONLY",
                principal="budget-test",
                request_id=request_id,
            )
    assert dispositions == ["eligible"] * 3 + ["withheld:budget"]
    assert all(
        scheduler.campaign.server_generation_id != a.manifest.provenance.generation_id
        for a in artifacts
    )
    with eval_connect() as conn:
        rows = conn.execute(
            "SELECT ordinal FROM eval.feedback_reservations WHERE program_id=%s ORDER BY ordinal",
            [original.manifest.provenance.program_id],
        ).fetchall()
        assert rows == [(1,), (2,), (3,), (4,)]


@pytest.mark.database
def test_intake_page_cursor_and_queue_rollback_together(
    intake_publication, scheduler_factory, eval_connect, monkeypatch
):
    artifact = intake_publication()
    scheduler = scheduler_factory({artifact.manifest.family_id: "root"})

    def fail(*args):
        raise RuntimeError("controlled-dispatch-failure")

    monkeypatch.setattr(scheduler, "_dispatch", fail)
    with pytest.raises(RuntimeError, match="controlled-dispatch"):
        scheduler.poll_once()
    with eval_connect() as conn:
        assert conn.execute(
            "SELECT count(*) FROM eval.intake WHERE campaign_id=%s",
            [scheduler.campaign.campaign_id],
        ).fetchone() == (0,)
        assert conn.execute(
            "SELECT count(*) FROM eval.intake_cursor WHERE campaign_id=%s",
            [scheduler.campaign.campaign_id],
        ).fetchone() == (0,)


@pytest.mark.database
def test_new_private_tables_remain_append_only_and_unavailable_to_feedback(
    intake_publication, scheduler_factory, eval_connect
):
    artifact = intake_publication()
    scheduler = scheduler_factory({artifact.manifest.family_id: "root"})
    scheduler.poll_once()
    tables = (
        "intake_campaigns",
        "intake_transitions",
        "intake_lineages",
        "intake_behavior",
        "feedback_reservations",
    )
    with eval_connect() as conn:
        for table in tables:
            assert conn.execute(
                "SELECT has_table_privilege('feedback_ro',%s,'SELECT'),"
                "has_table_privilege('eval_rw',%s,'UPDATE')",
                ["eval." + table, "eval." + table],
            ).fetchone() == (False, False)
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(f"DELETE FROM eval.{table}")
    with eval_connect("postgres") as owner:
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="insert-only table"):
            owner.execute(
                "UPDATE eval.intake_campaigns SET sha256=%s WHERE id=%s",
                ["0" * 64, scheduler.campaign.campaign_id],
            )


@pytest.mark.database
def test_reservation_requires_transaction_and_rollback_restores_budget(
    intake_publication, scheduler_factory, eval_connect
):
    artifact = intake_publication()
    scheduler = scheduler_factory({artifact.manifest.family_id: "root"})
    scheduler.poll_once()
    job = scheduler.claim(worker="budget-test", lease_seconds=60, request_id=uuid4())
    assert job is not None
    request_id = uuid4()
    with eval_connect() as conn:
        with pytest.raises(ValueError, match="active transaction"):
            scheduler.reserve_feedback(conn, identity(scheduler, artifact), request_id=request_id)
        with pytest.raises(RuntimeError, match="controlled-failure"), conn.transaction():
            assert (
                scheduler.reserve_feedback(
                    conn, identity(scheduler, artifact), request_id=request_id
                )
                == "eligible"
            )
            raise RuntimeError("controlled-failure")
        assert conn.execute(
            "SELECT count(*) FROM eval.feedback_reservations WHERE request_id=%s", [request_id]
        ).fetchone() == (0,)
        assert conn.execute(
            "SELECT count(*) FROM eval.events WHERE request_id=%s", [request_id]
        ).fetchone() == (0,)
        assert conn.execute(
            "SELECT feedback_disposition FROM eval.intake WHERE id=%s",
            [identity(scheduler, artifact)],
        ).fetchone() == (None,)
        with conn.transaction():
            scheduler.reserve_feedback(conn, identity(scheduler, artifact), request_id=uuid4())
        assert conn.execute(
            "SELECT ordinal FROM eval.feedback_reservations WHERE artifact_version_id=%s",
            [UUID(artifact.manifest.artifact_version_id)],
        ).fetchone() == (1,)


@pytest.mark.database
def test_campaign_restart_cannot_reset_feedback_or_rebind_existing_lineage(
    intake_publication, scheduler_factory, eval_connect
):
    artifact = intake_publication()
    roots = {artifact.manifest.family_id: "root"}
    scheduler = scheduler_factory(roots)
    scheduler.poll_once()
    job = scheduler.claim(worker="budget-test", lease_seconds=60, request_id=uuid4())
    assert job is not None
    with eval_connect() as conn, conn.transaction():
        scheduler.reserve_feedback(conn, identity(scheduler, artifact), request_id=uuid4())
    restarted = scheduler_factory(roots, generation=scheduler.campaign.server_generation_id)
    restarted.poll_once()
    assert restarted.claim(worker="restart", lease_seconds=60, request_id=uuid4()) is not None
    with eval_connect() as conn, conn.transaction():
        restarted.reserve_feedback(conn, identity(restarted, artifact), request_id=uuid4())
        assert conn.execute(
            "SELECT count(*),max(ordinal) FROM eval.feedback_reservations "
            "WHERE artifact_version_id=%s",
            [UUID(artifact.manifest.artifact_version_id)],
        ).fetchone() == (1, 1)
    changed = scheduler_factory(roots, campaign_id=scheduler.campaign.campaign_id)
    with pytest.raises(ValueError, match="cannot be changed or reset"):
        changed.poll_once()
    rebound = scheduler_factory({artifact.manifest.family_id: "new-budget"})
    with pytest.raises(ValueError, match="conflicts with existing exposure"):
        rebound.poll_once()


@pytest.mark.database
def test_concurrent_reservations_serialize_unique_ordinals(
    intake_publication, scheduler_factory, eval_connect
):
    original = intake_publication(1)
    second = intake_publication(2, parent=original, branch=True)
    policy = IntakePolicy.model_validate_json(
        (ROOT / "configs/evaluation/intake_v1.json").read_bytes()
    ).model_copy(update={"max_ready_jobs_per_campaign": 2})
    scheduler = scheduler_factory({original.manifest.family_id: "root"}, policy=policy)
    assert scheduler.poll_once()["queued"] == 2
    for _ in range(2):
        assert scheduler.claim(worker="budget-test", lease_seconds=60, request_id=uuid4())

    def reserve(artifact):
        with eval_connect() as conn, conn.transaction():
            return scheduler.reserve_feedback(
                conn, identity(scheduler, artifact), request_id=uuid4()
            )

    with ThreadPoolExecutor(2) as pool:
        assert list(pool.map(reserve, [original, second])) == ["eligible", "eligible"]
    with eval_connect() as conn:
        assert conn.execute(
            "SELECT ordinal FROM eval.feedback_reservations WHERE program_id=%s ORDER BY ordinal",
            [original.manifest.provenance.program_id],
        ).fetchall() == [(1,), (2,)]


def behavior(scope="0" * 64):
    table = {
        "columns": ["date", "code", "score", "rank", "selected"],
        "dtypes": ["Date", "String", "Float64", "Int64", "Boolean"],
        "rows": [["2021-01-01", "A", 1.0, 1, True], ["2021-01-01", "B", 0.5, 2, False]],
    }
    return DevelopmentBehavior.model_validate(
        {
            "schema_version": "1",
            "semantic_scope_sha256": scope,
            "complete_original_eligible_outputs": True,
            "tables": {"weekly": table, "monthly": deepcopy(table)},
            "score_columns": {"weekly": ["score"], "monthly": ["score"]},
        }
    )


def test_approved_behavior_equivalence_is_full_structure_not_correlation(screening_policy):
    reference = behavior()
    value = reference.model_dump(mode="json")
    value["tables"]["weekly"]["rows"][0][2] += 1e-13
    assert equivalent(DevelopmentBehavior.model_validate(value), reference, screening_policy)
    for column, changed in [(0, "2021-01-02"), (1, "C"), (2, 1.01), (3, 2), (4, False)]:
        altered = reference.model_dump(mode="json")
        altered["tables"]["monthly"]["rows"][0][column] = changed
        assert not equivalent(
            DevelopmentBehavior.model_validate(altered), reference, screening_policy
        )
    assert not equivalent(behavior("1" * 64), reference, screening_policy)
    altered = reference.model_dump(mode="json")
    altered["tables"]["monthly"]["rows"][0][2] = None
    assert not equivalent(DevelopmentBehavior.model_validate(altered), reference, screening_policy)
    for table in altered["tables"].values():
        table["rows"] = []
    empty = DevelopmentBehavior.model_validate(altered)
    assert not equivalent(empty, empty, screening_policy)


def test_screening_policy_preserves_measurement_and_approved_values(screening_policy):
    protocol = load_yaml(
        ROOT / "configs/evaluation/pilot_p0_p1_verification_v1.yaml", FrozenProtocol
    )
    assert screening_policy.protocol_sha256 == protocol.sha256
    assert screening_policy.score_atol == protocol.atol == 1e-12
    assert screening_policy.score_rtol == protocol.rtol == 1e-12
    assert screening_policy.feedback_versions_per_lineage_generation == 3
    assert (
        screening_policy.required_eligible_coverage
        == screening_policy.reject_constant_scorer_fraction
        == 1
    )
    assert screening_policy.scope == "P0_P1_verification_only"
    assert screening_policy.fixed_position_strategy_exempt
    for field, value in [
        ("required_eligible_coverage", 0.8),
        ("reject_constant_scorer_fraction", 0.1),
    ]:
        with pytest.raises(ValueError):
            PilotScreeningPolicy.model_validate({**screening_policy.model_dump(), field: value})


@pytest.mark.database
def test_semantic_scope_prevents_unsafe_cross_snapshot_dedup(intake_publication, scheduler_factory):
    artifact = intake_publication()
    scheduler = scheduler_factory({artifact.manifest.family_id: "root"})
    original = semantic_scope(artifact, scheduler.campaign)
    for field in ("protocol_hash", "snapshot_id", "runtime_hash", "screening_policy_hash"):
        assert (
            semantic_scope(artifact, scheduler.campaign.model_copy(update={field: "f" * 64}))
            != original
        )
    forged = artifact.model_copy(
        update={
            "manifest": artifact.manifest.model_copy(update={"canonical_fingerprint": "f" * 64})
        }
    )
    with pytest.raises(ValueError, match="declaration mismatch"):
        verify_publication(forged, scheduler.dsl_configs)


@pytest.mark.database
def test_behavior_lookup_requires_compatible_persisted_evidence(
    intake_publication, scheduler_factory, eval_connect, tmp_path
):
    first, candidate = intake_publication(1), intake_publication(2)
    scheduler = scheduler_factory(
        {first.manifest.family_id: "a", candidate.manifest.family_id: "b"}
    )
    scheduler.poll_once()
    scope = semantic_scope(candidate, scheduler.campaign)
    proof = behavior(scope)
    store = EvidenceStore(tmp_path / "private-evidence")
    with eval_connect() as conn, conn.transaction():
        assert (
            scheduler.behavior_duplicate(conn, identity(scheduler, candidate), proof, store) is None
        )
        # Synthetic persisted behavior fixture, not a measured or sandboxed artifact.
        conn.execute(
            "UPDATE eval.intake SET state='screen_passed',request_id=%s WHERE id=%s",
            [uuid4(), identity(scheduler, first)],
        )
        conn.execute(
            "INSERT INTO eval.intake_behavior(id,intake_id,semantic_scope_sha256,"
            "payload,created_by,request_id) VALUES(%s,%s,%s,%s,'fixture',%s)",
            [
                uuid4(),
                identity(scheduler, first),
                scope,
                Jsonb(store.json(proof.model_dump(mode="json")).model_dump(mode="json")),
                uuid4(),
            ],
        )
        assert scheduler.behavior_duplicate(
            conn, identity(scheduler, candidate), proof, store
        ) == identity(scheduler, first)
