"""All tests are offline except explicitly configured local database/socket checks."""

import socket

import pytest


@pytest.fixture(autouse=True, scope="session")
def forbid_model_requests():
    """No test reaches an LLM provider: PydanticAI refuses every real model request, and
    research tests use scripted FunctionModels (P4.12)."""
    import pydantic_ai.models

    pydantic_ai.models.ALLOW_MODEL_REQUESTS = False
    yield


@pytest.fixture(autouse=True)
def forbid_external_network(monkeypatch):
    original = socket.socket.connect

    def local_only(sock, address):
        if isinstance(address, tuple) and address[0] not in {
            "127.0.0.1",
            "::1",
            "localhost",
            "postgres",
        }:
            raise AssertionError("Tests must not call external services or real LLM providers")
        return original(sock, address)

    monkeypatch.setattr(socket.socket, "connect", local_only)


@pytest.fixture(scope="session")
def small_zones(tmp_path_factory):
    """The small planted world written as full and research snapshots."""
    from tests.synthetic_fixtures import build_small_zones

    return build_small_zones(tmp_path_factory.mktemp("snapshots"), "planted")


@pytest.fixture(scope="session")
def replay_zones(tmp_path_factory):
    """The 800-day planted world with a replay tail after W3 (Phase 6 incubation)."""
    from tests.synthetic_fixtures import build_small_zones

    return build_small_zones(tmp_path_factory.mktemp("replay-snapshots"), "planted", replay=True)
