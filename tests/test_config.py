from pathlib import Path

import pytest
from qfr_core.config import CONFIG_FILES, MCPConfig, RuntimeSettings, load_config


def test_all_configurations_load_and_have_stable_identities():
    for kind in CONFIG_FILES:
        first = load_config(kind, Path("configs"))
        assert first == load_config(kind, Path("configs"))
        assert len(first.sha256) == 64


def test_mcp_rejects_non_loopback_publication():
    values = load_config("mcp", Path("configs")).values | {"bind": "0.0.0.0"}
    with pytest.raises(ValueError, match="loopback"):
        MCPConfig.model_validate(values)


def test_secrets_are_environment_only_and_repr_is_hidden(monkeypatch):
    monkeypatch.setenv("QFR_MCP_TOKEN", "test-secret")
    settings = RuntimeSettings()
    assert "test-secret" not in repr(settings)
    assert settings.mcp_token.get_secret_value() == "test-secret"


def test_authoritative_release_and_provider_defaults():
    assert load_config("policy", Path("configs")).values["release_timing"] == "immediate"
    providers = load_config("providers", Path("configs")).values["providers"]
    assert set(providers) == {"deepseek", "kimi", "glm"}
    assert providers["deepseek"]["models"]["deepseek-flash"]["thinking"] == "off"
