# Stage 4 loopback connectivity: pending deployment approval

Revision 1, October 28, 2026. **Proposal only.** No relay, network, listener or
Docker/host setting has been created or activated by this change. The current
Compose topology is unchanged. Stage 4 remains incomplete.

## Observed failure and its scope

On reviewed commit `ba803ef2850d072d4d3f06fe95f07f919bb11b69`, the Mac reported
**1,131 native tests passed with no skips**, and **1,105 container tests passed
with 26 skips**. These suite results do not prove the deployed host connection.
The Stage 4 MCP container has a configured `127.0.0.1:8000` publication, but no
active Docker port mapping. All four attached networks are internal. The actual
Mac Codex/second-client flow and elapsed six-hour release have not started.

The repository defect is an unverified deployment assumption: the overlay and
guide treated a declared port as a usable host endpoint. Docker's internal mode
omits the default route and blocks cross-network traffic; Docker Desktop needs
its backend's host port forwarding to reach Linux containers from macOS.
The same internal-only port-publication symptom is recorded in upstream Moby
issue 36174. That historical issue is corroboration, not proof of every current
engine's behavior; retain the Mac engine version and actual inspection evidence.

An additional ordinary bridge attached directly to MCP is a small YAML change,
but it also adds outbound connectivity to a service holding scoped tokens. It
is **not** merely a loopback-bind repair. Reusing `db-loopback` would additionally
place MCP on a PostgreSQL network and is not proposed.

## Proposed production change for specific approval

Use a dedicated, bounded TCP relay in a separate non-root container. Reuse the
reviewed `qfr_mcp` application image with a new fixed-destination relay entry
point; no new third-party image, package or daemon grant is needed. The relay
implementation and versioned operational profile would be reviewed and tested
before activation. It is not implemented in this proposal checkpoint.

| Element | Exact proposed change |
|---|---|
| New service `mcp-ingress` | Publish only `127.0.0.1:${QFR_MCP_PORT}:8000/tcp` on the existing Desktop engine. Do not publish IPv6, all-interface, LAN or remote ports. |
| New `mcp-host-edge` bridge | Non-internal, default NAT, attached only to `mcp-ingress`. This supplies the host-publication path and permits relay-container egress. |
| New `mcp-ingress` bridge | Internal; attach only the relay and `mcp-api`. The relay's sole application destination is `mcp-api:8000`. |
| Existing MCP service | Remove its ineffective host-port declaration; retain its four existing internal networks and add only the new internal ingress network. |
| Other services | No new network attachments, ports, credentials, socket access or mounts. PostgreSQL and evaluator isolation stay unchanged. |
| Relay controls | UID/GID 65532, read-only root, all capabilities dropped, no-new-privileges, 128 MiB memory with no extra swap, 0.25 CPU, 32 PIDs, no automatic restart. Read-only non-secret configuration only; no data/credential/Docker/controller mounts. |
| Versioned relay bounds | At most 16 connections, 64 KiB copy chunks, 5-second upstream-connect timeout and 60-second inactivity timeout. Close connections on upstream loss or shutdown; no request retry or disk buffering. These transport limits never complete or cancel a durable job. |

The relay passes bytes without interpreting a client-selected destination,
rewriting Host/Origin/Authorization, following redirects, caching or logging
payloads. It is not an HTTP CONNECT or general egress proxy. Existing MCP
authentication, DNS-rebinding protection, request limits and public-key checks
remain authoritative. Persistent MCP sessions and binary downloads must pass
the actual-client tests through this path.

**Residual risk to approve:** the relay has ordinary outbound connectivity on
its new bridge and sees plaintext HTTP, including bearer tokens, transiently in
memory. A compromised relay could exfiltrate or replay that traffic. A loopback
publication restricts intended inbound reach; it does not block relay egress or
authenticate other local host users. Do not describe this design as an egress
firewall. MCP itself retains internal-only networks, but an internal bridge is
not a proof against all Docker-host/gateway access. Retain the existing shared-
kernel risk and test actual denied paths. No additional Docker API access is
granted to the relay or any API.

