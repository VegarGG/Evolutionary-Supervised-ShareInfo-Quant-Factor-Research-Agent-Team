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
        assert not service.get("privileged", False)
        assert not service.get("devices") and not service.get("cap_add")
        assert service.get("pid") != "host" and service.get("network_mode") != "host"
        assert str(service["user"]).split(":")[0] not in ("0", "root", "")
        assert "no-new-privileges:true" in service["security_opt"]
        # SBX-05: application roles cannot gain host writes through a bind,
        # a volume, a device, or a Docker/container-runtime control socket.
        for volume in service.get("volumes", []):
            if isinstance(volume, str):
                assert volume.rsplit(":", 1)[-1] == "ro"
                assert not any(
                    token in volume for token in ("docker.sock", "containerd.sock", "/run/docker")
                )
            else:
                assert volume.get("read_only") is True
                assert not any(
                    token in str(volume)
                    for token in ("docker.sock", "containerd.sock", "/run/docker")
                )
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
    postgres = services["postgres"]
    assert postgres["entrypoint"] == ["bash", "/opt/qfr/postgres/entrypoint.sh"]
    assert postgres["command"] == ["postgres"]
    assert postgres["tmpfs"] == [
        "/run/qfr-postgres-secrets:rw,noexec,nosuid,nodev,size=64k,mode=0700"
    ]
    assert "./postgres:/opt/qfr/postgres:ro" in postgres["volumes"]
    for name, service in services.items():
        if name != "postgres":
            assert service["read_only"]
            assert service["cap_drop"] == ["ALL"]
            assert "postgres_password" not in service.get("secrets", [])
            assert not any("docker.sock" in item for item in service.get("volumes", []))
