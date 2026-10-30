"""Trusted pure-data and socket-error fixtures; no real external connection calls."""

import errno
import ipaddress
import socket
import struct
import time
from dataclasses import replace
from pathlib import Path

import pytest
from qfr_core import sandbox_network as network
from qfr_eval.sandbox.models import DockerNativeProfile
from qfr_eval.sandbox.native import native_probe_source


def packed(address):
    return ipaddress.ip_address(address).packed


def route(address="127.0.0.0", prefix=8, *, kind=1, interface=1, extra=()):
    return network.Route(
        network.INET if ":" not in address else network.INET6,
        prefix,
        0,
        0,
        kind,
        ((1, packed(address)), (4, struct.pack("=I", interface)), *extra),
    )


@pytest.fixture
def isolated():
    return network.NetworkSnapshot(
        (network.Link(1, 772, 0x10049, 0, "lo"),),
        (network.Address(1, network.INET, 8, 254, (packed("127.0.0.1"),)),),
        (route(), route("127.0.0.1", 32, kind=2), route("127.255.255.255", 32, kind=3)),
    )


def test_inactive_addressless_tunnel_templates_do_not_imply_connectivity(isolated):
    templates = tuple(
        network.Link(index, 768, 0x80, 2, f"template-{index}") for index in range(2, 11)
    )
    value = replace(isolated, links=isolated.links + templates)
    assert all(network.isolated_state(value).values())
    # Loopback identity comes from kernel type/flags, never the interface name.
    renamed = replace(value, links=(replace(value.links[0], name="local"), *templates))
    assert all(network.isolated_state(renamed).values())


@pytest.mark.parametrize(
    "flags,state",
    [(1, 2), (0x40, 2), (0x10000, 2), (0x20000, 2), (0, 0), (0, 1), (0, 4), (0, 5), (0, 6)],
)
def test_active_or_unknown_interface_fails_even_if_named_like_a_template(isolated, flags, state):
    value = replace(isolated, links=(*isolated.links, network.Link(2, 768, flags, state, "tunl0")))
    assert not network.isolated_state(value)["network_links_inactive"]


def test_deceptive_loopback_name_or_flags_do_not_pass(isolated):
    for false_loop in (network.Link(2, 1, 0x8, 2, "lo"), network.Link(2, 772, 0, 2, "lo")):
        assert not network.isolated_state(replace(isolated, links=(*isolated.links, false_loop)))[
            "network_links_inactive"
        ]
    assert not network.isolated_state(replace(isolated, links=()))["network_links_inactive"]


@pytest.mark.parametrize(
    "address,prefix,index",
    [
        ("192.0.2.1", 24, 2),
        ("192.0.2.1", 32, 1),
        ("127.0.0.1", 8, 2),
        ("2001:db8::1", 64, 2),
        ("fe80::1", 64, 2),
        ("::1", 0, 1),
    ],
)
def test_all_addresses_including_down_devices_and_ipv6_are_checked(
    isolated, address, prefix, index
):
    family = network.INET if ":" not in address else network.INET6
    value = replace(
        isolated,
        addresses=(
            *isolated.addresses,
            network.Address(index, family, prefix, 254, (packed(address),)),
        ),
    )
    assert not network.isolated_state(value)["network_addresses_loopback_only"]


@pytest.mark.parametrize(
    "bad",
    [
        route("0.0.0.0", 0),
        route("192.0.2.0", 24),
        route("2001:db8::", 64),
        route("::", 0),
        route(interface=2),
        route(prefix=0),
        route(kind=9),
        route(kind=10),
        route(extra=((5, packed("127.0.0.1")),)),  # gateway
        route(extra=((9, b"multipath"),)),
        route(extra=((18, b"alternate family"),)),
        route(extra=((22, b"encapsulation"),)),
        route(extra=((30, struct.pack("=I", 1)),)),
        route(extra=((77, b"unknown forwarding feature"),)),
        route(extra=((7, packed("192.0.2.1")),)),
    ],
)
def test_default_external_alternate_and_deceptive_routes_fail(isolated, bad):
    assert not network.isolated_state(replace(isolated, routes=(*isolated.routes, bad)))[
        "network_routes_nonforwarding"
    ]


