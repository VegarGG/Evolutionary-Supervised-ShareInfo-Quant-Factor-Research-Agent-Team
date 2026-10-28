"""Linux-only, read-only no-egress probe v1 for the trusted sandbox bootstrap.

Uses complete RTNETLINK dumps, not device names or operstate alone. Never changes
links/routes and never sends candidate data. Unknown/incomplete observations fail.
The surrounding backend must also prove network=none, no NET_ADMIN/NET_RAW, no
new privileges and a private network namespace. This is not a kernel-escape proof.
"""

import errno
import ipaddress
import socket
import struct
import time
from dataclasses import dataclass

# Linux UAPI families are fixed even when fixtures are parsed on macOS.
INET = 2
INET6 = 10

_HEADER = struct.Struct("=IHHII")
_LINK = struct.Struct("=BxHiII")
_ADDRESS = struct.Struct("=BBBBI")
_ROUTE = struct.Struct("=BBBBBBBBI")
_UP_FLAGS = 0x1 | 0x40 | 0x10000 | 0x20000  # UP, RUNNING, LOWER_UP, DORMANT
_LOOPBACK = 0x8
_MAX_DUMP_BYTES = 1048576
_MAX_MESSAGES = 4096


def _align(size: int) -> int:
    return (size + 3) & ~3


def attributes(data: bytes) -> dict[int, bytes]:
    result: dict[int, bytes] = {}
    offset = 0
    while offset < len(data):
        if len(data) - offset < 4:
            raise ValueError("truncated network attribute")
        size, kind = struct.unpack_from("=HH", data, offset)
        if size < 4 or offset + size > len(data):
            raise ValueError("invalid network attribute length")
        if kind & 0x4000:
            raise ValueError("unexpected network attribute byte order")
        kind &= 0x3FFF  # NLA_F_NESTED marks containers, not scalar byte order.
        if kind in result:
            raise ValueError("duplicate network attribute")
        result[kind] = data[offset + 4 : offset + size]
        offset += _align(size)
    return result


def messages(data: bytes, sequence: int, port: int) -> list[tuple[int, bytes]]:
    result = []
    offset = 0
    while offset < len(data):
        if len(data) - offset < _HEADER.size:
            raise ValueError("truncated netlink header")
        size, kind, flags, seq, pid = _HEADER.unpack_from(data, offset)
        if size < _HEADER.size or offset + size > len(data) or seq != sequence or pid != port:
            raise ValueError("inconsistent netlink message")
        if flags & (0x10 | 0x20):  # DUMP_INTR / DUMP_FILTERED: incomplete evidence
            raise ValueError("interrupted or filtered network dump")
        if not flags & 0x2:  # NLM_F_MULTI
            raise ValueError("network dump is not multipart")
        if kind in (1, 2, 4):  # NOOP / ERROR / OVERRUN are not complete dump data
            raise ValueError("network dump did not complete cleanly")
        result.append((kind, data[offset + _HEADER.size : offset + size]))
        offset += _align(size)
    return result


def _dump(
    channel: socket.socket,
    request: int,
    response: int,
    payload: bytes,
    sequence: int,
    deadline: float,
) -> tuple[bytes, ...]:
    port = channel.getsockname()[0]
    header = _HEADER.pack(_HEADER.size + len(payload), request, 0x301, sequence, port)
    channel.sendto(header + payload, (0, 0))  # REQUEST | ROOT | MATCH; no write operation
    result: list[bytes] = []
    total = 0
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("bounded network dump")
        channel.settimeout(remaining)
        data, _, flags, sender = channel.recvmsg(65536)
        total += len(data)
        if not data or flags & socket.MSG_TRUNC or sender != (0, 0) or total > _MAX_DUMP_BYTES:
            raise ValueError("network dump is not complete kernel evidence")
        batch = messages(data, sequence, port)
        for index, (kind, item) in enumerate(batch):
            if kind == 3:  # NLMSG_DONE includes an integer return code
                if index != len(batch) - 1 or item != b"\0\0\0\0":
                    raise ValueError("network dump completion is invalid")
                return tuple(result)
            if kind != response or len(result) >= _MAX_MESSAGES:
                raise ValueError("unexpected or oversized network dump")
            result.append(item)


