import pytest


@pytest.fixture(scope="session")
def null_zones(tmp_path_factory):
    """The small null world (no planted signal) written as full and research snapshots."""
    from tests.synthetic_fixtures import build_small_zones

    return build_small_zones(tmp_path_factory.mktemp("null-snapshots"), "null")


def _benchmark_world(tmp_path_factory, name):
    from tests.synthetic_fixtures import BENCHMARK_SIZE, build_small_zones

    root = tmp_path_factory.mktemp(f"{name}-benchmark-snapshots")
    return build_small_zones(root, name, replay=True, size=BENCHMARK_SIZE)


@pytest.fixture(scope="session")
def planted_world(tmp_path_factory):
    """The Phase 6 benchmark worlds: the shipped generator's 300 instruments and 240-name
    universe on the 800-day calendar with a replay tail (tests/synthetic_fixtures.py)."""
    return _benchmark_world(tmp_path_factory, "planted")


@pytest.fixture(scope="session")
def null_world(tmp_path_factory):
    return _benchmark_world(tmp_path_factory, "null")


@pytest.fixture(scope="session")
def decay_world(tmp_path_factory):
    return _benchmark_world(tmp_path_factory, "decay")
