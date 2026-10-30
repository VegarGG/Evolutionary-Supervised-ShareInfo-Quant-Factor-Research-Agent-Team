import pytest

from tests.eval.eval_rig import eval_rig


@pytest.fixture
def rig(tmp_path, small_zones):
    with eval_rig(tmp_path, small_zones) as built:
        yield built
