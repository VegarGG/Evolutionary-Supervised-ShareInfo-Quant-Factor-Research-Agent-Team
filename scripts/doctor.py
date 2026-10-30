"""Inspect the running Phase 0 stack without changing Docker or host settings."""

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import yaml

root = Path(__file__).resolve().parents[1]
compose = [
    "docker",
    "compose",
    "--env-file",
    str(root / ".env"),
    "-f",
    str(root / "infra/docker-compose.yml"),
]
checks = []


def record(name, passed, detail):
    checks.append({"check": name, "status": "PASS" if passed else "FAIL", "detail": detail})


def run(args):
    return subprocess.run(args, text=True, capture_output=True, check=True).stdout


try:
    info = json.loads(run(["docker", "info", "--format", "{{json .}} "]))
    required = yaml.safe_load((root / "configs/deployment.yaml").read_text())["docker_minimum"]
    record("native_arm64", info["Architecture"] in {"aarch64", "arm64"}, info["Architecture"])
    record(
        "docker_cpus",
        info["NCPU"] >= required["cpus"],
        {"actual": info["NCPU"], "minimum": required["cpus"]},
    )
    record(
        "docker_memory",
        info["MemTotal"] >= required["memory_gb"] * 1024**3,
        {"bytes": info["MemTotal"], "minimum_gib": required["memory_gb"]},
    )
    ids = run(compose + ["ps", "-aq"]).split()
    containers = json.loads(run(["docker", "inspect", *ids])) if ids else []
    record("containers_exist", bool(containers), len(containers))
    expected = yaml.safe_load((root / "infra/docker-compose.yml").read_text())["services"]
    seen = set()
    checked_images = set()
    for container in containers:
        config = container["Config"]
        service = config["Labels"]["com.docker.compose.service"]
        seen.add(service)
        image_id = container["Image"]
        if image_id not in checked_images:
            architecture = run(
                ["docker", "image", "inspect", image_id, "--format", "{{.Architecture}}"]
            ).strip()
            record("image_architecture:" + config["Image"], architecture == "arm64", architecture)
            checked_images.add(image_id)
        state = container["State"]
        if service in {"postgres", "qfr-mcp"}:
            good = state["Running"] and state.get("Health", {}).get("Status") == "healthy"
        else:
            good = state["Status"] == "exited" and state["ExitCode"] == 0
        record(
            "service:" + service, good, {"state": state["Status"], "exit_code": state["ExitCode"]}
        )
        record(
            "hardening:" + service,
            config["User"] not in {"", "root", "0", "0:0"}
            and container["HostConfig"]["ReadonlyRootfs"]
            and "ALL" in container["HostConfig"].get("CapDrop", [])
            and any(
                "no-new-privileges" in s for s in container["HostConfig"].get("SecurityOpt", [])
            ),
            "non-root, read-only, dropped capabilities",
        )
        names = {e.split("=", 1)[0] for e in config.get("Env", [])}
        provider_keys = names & {"DEEPSEEK_API_KEY", "MOONSHOT_API_KEY", "ZHIPU_API_KEY"}
        record(
            "BND-07:" + service,
            not provider_keys or service == "research-worker",
            sorted(provider_keys),
        )
        record("timezone:" + service, "TZ=Asia/Shanghai" in config.get("Env", []), "Asia/Shanghai")
        ports = container["HostConfig"].get("PortBindings") or {}
        record(
            "loopback_ports:" + service,
            all(
                service == "qfr-mcp" and v["HostIp"] == "127.0.0.1"
                for values in ports.values()
                for v in values
            ),
            ports,
        )
        mounts = container["Mounts"]
        if service.startswith("research-"):
            record(
                "BND-08:" + service,
                all(
                    m["Destination"] in {"/var/log/qfr/" + service, "/data/research"}
                    for m in mounts
                ),
                [{"destination": m["Destination"], "rw": m["RW"]} for m in mounts],
            )
        if service == "qfr-mcp":
            record(
                "BND-08:qfr-mcp",
                any(m["Destination"] == "/var/log/qfr" and not m["RW"] for m in mounts),
                "whole logs volume read-only",
            )
            if state["Running"]:
                permission_probe = (
                    "import json,os; from pathlib import Path; "
                    "root=Path('/var/log/qfr'); "
                    "print(json.dumps({p.name:{'read':os.access(p,os.R_OK),"
                    "'write':os.access(p,os.W_OK)} for p in root.iterdir() if p.is_dir()}))"
                )
                access = json.loads(
                    run(compose + ["exec", "-T", "qfr-mcp", "python", "-c", permission_probe])
                )
                record(
                    "log_volume_permissions",
                    bool(access)
                    and all(
                        value["read"] and value["write"] == (name == "qfr-mcp")
                        for name, value in access.items()
                    ),
                    access,
                )
    record(
        "all_services_accounted_for",
        set(expected) <= seen,
        {"missing": sorted(set(expected) - seen)},
    )
    sql = (
        "SELECT datname FROM pg_database WHERE datname IN "
        "('research_db','registry_db','eval_db','control_db') ORDER BY "
        "datname"
    )
    databases = run(
        compose + ["exec", "-T", "postgres", "psql", "-U", "postgres", "-Atc", sql]
    ).split()
    record("four_databases", len(databases) == 4, databases)
    sql = (
        "SELECT rolname FROM pg_roles WHERE rolname IN "
        "('registry_app','research_rw','eval_rw','feedback_ro','control_rw') "
        "ORDER BY rolname"
    )
    roles = run(compose + ["exec", "-T", "postgres", "psql", "-U", "postgres", "-Atc", sql]).split()
    record("five_application_roles", len(roles) == 5, roles)
    disk = (
        run(compose + ["exec", "-T", "postgres", "df", "-Pk", "/var/lib/postgresql/data"])
        .splitlines()[-1]
        .split()
    )
    record(
        "docker_disk",
        int(disk[1]) * 1024 >= required["disk_gb"] * 1024**3,
        {"total_bytes": int(disk[1]) * 1024, "available_bytes": int(disk[3]) * 1024},
    )
    record("disk_headroom", int(disk[3]) > 0, {"available_bytes": int(disk[3]) * 1024})
    import urllib.error
    import urllib.request

    # An unauthenticated response proves the intended loopback listener is reachable.
    reachable = False
    try:
        urllib.request.urlopen("http://127.0.0.1:8765/mcp", timeout=3)
    except urllib.error.HTTPError as error:
        reachable = error.code == 401
    except OSError:
        pass
    record("host_mcp_loopback", reachable, "Expected bearer challenge on 127.0.0.1:8765")
except (subprocess.CalledProcessError, KeyError, ValueError, IndexError) as error:
    record("doctor_execution", False, type(error).__name__)

result = {
    "at": datetime.now(UTC).isoformat(),
    "phase": 0,
    "status": "PASS" if checks and all(c["status"] == "PASS" for c in checks) else "FAIL",
    "checks": checks,
    "limitations": [
        "Domain services are successful Phase 0 placeholders.",
        "Run the PostgreSQL boundary suite separately; this report does not replace it.",
    ],
}
directory = root / "exports/doctor"
directory.mkdir(parents=True, exist_ok=True)
destination = directory / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + ".json")
destination.write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result, indent=2))
raise SystemExit(0 if result["status"] == "PASS" else 1)