@dataclass(frozen=True)
class Link:
    index: int
    hardware_type: int
    flags: int
    state: int
    name: str


@dataclass(frozen=True)
class Address:
    index: int
    family: int
    prefix: int
    scope: int
    values: tuple[bytes, ...]


@dataclass(frozen=True)
class Route:
    family: int
    prefix: int
    source_prefix: int
    tos: int
    kind: int
    # Keep stable routing semantics, exclude only cache counters/expiry statistics.
    values: tuple[tuple[int, bytes], ...]


@dataclass(frozen=True)
class NetworkSnapshot:
    links: tuple[Link, ...]
    addresses: tuple[Address, ...]
    routes: tuple[Route, ...]


def parse_snapshot(
    links: tuple[bytes, ...], addresses: tuple[bytes, ...], routes: tuple[bytes, ...]
) -> NetworkSnapshot:
    parsed_links = []
    for data in links:
        family, hardware, index, flags, _ = _LINK.unpack_from(data)
        attrs = attributes(data[_LINK.size :])
        name = attrs[3]
        if family != 0 or index <= 0 or not name.endswith(b"\0") or b"\0" in name[:-1]:
            raise ValueError("invalid network interface identity")
        if len(attrs[16]) != 1:
            raise ValueError("unobservable interface state")
        parsed_links.append(Link(index, hardware, flags, attrs[16][0], name[:-1].decode()))
    if len({v.index for v in parsed_links}) != len(parsed_links):
        raise ValueError("duplicate network interface index")
    parsed_addresses = []
    for data in addresses:
        family, prefix, _, scope, index = _ADDRESS.unpack_from(data)
        attrs = attributes(data[_ADDRESS.size :])
        if not set(attrs) <= {1, 2, 3, 4, 5, 6, 7, 8, 9, 11}:
            raise ValueError("unknown address observation")
        values = tuple(attrs[key] for key in (1, 2, 4, 5, 7) if key in attrs)
        if not values:
            raise ValueError("unobservable interface address")
        parsed_addresses.append(Address(index, family, prefix, scope, values))
    parsed_routes = []
    for data in routes:
        family, prefix, source, tos, table, protocol, scope, kind, flags = _ROUTE.unpack_from(data)
        attrs = attributes(data[_ROUTE.size :])
        # Preserve table, protocol, scope and flags for before/after consistency.
        attrs[0x4000] = struct.pack("=BBBBI", table, protocol, scope, kind, flags)
        parsed_routes.append(
            Route(
                family,
                prefix,
                source,
                tos,
                kind,
                tuple(sorted((k, v) for k, v in attrs.items() if k not in (12, 23))),
            )
        )
    return NetworkSnapshot(
        tuple(sorted(parsed_links, key=lambda x: x.index)),
        tuple(sorted(parsed_addresses, key=repr)),
        tuple(sorted(parsed_routes, key=repr)),
    )


def observe_network() -> NetworkSnapshot:
    if not hasattr(socket, "AF_NETLINK"):
        raise ValueError("Linux network observation unavailable")
    deadline = time.monotonic() + 2.0
    with socket.socket(socket.AF_NETLINK, socket.SOCK_RAW, 0) as channel:
        channel.settimeout(2.0)
        channel.bind((0, 0))
        links = _dump(channel, 18, 16, _LINK.pack(0, 0, 0, 0, 0), 1, deadline)
        addresses = _dump(channel, 22, 20, _ADDRESS.pack(0, 0, 0, 0, 0), 2, deadline)
        routes = _dump(channel, 26, 24, _ROUTE.pack(0, 0, 0, 0, 0, 0, 0, 0, 0), 3, deadline)
    return parse_snapshot(links, addresses, routes)


def _loopback(family: int, value: bytes, prefix: int) -> bool:
    size = {INET: 4, INET6: 16}.get(family)
    if size is None or len(value) != size or not 0 <= prefix <= size * 8:
        return False
    address = ipaddress.ip_address(value)
    # Require the whole prefix to stay in loopback, not merely its first address.
    return address.is_loopback and prefix >= (8 if size == 4 else 128)


def _index(value: bytes) -> int:
    if len(value) != 4:
        raise ValueError("invalid route interface index")
    return int(struct.unpack("=I", value)[0])


