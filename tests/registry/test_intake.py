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


@pytest.fixture
def screening_transaction_case(intake_publication, scheduler_factory, eval_connect, tmp_path):
    """Synthetic quality failure; this fixture proves atomic DB behavior, not inference."""
    from qfr_eval.protocols.store import activate_protocol, create_protocol
    from qfr_eval.records import RuntimeIdentity
    from qfr_eval.runtime import implementation_hash, software_identity
    from qfr_eval.scheduler.dedup import digest
    from qfr_eval.screening.models import ScreeningExecutionPolicy
    from qfr_eval.screening.records import ScreeningOutcome, ScreeningRequest

    artifact = intake_publication()
    scheduler = scheduler_factory({artifact.manifest.family_id: "atomic-screening-lineage"})
    runtime = RuntimeIdentity(
        evaluator_git_sha="1" * 40,
        implementation_sha256=implementation_hash(),
        image_digest="2" * 64,
        software=software_identity(),
    )
    scheduler.campaign = scheduler.campaign.model_copy(
        update={
            "runtime_hash": digest(runtime.model_dump(mode="json")),
        }
    )
    path = ROOT / "configs/evaluation/pilot_p0_p1_verification_v1.yaml"
    protocol = load_yaml(path, FrozenProtocol)
    with eval_connect() as conn:
        create_protocol(conn, path, principal="screening-transaction-fixture", request_id=uuid4())
        activate_protocol(
            conn,
            protocol.protocol_id,
            protocol.version,
            expected_hash=protocol.sha256,
            principal="screening-transaction-fixture",
            request_id=uuid4(),
        )
    execution = ScreeningExecutionPolicy.model_validate_json(
        (ROOT / "configs/evaluation/screening_execution_v1.json").read_bytes()
    )
    adapter, inputs = screening_fixture_inputs()
    outcome = ScreeningOutcome(
        schema_version="1",
        kind="factor",
        execution="dsl",
        status="insufficient_data",
        reason_codes=["LOW_COVERAGE"],
        coverage=None,
        causality=None,
        output_sha256=None,
        document_checks={},
    )

    def claim_artifact(value):
        scheduler.poll_once()
        job = scheduler.claim(
            worker="screening-transaction-fixture", lease_seconds=120, request_id=uuid4()
        )
        assert job is not None and job["payload"]["intake_id"] == str(identity(scheduler, value))
        request = ScreeningRequest(
            schema_version="1",
            stage="screening",
            window="development",
            intake_id=identity(scheduler, value),
            campaign_id=scheduler.campaign.campaign_id,
            artifact_version_id=UUID(value.manifest.artifact_version_id),
            content_hash=value.manifest.content_hash,
            program_id=value.manifest.provenance.program_id,
            family_id=value.manifest.family_id,
            protocol_id=protocol.protocol_id,
            protocol_version=protocol.version,
            protocol_hash=protocol.sha256,
            snapshot_id=scheduler.campaign.snapshot_id,
            screening_policy_hash=scheduler.screening.sha256,
            execution_policy_hash=digest(execution.model_dump(mode="json")),
            adapter_profile_hash=digest(adapter.model_dump(mode="json")),
            development_input_sha256=digest(inputs.model_dump(mode="json")),
            probe_input_sha256=None,
            runtime=runtime,
            runner_image_digest=None,
            generation_id=scheduler.campaign.server_generation_id,
        )
        return job, request

    return (
        scheduler,
        artifact,
        outcome,
        execution,
        EvidenceStore(tmp_path / "screening"),
        claim_artifact,
    )


def screening_fixture_inputs():
    from qfr_core.contracts.execution import RunnerInput
    from qfr_eval.screening.models import KindAdapterProfile

    profile = KindAdapterProfile.model_validate_json(
        (ROOT / "configs/evaluation/kind_adapter_fixture_v1.json").read_bytes()
    )
    inputs = RunnerInput.model_validate(
        {
            "schema_version": "1",
            "seed": 123,
            "tables": {
                "prices": {
                    "columns": ["date", "code", "close"],
                    "dtypes": ["Date", "String", "Float64"],
                    "rows": [],
                }
            },
        }
    )
    return profile, inputs


