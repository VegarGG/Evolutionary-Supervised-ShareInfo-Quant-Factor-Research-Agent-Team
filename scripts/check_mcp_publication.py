"""Read-only Docker port metadata check; never a substitute for host MCP acceptance.

Inspect only selected fields, never environment, credentials, mounts or request data.
This command sends no application request and creates no Docker resource or credential.
"""

import argparse
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "configs/infra/mcp_publication_check_v1.json"
INSPECT_FORMAT = (
    '{"running":{{json .State.Running}},'
    '"network_mode":{{json .HostConfig.NetworkMode}},'
    '"configured_ports":{{json .HostConfig.PortBindings}},'
    '"active_ports":{{json .NetworkSettings.Ports}}}'
)


class PublicationError(ValueError):
    """Only fixed non-sensitive reason codes cross the diagnostic boundary."""


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise PublicationError("invalid_inspection")
        value[key] = item
    return value


def _nonfinite(_):
    raise PublicationError("invalid_inspection")


def _bindings(value):
    if value is None:
        return []
    if not isinstance(value, dict):
        raise PublicationError("invalid_inspection")
    result = []
    for port, bindings in value.items():
        if bindings is None:
            continue  # An EXPOSE declaration is not a host publication.
        if not isinstance(bindings, list):
            raise PublicationError("invalid_inspection")
        for binding in bindings:
            if not isinstance(binding, dict) or set(binding) != {"HostIp", "HostPort"}:
                raise PublicationError("invalid_inspection")
            if not all(isinstance(v, str) for v in binding.values()):
                raise PublicationError("invalid_inspection")
            result.append((port, binding["HostIp"], binding["HostPort"]))
    return result


def check_observation(raw, host_port, policy):
    if type(host_port) is not int or not 1 <= host_port <= 65535:
        raise PublicationError("invalid_host_port")
    if len(raw) > policy["max_inspection_bytes"]:
        raise PublicationError("inspection_too_large")
    try:
        value = json.loads(raw, object_pairs_hook=_unique, parse_constant=_nonfinite)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise PublicationError("invalid_inspection") from error
    if not isinstance(value, dict) or set(value) != {
        "running",
        "network_mode",
        "configured_ports",
        "active_ports",
    }:
        raise PublicationError("invalid_inspection")
    if value["running"] is not True:
        raise PublicationError("publisher_not_running")
    mode = value["network_mode"]
    if not isinstance(mode, str) or not mode or mode in {"host", "none"} or ":" in mode:
        raise PublicationError("unsupported_network_mode")
    expected = [(policy["container_port"], policy["host_ip"], str(host_port))]
    if _bindings(value["configured_ports"]) != expected:
        raise PublicationError("unexpected_configured_publication")
    active = _bindings(value["active_ports"])
    if not active:
        raise PublicationError("mcp_port_not_published")
    if active != expected:
        raise PublicationError("unexpected_active_publication")


def inspect_publication(container_id, host_port, policy):
    # Require the exact container observed by `compose ps -q`, not an option/name
    # interpreted by a shell or an ambiguous set of containers.
    if not re.fullmatch(r"[0-9a-f]{64}", container_id):
        raise PublicationError("invalid_container_id")
    try:
        result = subprocess.run(
            ["docker", "container", "inspect", "--format", INSPECT_FORMAT, container_id],
            capture_output=True,
            timeout=policy["inspect_timeout_seconds"],
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise PublicationError("docker_inspection_unavailable") from error
    if result.returncode:
        # Daemon/CLI stderr can include private endpoint paths. Do not echo it.
        raise PublicationError("docker_inspection_failed")
    check_observation(result.stdout, host_port, policy)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", required=True)
    parser.add_argument("--host-port", type=int, required=True)
    args = parser.parse_args()
    policy = json.loads(POLICY.read_bytes())
    try:
        inspect_publication(args.container, args.host_port, policy)
    except PublicationError as error:
        print(json.dumps({"status": "blocked", "reason": str(error)}))
        return 1
    print(json.dumps({"status": "publication_metadata_only", "host_mcp_acceptance": "unrun"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