Approval would cover creating these two project-local bridges, deploying this
one restricted relay, moving the single loopback publication and attaching MCP
to the additional internal network. It would not authorize host networking,
firewall/sysctl/daemon/Desktop changes, new capabilities, LAN exposure, a database
network attachment, remote access, persistent credentials or provider calls.
All network activation remains paused until that specific approval arrives.

## Read-only prerequisite check

The new operator checker inspects only running state, network mode and configured
versus active port bindings. It never reads container environment or mounts,
prints daemon stderr, sends an HTTP request or changes Docker state. Obtain the
exact full container ID through the existing Compose project's `ps -q mcp-api`.
After an approved relay deployment, inspect the relay ID instead. Then run:

```sh
uv run --locked --all-packages python -m scripts.check_mcp_publication \
  --container "$QFR_MCP_PUBLISHER_ID" --host-port "$QFR_MCP_PORT"
```

The versioned check profile is
`configs/infra/mcp_publication_check_v1.json`. Missing actual mapping returns
`blocked: mcp_port_not_published`, even when configuration declares the correct
port. Wildcard/additional/mismatched publications and stopped/shared-network
containers also fail. A successful check says `publication_metadata_only`, with
host MCP acceptance still `unrun`. It cannot establish reachability, endpoint
identity, authentication, LAN refusal or financial acceptance. Unit fixtures
exercise that distinction without starting Docker.

## Test-only alternative over existing networking

An operator can execute a short-lived, model-free SDK client under the existing
non-root MCP container identity, connecting to its `127.0.0.1:8000` listener (or
use an already authorized client on an existing internal network). Use only the
existing short-lived scoped test token via a private input/environment mechanism;
do not print it or substitute the service's backend credentials. No network,
port, socket grant, package installation or new persistent credential is needed.
Docker exec is initiated by the existing host operator, not by an API container.
Bound its lifetime externally; it ends on container restart. Preserve evidence
and job IDs independently of the temporary client.

This can test deployed discovery/authentication, idempotency, reconnect, durable
state and signed results through the real APIs. It is **container-side transport
evidence only**. It does not prove Mac host reachability or actual Mac Codex
acceptance and cannot close MCP-01/ARCH-01. No host forwarding listener or
Docker-exec stdio bridge is silently introduced. Neither this option nor its
description starts a real release wait or grants evaluation/query authority.

## Acceptance after approval

Record the exact Mac/Desktop/Engine versions and inspected mappings. Docker
documents a localhost-publication caveat before Engine 28; do not infer a safe
version or change it automatically. Require a real Mac loopback connection and
refusal on non-loopback/IPv6 paths, exact network membership, absent new database/
controller/Docker access, unchanged non-root/capability/mount limits, and the
actual two-client sequence. Record the relay's possible egress honestly; no
internet/provider request is needed for these checks.

Verify authentication/Host/Origin failures, oversized requests, binary transfers,
connection pressure, upstream outage, process restart and durable jobs, including
lost-ack retry without duplicate side effects. Run the final-source image/check
matrix on the Mac, carrying unchanged evidence only with verified input identity.
Then complete the real P0/P1 measurement, actual UTC release eligibility, signed
negative delivery and export gates. Pending elapsed time remains pending.

Primary sources, reviewed October 28, 2026:

- [Docker internal network mode](https://docs.docker.com/reference/cli/docker/network/create/#network-internal-mode---internal)
- [Docker port publication and localhost caveat](https://docs.docker.com/engine/network/port-publishing/)
- [Docker Desktop host/container networking](https://docs.docker.com/desktop/features/networking/networking-how-tos/)
- [Upstream Moby issue 36174](https://github.com/moby/moby/issues/36174)
- [Docker exec lifetime and environment](https://docs.docker.com/reference/cli/docker/container/exec/)
