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


def _mounts(source):
    """Services mounting a volume or bind source, mapped to whether they may write it."""
    return {
        name: not volume["read_only"]
        for name, service in COMPOSE["services"].items()
        for volume in service.get("volumes", [])
        if volume["source"] == source
    }


def test_bnd_06_research_services_see_only_the_research_snapshot():
    for name in ("research-api", "research-worker"):
        service = COMPOSE["services"][name]
        sources = {v["source"] for v in service["volumes"]}
        assert sources == {"qfr_logs", "snapshots_research"}, name
        research = next(v for v in service["volumes"] if v["source"] == "snapshots_research")
        assert research["read_only"] is True
        assert service["environment"]["QFR_RESEARCH_SNAPSHOT_DIR"] == research["target"]
        assert "QFR_FULL_SNAPSHOT_DIR" not in service["environment"]


def test_bnd_06_only_data_ingest_writes_snapshots_and_raw_data():
    assert {n for n, rw in _mounts("snapshots_research").items() if rw} == {"data-ingest"}
    assert {n for n, rw in _mounts("snapshots_full").items() if rw} == {"data-ingest"}
    assert _mounts("data_raw") == {"data-ingest": True}
    full_readers = set(_mounts("snapshots_full"))
    assert not full_readers & {"research-api", "research-worker", "qfr-mcp", "feedback-api"}


def test_bnd_06_epochs_protocols_and_data_configs_stay_in_the_evaluation_zone():
    for source in ("../configs/epochs", "../configs/protocols", "../configs/data"):
        for name, writable in _mounts(source).items():
            assert COMPOSE["services"][name]["environment"]["QFR_ZONE"] == "eval", name
            assert writable is False
    # The synthetic world's planted signals live in configs/data: ingest only.
    assert set(_mounts("../configs/data")) == {"data-ingest"}


def test_data_ingest_writes_each_zone_at_its_mount_point():
    service = COMPOSE["services"]["data-ingest"]
    targets = {v["source"]: v["target"] for v in service["volumes"]}
    environment = service["environment"]
    assert environment["QFR_FULL_SNAPSHOT_DIR"] == targets["snapshots_full"]
    assert environment["QFR_RESEARCH_SNAPSHOT_DIR"] == targets["snapshots_research"]
    assert environment["QFR_RAW_DIR"] == targets["data_raw"]
    assert service["build"] == {
        "context": "..",
        "dockerfile": "infra/Dockerfile",
        "target": "eval",
        "args": {"QFR_PACKAGE": "qfr-eval"},
    }


EVAL_SERVICES = {
    "eval-scheduler": ["python", "-m", "qfr_eval.scheduler"],
    "eval-worker": ["python", "-m", "qfr_eval.worker"],
    "release-worker": ["python", "-m", "qfr_eval.release"],
    "sim-engine": ["python", "-m", "qfr_eval.sim"],
    "feedback-api": ["python", "-m", "qfr_eval.feedback_api"],
    "eval-admin-api": ["python", "-m", "qfr_eval.admin_api"],
}


def test_phase_3_evaluation_services_run_the_eval_image():
    for name, command in EVAL_SERVICES.items():
        service = COMPOSE["services"][name]
        assert service["command"] == command, name
        assert service["build"]["target"] == "eval"
        assert service["build"]["args"] == {"QFR_PACKAGE": "qfr-eval"}
        assert service["environment"]["QFR_ZONE"] == "eval"
    ingest = COMPOSE["services"]["data-ingest"]["command"]
    assert ingest[:3] == ["qfr", "data", "serve"]
    assert COMPOSE["services"]["eval-worker"]["deploy"]["replicas"] == 2


def test_the_evaluation_store_is_written_only_by_the_worker():
    assert _mounts("eval_store") == {
        "eval-worker": True,
        "eval-scheduler": False,
        "eval-admin-api": False,
        "sim-engine": False,
        "backup": False,
    }


def test_phase_7_operations_services_hold_only_what_they_need():
    """ops-nightly: control_db and the logs volume (it compresses and deletes old days)
    and the backups folder read-only. backup: the migration roles it dumps with, the
    snapshot and store volumes read-only, its own log folder and the backups folder.
    Neither has egress, a published port, a provider key or a service token."""
    deployment = yaml.safe_load(Path("configs/deployment.yaml").read_text())
    nightly = COMPOSE["services"]["ops-nightly"]
    assert nightly["command"] == ["python", "-m", "qfr_mcp.nightly"]
    assert nightly["networks"] == ["control_net"] and "ports" not in nightly
    assert {k for k in nightly["environment"] if k.endswith(("_URL", "_TOKEN"))} == {
        "CONTROL_DB_URL"
    }
    assert {(v["source"], v["target"], v["read_only"]) for v in nightly["volumes"]} == {
        ("qfr_logs", "/var/log/qfr", False),
        ("../backups", "/backups", True),
    }
    backup = COMPOSE["services"]["backup"]
    assert backup["build"]["target"] == "backup" and backup["command"] == ["qfr-backup", "serve"]
    assert backup["networks"] == ["control_net"] and "ports" not in backup
    environment = backup["environment"]
    assert {k for k in environment if k.endswith(("_URL", "_TOKEN"))} == {
        "REGISTRY_MIGRATION_URL", "RESEARCH_MIGRATION_URL", "EVAL_MIGRATION_URL",
        "CONTROL_MIGRATION_URL",
    }  # fmt: skip
    # The schedule and retention are deployment.yaml's, passed to the script.
    assert environment["QFR_NIGHTLY_LOCAL"] == deployment["schedule"]["nightly_local"]
    assert int(environment["QFR_BACKUP_DAILY_RETENTION"]) == deployment["backup"]["daily_retention"]
    assert (
        int(environment["QFR_BACKUP_MONTHLY_RETENTION"])
        == deployment["backup"]["monthly_retention"]
    )
    writable = {v["target"] for v in backup["volumes"] if not v["read_only"]}
    assert writable == {"/backups", "/var/log/qfr/backup"}
    assert {v["source"] for v in backup["volumes"] if v["target"].startswith("/mirror/")} == {
        "snapshots_full", "snapshots_research", "eval_store",
    }  # fmt: skip
    # Every service that writes logs gets its folder from init-volumes.
    created = COMPOSE["services"]["init-volumes"]["command"][2]
    for name in ("ops-nightly", "backup"):
        assert f"Path('/var/log/qfr/{name}').mkdir" in created


def test_feedback_api_reads_released_views_only():
    service = COMPOSE["services"]["feedback-api"]
    assert "FEEDBACK_DB_URL" in service["environment"]
    assert "EVAL_DB_URL" not in service["environment"]
    assert {v["source"] for v in service["volumes"]} == {"qfr_logs"}
    assert service["environment"]["FEEDBACK_READER_TOKEN"]


def test_release_policies_and_quotas_are_mounted_only_into_the_scheduler():
    for source in ("../configs/release_policies", "../configs/quotas"):
        assert _mounts(source) == {"eval-scheduler": False}
