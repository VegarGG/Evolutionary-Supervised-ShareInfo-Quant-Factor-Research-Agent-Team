"""Real-DB delivery retry/rollback/auth tests over declared synthetic evidence."""

from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from qfr_core.contracts.feedback import FeedbackReadPolicy
from qfr_eval.delivery.store import DeliveryConflict, persist_delivery
from qfr_eval.feedback.app import create_app
from qfr_eval.feedback.reads import FeedbackReader
from test_delivery_checker import changed, delivery_case
from test_feedback import authority as authority_for
from test_release_preparation import ROOT

pytestmark = pytest.mark.database


def persist(factory, case, *, request_id=None, connection=None):
    def run(conn):
        return persist_delivery(
            conn,
            case.context,
            case.proposal,
            case.registry,
            case.policy,
            case.verifier,
            case.signer,
            case.store,
            principal="synthetic-delivery-worker",
            request_id=request_id or uuid4(),
        )

    if connection is not None:
        return run(connection)
    with factory() as conn:
        return run(conn)


def test_independent_delivery_retry_is_one_signed_immutable_attempt(eval_connect, tmp_path):
    case = delivery_case(eval_connect, tmp_path)
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: persist(eval_connect, case), range(3)))
    assert results[0] == results[1] == results[2] and results[0].result == "pass"
    with eval_connect() as conn:
        rows = conn.execute(
            "SELECT id,receipt_id FROM eval.delivery_attempts WHERE job_id=%s",
            [case.context.job.job_id],
        ).fetchall()
        assert len(rows) == 1 and str(rows[0][1]) == results[0].receipt_id
        for table in ("delivery_attempts", "delivery_receipts"):
            for verb in ("UPDATE", "DELETE", "TRUNCATE"):
                assert conn.execute(
                    "SELECT has_table_privilege(current_user,%s,%s)", ["eval." + table, verb]
                ).fetchone() == (False,)
        assert conn.execute(
            "SELECT count(*) FROM eval.events WHERE payload->>'entity_id'=%s", [str(rows[0][0])]
        ).fetchone() == (1,)
    case.proposal = changed(case.proposal, conclusion="empty_shortlist")
    with pytest.raises(DeliveryConflict, match="different content"):
        persist(eval_connect, case)


def test_failed_receipt_retained_and_new_proposal_needed_for_new_attempt(eval_connect, tmp_path):
    case = delivery_case(eval_connect, tmp_path)
    missing = case.proposal.released_report_refs
    case.proposal = changed(case.proposal, released_report_refs=[])
    first = persist(eval_connect, case)
    assert first.result == "fail" and persist(eval_connect, case) == first
    case.proposal = changed(case.proposal, proposal_id=str(uuid4()), released_report_refs=missing)
    second = persist(eval_connect, case)
    assert second.result == "pass" and second.receipt_id != first.receipt_id
    with eval_connect() as conn:
        assert conn.execute(
            "SELECT count(*) FROM eval.delivery_attempts WHERE job_id=%s", [case.context.job.job_id]
        ).fetchone() == (2,)


def test_failure_after_receipt_write_rolls_back_receipt_attempt_and_audit(eval_connect, tmp_path):
    case = delivery_case(eval_connect, tmp_path)
    request = uuid4()

    class Interrupt:
        def __init__(self, conn):
            self.conn = conn

        def __getattr__(self, name):
            return getattr(self.conn, name)

        def execute(self, query, params=None):
            if query.startswith("INSERT INTO eval.delivery_attempts"):
                raise RuntimeError("synthetic delivery fault after receipt")
            return self.conn.execute(query, params)

    with eval_connect() as conn:
        with pytest.raises(RuntimeError, match="synthetic delivery"):
            persist(eval_connect, case, request_id=request, connection=Interrupt(conn))
        for table in ("events", "delivery_receipts", "delivery_attempts"):
            assert conn.execute(
                f"SELECT count(*) FROM eval.{table} WHERE request_id=%s", [request]
            ).fetchone() == (0,)
    assert persist(eval_connect, case).result == "pass"


def test_delivery_feedback_is_signed_scoped_get_only_and_has_no_private_grant(
    eval_connect, tmp_path
):
    case = delivery_case(eval_connect, tmp_path)
    result = persist(eval_connect, case)
    authority, headers = authority_for(case.context.job.project_id)
    reader = FeedbackReader(
        lambda: eval_connect("feedback_ro"),
        FeedbackReadPolicy.model_validate_json(
            (ROOT / "configs/feedback/read_policy_v1.json").read_bytes()
        ),
        verifier=case.verifier,
    )
    logs = []
    url = "/v1/delivery-receipts/" + result.receipt_id
    with TestClient(create_app(reader, authority=authority, request_log=logs.append)) as client:
        assert client.get(url).status_code == 401
        response = client.get(url, headers=headers)
        assert response.status_code == 200 and response.json() == result.model_dump(mode="json")
        assert client.post(url, headers=headers, json={"result": "pass"}).status_code == 405
    wrong, headers = authority_for(str(uuid4()))
    with TestClient(create_app(reader, authority=wrong)) as client:
        assert client.get(url, headers=headers).status_code == 404
    assert all("payload" not in entry for entry in logs)
    with eval_connect("feedback_ro") as conn:
        for table in ("delivery_attempts", "delivery_receipts"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(f"SELECT * FROM eval.{table}")
        assert conn.execute("SELECT count(*) FROM feedback.delivery_receipts_v").fetchone() == (0,)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(
                "DELETE FROM feedback.delivery_receipts_v WHERE id=%s", [UUID(result.receipt_id)]
            )
        with pytest.raises(PermissionError):
            persist(eval_connect, case, connection=conn)
