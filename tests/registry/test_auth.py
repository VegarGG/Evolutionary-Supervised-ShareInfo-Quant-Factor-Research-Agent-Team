import json
import secrets
import socket
import threading
import time
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient
from qfr_core.contracts.publication import RegistryAuthenticationConfiguration
from qfr_registry.api.app import create_app
from qfr_registry.auth import StaticTokenAuthorizer
from qfr_registry.policy import RegistryReadPolicy


@pytest.fixture
def authentication(program):
    roles = ("publisher", "reader", "evaluator", "outside")
    values = {role.upper() + "_TOKEN": secrets.token_urlsafe(32) for role in roles}
    config = RegistryAuthenticationConfiguration(
        revision=1,
        enabled=True,
        minimum_token_bytes=32,
        maximum_token_bytes=512,
        bindings=[
            {
                "principal": "fixture-" + role,
                "token_ref": "env:" + role.upper() + "_TOKEN",
                "roles": ["reader" if role == "outside" else role],
                "programs": ["different-program" if role == "outside" else program],
            }
            for role in roles
        ],
    )
    return config, values


@pytest.fixture
def authenticated_app(registry_service, authentication):
    config, values = authentication
    events = []
    app = create_app(
        registry_service,
        authorize=StaticTokenAuthorizer(config, values),
        request_log=events.append,
        read_policy=RegistryReadPolicy.model_validate_json(
            Path("configs/registry/read_v1.json").read_bytes()
        ),
    )
    return app, events


def headers(authentication, role="publisher"):
    return {"authorization": "Bearer " + authentication[1][role.upper() + "_TOKEN"]}


def test_missing_invalid_and_reused_token_values_fail_without_echo(authentication):
    config, values = authentication
    reference = next(iter(values))
    for value in (None, "", "too-short", "x" * 513, "x" * 32 + "\n", "密" * 32):
        environment = dict(values)
        if value is None:
            environment.pop(reference)
        else:
            environment[reference] = value
        with pytest.raises(ValueError, match="token is missing or invalid") as caught:
            StaticTokenAuthorizer(config, environment)
        assert str(caught.value) == "configured registry token is missing or invalid"
    environment = {key: values[reference] for key in values}
    with pytest.raises(ValueError, match="distinct principals"):
        StaticTokenAuthorizer(config, environment)
    authorizer = StaticTokenAuthorizer(config, values)
    assert all(value not in repr(authorizer.tokens) for value in values.values())


def test_authentication_configuration_has_no_implicit_grants(authentication):
    config, _ = authentication
    value = config.model_dump(mode="json")
    for field, invalid in (("roles", ["owner"]), ("programs", ["*"]), ("programs", [" "])):
        body = json.loads(json.dumps(value))
        body["bindings"][0][field] = invalid
        with pytest.raises(ValueError):
            RegistryAuthenticationConfiguration.model_validate(body)
    for update in ({"enabled": False}, {"bindings": []}, {"maximum_token_bytes": 31}):
        with pytest.raises(ValueError):
            RegistryAuthenticationConfiguration.model_validate({**value, **update})
    with pytest.raises(ValueError, match="unique"):
        RegistryAuthenticationConfiguration.model_validate(
            {**value, "bindings": value["bindings"] * 2}
        )
    disabled = RegistryAuthenticationConfiguration.model_validate_json(
        Path("configs/registry/authentication_v1.json").read_bytes()
    )
    assert not disabled.enabled and not StaticTokenAuthorizer(disabled, {}).tokens


def test_default_request_log_emits_without_external_logging_configuration(registry_service, capsys):
    identity = str(uuid4())
    response = TestClient(create_app(registry_service)).get(
        "/healthz?private=query",
        headers={
            "x-request-id": identity,
            "authorization": "Bearer synthetic-private-header",
        },
    )
    assert response.status_code == 200 and response.headers["x-request-id"] == identity
    captured = capsys.readouterr().err
    record = json.loads(captured)
    assert record["request_id"] == identity and record["principal"] == "anonymous"
    assert record["route"] == "/healthz" and record["status"] == 200
    assert "private" not in captured


@pytest.mark.database
def test_bearer_header_only_and_all_failures_have_attributed_request_ids(
    authentication, authenticated_app, draft
):
    app, events = authenticated_app
    client = TestClient(app)
    good = headers(authentication)
    for supplied in (
        {},
        {"authorization": "Bearer unknown"},
        {"authorization": "Basic " + "x" * 32},
        [("authorization", good["authorization"])] * 2,
    ):
        response = client.post(
            "/v1/artifacts", json=draft().model_dump(mode="json"), headers=supplied
        )
        assert response.status_code == 401 and response.headers["www-authenticate"] == "Bearer"
        assert UUID(response.headers["x-request-id"])
        assert events[-1]["principal"] == "anonymous" and events[-1]["status"] == 401
    token = authentication[1]["PUBLISHER_TOKEN"]
    assert client.get("/v1/artifacts?since_seq=0&limit=1&token=" + token).status_code == 401
    assert token not in json.dumps(events)
    for request_ids in (
        {"x-request-id": "invalid-and-private"},
        [("x-request-id", str(uuid4()))] * 2,
    ):
        response = client.get("/healthz", headers=request_ids)
        assert response.status_code == 400 and UUID(response.headers["x-request-id"])
    assert "invalid-and-private" not in json.dumps(events)
    assert all(datetime.fromisoformat(event["at"]).tzinfo for event in events)


