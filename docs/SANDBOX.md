# Artifact execution boundary

macOS/Apple Silicon on the existing Mac Studio Docker Desktop is the first
acceptance target; Linux AMD64 remains a separately validated target. Decision
S3-26 records approval of ordinary Docker's residual shared-kernel risk and the
trusted evaluator controller's Docker API grant. No extra VM, gVisor registration,
privileged container, added capability, TCP endpoint or host permission change is
part of that grant. **The first Mac Docker-native readiness attempt failed;
acceptance of the corrected source remains pending.**

## Docker-native backend

`DockerNativeProfile/2` and `DockerNativeReadiness/2` identify the new shared-kernel
boundary; `sandbox_docker_native_v1.json` is distinct from retained runsc profiles.
The approved financial protocol, seeds, goldens and exposure accounting are
unchanged. Old records are not relabelled or rewritten. The native profile uses
16 total container tasks, including trusted overhead, instead of cross-container
per-real-UID RLIMIT_NPROC; all other pilot CPU/memory/deadline/output limits remain.

Only the trusted controller opens the existing Unix Docker API. It has no DB
credential, provider key, signing key or full-data mount. The evaluator worker
uses a 0600 Unix socket in a 0700 named volume. Research/MCP/Registry/artifacts
have neither socket mounted. The serialized controller accepts only bounded
contract/package/input requests for its preconfigured profile and immutable image.
It cannot accept caller-supplied Docker options, mounts, runtimes, URLs or pulls.
A read-only Docker socket mount still grants powerful API authority; it is not a
read-only API. Explicit engine socket path and existing socket GID are required.

Each job uses a labelled size-bounded tmpfs volume for sanitized inputs. A trusted
idle helper mounts it while the controller transfers a generated regular-file tar
through the local Docker API. Checksums and modes are verified. The candidate's
read-only mount starts before the helper is removed, retaining the tmpfs contents;
writer removal and a second seal check precede candidate execution. There is no
host-data bind or writable host result mount. Capped results use the existing
no-follow reader and independent typed validation. Input volume and containers
are removed with ownership and absence checks. Uncertain cleanup poisons the
controller; startup refuses leftover labelled resources, requiring explicit
inspection, rather than silently deleting them or accepting another job.

The native execution command starts a small trusted supervisor inside the same
job cgroup before launching the guest. Its overhead counts against the unchanged
16-task and memory limits. It holds non-inherited, read-only descriptors for
`memory.events` and `pids.events`, requires a fresh zero-event baseline and rejects
missing, malformed or backwards counters. After the guest exits, positive OOM
events classify memory failure; otherwise positive PID-limit events classify
process failure. Combined exhaustion reports memory first. A bare candidate
SIGKILL/exit 137 does not prove OOM. An unexplained supervisor exit without OOM
evidence is backend unavailable, not a guessed candidate failure. The supervisor
uses the existing bounded, no-follow result
reader in its own process, avoiding an extra exec when the task limit is full.
Its whole execution/result collection remains externally deadline-bounded;
uncertain observation fails as backend unavailable. External ownership-verified
cleanup remains mandatory, including any background descendants.

These are Linux [cgroup v2 event counters](https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html),
not candidate exception messages or guesses from elapsed time. The container's
`OOMKilled` flag is retained only as fallback evidence when the supervisor itself
cannot complete. New supervisor code requires a rebuilt core image; historical
runsc commands and profiles remain unchanged.

The engine must implement API v1.45, cgroup v2, runc and seccomp. Every actual job
is inspected for its runtime, namespaces, no-network setting, non-root UID,
capabilities, no-new-privileges, exact memory/swap/CPU/PID/ulimit/tmpfs limits,
readonly input, image and pinned Moby seccomp policy. Readiness additionally checks
the guest's effective cgroup values, process flags, denied writes/network and
absence of private packages/assets. Native engine OS/CPU and controller OS/CPU are
separate evidence fields; a Linux controller cannot certify the physical Mac host.

The native no-egress probe reads complete, bounded Linux RTNETLINK link, address
and route dumps for all families and routing tables. Device names are not a
security boundary: Desktop may expose inactive tunnel templates even with
`network=none`. Exactly one actual loopback device must be up. Every other device
must have inactive administrative/carrier flags and a down operational state, no
IP address, and no forwarding route. Loopback addresses and routes must remain
entirely within 127/8 or ::1/128. Default/external routes, gateways, alternate
nexthops, multipath, unknown forwarding features and contradictory state fail.
Explicit discard routes are distinguished from routes that continue lookup.

Only after those structural checks pass does the trusted probe attempt bounded
IPv4 and IPv6 TCP/UDP connections to fixed documentation addresses, without DNS
or application payload. Only the kernel's network-unreachable result passes;
refusal, timeout, permission errors and connection success fail. An explicitly
unsupported IPv6 socket family establishes protocol absence. A second full snapshot
must match the first. Interrupted, filtered, truncated, malformed, unreadable or
changing observations fail closed. The existing private namespace, `network=none`,
dropped capabilities, pinned seccomp and no-new-privileges checks remain required.
This is operational isolation evidence, not protection from a kernel escape.

