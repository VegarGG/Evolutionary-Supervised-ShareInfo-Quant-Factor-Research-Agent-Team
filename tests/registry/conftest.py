import pytest

from tests.registry_rig import registry_rig


@pytest.fixture
def rig(tmp_path):
    with registry_rig(tmp_path) as built:
        yield built
