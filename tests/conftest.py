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
    from qfr_core.data.panel import sanity_checks
    from qfr_core.data.snapshot import SnapshotData, SnapshotSource, ZoneDirs
    from qfr_eval.ingest.zones import build_zones

    from tests.synthetic_fixtures import BuiltZones, small_epoch, small_world

    world = small_world()
    root = tmp_path_factory.mktemp("snapshots")
    data = SnapshotData(
        world.panel, world.membership, world.calendar, {"ground_truth.json": b"{}\n"}
    )
    source = SnapshotSource(
        "synthetic", None, None, {"world": "planted"}, {}, sanity_checks(world.panel)
    )
    research = SnapshotSource("synthetic", None, None, {}, {}, {})
    built = build_zones(
        ZoneDirs.under(root),
        data,
        source,
        small_epoch(),
        ["full", "research"],
        research_source=research,
    )
    return BuiltZones(root, world, built.snapshots["full"], built.snapshots["research"])
