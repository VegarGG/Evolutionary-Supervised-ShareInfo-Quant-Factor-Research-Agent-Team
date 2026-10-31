import pytest


@pytest.fixture(scope="session")
def null_zones(tmp_path_factory):
    """The small null world (no planted signal) written as full and research snapshots."""
    from tests.synthetic_fixtures import build_small_zones

    return build_small_zones(tmp_path_factory.mktemp("null-snapshots"), "null")
