"""Read-boundary tests with synthetic structural reports, not signed acceptance.

The signing package adds cryptographic publication tests. These fixtures use
explicit source clocks to test DB visibility; no elapsed wait is claimed.
"""

import json
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb
from qfr_core.access import BearerAuthority, ServicePrincipal
from qfr_core.contracts.access import ServiceAuthentication
from qfr_core.contracts.feedback import FeedbackReadPolicy
from qfr_core.contracts.reports import ReleasedReport
from qfr_eval.feedback.app import create_app
from qfr_eval.feedback.reads import FeedbackReader, FeedbackUnavailable
from qfr_eval.release.cards import publish_policy_cards
from qfr_eval.release.store import enqueue_source
from test_release_database import stock_policy, store_stock_record, subject
from test_release_preparation import pilot_policy

pytestmark = pytest.mark.database
ROOT = Path(__file__).resolve().parents[2]


def authority(program):
    token = secrets.token_urlsafe(32)
    config = ServiceAuthentication.model_validate(
        dict(
            revision=1,
            audience="feedback",
            minimum_token_bytes=32,
            maximum_token_bytes=4096,
            bindings=[
                dict(
                    principal="synthetic-reader",
                    token_ref="env:SYNTHETIC_FEEDBACK_TOKEN",
                    roles=["reader"],
                    programs=[program],
                )
            ],
        )
    )
    return BearerAuthority(config, {"SYNTHETIC_FEEDBACK_TOKEN": token}), {
        "Authorization": "Bearer " + token
    }


def reader(factory, **changes):
    policy = FeedbackReadPolicy.model_validate_json(
        (ROOT / "configs/feedback/read_policy_v1.json").read_bytes()
    )
    return FeedbackReader(lambda: factory("feedback_ro"), policy.model_copy(update=changes))


def fixture_report(conn, program, *, kind="screening", publication=True, future=False, extra=None):
    policy = stock_policy(conn)
    item = subject(program=program)
    record = store_stock_record(
        conn,
        item,
        completed_at=datetime.now(UTC) + (timedelta(days=1) if future else -timedelta(hours=7)),
    )
    queue = enqueue_source(
        conn,
        "official_record",
        record.record_id,
        policy.sha256,
        principal="synthetic-test-only",
        request_id=uuid4(),
    )
    value = json.loads((ROOT / "contracts/examples/ReleasedReport.valid.json").read_bytes())
    report_id = uuid4()
    content = (
        dict(type="library", membership="active")
        if kind == "library"
        else dict(type="screening", status="pass")
    )
    value.update(
        report_id=str(report_id),
        identity=record.identity.model_dump(mode="json"),
        program_id=program,
        family_id=item.family_id,
        content=content,
        released_at=datetime.now(UTC).isoformat(),
        reason_codes=[],
        flags=[],
    )
    report = ReleasedReport.model_validate(value)
    if extra:
        value.update(extra)
    with conn.transaction():
        conn.execute(
            "INSERT INTO eval.released_reports(id,payload,created_by,request_id,"
            "artifact_version_id,content_hash,protocol_version,dataset_version_id,"
            "evaluator_version) "
            "VALUES(%s,%s,'synthetic-test-only',%s,%s,%s,%s,%s,%s)",
            [
                report_id,
                Jsonb(value),
                uuid4(),
                item.artifact_version_id,
                record.identity.content_hash,
                record.identity.protocol_version,
                record.identity.dataset_version_id,
                record.identity.evaluator_version,
            ],
        )
        if publication:
            conn.execute(
                "INSERT INTO eval.release_publications(id,queue_id,payload,created_by,"
                "request_id,numeric_values) VALUES(%s,%s,%s,'synthetic-test-only',%s,0)",
                [report_id, queue, Jsonb({"fixture": "structural_read_test_only"}), uuid4()],
            )
            conn.execute(
                "UPDATE eval.release_queue SET state='published',published_report_id=%s "
                "WHERE id=%s",
                [report_id, queue],
            )
    return report


def test_bnd_03_every_openapi_operation_is_get_and_all_writes_refused(eval_connect):
    principal = str(uuid4())
    auth, headers = authority(principal)
    events = []
    client = TestClient(create_app(reader(eval_connect), authority=auth, request_log=events.append))
    paths = client.get("/openapi.json").json()["paths"]
    assert paths and all(set(operations) == {"get"} for operations in paths.values())
    assert not any(
        word in str(paths).lower() for word in ("eval-admin", "official_record", "cancel", "quota")
    )
    for method in ("post", "put", "patch", "delete", "head", "options", "trace"):
        response = client.request(method, "/v1/reports", headers=headers)
        assert response.status_code == 405
    assert client.get("/v1/reports").status_code == 401
    assert client.get("/v1/reports", headers={"Authorization": "Bearer bad"}).status_code == 401
    assert client.get("/v1/reports", headers=headers).status_code == 200
    assert client.get("/v1/official-records", headers=headers).status_code == 404
    assert headers["Authorization"] not in json.dumps(events)
    assert all(event["request_id"] for event in events)
    assert any(event["principal"] == "synthetic-reader" for event in events)


