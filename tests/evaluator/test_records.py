from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from qfr_core.configuration import load_yaml
from qfr_core.contracts.data import SnapshotManifest
from qfr_core.contracts.enums import ReasonCode
from qfr_eval.artifact_store import EvidenceStore
from qfr_eval.measurement import MeasuredRun, failed_measurement, measure_pilot
from qfr_eval.persistence import ids_for_request, persist_run, verify_receipt
from qfr_eval.protocols.models import FrozenProtocol
from qfr_eval.records import EvaluationRequest, TrialLedgerEntry
from qfr_eval.runtime import (
    builtin_definition,
    capture_runtime,
    verify_runtime,
)


def request_fixture(intent="evaluated"):
    protocol = load_yaml(
        Path("configs/evaluation/pilot_p0_p1_verification_v1.yaml"), FrozenProtocol
    )
    artifact, digest, _ = builtin_definition("baseline")
    runtime = capture_runtime(
        evaluator_git_sha="1" * 40,
        image_digest="2" * 64,
    )
    request = EvaluationRequest(
        schema_version="1",
        variant="baseline",
        artifact_version_id=artifact,
        content_hash=digest,
        protocol_id=protocol.protocol_id,
        protocol_version=protocol.version,
        protocol_hash=protocol.sha256,
        snapshot_id="0" * 64,
        epoch_id="transaction-fixture",
        window="validation",
        cycle="weekly",
        program_id=str(uuid4()),
        family_id="fixture",
        economic_lineage_id="fixture",
        generation_id="fixture",
        cohort_id="fixture",
        intent=intent,
        runtime=runtime,
    )
    snapshot = SnapshotManifest.model_validate_json(
        Path("contracts/examples/SnapshotManifest.valid.json").read_bytes()
    )
    return protocol, request, snapshot


def test_private_evidence_store_concurrent_identity_integrity_and_paths(tmp_path):
    store = EvidenceStore(tmp_path / "evidence")
    with ThreadPoolExecutor(4) as pool:
        files = list(pool.map(lambda _: store.json({"same": "content"}), range(8)))
    assert all(f == files[0] for f in files)
    assert not list(store.objects.glob(".staging-*"))
    with pytest.raises(ValueError, match="path"):
        store.read(files[0].model_copy(update={"relative_path": "../outside"}))
    path = store.root / files[0].relative_path
    path.write_bytes(b"corruption")
    with pytest.raises(ValueError, match="hash"):
        store.read(files[0])
    with pytest.raises(ValueError, match="corrupt"):
        store.json({"same": "content"})


def test_runtime_and_request_fail_closed_on_unpinned_or_confirmation_inputs():
    _, request, _ = request_fixture()
    verify_runtime(request.runtime)
    with pytest.raises(ValueError, match="runtime differs"):
        verify_runtime(request.runtime.model_copy(update={"implementation_sha256": "0" * 64}))
    with pytest.raises(ValueError):
        EvaluationRequest.model_validate(
            {**request.model_dump(mode="json"), "window": "confirmation"}
        )
    with pytest.raises(ValueError, match="non-selectable"):
        EvaluationRequest.model_validate(
            {**request.model_dump(mode="json"), "variant": "N1_reversal_weight040"}
        )