def _persist_screening(conn, case, job, request, request_id, fence=None):
    from qfr_eval.screening.persistence import persist_screening

    scheduler, _, outcome, execution, store, _ = case
    adapter, inputs = screening_fixture_inputs()
    return persist_screening(
        conn,
        scheduler,
        request,
        outcome,
        store,
        execution_policy=execution,
        adapter_profile=adapter,
        development_input=inputs,
        probe_input=None,
        output=None,
        behavior=None,
        job_id=job["id"],
        worker="screening-transaction-fixture",
        fence=job["fence"] if fence is None else fence,
        request_id=request_id,
    )


@pytest.fixture
def screening_worker_case(screening_transaction_case):
    """Real registry/DB and DSL execution; small synthetic temporal inputs."""
    from datetime import date

    import polars as pl
    from qfr_core.contracts.execution import RunnerInput
    from qfr_core.runner_tables import pack_table
    from qfr_eval.records import RuntimeIdentity
    from qfr_eval.runtime import implementation_hash, software_identity
    from qfr_eval.screening.documents import ReleasedEvidence
    from qfr_eval.screening.models import KindAdapterProfile
    from qfr_eval.screening.worker import InputSlices, ScreeningWorker

    scheduler, artifact, _, execution, store, _ = screening_transaction_case
    protocol = load_yaml(
        ROOT / "configs/evaluation/pilot_p0_p1_verification_v1.yaml", FrozenProtocol
    )
    days = [
        date(2020, 1, 1),
        date(2020, 2, 1),
        *protocol.diagnostics.prefix_cutoffs,
        date(2022, 12, 30),
        date(2024, 12, 30),
    ]
    prices = pl.DataFrame(
        [
            (d, code, float(10 + i * j))
            for i, d in enumerate(sorted(set(days)))
            for j, code in enumerate(("a", "b"), start=1)
        ],
        schema={"date": pl.Date, "code": pl.String, "close": pl.Float64},
        orient="row",
    )
    reads = []

    def read(value, cutoff, seed):
        reads.append((value.manifest.artifact_version_id, cutoff))
        return RunnerInput(
            schema_version="1",
            seed=seed,
            tables={"prices": pack_table(prices.filter(pl.col("date") <= cutoff))},
        )

    inputs = InputSlices(scheduler.campaign.snapshot_id, read)
    runtime = RuntimeIdentity(
        evaluator_git_sha="1" * 40,
        implementation_sha256=implementation_hash(),
        image_digest="2" * 64,
        software=software_identity(),
    )
    profile = KindAdapterProfile.model_validate_json(
        (ROOT / "configs/evaluation/kind_adapter_pilot_v1.json").read_bytes()
    )
    worker = ScreeningWorker(
        scheduler,
        protocol,
        runtime,
        inputs,
        store,
        execution,
        {"pilot_industry_v1": profile},
        None,
        worker="screening-worker-test",
        released=ReleasedEvidence({}, {}, frozenset()),
    )
    return worker, artifact, reads


@pytest.mark.database
def test_screened_execution_source_is_frozen_before_registry_becomes_unavailable(
    screening_worker_case, eval_connect, monkeypatch
):
    from qfr_eval.registry_execution import binding_for_screen, screening_source

    worker, original, _ = screening_worker_case
    worker.scheduler.poll_once()
    result = worker.run_once()
    assert result.status == "recorded" and result.receipt is not None

    def unavailable(*args, **kwargs):
        raise AssertionError("frozen execution must not contact the Registry")

    monkeypatch.setattr(RegistryClient, "get", unavailable)
    monkeypatch.setattr(RegistryClient, "payload", unavailable)
    with eval_connect() as conn:
        binding = binding_for_screen(conn, result.receipt.record_id, worker.store)
        record, receipt, bundle = screening_source(conn, binding.screening_record_id, worker.store)
        assert bundle.artifact == original and bundle.assets() == {}
        assert bundle.sandbox_profile is None  # Actual DSL; no sandbox evidence fabricated.
        assert record.outcome.status == "passed"
        assert binding.screening_receipt_hash == receipt.receipt_hash
        assert binding.execution_bundle == receipt.files["execution_bundle"]
        assert conn.execute(
            "SELECT count(*) FROM eval.feedback_reservations WHERE artifact_version_id=%s",
            [record.request.artifact_version_id],
        ).fetchone() == (1,)
        (worker.store.root / binding.execution_bundle.relative_path).write_bytes(b"corrupt")
        with pytest.raises(ValueError, match="hash"):
            screening_source(conn, binding.screening_record_id, worker.store)