def test_discard_routes_are_distinct_from_throw_to_another_table(isolated):
    for kind in (6, 7, 8):
        discard = network.Route(network.INET6, 0, 0, 0, kind, ())
        assert all(
            network.isolated_state(replace(isolated, routes=(*isolated.routes, discard))).values()
        )
    thrown = network.Route(network.INET, 0, 0, 0, 9, ())
    assert not network.isolated_state(replace(isolated, routes=(thrown,)))[
        "network_routes_nonforwarding"
    ]


def test_linux_ipv6_uapi_is_not_the_macos_socket_family_number(isolated):
    address = network.Address(1, 10, 128, 254, (packed("::1"),))
    local_route = route("::1", 128, kind=2)
    assert local_route.family == 10
    snapshot = replace(
        isolated, addresses=(*isolated.addresses, address), routes=(*isolated.routes, local_route)
    )
    assert all(network.isolated_state(snapshot).values())


class DeniedSocket:
    def __init__(self, error):
        self.error = error

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def settimeout(self, value):
        assert 0 < value <= 0.25

    def connect(self, destination):
        assert destination[0] in ("203.0.113.1", "2001:db8::1")
        if self.error is not None:
            raise OSError(self.error, "synthetic failure")


@pytest.mark.parametrize("family", [socket.AF_INET, socket.AF_INET6])
def test_both_tcp_and_udp_need_kernel_unreachable(monkeypatch, family):
    calls = []

    def make(actual_family, kind):
        calls.append((actual_family, kind))
        return DeniedSocket(errno.ENETUNREACH)

    monkeypatch.setattr(network.socket, "socket", make)
    assert network.denied_connections(family)
    assert calls == [(family, socket.SOCK_STREAM), (family, socket.SOCK_DGRAM)]


@pytest.mark.parametrize(
    "error",
    [
        None,
        errno.ECONNREFUSED,
        errno.ETIMEDOUT,
        errno.EPERM,
        errno.EHOSTUNREACH,
        errno.ENETDOWN,
        errno.EAFNOSUPPORT,
    ],
)
def test_refused_permission_timeout_unknown_or_success_is_not_no_route(monkeypatch, error):
    monkeypatch.setattr(network.socket, "socket", lambda *args: DeniedSocket(error))
    assert not network.denied_connections(socket.AF_INET)
    assert not network.denied_connections(socket.AF_INET6)


def test_explicitly_unavailable_ipv6_differs_from_unknown_socket_failure(monkeypatch):
    def unavailable(*args):
        raise OSError(errno.EAFNOSUPPORT, "synthetic absent protocol")

    monkeypatch.setattr(network.socket, "socket", unavailable)
    assert network.denied_connections(socket.AF_INET6)
    assert not network.denied_connections(socket.AF_INET)


def test_complete_stable_observation_precedes_any_negative_connect(monkeypatch, isolated):
    calls = []
    monkeypatch.setattr(network, "observe_network", lambda: isolated)
    monkeypatch.setattr(network, "denied_connections", lambda family: calls.append(family) or True)
    assert all(network.audit_network().values())
    assert calls == [socket.AF_INET, socket.AF_INET6]
    calls.clear()
    external = replace(isolated, routes=(*isolated.routes, route("0.0.0.0", 0)))
    monkeypatch.setattr(network, "observe_network", lambda: external)
    assert not network.audit_network()["network_denied"]
    assert not calls


def test_changing_or_unreadable_observation_never_passes(monkeypatch, isolated):
    observations = iter((isolated, replace(isolated, addresses=())))
    monkeypatch.setattr(network, "observe_network", lambda: next(observations))
    monkeypatch.setattr(network, "denied_connections", lambda _: True)
    checks = network.audit_network()
    assert not checks["network_snapshot_stable"] and not checks["network_denied"]

    def missing():
        raise PermissionError("synthetic missing kernel observation")

    monkeypatch.setattr(network, "observe_network", missing)
    checks = network.audit_network()
    assert not checks["network_observed"] and not checks["network_denied"]