@pytest.mark.database
@pytest.mark.parametrize(
    "intent,failed",
    [("evaluated", False), ("withheld", False), ("diagnostic", False), ("evaluated", True)],
)
def test_evl_02_06_records_all_attempts_atomically_with_private_receipts(
    eval_connect, tmp_path, intent, failed
):
    protocol, request, snapshot = request_fixture(intent)
    request_id = uuid4()
    record_id, trial_id, _ = ids_for_request(request_id)
    run = failed_measurement(request, str(trial_id), ReasonCode.LOW_COVERAGE)
    if not failed:
        observation = run.summary.observation.model_copy(
            update={"status": intent, "selectable": intent != "diagnostic"}
        )
        run = MeasuredRun(
            run.summary.model_copy(
                update={"status": "complete", "reason_codes": [], "observation": observation}
            ),
            {},
            [],
        )
    store = EvidenceStore(tmp_path / "evidence")
    with eval_connect() as conn:
        record, receipt = persist_run(
            conn,
            request,
            protocol,
            snapshot,
            run,
            [],
            {},
            store,
            principal="record-test",
            request_id=request_id,
        )
        assert all(record.identity.model_dump().values())
        assert record.status == (
            "failed" if failed else "withheld" if intent == "withheld" else "complete"
        )
        assert (
            receipt.authenticity == "internal_unsigned"
            and receipt.results_hash == record.results_hash
        )
        verify_receipt(receipt, store)
        row = conn.execute(
            "SELECT payload FROM eval.trial_ledger WHERE id=%s", [trial_id]
        ).fetchone()
        trial = TrialLedgerEntry.model_validate(row[0])
        assert trial.status == ("failed" if failed else intent)
        assert trial.selectable == (not failed and intent != "diagnostic")
        assert trial.official_record_id == str(record_id)
        assert (
            conn.execute(
                "SELECT count(*) FROM eval.events WHERE request_id=%s", [request_id]
            ).fetchone()[0]
            == len(run.summary.metrics) + 3
        )
        repeated = persist_run(
            conn,
            request,
            protocol,
            snapshot,
            run,
            [],
            {},
            store,
            principal="record-test",
            request_id=request_id,
        )
        assert repeated == (record, receipt)
        assert conn.execute(
            "SELECT count(*) FROM eval.trial_ledger WHERE official_record_id=%s", [record_id]
        ).fetchone() == (1,)
        with pytest.raises(psycopg.Error):
            conn.execute("UPDATE eval.official_records SET payload='{}' WHERE id=%s", [record_id])
        with pytest.raises(ValueError, match="receipt hash"):
            verify_receipt(receipt.model_copy(update={"protocol_hash": "f" * 64}), store)


@pytest.mark.database
def test_evl_06_transaction_failure_leaves_no_record_trial_metrics_or_audit(eval_connect, tmp_path):
    from qfr_eval.statistics.clustering import BehavioralFingerprint, cluster_trials

    protocol, request, snapshot = request_fixture()
    request_id = uuid4()
    _, trial_id, _ = ids_for_request(request_id)
    run = failed_measurement(request, str(trial_id), ReasonCode.LOW_COVERAGE)
    fingerprint = BehavioralFingerprint.model_validate_json(
        Path(
            "packages/qfr_eval/src/qfr_eval/private_contracts/BehavioralFingerprint.valid.json"
        ).read_bytes()
    ).model_copy(
        update={
            "artifact_version_id": str(request.artifact_version_id),
            "content_hash": request.content_hash,
            "protocol_hash": request.protocol_hash,
            "snapshot_id": request.snapshot_id,
            "epoch_id": request.epoch_id,
        }
    )
    clusters = cluster_trials(
        [run.summary.observation], {str(trial_id): fingerprint}, protocol.diagnostics
    )
    store = EvidenceStore(tmp_path / "evidence")
    with eval_connect() as conn:
        with pytest.raises(RuntimeError), conn.transaction():
            persist_run(
                conn,
                request,
                protocol,
                snapshot,
                run,
                [],
                {},
                store,
                principal="rollback-test",
                request_id=request_id,
                fingerprint=fingerprint,
                clusters=clusters,
                frozen_fingerprints={},
            )
            raise RuntimeError("injected failure after every insert")
        for table in [
            "runs",
            "metrics",
            "series_files",
            "official_records",
            "trial_ledger",
            "fingerprints",
            "trial_clusters",
            "events",
        ]:
            assert conn.execute(
                f"SELECT count(*) FROM eval.{table} WHERE request_id=%s", [request_id]
            ).fetchone() == (0,)
        # Reusable private objects may remain; no committed DB reference claims success.
        assert list(store.objects.iterdir())


