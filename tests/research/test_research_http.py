"""Real research database behind HTTP; explicit unit-only synthetic public evidence."""

import asyncio
import json
import secrets
import threading
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from qfr_core.access import BearerAuthority
from qfr_core.contracts.access import ServiceAuthentication
from qfr_core.exports import verify_export
from qfr_research.api.app import create_app
from qfr_research.api.exports import Exports
from test_delivery_acceptance import delivery_setup, seal_receipt
from test_research_jobs import changed, setup_service

pytestmark = pytest.mark.database


def auth(program, *, roles=None):
    token = secrets.token_urlsafe(32)
    config = ServiceAuthentication(
        revision=1,
        audience="research",
        minimum_token_bytes=32,
        maximum_token_bytes=256,
        bindings=[
            dict(
                principal="synthetic-http",
                token_ref="env:SYNTHETIC_TOKEN",
                roles=roles or ["research_lead"],
                programs=[str(program)],
            )
        ],
    )
    return BearerAuthority(config, {"SYNTHETIC_TOKEN": token}), {"Authorization": "Bearer " + token}


def client(case, **kwargs):
    authority, headers = auth(case.program)
    return TestClient(create_app(case.service, authority=authority, **kwargs), headers=headers)


def test_http_lost_ack_restart_conflict_and_scoped_control(research_connect, tmp_path):
    case = setup_service(research_connect, tmp_path, service_class=Exports)
    route = f"/v1/programs/{case.program}/jobs"
    value = case.admission.model_dump(mode="json")
    with client(case) as first:
        validation = first.post(f"/v1/programs/{case.program}/input-validation", json=value)
        assert validation.status_code == 200 and validation.json()["runnable"]
        result = first.post(route, json=value)
        assert result.status_code == 200, result.text
        saved = result.json()
        assert saved["job"]["state"] == "ready" and saved["revision"] == 1
    case.service = Exports(case.service.storage, case.service.evidence, case.service.research_root)
    with client(case) as second:
        assert second.post(route, json=value).json() == saved
        # Use a schema-valid change; different bytes under the same key must conflict.
        altered = changed(
            case.admission,
            input_bundle=changed(case.admission.input_bundle, objective="different objective"),
            brief=changed(case.admission.brief, objective="different objective"),
        ).model_dump(mode="json")
        assert second.post(route, json=altered).status_code == 409
        job = saved["job"]["job_id"]
        read = second.get(f"/v1/jobs/{job}")
        assert read.status_code == 200 and read.json() == saved
        action = dict(operation_key="start", expected_revision=1, action="start")
        running = second.post(f"/v1/jobs/{job}/control", json=action)
        assert running.status_code == 200 and running.json()["job"]["state"] == "running"
        assert second.post(f"/v1/jobs/{job}/control", json=action).json() == running.json()
        assert (
            second.post(
                f"/v1/jobs/{job}/control",
                json={**action, "operation_key": "other", "action": "pause"},
            ).status_code
            == 409
        )
        assert second.get(route).json()["items"][0] == running.json()
        assert second.get("/v1/programs").json()["items"][0]["program_id"] == str(case.program)
    outsider, headers = auth(uuid4())
    with TestClient(create_app(case.service, authority=outsider), headers=headers) as outside:
        assert outside.get(f"/v1/jobs/{job}").status_code == 404
        assert outside.get("/v1/programs").json()["items"] == []


def test_http_released_receipt_to_verified_export(research_connect, tmp_path):
    case = delivery_setup(research_connect, tmp_path, service_class=Exports)
    receipt = seal_receipt(case)
    with client(case) as http:
        root = f"/v1/jobs/{case.status.job.job_id}"
        candidate = http.get(root + f"/delivery-proposals/{case.proposal.proposal_id}")
        assert candidate.status_code == 200
        accepted = http.post(
            root + "/delivery-receipts",
            json=dict(
                operation_key="accept",
                expected_revision=case.status.revision,
                receipt_id=receipt.receipt_id,
                proposal_id=case.proposal.proposal_id,
            ),
        )
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["job"]["state"] == "completed"
        exported = http.post(
            root + "/exports", json=dict(operation_key="export", shortlist_only=False)
        )
        assert exported.status_code == 200, exported.text
        ref = exported.json()
        archive = http.get(ref["download_path"])
        assert archive.status_code == 200 and archive.headers["content-type"] == "application/zip"
        verify_export(
            archive.content,
            case.evidence.verifier,
            case.service.policy,
            expected_manifest_sha256=ref["manifest_sha256"],
        )


