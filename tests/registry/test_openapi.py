"""BND-09 and the authentication edge. No database is needed: requests are refused or
answered before any query runs."""

import io
from pathlib import Path

from qfr_core.config import logging_config, registry_config
from qfr_core.logging import JsonLogger
from qfr_registry.app import create_app
from qfr_registry.auth import TokenAuth
from qfr_registry.db import Database
from starlette.testclient import TestClient

from tests.registry_rig import LIMITS, TOKENS, headers

ALLOWED_MUTATIONS = {
    ("post", "/v1/artifacts"),
    ("post", "/v1/pools/{pool}/entries"),
    ("post", "/v1/pools/{pool}/entries/{entry_id}/events"),
}


def offline_app(tmp_path):
    logger = JsonLogger(
        "registry-api", "registry", tmp_path, logging_config(Path("configs")), stdout=io.StringIO()
    )
    # The engine is never connected: every request below is answered before a query.
    db = Database("postgresql+psycopg://nobody:none@127.0.0.1:1/none")
    return create_app(db, TokenAuth(TOKENS), registry_config(Path("configs")), LIMITS, logger)


def test_bnd_09_openapi_has_only_the_three_mutation_routes(tmp_path):
    document = offline_app(tmp_path).openapi()
    operations = {
        (method, path)
        for path, item in document["paths"].items()
        for method in item
        if method in {"get", "post", "put", "patch", "delete", "head", "options", "trace"}
    }
    mutations = {op for op in operations if op[0] != "get"}
    assert mutations == ALLOWED_MUTATIONS
    assert ("get", "/v1/pools/{pool}") in operations
    assert ("get", "/v1/artifacts") in operations


def test_bnd_09_pool_routes_reject_every_token_but_control(tmp_path):
    with TestClient(offline_app(tmp_path)) as client:
        for path in (
            "/v1/pools/factor/entries",
            "/v1/pools/factor/entries/019a35e0-0000-7000-8000-000000000001/events",
        ):
            for role in ("publisher", "reader", "evaluator"):
                response = client.post(path, json={}, headers=headers(role))
                assert response.status_code == 403, (path, role)
                assert response.json()["error"] == "FORBIDDEN_ROLE"
            assert client.post(path, json={}).status_code == 401
            bad = client.post(path, json={}, headers={"Authorization": "Bearer wrong"})
            assert bad.status_code == 401


def test_no_put_patch_or_delete_route_exists(tmp_path):
    with TestClient(offline_app(tmp_path)) as client:
        for method in ("put", "patch", "delete"):
            response = client.request(
                method,
                "/v1/artifacts/019a35e0-0000-7000-8000-000000000001",
                headers=headers("control"),
            )
            assert response.status_code == 405


def test_tokens_must_be_distinct_and_complete():
    import pytest

    with pytest.raises(ValueError):
        TokenAuth(TOKENS | {"reader": TOKENS["control"]})
    with pytest.raises(ValueError):
        TokenAuth(TOKENS | {"evaluator": ""})


def test_oversized_bodies_are_refused_and_errors_carry_the_request_id(tmp_path):
    with TestClient(offline_app(tmp_path)) as client:
        response = client.post(
            "/v1/artifacts",
            content=b"x" * (1048576 + 1),
            headers=headers("publisher", **{"X-Request-Id": "req-big"}),
        )
        assert response.status_code == 413
        assert response.json() == {
            "error": "BODY_TOO_LARGE",
            "message": "the request body is too large",
            "request_id": "req-big",
            "details": [],
        }
        assert response.headers["X-Request-Id"] == "req-big"