@pytest.mark.database
def test_screening_worker_behavior_duplicate_never_reads_validation_or_counts_trial(
    screening_worker_case,
    registry_http,
    draft,
    eval_connect,
):
    from qfr_eval.screening.persistence import verify_screening_receipt

    worker, original, reads = screening_worker_case
    scheduler = worker.scheduler
    scheduler.poll_once()
    result = worker.run_once()
    assert result.status == "recorded" and result.receipt is not None
    verify_screening_receipt(result.receipt, worker.store)
    with eval_connect() as conn:
        row = conn.execute(
            "SELECT payload FROM eval.official_records WHERE id=%s", [result.receipt.record_id]
        ).fetchone()
    assert row[0]["record"]["outcome"]["status"] == "passed"
    assert [d for _, d in reads] == [
        worker.protocol.windows[w].end for w in ("development", "validation")
    ]
    body = draft("Ref($close,1)*($close/$close)").model_dump(mode="json")
    body["manifest"].update(
        eligible_protocols=[worker.protocol.protocol_id],
        parent_version_ids=[original.manifest.artifact_version_id],
        family_id=original.manifest.family_id,
        name=original.manifest.name,
    )
    body["manifest"]["rationale"]["change_summary"] = (
        "Different AST; identical complete development behavior"
    )
    duplicate = registry_http.publish(PublicationRequest.model_validate(body)).artifact
    assert duplicate.manifest.canonical_fingerprint != original.manifest.canonical_fingerprint
    scheduler.poll_once()
    before = len(reads)
    result = worker.run_once()
    assert result.status == "duplicate"
    assert reads[before:] == [
        (duplicate.manifest.artifact_version_id, worker.protocol.windows["development"].end)
    ]
    with eval_connect() as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM eval.official_records WHERE artifact_version_id=%s",
                [UUID(duplicate.manifest.artifact_version_id)],
            ).fetchone()[0]
            == 0
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM eval.feedback_reservations WHERE artifact_version_id=%s",
                [UUID(duplicate.manifest.artifact_version_id)],
            ).fetchone()[0]
            == 0
        )
        assert conn.execute(
            "SELECT state,duplicate_of FROM eval.intake WHERE id=%s", [result.intake_id]
        ).fetchone() == ("duplicate", identity(scheduler, original))


@pytest.mark.database
def test_screening_worker_development_failure_never_requests_validation(
    screening_worker_case, eval_connect
):
    import polars as pl
    from qfr_core.contracts.execution import RunnerInput
    from qfr_core.runner_tables import pack_table, unpack_table
    from qfr_eval.screening.worker import InputSlices

    worker, artifact, reads = screening_worker_case
    original_read = worker.inputs.read

    def flat(value, cutoff, seed):
        request = original_read(value, cutoff, seed)
        frame = unpack_table(request.tables["prices"]).with_columns(pl.lit(1.0).alias("close"))
        return RunnerInput(schema_version="1", seed=seed, tables={"prices": pack_table(frame)})

    worker.inputs = InputSlices(worker.inputs.snapshot_id, flat)
    worker.scheduler.poll_once()
    result = worker.run_once()
    assert result.status == "recorded" and result.receipt is not None
    assert len(reads) == 1
    with eval_connect() as conn:
        row = conn.execute(
            "SELECT payload FROM eval.official_records WHERE id=%s", [result.receipt.record_id]
        ).fetchone()
        assert row[0]["record"]["outcome"]["reason_codes"] == ["DEGENERATE"]
        assert (
            conn.execute(
                "SELECT payload->>'status' FROM eval.trial_ledger WHERE official_record_id=%s",
                [result.receipt.record_id],
            ).fetchone()[0]
            == "failed"
        )