@pytest.mark.database
def test_roles_programs_and_publisher_attribution_cannot_be_forged(
    authentication, authenticated_app, draft, registry_connect
):
    app, events = authenticated_app
    client = TestClient(app)
    body = draft().model_dump(mode="json")
    for role in ("reader", "evaluator", "outside"):
        assert (
            client.post(
                "/v1/artifacts", json=body, headers=headers(authentication, role)
            ).status_code
            == 403
        )
    request_id = uuid4()
    response = client.post(
        "/v1/artifacts",
        json=body,
        headers={
            **headers(authentication),
            "x-request-id": str(request_id),
        },
    )
    assert response.status_code == 201
    artifact = response.json()["artifact"]
    assert artifact["manifest"]["created_by"] == "fixture-publisher"
    assert response.headers["x-request-id"] == str(request_id)
    assert events[-1]["principal"] == "fixture-publisher"
    assert events[-1]["request_id"] == str(request_id)
    with registry_connect() as conn:
        writes = conn.execute(
            "SELECT created_by,request_id,created_at,payload FROM registry.registry_events "
            "WHERE request_id=%s",
            [request_id],
        ).fetchall()
    assert len(writes) == 4  # Family, canonical payload, version, idempotency receipt.
    assert all(w[0] == "fixture-publisher" and w[1] == request_id and w[2].tzinfo for w in writes)
    for role in ("publisher", "reader", "evaluator"):
        assert (
            client.get(
                "/v1/artifacts/" + artifact["manifest"]["artifact_version_id"],
                headers=headers(authentication, role),
            ).status_code
            == 200
        )
    assert (
        client.get(
            "/v1/artifacts/" + artifact["manifest"]["artifact_version_id"],
            headers=headers(authentication, "outside"),
        ).status_code
        == 404
    )
    listing = "/v1/artifacts?since_seq=0&limit=1"
    assert client.get(listing, headers=headers(authentication)).status_code == 403
    assert client.get(listing, headers=headers(authentication, "evaluator")).status_code == 200
    body["manifest"]["created_by"] = "forged-owner"
    assert (
        client.post("/v1/artifacts", json=body, headers=headers(authentication)).status_code == 400
    )
    assert all(value not in json.dumps(events) for value in authentication[1].values())
    assert "forged-owner" not in json.dumps(events)


@pytest.mark.database
def test_request_logging_covers_oversized_unknown_and_failed_requests(
    authentication, authenticated_app, registry_service, draft, monkeypatch
):
    app, events = authenticated_app
    client = TestClient(app, raise_server_exceptions=False)
    request_id = str(uuid4())
    client.get("/unknown-private-path?private=value", headers={"x-request-id": request_id})
    assert events[-1]["route"] == "unmatched" and events[-1]["status"] == 404
    assert events[-1]["request_id"] == request_id
    client.post("/v1/artifacts", content=b"x" * (registry_service.policy.max_request_bytes + 1))
    assert events[-1]["status"] == 413

    def fail(*args):
        raise RuntimeError("controlled-private-error")

    monkeypatch.setattr(registry_service, "publish", fail)
    response = client.post(
        "/v1/artifacts", json=draft().model_dump(mode="json"), headers=headers(authentication)
    )
    assert response.status_code == 500
    assert events[-1]["principal"] == "fixture-publisher" and events[-1]["status"] == 500
    assert all(
        value not in json.dumps(events)
        for value in (
            "unknown-private-path",
            "private=value",
            "controlled-private-error",
        )
    )


@pytest.mark.database
def test_real_loopback_http_publication_read_and_retry_audit(
    authenticated_app, authentication, draft, registry_connect
):
    app, events = authenticated_app
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        address = listener.getsockname()
        server = uvicorn.Server(
            uvicorn.Config(
                app,
                log_config=None,
                access_log=False,
                lifespan="off",
                timeout_keep_alive=1,
            )
        )
        worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        worker.start()
        try:
            deadline = time.monotonic() + 5
            while not server.started and worker.is_alive() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert server.started
            with httpx.Client(
                base_url=f"http://127.0.0.1:{address[1]}", timeout=5, trust_env=False
            ) as client:
                body = draft().model_dump(mode="json")
                first = client.post("/v1/artifacts", json=body, headers=headers(authentication))
                assert first.status_code == 201
                retry_id = str(uuid4())
                retry = client.post(
                    "/v1/artifacts",
                    json=body,
                    headers={
                        **headers(authentication),
                        "x-request-id": retry_id,
                    },
                )
                assert (
                    retry.status_code == 200
                    and retry.json()["artifact"] == first.json()["artifact"]
                )
                identity = first.json()["artifact"]["manifest"]["artifact_version_id"]
                fetched = client.get(
                    "/v1/artifacts/" + identity, headers=headers(authentication, "evaluator")
                )
                assert fetched.status_code == 200 and fetched.json() == first.json()["artifact"]
            with registry_connect() as conn:
                row = conn.execute(
                    "SELECT created_by,payload->>'action' FROM registry.registry_events "
                    "WHERE request_id=%s",
                    [UUID(retry_id)],
                ).fetchone()
            assert row == ("fixture-publisher", "publication_retry")
            assert len(events) == 3
        finally:
            server.should_exit = True
            worker.join(timeout=5)
            assert not worker.is_alive()
