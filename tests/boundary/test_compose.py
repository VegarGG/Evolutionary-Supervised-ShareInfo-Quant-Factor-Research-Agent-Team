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


def test_native_overlay_grants_only_controller_and_private_evaluator_channel():
    overlay = yaml.safe_load((ROOT / "infra/docker-compose.sandbox.yml").read_text())
    assert set(overlay["services"]) == {"sandbox-controller", "eval-worker"}
    controller = overlay["services"]["sandbox-controller"]
    assert controller["profiles"] == ["sandbox"]
    assert controller["network_mode"] == "none"
    assert controller["read_only"] and controller["cap_drop"] == ["ALL"]
    assert controller["user"] == "65532:65532"
    assert controller["group_add"] == [
        "${QFR_DOCKER_SOCKET_GID:?supply the socket GID observed inside the controller}"
    ]
    assert controller["security_opt"] == ["no-new-privileges:true"]
    assert not controller.get("secrets") and not controller.get("ports")
    assert not controller.get("devices") and not controller.get("privileged")
    assert not controller.get("use_api_socket")
    mounts = controller["volumes"]
    assert len(mounts) == 3
    assert mounts[0]["target"] == "/var/run/docker.sock"
    assert mounts[0]["read_only"] and not mounts[0]["bind"]["create_host_path"]
    assert "${QFR_DOCKER_SOCKET:?" in mounts[0]["source"]
    assert mounts[1]["target"] == "/etc/qfr/sandbox-controller.json"
    assert mounts[2] == "sandbox-control:/run/qfr-sandbox"
    worker = overlay["services"]["eval-worker"]
    assert not worker.get("group_add")
    assert worker["volumes"] == ["sandbox-control:/run/qfr-sandbox:ro"]
    assert worker["environment"] == {
        "QFR_SANDBOX_CONTROLLER_SOCKET": "/run/qfr-sandbox/controller.sock"
    }


def test_stage4_overlay_retains_database_and_source_separation():
    base = yaml.safe_load((ROOT / "infra/docker-compose.yml").read_text())
    overlay = yaml.safe_load((ROOT / "infra/docker-compose.stage4.yml").read_text())
    assert set(overlay["services"]) == {
        "mcp-api",
        "research-api",
        "registry-api",
        "feedback-api",
        "quarantine-api",
    }
    assert overlay["networks"] == {"quarantine-edge": {"internal": True}}
    for name, changed in overlay["services"].items():
        effective = {**base["services"].get(name, {}), **changed}
        assert effective["user"] == "65532:65532"
        assert effective["read_only"] and effective["cap_drop"] == ["ALL"]
        assert effective["security_opt"] == ["no-new-privileges:true"]
        assert not any(effective.get(k) for k in ["cap_add", "privileged", "devices", "group_add"])
        assert effective["mem_limit"] == effective["memswap_limit"]
        assert effective["pids_limit"] <= 64 and effective["cpus"] == 1
        assert effective["logging"]["options"] == {"max-size": "10m", "max-file": "2"}
        assert all(p.startswith("127.0.0.1:") for p in effective.get("ports", []))
        # Overlay lists merge with base lists: examine both, not just the changed dict.
        volumes = [*base["services"].get(name, {}).get("volumes", []), *changed.get("volumes", [])]
        assert not any("sock" in str(v) for v in volumes)
        if name in {"mcp-api", "research-api"}:
            assert "eval-db" not in effective["networks"]
            assert not any(
                token in str(volumes)
                for token in ["full-snapshot", "quarantine-sources", "/imports", "epochs"]
            )
            assert all(v.endswith(":ro") if isinstance(v, str) else v["read_only"] for v in volumes)
        if name == "quarantine-api":
            assert effective["networks"] == ["quarantine-edge"]
            assert not effective.get("secrets") and not effective.get("environment")
            assert not effective.get("ports")
        for volume in changed.get("volumes", []):
            if isinstance(volume, dict):
                assert volume["read_only"] and volume["bind"]["create_host_path"] is False
    assert overlay["services"]["mcp-api"]["command"][2] == "qfr_mcp.serve"
    imports = yaml.safe_load((ROOT / "infra/docker-compose.stage4-import.yml").read_text())
    assert set(imports["services"]) == {"quarantine-api"}
    mount = imports["services"]["quarantine-api"]["volumes"][0]
    assert mount["read_only"] and not mount["bind"]["create_host_path"]
    assert mount["target"] == "/imports/originals"