@pytest.mark.database
def test_worker_lease_renewal_is_fenced_without_elapsed_completion(
    screening_worker_case, eval_connect
):
    from qfr_eval.screening.worker import LeaseKeeper, LeaseLost

    worker, _, _ = screening_worker_case
    scheduler = worker.scheduler
    scheduler.poll_once()
    job = scheduler.claim(worker=worker.worker, lease_seconds=120, request_id=uuid4())
    keeper = LeaseKeeper(eval_connect, job["id"], job["fence"], worker.worker, worker.policy)
    keeper.renew()
    with eval_connect() as conn:
        row = conn.execute("SELECT state,fence FROM eval.jobs WHERE id=%s", [job["id"]]).fetchone()
        assert row == ("running", job["fence"])
    stale = LeaseKeeper(eval_connect, job["id"], job["fence"] - 1, worker.worker, worker.policy)
    with pytest.raises(LeaseLost):
        stale.renew()


@pytest.mark.database
def test_missing_sandbox_defers_real_queued_model_without_record_or_budget(
    screening_worker_case,
    registry_http,
    eval_connect,
):
    import hashlib
    import json

    from qfr_core.contracts.intake import ExecutionContract
    from qfr_registry.seeds import package_seed

    worker, original, reads = screening_worker_case
    body = json.loads((ROOT / "contracts/examples/ExecutionContract.valid.json").read_bytes())
    body.update(
        runner="qfr-json-runner/1",
        interface="function",
        command=None,
        function="runner.py:run",
        input_schema_ref="RunnerInput/1",
        output_schema_ref="RunnerOutput/1",
        dependency_lock_sha256=hashlib.sha256((ROOT / "uv.lock").read_bytes()).hexdigest(),
    )
    request = package_seed(
        ROOT,
        original.manifest.provenance.program_id,
        "unavailable-model",
        "model",
        ExecutionContract.model_validate(body),
        source=(ROOT / "fixtures/artifacts/runners/generic.py").read_bytes(),
        weights={"kind": "model", "coefficient": 0.5},
        source_hashes=[],
    )
    request = request.model_copy(
        update={
            "profile": "pilot_industry_v1",
            "manifest": request.manifest.model_copy(
                update={"eligible_protocols": [worker.protocol.protocol_id]}
            ),
        }
    )
    artifact = registry_http.publish(request).artifact
    scheduler = worker.scheduler
    scheduler.campaign = scheduler.campaign.model_copy(
        update={
            "allowed_kinds": [artifact.manifest.kind],
            "root_lineages": {UUID(artifact.manifest.family_id): "missing-backend-test"},
        }
    )
    scheduler.poll_once()
    assert worker.sandbox is None
    result = worker.run_once()
    assert result.status == "deferred" and result.reason == "BACKEND_UNAVAILABLE"
    assert len(reads) == 1 and reads[0][1] == worker.protocol.windows["development"].end
    with eval_connect() as conn:
        assert (
            conn.execute(
                "SELECT state FROM eval.intake WHERE id=%s", [result.intake_id]
            ).fetchone()[0]
            == "queued"
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM eval.official_records WHERE artifact_version_id=%s",
                [UUID(artifact.manifest.artifact_version_id)],
            ).fetchone()[0]
            == 0
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM eval.feedback_reservations WHERE artifact_version_id=%s",
                [UUID(artifact.manifest.artifact_version_id)],
            ).fetchone()[0]
            == 0
        )


def test_model_description_rename_cannot_change_behavior_comparison_scope(screening_policy):
    import json

    from qfr_core.contracts.publication import PublishedArtifact

    manifest = json.loads((ROOT / "contracts/examples/artifact_kinds/model.json").read_bytes())
    original = PublishedArtifact.model_validate(
        {
            "manifest": manifest,
            "profile": "pilot_industry_v1",
            "version_no": 1,
            "published_seq": 1,
            "dsl_policy_hash": None,
            "payload_digest": manifest["content_hash"],
        }
    )
    campaign = IntakeCampaign.model_validate_json(
        (
            ROOT / "packages/qfr_eval/src/qfr_eval/private_contracts/IntakeCampaign.valid.json"
        ).read_bytes()
    )
    renamed = original.model_copy(
        update={
            "manifest": original.manifest.model_copy(
                update={
                    "name": "renamed",
                    "title": "Changed title",
                    "payload": original.manifest.payload.model_copy(
                        update={"specification": "Descriptive rename"}
                    ),
                }
            )
        }
    )
    assert semantic_scope(original, campaign) == semantic_scope(renamed, campaign)


