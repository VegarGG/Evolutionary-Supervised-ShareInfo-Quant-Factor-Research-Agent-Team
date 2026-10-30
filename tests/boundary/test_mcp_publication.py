"""A declared loopback port must not become false deployed-readiness evidence."""

import json
import subprocess

import pytest

from scripts import check_mcp_publication as check

POLICY = json.loads(check.POLICY.read_bytes())


def observation():
    ports = {"8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8000"}]}
    return {
        "running": True,
        "network_mode": "example_mcp-loopback",
        "configured_ports": ports,
        "active_ports": json.loads(json.dumps(ports)),
    }


def validate(value):
    check.check_observation(json.dumps(value).encode(), 8000, POLICY)


@pytest.mark.parametrize("active", [None, {}, {"8000/tcp": None}, {"8000/tcp": []}])
def test_declared_port_without_actual_binding_is_blocked(active):
    value = observation()
    value["active_ports"] = active
    with pytest.raises(check.PublicationError, match="^mcp_port_not_published$"):
        validate(value)


@pytest.mark.parametrize("ip", ["0.0.0.0", "::", "::1", "", "192.0.2.1", "127.0.0.2"])
def test_unapproved_actual_bind_address_is_blocked(ip):
    value = observation()
    value["active_ports"]["8000/tcp"][0]["HostIp"] = ip
    with pytest.raises(check.PublicationError, match="^unexpected_active_publication$"):
        validate(value)


@pytest.mark.parametrize("field", ["configured_ports", "active_ports"])
@pytest.mark.parametrize("kind", ["extra", "duplicate", "wrong_port"])
def test_no_additional_or_mismatched_publication(field, kind):
    value = observation()
    if kind == "extra":
        value[field]["8001/tcp"] = [{"HostIp": "127.0.0.1", "HostPort": "8001"}]
    elif kind == "duplicate":
        value[field]["8000/tcp"].append({"HostIp": "::", "HostPort": "8000"})
    else:
        value[field]["8000/tcp"][0]["HostPort"] = "8001"
    with pytest.raises(
        check.PublicationError, match=f"^unexpected_{field.split('_')[0]}_publication$"
    ):
        validate(value)


@pytest.mark.parametrize("mode", ["host", "none", "container:other", "", None])
def test_shared_or_unknown_network_mode_is_not_accepted(mode):
    value = observation()
    value["network_mode"] = mode
    with pytest.raises(check.PublicationError, match="^unsupported_network_mode$"):
        validate(value)


@pytest.mark.parametrize("running", [False, 1, "true", None])
def test_stopped_or_invalid_state_is_not_accepted(running):
    value = observation()
    value["running"] = running
    with pytest.raises(check.PublicationError, match="^publisher_not_running$"):
        validate(value)


@pytest.mark.parametrize(
    "raw",
    [b"null", b"[]", b"{", b'{"running":true,"running":false}', b'{"x":NaN}', b"\xff"],
)
def test_invalid_observation_fails_without_echoing_input(raw):
    with pytest.raises(check.PublicationError, match="^invalid_inspection$"):
        check.check_observation(raw, 8000, POLICY)


def test_actual_binding_and_unpublished_expose_metadata():
    value = observation()
    value["active_ports"]["9999/tcp"] = None
    validate(value)
    value["active_ports"]["8000/tcp"][0]["HostPort"] = 8000
    with pytest.raises(check.PublicationError, match="^invalid_inspection$"):
        validate(value)


def test_bounded_read_only_command_and_metadata_is_not_acceptance(monkeypatch, capsys):
    def run(command, **kwargs):
        assert command == [
            "docker",
            "container",
            "inspect",
            "--format",
            check.INSPECT_FORMAT,
            "a" * 64,
        ]
        assert kwargs == {"capture_output": True, "timeout": 10, "check": False}
        assert ".Config.Env" not in check.INSPECT_FORMAT
        assert ".Mounts" not in check.INSPECT_FORMAT
        return subprocess.CompletedProcess(command, 0, json.dumps(observation()).encode(), b"")

    monkeypatch.setattr(check.subprocess, "run", run)
    monkeypatch.setattr("sys.argv", ["check", "--container", "a" * 64, "--host-port", "8000"])
    assert check.main() == 0
    assert json.loads(capsys.readouterr().out) == {
        "status": "publication_metadata_only",
        "host_mcp_acceptance": "unrun",
    }


@pytest.mark.parametrize("failure", ["timeout", "daemon", "missing"])
def test_docker_failure_is_bounded_and_redacted(monkeypatch, capsys, failure):
    def run(command, **_):
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, 10, output=b"private-output")
        if failure == "missing":
            raise OSError("private-path")
        return subprocess.CompletedProcess(command, 1, b"", b"private-daemon-output")

    monkeypatch.setattr(check.subprocess, "run", run)
    monkeypatch.setattr("sys.argv", ["check", "--container", "a" * 64, "--host-port", "8000"])
    assert check.main() == 1
    assert "private" not in capsys.readouterr().out


def test_invalid_target_and_oversized_output_cannot_pass(monkeypatch):
    def forbidden(*_, **__):
        raise AssertionError("Docker must not run for an invalid target")

    monkeypatch.setattr(check.subprocess, "run", forbidden)
    with pytest.raises(check.PublicationError, match="^invalid_container_id$"):
        check.inspect_publication("--all", 8000, POLICY)
    with pytest.raises(check.PublicationError, match="^inspection_too_large$"):
        check.check_observation(b" " * (POLICY["max_inspection_bytes"] + 1), 8000, POLICY)
    with pytest.raises(check.PublicationError, match="^invalid_host_port$"):
        check.check_observation(json.dumps(observation()).encode(), 0, POLICY)
