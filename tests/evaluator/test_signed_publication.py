"""Real database/cryptography with synthetic measurements and declared source clocks."""

import json
import os
import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from qfr_core.access import ServicePrincipal
from qfr_core.contracts.feedback import FeedbackReadPolicy
from qfr_core.contracts.reports import ReleasedReport
from qfr_core.signatures import SignatureRejected
from qfr_eval.admin.cli import main as admin_main
from qfr_eval.artifact_store import EvidenceStore
from qfr_eval.feedback.reads import FeedbackReader
from qfr_eval.release.publish import publish_one
from qfr_eval.release.store import enqueue_source
from qfr_eval.scheduler.dedup import digest
from qfr_eval.signing import EvaluatorSigner
from test_release_preparation import ROOT, pilot_policy, store_pilot

pytestmark = pytest.mark.database


def keys():
    signer = EvaluatorSigner(
        secrets.token_bytes(32), purposes=["released_report", "measurement_receipt"]
    )
    return signer, signer.verifier(maximum_document_bytes=1048576)


def source(factory, store, *, future=False, ordinal=1, policy_version=2):
    at = datetime.now(UTC) + (timedelta(days=1) if future else -timedelta(hours=7))
    with factory() as conn:
        policy = pilot_policy(conn, version=policy_version)
        record, request = store_pilot(conn, completed_at=at, evidence_store=store, ordinal=ordinal)
        queue = enqueue_source(
            conn,
            "official_record",
            UUID(record.record_id),
            policy.sha256,
            principal="synthetic",
            request_id=uuid4(),
        )
        frozen = conn.execute(
            "SELECT payload FROM eval.official_records WHERE id=%s", [record.record_id]
        ).fetchone()[0]
    return queue, record, request, frozen


def publish(factory, queue, store, signer, verifier, *, request_id=None):
    with factory() as conn:
        return publish_one(
            conn,
            queue,
            signer,
            verifier,
            principal="synthetic-evaluator",
            request_id=request_id or uuid4(),
            evidence_store=store,
        )


def test_atomic_signed_publication_concurrent_retry_and_original_receipt_unchanged(
    eval_connect, tmp_path
):
    store, (signer, verifier) = EvidenceStore(tmp_path / "evidence"), keys()
    queue, record, request, frozen = source(eval_connect, store)
    with ThreadPoolExecutor(max_workers=3) as pool:
        reports = list(
            pool.map(lambda _: publish(eval_connect, queue, store, signer, verifier), range(3))
        )
    assert reports[0] == reports[1] == reports[2]
    report = verifier.report(reports[0])
    assert report.content.hurdle_flags.overall == "fail"
    assert report.content.minimum_detectable_effect.value is not None
    with eval_connect() as conn:
        assert (
            conn.execute(
                "SELECT payload FROM eval.official_records WHERE id=%s", [record.record_id]
            ).fetchone()[0]
            == frozen
        )
        assert conn.execute(
            "SELECT count(*) FROM eval.release_publications WHERE queue_id=%s", [queue]
        ).fetchone() == (1,)
        wrapper, sha = conn.execute(
            "SELECT payload,payload_sha256 FROM eval.signed_measurement_receipts "
            "WHERE official_record_id=%s",
            [record.record_id],
        ).fetchone()
        assert wrapper["receipt"] == frozen["receipt"] and digest(wrapper) == sha
        assert wrapper["receipt"]["authenticity"] == "internal_unsigned"
        assert conn.execute(
            "SELECT count(*) FROM eval.ladder_state WHERE "
            "payload->'scalar'->>'origin_artifact_version_id'=%s",
            [str(request.artifact_version_id)],
        ).fetchone() == (1,)
    reader = FeedbackReader(
        lambda: eval_connect("feedback_ro"),
        FeedbackReadPolicy.model_validate_json(
            (ROOT / "configs/feedback/read_policy_v1.json").read_bytes()
        ),
        verifier=verifier,
    )
    principal = ServicePrincipal(
        "test-reader", "feedback", frozenset({"reader"}), frozenset({request.program_id})
    )
    assert reader.get(principal, UUID(report.report_id)) == report


def assert_pending(conn, queue, record, request_id):
    assert conn.execute(
        "SELECT state,published_report_id FROM eval.release_queue WHERE id=%s", [queue]
    ).fetchone() == ("pending", None)
    assert conn.execute(
        "SELECT count(*) FROM eval.release_publications WHERE queue_id=%s", [queue]
    ).fetchone() == (0,)
    assert conn.execute(
        "SELECT count(*) FROM eval.signed_measurement_receipts WHERE official_record_id=%s",
        [record.record_id],
    ).fetchone() == (0,)
    assert conn.execute(
        "SELECT count(*) FROM eval.events WHERE request_id=%s", [request_id]
    ).fetchone() == (0,)


