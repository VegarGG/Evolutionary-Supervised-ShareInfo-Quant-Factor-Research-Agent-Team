"""`just doctor` (DEP-01, PLAN Section 17.3): inspect the running stack without changing
Docker or host settings. The report is written to exports/doctor/ and logged by
ops-nightly."""

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from qfr_mcp.nightly import backup_status

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
observations = []
# Long-running services by Phase 7; the rest are one-shot jobs that exit 0.
RUNNING_SERVICES = {
    "ops-nightly",
    "backup",
    "postgres",
    "qfr-mcp",
    "registry-api",
    "research-api",
    "research-worker",
    "eval-scheduler",
    "eval-worker",
    "release-worker",
    "sim-engine",
    "feedback-api",
    "eval-admin-api",
    "data-ingest",
}
# BND-09: the registry's only mutation routes.
REGISTRY_MUTATIONS = [
    "POST /v1/artifacts",
    "POST /v1/pools/{pool}/entries",
    "POST /v1/pools/{pool}/entries/{entry_id}/events",
]


def record(name, passed, detail):
    checks.append({"check": name, "status": "PASS" if passed else "FAIL", "detail": detail})


def run(args):
    return subprocess.run(args, text=True, capture_output=True, check=True).stdout


try:
    info = json.loads(run(["docker", "info", "--format", "{{json .}} "]))
    deployment = yaml.safe_load((root / "configs/deployment.yaml").read_text())
    required = deployment["docker_minimum"]
    record("native_arm64", info["Architecture"] in {"aarch64", "arm64"}, info["Architecture"])
    record(
        "docker_cpus",
        info["NCPU"] >= required["cpus"],
        {"actual": info["NCPU"], "minimum": required["cpus"]},
    )
    memory = deployment["docker_memory"]
    observations.append(
        {
            "observation": "docker_memory",
            "bytes": info["MemTotal"],
            "expected_gib": memory["expected_gib"],
            "policy": memory["policy"],
            "below_expectation": info["MemTotal"] < memory["expected_gib"] * 1024**3,
            "minimum_enforced": False,
        }
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
        record(
            "oom:" + service,
            state.get("OOMKilled") is False,
            {"container": container["Name"], "oom_killed": state.get("OOMKilled")},
        )
        if service in RUNNING_SERVICES:
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
            record(
                "BND-06:" + service,
                all(m["Destination"] not in {"/data/full", "/data/raw"} for m in mounts)
                and all(not m["RW"] for m in mounts if m["Destination"] == "/data/research"),
                "research snapshot read-only; no full snapshot or raw data",
            )
        if service == "data-ingest":
            writable = {m["Destination"] for m in mounts if m["RW"]}
            record(
                "BND-06:data-ingest",
                {"/data/full", "/data/research", "/data/raw"} <= writable,
                sorted(writable),
            )
        if service == "registry-api" and state["Running"]:
            openapi_probe = (
                "import json,urllib.request; "
                "d=json.load(urllib.request.urlopen('http://127.0.0.1:8000/openapi.json')); "
                "print(json.dumps(sorted(m.upper()+' '+p for p,i in d['paths'].items() "
                "for m in i if m!='get')))"
            )
            mutations = json.loads(
                run(compose + ["exec", "-T", "registry-api", "python", "-c", openapi_probe])
            )
            record("BND-09:registry_mutation_routes", mutations == REGISTRY_MUTATIONS, mutations)
        if service == "feedback-api" and state["Running"]:
            # BND-03: the Feedback API's OpenAPI document holds GET operations only.
            openapi_probe = (
                "import json,urllib.request; "
                "d=json.load(urllib.request.urlopen('http://127.0.0.1:8000/openapi.json')); "
                "print(json.dumps(sorted({m for i in d['paths'].values() for m in i})))"
            )
            methods = json.loads(
                run(compose + ["exec", "-T", "feedback-api", "python", "-c", openapi_probe])
            )
            record("BND-03:feedback_get_only", methods == ["get"], methods)
        log_mounts = [m for m in mounts if m["Destination"].startswith("/var/log/qfr")]
        if log_mounts and service not in {"init-volumes"} and state["Running"]:
            # Each service can write its own log folder (Section 15.1).
            folder = "/var/log/qfr/" + service
            writable = subprocess.run(
                compose + ["exec", "-T", service, "sh", "-c", 'test -w "$1"', "sh", folder],
                capture_output=True,
                check=False,
            )
            record("log_writable:" + service, writable.returncode == 0, folder)
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
    # Memory actually used per container, for sizing Docker Desktop (owner decision).
    stats = (
        run(
            [
                "docker",
                "stats",
                "--no-stream",
                "--format",
                "{{json .}}",
                *[c["Id"] for c in containers],
            ]
        ).splitlines()
        if containers
        else []
    )
    usage = {}
    for line in stats:
        item = json.loads(line)
        usage[item.get("Name", "?")] = {"memory": item.get("MemUsage"), "cpu": item.get("CPUPerc")}
    observations.append({"observation": "container_memory", "containers": usage})
    record(
        "all_services_accounted_for",
        set(expected) <= seen,
        {"missing": sorted(set(expected) - seen)},
    )
    networks = json.loads(
        run(
            [
                "docker",
                "network",
                "inspect",
                *sorted(
                    {
                        name
                        for container in containers
                        for name in container["NetworkSettings"]["Networks"]
                    }
                ),
            ]
        )
    )
    by_name = {
        n["Labels"]["com.docker.compose.network"]: n
        for n in networks
        if (n.get("Labels") or {}).get("com.docker.compose.network")
    }
    for name in ("control_net", "research_net", "registry_net", "eval_net"):
        record("internal_network:" + name, by_name[name]["Internal"], "internal Docker network")
    ingress = by_name["mcp_ingress_net"]
    ingress_members = [
        c["Config"]["Labels"]["com.docker.compose.service"]
        for c in containers
        if ingress["Name"] in c["NetworkSettings"]["Networks"]
    ]
    record(
        "mcp_only_ingress",
        ingress_members == ["qfr-mcp"] and not ingress["Internal"],
        {"members": ingress_members, "outbound_allowed_by_owner": True},
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
    if reachable:
        # Read-only: qfr.setup.status reports the setup state and the pool counts.
        values = dict(
            line.split("=", 1)
            for line in (root / ".env").read_text().splitlines()
            if "=" in line and not line.startswith("#")
        )
        request = urllib.request.Request(
            "http://127.0.0.1:8765/mcp",
            data=json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "qfr.setup.status", "arguments": {}},
                }
            ).encode(),
            headers={
                "Authorization": "Bearer " + values["QFR_MCP_TOKEN"],
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            setup = json.load(response)["result"]["structuredContent"]["data"]
        record("registry_reachable_from_mcp", setup["registry"] == "ok", setup["registry"])
        observations.append(
            {
                "observation": "setup",
                "data": setup["steps"]["data"],
                "snapshot_ids": setup.get("snapshot_ids"),
                "pool": setup["steps"]["pool"]["status"],
                "providers": setup["steps"]["providers"],
                "pool_counts": setup["pool_counts"],
                "notice": setup["notice"],
                "setup_complete": setup["setup_complete"],
            }
        )
    # Backups are reported, not required: a new installation has none until the first
    # night (Section 17.5). ops-nightly raises the alert when they go stale.
    observations.append(
        {
            "observation": "backups",
            **backup_status(
                root / "backups",
                datetime.now(ZoneInfo(deployment["timezone"])).date(),
                int(deployment["backup"]["stale_after_days"]),
            ),
        }
    )
except (subprocess.CalledProcessError, KeyError, ValueError, IndexError, OSError) as error:
    record("doctor_execution", False, type(error).__name__)

result = {
    "at": datetime.now(UTC).isoformat(),
    "phase": 7,
    "status": "PASS" if checks and all(c["status"] == "PASS" for c in checks) else "FAIL",
    "checks": checks,
    "observations": observations,
    "limitations": [
        "Provider readiness is the latest `qfr llm probe` result in qfr.setup.status; the "
        "doctor itself never calls a provider.",
        "Container memory is a point-in-time docker stats sample, not a peak.",
        "Run the PostgreSQL boundary suite separately; this report does not replace it.",
        "OOM checks cover current container state, not an indefinite historical event record.",
    ],
}
directory = root / "exports/doctor"
directory.mkdir(parents=True, exist_ok=True)
destination = directory / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + ".json")
result["path"] = "exports/doctor/" + destination.name
destination.write_text(json.dumps(result, indent=2) + "\n")
logged = subprocess.run(
    compose + ["exec", "-T", "ops-nightly", "qfr", "ops", "record", "doctor"],
    input=json.dumps(result),
    text=True,
    capture_output=True,
    check=False,
)
result["logged"] = logged.returncode == 0
print(json.dumps(result, indent=2))
raise SystemExit(0 if result["status"] == "PASS" else 1)
