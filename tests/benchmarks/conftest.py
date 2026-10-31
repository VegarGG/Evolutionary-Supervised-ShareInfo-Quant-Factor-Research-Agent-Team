import pytest


@pytest.fixture(scope="session")
def null_zones(tmp_path_factory):
    """The small null world (no planted signal) written as full and research snapshots."""
    from tests.synthetic_fixtures import build_small_zones

    return build_small_zones(tmp_path_factory.mktemp("null-snapshots"), "null")


def _validation_world(tmp_path_factory, name):
    from tests.synthetic_fixtures import build_validation_zones

    return build_validation_zones(tmp_path_factory.mktemp(f"{name}-validation-snapshots"), name)


@pytest.fixture(scope="session")
def planted_world(tmp_path_factory):
    """The Phase 6 validation worlds: the shipped synthetic world and epoch with a replay
    tail after W3 (tests/synthetic_fixtures.py)."""
    return _validation_world(tmp_path_factory, "planted")


@pytest.fixture(scope="session")
def null_world(tmp_path_factory):
    return _validation_world(tmp_path_factory, "null")


@pytest.fixture(scope="session")
def decay_world(tmp_path_factory):
    """BM-DECAY's world: the shipped generator's size on the 800-day calendar, with a
    replay tail from W2 so monitoring spans the switch-off."""
    from tests.synthetic_fixtures import BENCHMARK_SIZE, build_small_zones

    root = tmp_path_factory.mktemp("decay-benchmark-snapshots")
    return build_small_zones(root, "decay", replay=True, size=BENCHMARK_SIZE)