def test_http_no_admin_auth_body_and_error_boundaries(research_connect, tmp_path, monkeypatch):
    case = setup_service(research_connect, tmp_path, service_class=Exports)
    logs = []
    with client(case, request_log=logs.append) as http:
        schema = http.get("/openapi.json")
        assert schema.status_code == 200
        paths = schema.json()["paths"]
        for forbidden in [
            "evaluate",
            "priority",
            "holdout",
            "official-record",
            "protocol-freeze",
            "sign",
        ]:
            assert not any(forbidden in path for path in paths)
        route = f"/v1/programs/{case.program}/jobs"
        marker = "synthetic-private-marker"
        for content in [
            b'{"a":1,"a":2}',
            b'{"a":NaN}',
            b'{"a":',
            b"[]",
            b'{"unexpected":"' + marker.encode() + b'"}',
        ]:
            response = http.post(
                route, content=content, headers={"Content-Type": "application/json"}
            )
            assert response.status_code == 400 and marker not in response.text
        assert (
            http.post(
                route,
                content=b"x" * (case.service.policy.max_request_bytes + 1),
                headers={"Content-Type": "application/json"},
            ).status_code
            == 413
        )
        assert http.request("GET", "/v1/programs", content=b"x").status_code == 400
        assert http.delete(route).status_code == 405
        assert (
            http.post(
                route,
                json=case.admission.model_dump(mode="json"),
                headers=[
                    ("Authorization", "Bearer " + "x" * 32),
                    ("Authorization", "Bearer " + "y" * 32),
                ],
            ).status_code
            == 401
        )

        def broken(*args, **kwargs):
            raise RuntimeError(marker)

        monkeypatch.setattr(case.service, "programs", broken)
        response = http.get("/v1/programs")
        assert response.status_code == 503 and marker not in response.text
    assert logs and marker not in json.dumps(logs) and "Authorization" not in json.dumps(logs)
    assert all(
        set(log) == {"request_id", "principal", "at", "method", "route", "status"} for log in logs
    )
    with TestClient(create_app(case.service)) as disabled:
        assert disabled.get("/healthz").status_code == 200
        assert disabled.get("/openapi.json").status_code == 401
    authority, headers = auth(case.program, roles=["reader"])
    with TestClient(create_app(case.service, authority=authority), headers=headers) as reader:
        assert (
            reader.post(
                f"/v1/programs/{case.program}/jobs", json=case.admission.model_dump(mode="json")
            ).status_code
            == 403
        )


def test_cancelled_status_request_does_not_cancel_durable_job(
    research_connect, tmp_path, monkeypatch
):
    case = setup_service(research_connect, tmp_path, service_class=Exports)
    admitted = case.service.admit(case.principal, case.program, case.admission, uuid4())
    identity = UUID(admitted.job.job_id)
    started, finish = threading.Event(), threading.Event()
    original = case.service.get_job

    def delayed(*args, **kwargs):
        started.set()
        assert finish.wait(3)
        return original(*args, **kwargs)

    monkeypatch.setattr(case.service, "get_job", delayed)
    authority, headers = auth(case.program)
    app = create_app(case.service, authority=authority)

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test", headers=headers
        ) as http:
            task = asyncio.create_task(http.get(f"/v1/jobs/{identity}"))
            assert await asyncio.to_thread(started.wait, 2)
            task.cancel()
            finish.set()
            with pytest.raises(asyncio.CancelledError):
                await task

    asyncio.run(scenario())
    assert original(case.principal, identity) == admitted