This probe follows the Linux [operstate semantics](https://www.kernel.org/doc/html/latest/networking/operstates.html),
[netlink dump protocol](https://www.kernel.org/doc/html/latest/userspace-api/netlink/intro.html)
and [RTNETLINK interface/address/route definitions](https://man7.org/linux/man-pages/man7/rtnetlink.7.html).
Docker's [none-network example](https://docs.docker.com/engine/network/drivers/none/)
does not establish an invariant about names of inactive kernel devices. The
guest core package now contains the observer: rebuild both the core-only sandbox
and evaluator/controller images for this source. An older image cannot supply
the probe and must fail readiness. Legacy runsc probe/evidence are unchanged.

`infra/docker-compose.sandbox.yml` is an opt-in overlay (`--profile sandbox`),
not an automatic startup or research trigger. Supply reviewed
`QFR_SANDBOX_CONTROLLER_CONFIG`, `QFR_DOCKER_SOCKET`, and `QFR_DOCKER_SOCKET_GID`
without changing their host permissions. Determine the GID **inside the intended
controller container**: Desktop may present a root-owned GID-0 socket while the
Mac host shows GID 20. The controller remains UID/GID 65532; only its existing
`group_add` receives the observed socket GID. GID 0 here is a container-local
supplemental group, not UID 0, a capability or a host-group change. Keep its mounts
restricted to the existing engine socket, configuration and private IPC volume.
Candidate/staging containers explicitly reject all supplemental groups, and the
evaluator worker receives only its private IPC socket, never this group/API grant.

For a read-only permission diagnosis, retain the deployment's existing Compose
project, files, environment and image options and run the controller service with
`run --rm --no-deps sandbox-controller python -m qfr_eval.sandbox.socket_check`.
This reports the mounted socket's numeric ownership/mode, process IDs/groups and
effective connect permission. Exit 1 means the grant is missing; it changes
nothing and does not contact Docker. Set the already-required GID variable to
that observed group for this controller only, then rerun the diagnostic and actual
Compose startup/boundary checks. There is no root entrypoint, chmod/chown, group
auto-discovery fallback, host group edit or new endpoint. If effective access is
still denied, startup fails and the reason must be investigated.

The config is a
`DockerControllerConfiguration`, with the native profile, loaded immutable image,
`docker_socket=/var/run/docker.sock`,
`control_socket=/run/qfr-sandbox/controller.sock`, `max_parallel_jobs=1`.
It contains no credential. The controller image pre-provisions the private socket
directory; only controller/eval-worker mount it. The existing eval-worker remains
idle until explicitly invoked with an evaluator-owned session configuration.

The controller has a 1.5 GiB/1 CPU/32-task envelope. A pilot job reserves two
1 GiB containers during handoff plus a 128 MiB input tmpfs; output scratch is
within the candidate's 1 GiB cgroup. Only one job runs at a time. Allow additional
headroom for the trusted evaluator, database and Docker overhead; run full pilot,
image matrices and large suites on the Mac. A measured budget violation fails;
no automatic resource increase or weaker profile is selected.

For actual Mac acceptance, load the rebuilt core-only sandbox image and set
`QFR_TEST_SANDBOX_BACKEND=docker-native`, `QFR_TEST_DOCKER_SOCKET` to the verified
existing engine Unix socket path, and `QFR_TEST_SANDBOX_IMAGE` to its immutable
local image ID. Run `tests/evaluator/test_sandbox.py`; the fixture launches a
separate controller with a curated environment that excludes DB/provider secrets.
For all four Registry pilot gates, additionally set
`QFR_TEST_PILOT_SANDBOX_IMAGE` to the same full core image and run
`tests/registry/test_pilot_execution.py` with required PostgreSQL, private inputs
and original oracle prerequisites. The tests retain every assertion; missing
inputs are UNRUN and supplied-but-unavailable controls fail. Test the real Compose
controller and role/socket boundaries separately; native fixture success does not
prove the containerized controller or Apple host acceptance.

See [the approved design](proposals/DOCKER_NATIVE_SANDBOX.md) for the complete
remaining gate matrix. Passing these tests cannot prove absence of kernel exploits.

## Retained runsc backend and historical evidence

The following describes the original versioned backend and its historical evidence.
It is retained for those records; it is not a fallback for a selected native profile.

The private evaluator controls Docker through an explicit local Unix socket.
Artifacts, research and MCP receive no socket. `SandboxRunner` accepts an immutable
local image ID and the versioned operational profile. It never pulls an image or
substitutes another runtime. Registered Docker metadata alone is insufficient:
readiness executes a trusted probe inside the requested gVisor container and
checks its actual process identity, capabilities, no-new-privileges flag, denied
network access, read-only root and absence of private packages/assets.

Every container uses `runsc`, no network, a non-root UID, ALL capabilities dropped,
no-new-privileges, a read-only root, CPU/memory/PID limits, disabled additional swap,
bounded file descriptors and file sizes, bounded noexec/nosuid/nodev tmpfs and no
Docker logs. The evaluator permits only a newly staged read-only input mount.
Its enclosing host directory remains 0700; only sanitized child directories and
copied input files are readable by the sandbox UID. Original files and their modes
are unchanged. This explicitly handles a host umask of 077.

The stdlib bridge lives in public core and imports no evaluator code. It applies
the declared seed to Python and NumPy, redirects candidate stdout/stderr away from
logs, and exports one capped JSON envelope. Diagnostics are fixed codes, never
candidate exception text. The reader opens only the expected regular result file
with `O_NOFOLLOW`; the evaluator separately caps the stream, deadline and schema.
The result stays in gVisor's tmpfs until cleanup. Docker `cp` cannot be relied on
to read that namespace. No writable host output mount is added to work around it.

External deadlines terminate the Docker control process and remove the named
container. Removal is verified; uncertain cleanup raises an error and cannot
produce a successful result. An internal supervisor lifetime also bounds orphaned
execution if the evaluator itself disappears. Queue recovery remains the private
scheduler's responsibility.

`configs/evaluation/sandbox_pilot_v2.json` records implementation resource limits,
separately from the approved measurement and financial screening policies. The
pilot profile currently allows one CPU, 1 GiB memory, 64 container tasks, 16 guest
processes, 120 CPU seconds and a 180-second execution deadline. These settings
require validation with the actual pilot runner image; small stdlib probes do not
establish that acceptance. `Dockerfile.sandbox` installs only public core and its
locked dependencies into the final image and rejects private QFR packages during
the build. Its image build and full pilot replay are pending.

Revision 2 binds the dependency lock containing evaluator thread-pool introspection.
Its runsc backend, user, security controls and all resource limits are identical to
the preserved `sandbox_pilot_v1.json`. Existing v1 artifacts/evidence keep their
original lock and profile identity; this revision is not a new sandbox backend or
Apple readiness claim. Final images and native Mac execution need fresh evidence.

The static source checks are defense in depth. They are never permission to run
Python outside this boundary. Constrained Python factors also reject direct date
and identifier access; imported package/model/strategy runners retain the declared
keys needed by their business rules. Unsupported interfaces or mismatched image,
lock, profile, seeds and limits fail explicitly.

Constrained factors additionally receive an anonymous numeric table: series and
observation indices plus declared numeric fields. No calendar, instrument names or
unsanitized input file accompanies it. The trusted adapter restores original keys
only after validating the exact returned anonymous grid. Frozen models require
matching declared and packaged JSON weights. Both paths have been exercised with
small actual gVisor fixtures; that evidence does not validate the full pilot image.

The causal screening layer compares exact output identity and structure, applies
the already-approved floating tolerances to numeric prefix comparisons, repeats
the same execution for exact deterministic hashes, and changes only post-cutoff
finite float inputs for perturbation. Its fixed scale is a versioned test operation,
not a change to measurement inputs. Both prefix and perturbation failures are
recorded for the planted lookahead fixture. Empty comparisons and absent future
observations cannot pass. The label remains “lookahead tested, not certified”.

Coverage uses evaluator-built original eligible grids. Returned rows cannot reduce
the denominator. Every required eligible score must exist and be finite. Constant
means exact equality across every eligible development cross-section; near-constant
values do not introduce another threshold. Partial constancy is diagnostic. A
fixed-position strategy exemption cannot exempt a factor or model.

Bounded acceptance tests use an explicit local `QFR_TEST_SANDBOX_IMAGE`; missing
configuration is reported as an unrun sandbox suite. A configured but unavailable
backend fails. Real cloud x86_64 tests have exercised 128 MiB/0.5 CPU/64 PID/2 MiB
tmpfs fixtures, including output limits, symlinks, bounded process creation,
timeouts, CPU and memory exhaustion, determinism and planted lookahead. This is
separate from full pilot acceptance, native Apple host validation and the final local CI
matrix. Heavy suites and image matrices remain assigned to the owner's Mac.

`bash scripts/build_sandbox_images.sh amd64` (or `arm64`) produces a separate
core-only OCI archive and source/platform digest evidence. It does not register
runsc, load/publish images, or claim runtime acceptance. The final full pilot
tests require an explicitly loaded immutable local image ID through
`QFR_TEST_PILOT_SANDBOX_IMAGE`; use the container platform matching the deployment
(`linux/arm64` on Apple, `linux/amd64` on Linux AMD64), record the actual host OS/CPU
and label emulation separately. Missing configuration is reported as UNRUN; supplying an
image while runsc is unavailable fails the readiness assertion.