def test_program_scoped_pagination_filters_and_reconnect_retain_only_released_rows(eval_connect):
    one, two = str(uuid4()), str(uuid4())
    with eval_connect() as conn:
        reports = [fixture_report(conn, one) for _ in range(3)]
        other = fixture_report(conn, two)
        unsigned = fixture_report(conn, one, publication=False)
        early = fixture_report(conn, one, future=True)
    auth, headers = authority(one)
    client = TestClient(
        create_app(
            reader(eval_connect, max_page_size=2), authority=auth, request_log=lambda _: None
        )
    )
    first = client.get("/v1/reports", headers=headers).json()
    assert [r["report_id"] for r in first["items"]] == [r.report_id for r in reports[:2]]
    assert first["has_more"]
    client.close()
    with TestClient(
        create_app(
            reader(eval_connect, max_page_size=2), authority=auth, request_log=lambda _: None
        )
    ) as client:
        second = client.get(
            "/v1/reports", params={"after_id": first["next_after_id"]}, headers=headers
        ).json()
        assert [r["report_id"] for r in second["items"]] == [reports[2].report_id]
        assert not second["has_more"]
        for item in (other, unsigned, early):
            assert client.get("/v1/reports/" + item.report_id, headers=headers).status_code == 404
        assert (
            client.get(
                "/v1/reports", params={"after_id": other.report_id}, headers=headers
            ).status_code
            == 404
        )
        assert client.get("/v1/reports", params={"limit": 3}, headers=headers).status_code == 400
        found = client.get(
            "/v1/reports",
            params={"version_id": reports[0].identity.artifact_version_id},
            headers=headers,
        ).json()
        assert len(found["items"]) == 1
        found = client.get(
            "/v1/reports", params={"family_id": reports[1].family_id}, headers=headers
        ).json()
        assert len(found["items"]) == 1
        assert (
            client.get("/v1/reports", params={"since": "2026-10-01"}, headers=headers).status_code
            == 400
        )
        status = client.get(
            "/v1/artifacts/" + reports[0].identity.artifact_version_id + "/status", headers=headers
        ).json()
        assert status["latest_released"]["report_id"] == reports[0].report_id
        hidden = client.get(
            "/v1/artifacts/" + other.identity.artifact_version_id + "/status", headers=headers
        ).json()
        assert hidden["latest_released"] is None and hidden["timeline"]["items"] == []


def test_library_is_released_only_and_cards_exclude_private_configuration(eval_connect):
    program = str(uuid4())
    with eval_connect() as conn:
        report = fixture_report(conn, program, kind="library")
        policy = pilot_policy(conn)
        first = publish_policy_cards(
            conn, policy.sha256, principal="synthetic-owner", request_id=uuid4()
        )
        assert (
            publish_policy_cards(
                conn, policy.sha256, principal="synthetic-owner", request_id=uuid4()
            )
            == first
        )
    auth, headers = authority(program)
    with TestClient(
        create_app(reader(eval_connect), authority=auth, request_log=lambda _: None)
    ) as client:
        result = client.get("/v1/library", headers=headers).json()
        assert [r["report_id"] for r in result["items"]] == [report.report_id]
        card = client.get(
            "/v1/cards/policy",
            params={"ref": f"{policy.policy_id}@{policy.version}"},
            headers=headers,
        )
        assert card.status_code == 200
        assert card.json()["policies"][0]["ladder_step"] == policy.ladder_step
        assert not any(
            key in card.json()["policies"][0]
            for key in ("windows", "protocol_sha256", "confirmation_queries_per_protocol")
        )
        with eval_connect() as conn:
            ref = conn.execute(
                "SELECT protocol_id||'@'||version FROM eval.protocols WHERE sha256=%s",
                [policy.protocol_sha256],
            ).fetchone()[0]
        protocol = client.get("/v1/cards/protocol", params={"ref": ref}, headers=headers)
        assert (
            protocol.status_code == 200
            and protocol.json()["protocols"][0]["exposure"] == "previously_seen"
        )
        assert "2020-01-01" not in protocol.text and "bootstrap" not in protocol.text


def test_wrong_database_role_corrupt_or_oversized_rows_fail_closed(eval_connect):
    program = str(uuid4())
    principal = ServicePrincipal("reader", "feedback", frozenset({"reader"}), frozenset({program}))
    wrong = FeedbackReader(eval_connect, reader(eval_connect).policy)
    with pytest.raises(FeedbackUnavailable, match="read-only database role"):
        wrong.page(principal, limit=1)
    with eval_connect() as conn:
        corrupt = fixture_report(conn, program, extra={"private_w3_marker": 0.987})
        good = fixture_report(conn, program)
    auth, headers = authority(program)
    with TestClient(
        create_app(reader(eval_connect), authority=auth, request_log=lambda _: None)
    ) as client:
        response = client.get("/v1/reports/" + corrupt.report_id, headers=headers)
        assert response.status_code == 503
        assert "private_w3_marker" not in response.text and "0.987" not in response.text
    with pytest.raises(FeedbackUnavailable, match="bounds"):
        reader(eval_connect, max_page_bytes=100).get(principal, UUID(good.report_id))


def test_reader_connections_restore_program_context_and_remain_read_only(eval_connect):
    program = str(uuid4())
    principal = ServicePrincipal("reader", "feedback", frozenset({"reader"}), frozenset({program}))
    import psycopg

    service = reader(eval_connect)
    with service.scoped(principal) as conn:
        assert conn.execute("SHOW transaction_read_only").fetchone() == ("on",)
        assert conn.execute("SELECT current_setting('qfr.program_ids')").fetchone() == (program,)
        with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
            conn.execute("SELECT * FROM eval.official_records")
    with eval_connect("feedback_ro") as conn:
        assert conn.execute(
            "SELECT coalesce(current_setting('qfr.program_ids',true),'')"
        ).fetchone() == ("",)
        assert conn.execute("SELECT count(*) FROM feedback.released_reports_v").fetchone() == (0,)