@pytest.mark.database
def test_screening_records_budget_and_fenced_completion_rollback_together(
    screening_transaction_case, eval_connect
):
    case = screening_transaction_case
    scheduler, artifact, _, _, _, claim_artifact = case
    job, request = claim_artifact(artifact)
    audit_id = uuid4()
    with pytest.raises(ValueError, match="stale or expired"):
        with eval_connect() as conn, conn.transaction():
            _persist_screening(conn, case, job, request, audit_id, job["fence"] + 1)
    with eval_connect() as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM eval.feedback_reservations WHERE program_id=%s",
                [request.program_id],
            ).fetchone()[0]
            == 0
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM eval.official_records WHERE artifact_version_id=%s",
                [request.artifact_version_id],
            ).fetchone()[0]
            == 0
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM eval.events WHERE request_id=%s", [audit_id]
            ).fetchone()[0]
            == 0
        )
        assert (
            conn.execute(
                "SELECT state FROM eval.intake WHERE id=%s", [request.intake_id]
            ).fetchone()[0]
            == "screening"
        )
    with eval_connect() as conn, conn.transaction():
        record, receipt = _persist_screening(conn, case, job, request, audit_id)
    assert record.outcome.status == "insufficient_data" and receipt.kind == "private_screening"
    with eval_connect() as conn:
        assert (
            conn.execute("SELECT state FROM eval.jobs WHERE id=%s", [job["id"]]).fetchone()[0]
            == "failed"
        )
        trial = conn.execute(
            "SELECT payload FROM eval.trial_ledger WHERE id=%s", [record.trial_id]
        ).fetchone()[0]
        assert trial["status"] == "failed" and trial["sampling_unit"] == "eligible_observation"
        assert (
            conn.execute(
                "SELECT count(*) FROM eval.events WHERE request_id=%s", [audit_id]
            ).fetchone()[0]
            >= 5
        )


@pytest.mark.database
def test_screening_concurrent_retry_is_one_immutable_record_trial_and_budget_slot(
    screening_transaction_case, eval_connect
):
    case = screening_transaction_case
    _, artifact, _, _, store, claim_artifact = case
    job, request = claim_artifact(artifact)
    audit_id = uuid4()

    def run():
        with eval_connect() as conn, conn.transaction():
            return _persist_screening(conn, case, job, request, audit_id)

    with ThreadPoolExecutor(4) as pool:
        receipts = list(pool.map(lambda _: run(), range(4)))
    assert all(value == receipts[0] for value in receipts)
    from qfr_eval.screening.persistence import verify_screening_receipt

    verify_screening_receipt(receipts[0][1], store)
    with eval_connect() as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM eval.official_records WHERE artifact_version_id=%s",
                [request.artifact_version_id],
            ).fetchone()[0]
            == 1
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM eval.trial_ledger WHERE official_record_id=%s",
                [receipts[0][0].record_id],
            ).fetchone()[0]
            == 1
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM eval.feedback_reservations WHERE program_id=%s",
                [request.program_id],
            ).fetchone()[0]
            == 1
        )


@pytest.mark.database
def test_screening_fourth_unique_version_is_recorded_and_feedback_is_withheld(
    screening_transaction_case, intake_publication, eval_connect
):
    case = screening_transaction_case
    _, artifact, _, _, _, claim_artifact = case
    records = []
    for index in range(4):
        if index:
            artifact = intake_publication(offset=index, parent=artifact)
        job, request = claim_artifact(artifact)
        with eval_connect() as conn, conn.transaction():
            record, _ = _persist_screening(conn, case, job, request, uuid4())
        records.append(record)
    assert [r.feedback_disposition for r in records] == ["eligible"] * 3 + ["withheld:budget"]
    with eval_connect() as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM eval.trial_ledger WHERE official_record_id=ANY(%s)",
                [[r.record_id for r in records]],
            ).fetchone()[0]
            == 4
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM eval.released_reports WHERE payload->>'program_id'=%s",
                [records[0].request.program_id],
            ).fetchone()[0]
            == 0
        )


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