def test_failure_after_ladder_write_rolls_back_all_publication_and_audit(eval_connect, tmp_path):
    store, (signer, verifier) = EvidenceStore(tmp_path / "evidence"), keys()
    queue, record, request, _ = source(eval_connect, store)
    request_id = uuid4()

    class InterruptBeforeLedger:
        def __init__(self, conn):
            self.conn = conn

        def __getattr__(self, name):
            return getattr(self.conn, name)

        def execute(self, sql, params=None):
            if "INSERT INTO eval.release_publications" in sql:
                raise RuntimeError("synthetic publication fault after Ladder write")
            return self.conn.execute(sql, params)

    with eval_connect() as conn:
        with pytest.raises(RuntimeError, match="after Ladder"):
            publish_one(
                InterruptBeforeLedger(conn),
                queue,
                signer,
                verifier,
                principal="synthetic",
                request_id=request_id,
                evidence_store=store,
            )
        assert_pending(conn, queue, record, request_id)
        assert conn.execute(
            "SELECT count(*) FROM eval.ladder_state WHERE "
            "payload->'scalar'->>'origin_artifact_version_id'=%s",
            [str(request.artifact_version_id)],
        ).fetchone() == (0,)
    assert publish(eval_connect, queue, store, signer, verifier).report_id


def test_future_batch_and_untrusted_signer_fail_before_visibility(eval_connect, tmp_path):
    store, (signer, verifier) = EvidenceStore(tmp_path / "evidence"), keys()
    future, record, _, _ = source(eval_connect, store, future=True)
    request_id = uuid4()
    with pytest.raises(ValueError, match="not due"):
        publish(eval_connect, future, store, signer, verifier, request_id=request_id)
    with eval_connect() as conn:
        assert_pending(conn, future, record, request_id)
    queue, record, _, _ = source(eval_connect, store)
    _, other = keys()
    with pytest.raises(SignatureRejected, match="unknown key"):
        publish(eval_connect, queue, store, signer, other, request_id=request_id)
    with eval_connect() as conn:
        assert_pending(conn, queue, record, request_id)


def test_corrupt_private_evidence_and_legacy_policy_do_not_get_signed(eval_connect, tmp_path):
    store, (signer, verifier) = EvidenceStore(tmp_path / "evidence"), keys()
    queue, record, _, body = source(eval_connect, store)
    item = next(iter(body["receipt"]["files"].values()))
    (store.root / item["relative_path"]).write_bytes(b"synthetic-tamper")
    request_id = uuid4()
    with pytest.raises(ValueError):
        publish(eval_connect, queue, store, signer, verifier, request_id=request_id)
    with eval_connect() as conn:
        assert_pending(conn, queue, record, request_id)
    queue, _, _, _ = source(eval_connect, store, policy_version=1)
    with pytest.raises(ValueError, match="revision 2"):
        publish(eval_connect, queue, store, signer, verifier)


def test_signed_withheld_attempt_discloses_no_outcomes(eval_connect, tmp_path):
    store, (signer, verifier) = EvidenceStore(tmp_path / "evidence"), keys()
    queue, _, _, _ = source(eval_connect, store, ordinal=4)
    report = publish(eval_connect, queue, store, signer, verifier)
    assert report.content.model_dump() == {"type": "withheld", "reason": "budget"}
    assert not report.flags and not report.reason_codes
    assert isinstance(verifier.report(report), ReleasedReport)


def test_owner_cli_receipt_and_bounded_program_publication(
    eval_connect, tmp_path, monkeypatch, capsys
):
    material = secrets.token_bytes(32)
    signer = EvaluatorSigner(material, purposes=["released_report", "measurement_receipt"])
    verifier = signer.verifier(maximum_document_bytes=1048576)
    key_path, trust_path = tmp_path / "ephemeral-key", tmp_path / "trust.json"
    key_path.write_bytes(material)
    key_path.chmod(0o600)
    trust_path.write_text(verifier.policy.model_dump_json())
    store = EvidenceStore(tmp_path / "evidence")
    queue, record, request, _ = source(eval_connect, store)
    other_queue, _, _, _ = source(eval_connect, store)
    monkeypatch.setenv("QFR_EVAL_DSN", os.environ["QFR_TEST_POSTGRES_DSN"])
    monkeypatch.setenv(
        "QFR_EVAL_PASSWORD_FILE",
        str(ROOT / ".secrets/eval_rw_password")
        if not os.environ.get("QFR_TEST_SECRET_DIR")
        else os.environ["QFR_TEST_SECRET_DIR"] + "/eval_rw_password",
    )
    common = [
        "--signing-key",
        str(key_path),
        "--verification-policy",
        str(trust_path),
        "--evidence-root",
        str(store.root),
        "--principal",
        "synthetic-evaluator",
        "--request-id",
        str(uuid4()),
    ]
    admin_main(["sign-receipt", "--record-id", record.record_id, *common])
    assert json.loads(capsys.readouterr().out) == {"signed_record_id": record.record_id}
    with eval_connect() as conn:
        policy = pilot_policy(conn, version=2)
    admin_main(
        [
            "release-ready",
            "--policy-sha256",
            policy.sha256,
            "--program-id",
            request.program_id,
            "--limit",
            "10",
            *common,
        ]
    )
    result = json.loads(capsys.readouterr().out)
    assert len(result["published_report_ids"]) == 1
    with eval_connect() as conn:
        assert conn.execute(
            "SELECT state FROM eval.release_queue WHERE id=%s", [queue]
        ).fetchone() == ("published",)
        assert conn.execute(
            "SELECT state FROM eval.release_queue WHERE id=%s", [other_queue]
        ).fetchone() == ("pending",)
    admin_main(
        [
            "release-ready",
            "--policy-sha256",
            policy.sha256,
            "--program-id",
            request.program_id,
            "--limit",
            "10",
            *common,
        ]
    )
    assert json.loads(capsys.readouterr().out) == {"published_report_ids": []}