@pytest.mark.parametrize(
    "flags,sequence,port", [(0x12, 1, 123), (0x22, 1, 123), (0, 1, 123), (2, 2, 123), (2, 1, 456)]
)
def test_incomplete_filtered_or_wrong_identity_netlink_messages_fail(flags, sequence, port):
    packet = struct.pack("=IHHII", 20, 3, flags, sequence, port) + b"\0" * 4
    with pytest.raises(ValueError):
        network.messages(packet, 1, 123)


@pytest.mark.parametrize(
    "data",
    [
        b"\0",
        struct.pack("=HH", 2, 1),
        struct.pack("=HH", 8, 1) + b"a",
        struct.pack("=HHI", 8, 0x4004, 1),
        struct.pack("=HHI", 8, 4, 1) * 2,
    ],
)
def test_malformed_or_ambiguous_attributes_fail(data):
    with pytest.raises(ValueError):
        network.attributes(data)


@pytest.mark.parametrize("failure", ["truncated", "nonkernel", "missing_done", "done_error"])
def test_dump_needs_complete_untruncated_kernel_completion(failure):
    class Channel:
        def getsockname(self):
            return (123, 0)

        def sendto(self, data, destination):
            assert destination == (0, 0)
            assert struct.unpack_from("=H", data, 4)[0] == 18  # GETLINK, never SETLINK

        def settimeout(self, value):
            assert 0 < value <= 1

        def recvmsg(self, size):
            assert size == 65536
            if failure == "missing_done":
                raise TimeoutError("synthetic incomplete dump")
            code = -errno.EPERM if failure == "done_error" else 0
            packet = struct.pack("=IHHIIi", 20, 3, 2, 1, 123, code)
            flags = socket.MSG_TRUNC if failure == "truncated" else 0
            sender = (9, 0) if failure == "nonkernel" else (0, 0)
            return packet, [], flags, sender

    with pytest.raises((ValueError, TimeoutError)):
        network._dump(Channel(), 18, 16, b"\0" * 16, 1, time.monotonic() + 1)


def test_external_route_in_nonstandard_table_is_not_filtered_out(isolated):
    other_table = route("0.0.0.0", 0, extra=((15, struct.pack("=I", 10000)),))
    assert not network.isolated_state(replace(isolated, routes=(other_table,)))[
        "network_routes_nonforwarding"
    ]


def attribute(kind, value):
    size = 4 + len(value)
    return struct.pack("=HH", size, kind) + value + b"\0" * ((-size) % 4)


def test_parsed_kernel_bytes_preserve_all_address_and_route_semantics():
    link = struct.pack("=BxHiII", 0, 772, 1, 0x10049, 0)
    link += attribute(3, b"lo\0") + attribute(16, b"\0")
    address = struct.pack("=BBBBI", network.INET, 8, 128, 254, 1)
    address += attribute(1, packed("127.0.0.1")) + attribute(2, packed("127.0.0.1"))
    raw_route = struct.pack("=BBBBBBBBI", network.INET, 8, 0, 0, 255, 2, 254, 2, 0)
    raw_route += attribute(1, packed("127.0.0.0")) + attribute(4, struct.pack("=I", 1))
    snapshot = network.parse_snapshot((link,), (address,), (raw_route,))
    assert all(network.isolated_state(snapshot).values())
    peer = address + attribute(5, packed("192.0.2.1"))
    assert not network.isolated_state(network.parse_snapshot((link,), (peer,), (raw_route,)))[
        "network_addresses_loopback_only"
    ]


def test_native_probe_uses_network_audit_and_preserves_other_controls():
    profile = DockerNativeProfile.model_validate_json(
        Path("configs/evaluation/sandbox_docker_native_v5.json").read_bytes()
    )
    source = native_probe_source(profile)
    compile(source, "trusted-native-probe", "exec")
    assert "checks.update(audit_network())" in source
    assert "if_nameindex" not in source and "s.connect" not in source
    for name in (
        "dropped_capabilities",
        "read_only_root",
        "seccomp_filter",
        "cgroup_pids",
        "no_new_privileges",
        "read_only_input",
    ):
        assert name in source
