"""Deployment topology is a contract even while all application services are stubs."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_compose_trust_zones():
    config = yaml.safe_load((ROOT / "infra/docker-compose.yml").read_text())
    services = config["services"]
    assert set(services) == {
        "postgres",
        "mcp-api",
        "research-api",
        "research-worker",
        "registry-api",
        "eval-scheduler",
        "eval-worker",
        "release-worker",
        "feedback-api",
        "eval-admin-api",
        "data-ingest",
    }
    for service in services.values():
        assert all(port.startswith("127.0.0.1:") for port in service.get("ports", []))
    for name in ["research-api", "research-worker", "mcp-api"]:
        service = services[name]
        assert all(
            "eval" not in item and "full" not in item and "epochs" not in item
            for item in service.get("volumes", []) + service.get("secrets", [])
        )
        assert "eval-db" not in service["networks"]
    for name in ["eval-worker", "eval-scheduler", "release-worker", "eval-admin-api"]:
        service = services[name]
        assert all(config["networks"][network].get("internal") for network in service["networks"])
        assert not any("API_KEY" in key for key in service.get("environment", {}))
    assert not services["mcp-api"].get("secrets")
    for name, service in services.items():
        if name != "postgres":
            assert service["read_only"]
            assert service["cap_drop"] == ["ALL"]
            assert "postgres_password" not in service.get("secrets", [])
            assert not any("docker.sock" in item for item in service.get("volumes", []))
