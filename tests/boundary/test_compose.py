import subprocess
from pathlib import Path

import yaml
from qfr_core.logging import PROVIDER_ENV

COMPOSE = yaml.safe_load(Path("infra/docker-compose.yml").read_text())


def test_bnd_04_import_contracts():
    result = subprocess.run(["lint-imports", "--no-cache"], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_bnd_07_only_worker_receives_provider_environment():
    for name, service in COMPOSE["services"].items():
        present = PROVIDER_ENV.intersection(service.get("environment", {}))
        assert not present or name == "research-worker"


def test_bnd_08_service_log_mounts():
    for name in ("research-api", "research-worker"):
        mounts = [v for v in COMPOSE["services"][name]["volumes"] if v["source"] == "qfr_logs"]
        assert len(mounts) == 1
        assert mounts[0]["volume"]["subpath"] == name
    mcp_mounts = COMPOSE["services"]["qfr-mcp"]["volumes"]
    whole = [v for v in mcp_mounts if v["source"] == "qfr_logs" and "volume" not in v]
    assert len(whole) == 1 and whole[0]["read_only"] is True


def test_private_data_and_epochs_are_not_in_research_or_control():
    for name in ("research-api", "research-worker", "qfr-mcp"):
        service = COMPOSE["services"][name]
        assert "QFR_EPOCH_CONFIG" not in service["environment"]
        assert all(v["source"] != "snapshots_full" for v in service["volumes"])
        assert all("epochs" not in v["source"] for v in service["volumes"])


def test_all_services_hardened_and_only_mcp_port_published():
    for name, service in COMPOSE["services"].items():
        assert not service["user"].startswith("0:")
        assert service["read_only"] is True
        assert service["cap_drop"] == ["ALL"]
        assert "no-new-privileges:true" in service["security_opt"]
        assert service["tmpfs"] and service["healthcheck"]
        assert service["deploy"]["resources"]["limits"]
        if "ports" in service:
            assert name == "qfr-mcp" and service["ports"] == ["127.0.0.1:8765:8765"]


def test_only_owner_authorized_services_have_external_egress():
    networks = COMPOSE["networks"]
    allowed = {
        "research-worker": ["research_egress_net"],
        "data-ingest": ["ingest_egress_net"],
        "qfr-mcp": ["mcp_ingress_net"],
    }
    for name, service in COMPOSE["services"].items():
        external = [
            n for n in service.get("networks", []) if not networks[n].get("internal", False)
        ]
        assert external == allowed.get(name, [])


def test_mcp_ingress_is_exclusive_and_cannot_bridge_research_or_eval():
    members = [
        name
        for name, service in COMPOSE["services"].items()
        if "mcp_ingress_net" in service.get("networks", [])
    ]
    assert members == ["qfr-mcp"]
    assert set(COMPOSE["services"]["qfr-mcp"]["networks"]) == {"control_net", "mcp_ingress_net"}
    for name in ("control_net", "research_net", "registry_net", "eval_net"):
        assert COMPOSE["networks"][name]["internal"] is True


def test_no_private_config_baked_into_runtime_image():
    dockerfile = Path("infra/Dockerfile").read_text()
    runtime = dockerfile.split("FROM python:3.12-slim AS runtime")[1].split("FROM runtime AS mcp")[
        0
    ]
    assert "COPY configs/epochs" not in runtime
    assert "COPY configs/protocols" not in runtime
    assert "COPY schemas/private" not in runtime
