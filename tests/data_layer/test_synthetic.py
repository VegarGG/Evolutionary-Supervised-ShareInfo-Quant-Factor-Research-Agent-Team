"""P1.2 uses real deterministic generation, not precomputed alpha-labelled scores."""

from pathlib import Path

import numpy as np
import pytest
from qfr_core.data_layer.synthetic import SyntheticConfig, generate

ROOT = Path(__file__).resolve().parents[2]


def config():
    base = SyntheticConfig.load(ROOT / "configs/data/synthetic.json")
    return SyntheticConfig.model_validate(base.model_dump() | {"days": 300, "instruments": 80})


@pytest.mark.parametrize("world", ["planted", "null", "decay"])
def test_synthetic_world_calibration_and_realism(world):
    result = generate(config(), world)
    truth = result.ground_truth
    assert result.panel.height == 300 * 80
    assert result.panel["is_suspended"].any()
    assert result.membership["in_csi300"].n_unique() == 2
    active = 0 if world == "null" else 2 if world == "planted" else 3
    assert all(
        abs(truth["calibrated_rankic"][i] - truth["targets"][i]) <= 0.005 for i in range(active)
    )
    if world == "null":
        assert truth["alpha"] == [0.0, 0.0, 0.0]
        repeat = generate(config(), world)
        assert result.panel.equals(repeat.panel)
    if world == "decay":
        assert truth["switch_off_day"] == 210
        assert truth["alpha"][2] > 0
    assert np.isfinite(result.panel["close"].to_numpy()).all()


def test_unreachable_calibration_fails_without_silent_fallback():
    settings = config().model_copy(
        update={"alpha_upper_bound": 1e-15, "calibration_bisections": 1, "calibration_sweeps": 1}
    )
    with pytest.raises(ValueError, match="calibration failed"):
        generate(settings, "planted")
