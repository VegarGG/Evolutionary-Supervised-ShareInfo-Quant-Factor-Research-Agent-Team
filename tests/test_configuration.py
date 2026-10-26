"""Offline config parsing and profile separation, not admission or paid-call preflight."""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError
from qfr_core.configuration import ConfigDocument, Settings, load_profile, load_yaml
from qfr_core.contracts.providers import ProviderProfiles
from qfr_eval.configuration import EpochConfig

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("profile", ["pilot_industry_v1", "stock_daily_v1"])
@pytest.mark.parametrize("kind", ["protocol", "release_policy", "quota", "charter", "job"])
def test_versioned_profile_loads(profile, kind):
    doc = load_profile(Settings(config_root=ROOT / "configs"), kind, profile)
    assert doc.status == "draft"
    assert doc.parameters


def test_case_defaults_do_not_bleed():
    settings = Settings(config_root=ROOT / "configs")
    pilot = load_profile(settings, "protocol", "pilot_industry_v1").parameters
    stock = load_profile(settings, "protocol", "stock_daily_v1").parameters
    assert pilot["universe"]["count"] == 31
    assert pilot["selection"]["fraction"] == 0.2
    assert stock["reference_strategy"]["top_n"] == 50
    assert pilot["bootstrap"]["formal"]["seed"] == 20261020
    for profile in ["pilot_industry_v1", "stock_daily_v1"]:
        job = load_profile(settings, "job", profile).parameters
        assert job["max_wall_clock_seconds"] is None
        assert job["max_generations"] is None
        assert job["authorized_spend_ref"] is None
        assert job["completion_requires_independent_receipt"] is True


def test_provider_example_preserves_unknowns_and_references(monkeypatch):
    monkeypatch.setenv("KIMI_API_KEY", "test-value-must-not-be-read")
    monkeypatch.setenv("QFR_MODEL", "must-not-override-role-routing")
    profiles = load_yaml(ROOT / "configs/research/models.yaml", ProviderProfiles)
    assert {e.vendor for e in profiles.provider_endpoints.values()} >= {
        "moonshot_kimi",
        "zai_glm",
        "deepseek",
    }
    assert profiles.provider_endpoints["kimi_primary"].api_key_ref == "env:KIMI_API_KEY"
    assert all(m.exact_model_id is None for m in profiles.model_profiles.values())
    assert all(m.verified_capabilities_ref is None for m in profiles.model_profiles.values())
    assert len({r.model_profile for r in profiles.role_profiles.values()}) == 3
    assert "test-value-must-not-be-read" not in profiles.model_dump_json()
    bad = profiles.model_dump()
    bad["model_profiles"]["kimi_selected"]["endpoint_ref"] = "missing"
    with pytest.raises(ValidationError, match="endpoint_ref"):
        ProviderProfiles.model_validate(bad)


def test_yaml_rejects_duplicate_keys_and_unsafe_tags(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("kind: protocol\nkind: job\n")
    with pytest.raises(ValueError, match="duplicate"):
        load_yaml(path, ConfigDocument)
    path.write_text("!!python/object/apply:os.system ['false']")
    with pytest.raises(yaml.constructor.ConstructorError):
        load_yaml(path, ConfigDocument)


def test_epochs_are_private_and_keep_original_replay_windows():
    pilot = load_yaml(ROOT / "configs/epochs/pilot_industry_v1.yaml", EpochConfig)
    assert pilot.windows["development"].end.isoformat() == "2022-12-31"
    assert pilot.original_replay_windows["development"].end.isoformat() == "2023-12-31"
    assert all(w.exposure == "previously_seen" for w in pilot.windows.values())
    stock = load_yaml(ROOT / "configs/epochs/stock_daily_v1.yaml", EpochConfig)
    assert stock.windows["W3"].end is None
    assert stock.embargo_trading_days == 20