def isolated_state(snapshot: NetworkSnapshot) -> dict[str, bool]:
    loops = {
        item.index
        for item in snapshot.links
        if item.hardware_type == 772 and item.flags & _LOOPBACK
    }
    links_safe = len(loops) == 1 and bool(snapshot.links)
    for item in snapshot.links:
        if item.index in loops:
            links_safe &= bool(item.flags & 0x1) and item.state in (0, 6)
        else:
            links_safe &= (
                not item.flags & (_UP_FLAGS | _LOOPBACK)
                and item.hardware_type != 772
                and item.state in (2, 3)
            )
    addresses_safe = bool(snapshot.addresses)
    for address in snapshot.addresses:
        addresses_safe &= (
            address.index in loops
            and address.scope == 254
            and all(_loopback(address.family, v, address.prefix) for v in address.values)
        )
    routes_safe = True
    for route in snapshot.routes:
        attrs = dict(route.values)
        # No alternate nexthop, gateway, multipath, encapsulation, NAT or unknown
        # forwarding extension. Even an external route on a down device fails.
        if (
            route.family not in (INET, INET6)
            or route.source_prefix != 0
            or route.tos != 0
            or not set(attrs) <= {1, 3, 4, 6, 7, 8, 15, 20, 0x4000}
        ):
            routes_safe = False
            continue
        output = _index(attrs[4]) if 4 in attrs else 0
        input_index = _index(attrs[3]) if 3 in attrs else 0
        if input_index not in loops | {0} or output not in loops | {0}:
            routes_safe = False
        if 7 in attrs and not _loopback(
            route.family, attrs[7], 32 if route.family == INET else 128
        ):
            routes_safe = False
        if route.kind in (6, 7, 8):  # BLACKHOLE, UNREACHABLE, PROHIBIT cannot forward
            continue
        # THROW is deliberately rejected: it continues lookup in another table.
        if (
            route.kind not in (1, 2, 3)
            or output not in loops
            or 1 not in attrs
            or not _loopback(route.family, attrs[1], route.prefix)
        ):
            routes_safe = False
    return {
        "network_links_inactive": bool(links_safe),
        "network_addresses_loopback_only": bool(addresses_safe),
        "network_routes_nonforwarding": routes_safe,
    }


def denied_connections(family: int) -> bool:
    destination = ("203.0.113.1", 9) if family == socket.AF_INET else ("2001:db8::1", 9, 0, 0)
    for kind in (socket.SOCK_STREAM, socket.SOCK_DGRAM):
        try:
            channel = socket.socket(family, kind)
        except OSError as error:
            if family == socket.AF_INET6 and error.errno == errno.EAFNOSUPPORT:
                continue  # Explicitly absent protocol, not a successful connection.
            return False
        with channel:
            channel.settimeout(0.25)
            try:
                channel.connect(destination)
            except OSError as error:
                if error.errno != errno.ENETUNREACH:
                    return False  # Refused, timeout, permission or unknown != no route.
            else:
                return False
    return True


def audit_network() -> dict[str, bool]:
    checks = {
        "network_observed": False,
        "network_snapshot_stable": False,
        "network_links_inactive": False,
        "network_addresses_loopback_only": False,
        "network_routes_nonforwarding": False,
        "ipv4_connect_denied": False,
        "ipv6_connect_denied": False,
    }
    try:
        before = observe_network()
        checks["network_observed"] = True
        checks.update(isolated_state(before))
        # Never attempt even the fixed test destinations if structural isolation
        # has failed. No DNS resolution or application payload is involved.
        if all(
            checks[k]
            for k in (
                "network_links_inactive",
                "network_addresses_loopback_only",
                "network_routes_nonforwarding",
            )
        ):
            checks["ipv4_connect_denied"] = denied_connections(socket.AF_INET)
            checks["ipv6_connect_denied"] = denied_connections(socket.AF_INET6)
        after = observe_network()
        checks["network_snapshot_stable"] = before == after
    except (OSError, ValueError, KeyError, struct.error, UnicodeError):
        checks["network_observed"] = False
    checks["no_external_interface"] = all(checks.values())
    checks["network_denied"] = checks["no_external_interface"]
    return checks