@pytest.mark.pilot
def test_real_pilot_measurement_uses_approved_windows_and_no_confirmation(pilot_sources):
    _, tables, _ = pilot_sources
    protocol, request, _ = request_fixture()
    run = measure_pilot(
        request,
        protocol,
        tables,
        trial_id=str(uuid4()),
        prior=[],
        prior_deltas={},
        effective_trials=None,
    )
    assert run.summary.status == "complete" and run.summary.period_count > 0
    assert run.summary.used_seeds and run.summary.uncertainty.draws == 10000
    assert run.summary.diagnostics["within_date_permutation"]["draws"] == 10000
    assert run.summary.diagnostics["confirmation_computed"] is False
    assert run.summary.family_statistics.raw_trials == 1
    assert run.summary.family_statistics.effective_trials is None
    for frame, _ in run.tables.values():
        for column in ("execution_date", "exit_date", "publication_date"):
            if column in frame.columns:
                assert not (frame[column] > protocol.windows["validation"].end).any()


@pytest.mark.database
@pytest.mark.pilot
def test_evl_02_06_verified_snapshot_to_real_database_and_corrupt_input_accounting(
    eval_connect, pilot_full_snapshot, tmp_path
):
    import shutil

    from qfr_core.data_layer.snapshots import Snapshot
    from qfr_eval.cluster_job import cluster_job
    from qfr_eval.protocols.store import activate_protocol, create_protocol
    from qfr_eval.service import evaluate
    from qfr_eval.statistics.clustering import BehavioralFingerprint, ClusterSnapshot

    protocol, request, _ = request_fixture()
    request = request.model_copy(update={"snapshot_id": pilot_full_snapshot.manifest.snapshot_id})
    store = EvidenceStore(tmp_path / "store")
    request_id = uuid4()
    with eval_connect() as conn:
        create_protocol(
            conn,
            Path("configs/evaluation/pilot_p0_p1_verification_v1.yaml"),
            principal="pipeline-test",
            request_id=uuid4(),
        )
        activate_protocol(
            conn,
            protocol.protocol_id,
            protocol.version,
            expected_hash=protocol.sha256,
            principal="pipeline-test",
            request_id=uuid4(),
        )
        record, receipt = evaluate(
            conn,
            request,
            pilot_full_snapshot,
            store,
            principal="pipeline-test",
            request_id=request_id,
        )
        assert record.status == "complete"
        fingerprint = BehavioralFingerprint.model_validate_json(
            store.read(receipt.files["fingerprint"])
        )
        assert len({day for day, _ in fingerprint.grid}) == 122
        clusters = ClusterSnapshot.model_validate_json(store.read(receipt.files["clusters"]))
        assert clusters.effective_trials == 1 and clusters.raw_trials == 1
        for table in ("fingerprints", "trial_clusters"):
            assert conn.execute(
                f"SELECT count(*) FROM eval.{table} WHERE request_id=%s", [request_id]
            ).fetchone() == (1,)
        cluster_request = uuid4()
        first_job = cluster_job(
            conn, request, store, principal="cluster-test", request_id=cluster_request
        )
        assert first_job == clusters
        assert record.identity.dataset_version_id == pilot_full_snapshot.manifest.snapshot_id
        assert {"record", "measurement", "context", "ledger", "periods", "markdown"} <= set(
            receipt.files
        )
        assert evaluate(
            conn,
            request,
            pilot_full_snapshot,
            store,
            principal="pipeline-test",
            request_id=request_id,
        ) == (record, receipt)
        damaged = tmp_path / "damaged" / pilot_full_snapshot.manifest.snapshot_id
        shutil.copytree(pilot_full_snapshot.path, damaged)
        snapshot = Snapshot.load(damaged)
        (damaged / snapshot.manifest.tables[0].files[0].path).write_bytes(b"damaged-test-copy")
        failed, _ = evaluate(
            conn, request, snapshot, store, principal="pipeline-test", request_id=uuid4()
        )
        assert failed.status == "failed" and failed.reason_codes == [ReasonCode.LOW_COVERAGE]
        latest = cluster_job(conn, request, store, principal="cluster-test", request_id=uuid4())
        assert latest.status == "insufficient_data" and latest.raw_trials == 2
        assert latest.effective_trials is None and len(latest.missing_trials) == 1
        assert (
            cluster_job(conn, request, store, principal="cluster-test", request_id=cluster_request)
            == first_job
        )
        assert conn.execute(
            "SELECT count(*) FROM eval.trial_ledger WHERE payload->>'program_id'=%s",
            [request.program_id],
        ).fetchone() == (2,)


