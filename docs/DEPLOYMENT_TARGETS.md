# Deployment targets and acceptance evidence

Owner-directed clarification, October 27, 2026. The governing contract is
[PLAN_ALIGNMENT section H](PLAN_ALIGNMENT.md#h-docker-and-architecture-acceptance);
the ordered gates are in development-plan sections 10 and 11. This document
changes deployment terminology and acceptance order, not measurement or isolation
requirements. Decision S3-18 records the amendment.

| Deployment target | Host OS / CPU | Engine and container platform | Acceptance order |
|---|---|---|---|
| Apple first | macOS / Apple Silicon ARM64, the Mac Studio | Existing Docker Desktop; Linux ARM64 engine and `linux/arm64` containers | First production release after the complete Apple gate passes |
| Linux AMD64 | Native Linux / AMD64 | Linux engine and `linux/amd64` containers | Supported follow-on target; separately validated before claiming production readiness there |

An Apple deployment is not a native macOS container image. Its native host tools,
MCP client, file imports and Docker Desktop integration must work on macOS even
though application containers run Linux. An ARM64 Linux cloud runner establishes
only its own Linux evidence. An AMD64 image built or run under emulation on the Mac
does not establish native Linux AMD64 acceptance. Both image variants remain in
the build matrix.

## Release and evidence matrix

| Evidence | First Apple release | Later Linux AMD64 acceptance |
|---|---|---|
| AC-01–AC-14 functional, boundary, provider and delivery checks | Required in the Apple deployment scope; no missing mandatory input or failed check becomes a pass | Repeat applicable deployment/end-to-end checks on the native Linux host, linked to the accepted source and configuration |
| ARCH-01 startup, imports, migrations, MCP, stop/resume and export | Required on the actual Mac Studio using its existing Docker Desktop | Required on native Linux AMD64 |
| Sandbox SBX-01–05 and executable pilot replay | Required through the actual Apple deployment; cloud fixtures cannot substitute | Required independently through the Linux deployment |
| Numerical/oracle checks and deterministic replays | Required at frozen tolerances with exact structural checks and runtime-specific hashes | Required with the same frozen rules and independent hashes |
| ARCH-02 native cross-target comparison | Record UNRUN if the Linux target record is not yet available; does not gate the first Apple release | Required against the accepted Apple record before Linux AMD64 readiness is claimed |
| Linux ARM64 and AMD64 image builds | Both required, with architecture and emulation recorded | Preserve both variants and target-specific digest evidence |
| Recovery and backup/restore drills | Required on the Apple deployment before release | Required on Linux AMD64 before its release claim |

No acceptance is claimed by this table. Linux AMD64 remains an intended supported
target while its native validation is pending. The Apple release must be labelled
with its target scope; it cannot advertise both targets as production-validated.

## Recording a run

Capture the exact source commit/tree, dependency lock, host OS/version/hardware
architecture, Docker Desktop or Linux engine version, container OS/architecture,
image identity, isolation runtime/version and native/emulated execution mode.
Record commands, timeouts, memory/disk/inode headroom, results and explicit skip or
UNRUN reasons. Keep host and container test reports separate. Link immutable
protocol, input and output hashes without publishing licensed data or credentials.

On Apple, exercise host import mounts and permissions, host loopback MCP access,
Compose initialization and restart, persistent state, stop/resume, artifact export
and isolation through the actual Desktop deployment. A container-only Python pass
does not cover these host integration paths. No runtime fingerprint or old report
is retrospectively relabelled as macOS evidence.

## Current execution boundary

Decision S3-26 records owner approval for an ordinary-Docker backend on the
existing engine, accepting residual shared-kernel risk and granting Docker API
access only to a trusted evaluator controller. No extra VM, gVisor registration,
privileged container, broad socket mode change or TCP Docker endpoint is part of
this deployment. Research/MCP/Registry/artifacts receive no controller channel.

Implementation and actual Apple acceptance are separate. The latest Mac report
passes actual readiness, SBX tests and the four Registry P0/P1 cases on the source
identified in [STAGE_3_ACCEPTANCE.md](STAGE_3_ACCEPTANCE.md). Subsequent reconciliation
also passes actual Compose restart, deployed socket boundaries and final local
image verification; Stage 3's Apple-first exit gate is green. Historical runsc
evidence keeps its original Linux scope. Native Linux AMD64 acceptance remains separately required before claiming
that target ready. See [SANDBOX.md](SANDBOX.md).