@pytest.mark.database
@pytest.mark.pilot
def test_evl_04_cli_reproduces_frozen_record_despite_later_trials(
    eval_connect, pilot_full_snapshot, tmp_path, monkeypatch
):
    import json
    import os
    import subprocess
    import sys
    from uuid import UUID

    from qfr_eval.protocols.store import activate_protocol, create_protocol
    from qfr_eval.reproduce import reproduce
    from qfr_eval.service import evaluate

    protocol, request, _ = request_fixture()
    request = request.model_copy(update={"snapshot_id": pilot_full_snapshot.manifest.snapshot_id})
    store = EvidenceStore(tmp_path / "store")
    with eval_connect() as conn:
        create_protocol(
            conn,
            Path("configs/evaluation/pilot_p0_p1_verification_v1.yaml"),
            principal="reproduce-test",
            request_id=uuid4(),
        )
        activate_protocol(
            conn,
            protocol.protocol_id,
            protocol.version,
            expected_hash=protocol.sha256,
            principal="reproduce-test",
            request_id=uuid4(),
        )
        record, _ = evaluate(
            conn,
            request,
            pilot_full_snapshot,
            store,
            principal="reproduce-test",
            request_id=uuid4(),
        )
        assert record.status == "complete"
        later_request = uuid4()
        _, later_trial, _ = ids_for_request(later_request)
        failed = failed_measurement(request, str(later_trial), ReasonCode.LOW_COVERAGE)
        persist_run(
            conn,
            request,
            protocol,
            pilot_full_snapshot.manifest,
            failed,
            [],
            {},
            store,
            principal="reproduce-test",
            request_id=later_request,
        )
        audit_id = uuid4()
        secret_dir = Path(os.environ.get("QFR_TEST_SECRET_DIR", Path.cwd() / ".secrets"))
        # Deliberate allowlist: no provider keys or unrelated cloud environment
        # are inherited by the evaluator CLI subprocess.
        environment = {
            "PATH": str(Path(sys.executable).parent),
            "QFR_EVAL_DSN": os.environ["QFR_TEST_POSTGRES_DSN"],
            "QFR_EVAL_PASSWORD_FILE": str(secret_dir / "eval_rw_password"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONHASHSEED": "37",
            # A conflicting caller default must be restored from the counted
            # request before the child initializes Polars. Strict hashes remain.
            "POLARS_MAX_THREADS": str(request.runtime.numerical_execution.polars_threads + 1),
        }
        completed = subprocess.run(
            [
                str(Path(sys.executable).with_name("qfr")),
                "eval",
                "reproduce",
                record.record_id,
                "--snapshot",
                str(pilot_full_snapshot.path),
                "--evidence-root",
                str(store.root),
                "--principal",
                "reproduce-cli-test",
                "--request-id",
                str(audit_id),
            ],
            env=environment,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
        result = json.loads(completed.stdout)
        assert result["status"] == "match" and result["series_match"]
        assert result["fingerprint_match"] and result["clusters_match"]
        assert (
            result["expected_results_hash"] == result["actual_results_hash"] == record.results_hash
        )
        assert conn.execute(
            "SELECT count(*) FROM eval.trial_ledger WHERE payload->>'program_id'=%s",
            [request.program_id],
        ).fetchone() == (2,)
        assert conn.execute(
            "SELECT payload->>'action' FROM eval.events WHERE request_id=%s", [audit_id]
        ).fetchone() == ("reproduction_match",)
        import qfr_eval.reproduce as replay

        original = replay.measure_pilot

        def wrong(*args, **kwargs):
            measured = original(*args, **kwargs)
            return MeasuredRun(
                measured.summary.model_copy(update={"period_count": 99999}),
                measured.tables,
                measured.primary_deltas,
            )

        monkeypatch.setattr(replay, "measure_pilot", wrong)
        mismatch = reproduce(
            conn,
            UUID(record.record_id),
            pilot_full_snapshot,
            store,
            principal="mismatch-test",
            request_id=uuid4(),
        )
        assert mismatch.status == "mismatch" and mismatch.actual_results_hash != record.results_hash
