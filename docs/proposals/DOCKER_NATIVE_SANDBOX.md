# Docker-native artifact execution — approved design, validation pending

Version 0.2.0, October 28, 2026. **Implementation in progress; runtime gates UNRUN.**
The owner explicitly approved ordinary Docker's residual shared-kernel risk and
Docker API access only for the trusted evaluator controller. Public approval
reference: `owner-approved-2026-10-28-docker-native-v1` (decision S3-26). Private
approval evidence stays outside Git. This grants no additional host/security
changes and waives no acceptance test. The existing Mac Studio Docker Desktop
remains the first deployment target; no new VM or gVisor registration is needed.

## Feasibility and security boundary

The explicit controls in [plan section 7.3](../HYBRID_V1_DEVELOPMENT_PLAN.md#73-execution-contracts-and-sandbox)
can be expressed using standard Docker container creation, namespaces, cgroups,
seccomp and process limits. A backend using Docker's ordinary OCI runtime is a
concrete engineering path, not yet evidence that those controls work on the Mac.
No gVisor registration, nested runtime, ECI subscription or additional VM is part
of this proposal.

There is a material difference: ordinary containers share the Desktop Linux
kernel with QFR's trusted services and other containers. gVisor interposes its
own userspace kernel. Network/mount denial does not make a kernel exploit
impossible, and passing the existing negative fixtures cannot prove equivalent
kernel-escape resistance. Docker Desktop's outer VM does not isolate one QFR
container from another inside that VM.

The owner has accepted this shared-kernel boundary for submitted Python. It is
not equivalent kernel-escape resistance to gVisor. The required controls and
negative fixtures remain acceptance requirements; a DSL-only result cannot
replace executable model/strategy/package acceptance.

## Proposed topology

- Keep the existing Compose services and three database/role boundaries.
- Add a small, trusted evaluator-side sandbox controller. It alone receives
  access to the existing local Docker API; it receives no database password,
  signing key, full dataset mount, Registry mutation authority or provider key.
- The evaluator sends bounded job inputs and a frozen execution specification
  over a private control channel accessible only to the evaluator. The controller
  is not a generic Docker proxy: no caller-selected host path, image pull, URL,
  runtime, mount, network, privilege flag or shell command is permitted.
- Every executable artifact gets a new disposable container. Research, MCP,
  Registry and artifact containers receive neither the Docker socket nor access
  to the controller. Only authorized input slices enter an artifact container.
- Keep timeout, output validation and container/volume cleanup outside candidate
  control. Control-plane failure or uncertain cleanup cannot produce success.

Docker API access is powerful even when its Unix socket bind mount is marked
read-only. The owner has now given this exact controller-only grant.
Do not use Compose `use_api_socket`, which can forward client credentials, or
enable a TCP Docker endpoint. Do not alter the daemon, socket permissions, Docker
group membership or host runtime settings to make the grant work silently.

The current Compose file does not give the evaluator Docker API access. Its
host-invoked runner is not proof that a fully containerized controller is already
deployed. The controller is a real architecture addition requiring review.

## Input and output lifecycle

The current runner stages a client-local temporary path and asks the daemon to
bind-mount it. Inside a controller container, that path need not exist in the
daemon's filesystem. Do not solve this with a broad host-directory mount.

Proposed replacement: a uniquely named, task-labelled Docker local volume backed
by size-capped tmpfs, with fixed driver options and no host-device/path option.
Docker documents tmpfs local-volume support on Linux and Docker Desktop; the
actual Mac lifecycle still needs validation.

1. A pinned trusted staging helper copies a bounded stream of validated regular
   files into this one volume; it never imports or executes the package. Hashes,
   file counts, aggregate size and directory/symlink rules are checked.
2. Create and start the candidate container with a trusted idle entrypoint and
   the input volume mounted read-only. Keep the tmpfs mounted during this handoff
   so that removing the last writer cannot discard the input prematurely.
3. Stop and remove the staging helper; verify that no writable helper attachment
   remains before candidate execution. Verify the candidate's input hashes.
4. Execute the declared entrypoint without network access. Scratch and the single
   result stay in bounded tmpfs. Use the existing bounded no-follow result reader;
   do not add a writable host output directory or deserialize arbitrary objects.
5. Remove and verify removal of the job's container and volume. Retry recovery
   reconciles recorded ownership and leases; it never prunes unrelated resources.

This flow is proposed, not tested. Input tmpfs memory is counted in the total job
and concurrency admission budget even when staging and execution use different
cgroups. Stage durations and transfer/output bytes need explicit bounds; a large
input or failed mount must fail clearly rather than spill to an uncapped disk.

## Runtime contract and retained controls

Add a versioned `docker-native-v1` backend identity and new immutable profile;
preserve all earlier runsc profiles, receipts and their serialization. New
deployments may select it only after the security decision and actual gates pass.
There is no automatic fallback from either backend to the other.

The new profile must retain:

- A local immutable image ID, pinned dependency lock, fixed entrypoint grammar,
  seeds and numerical controls; no pull, build, install or online inference at
  measurement time.
- Network mode `none`, private PID/IPC namespaces, non-root user, zero effective
  and bounding capabilities, no-new-privileges, no devices or host namespaces.
- Read-only root and input, no Docker/control socket, no private packages,
  credentials, protocol files or full datasets; only bounded scratch is writable.
- Enforced CPU quota and CPU-time limit, memory with no extra swap, task count,
  file-size and descriptor limits, capped result stream and external deadline.
- No candidate logging or exception-text release; only validated output and
  fixed diagnostic codes; verified cleanup including uncertain create outcomes.
- An explicit reviewed seccomp policy with pinned identity, derived from the
  applicable Docker profile without broadening its allowed operations. It must
  not disable seccomp/AppArmor or require privileged mode, SYS_ADMIN or host
  configuration. Missing required kernel controls fail readiness.

Readiness must validate actual container and guest state, not merely Docker's
reported default runtime. Reject an unexpected runtime, unenforced cgroup,
unconfined seccomp, wrong mounts/capabilities or missing proof. Record the Mac
host receipt separately from the Linux engine/container identity: Docker info's
`OSType` is the engine OS, not proof of a macOS host.

## Specific process-limit incompatibility to resolve

The current guest sets `RLIMIT_NPROC=16` and every sandbox uses UID 65532. Linux
accounts this limit by real user ID, including threads, rather than by container.
Ordinary containers can therefore interfere through that UID's process count;
the current setting cannot simply be relabelled as a private per-job limit.
This is a code/OS-semantics finding, not a reproduced Mac test failure.

Proposed native policy: use a per-container cgroup ceiling of 16 total tasks,
including trusted supervisor threads, instead of using shared-UID RLIMIT_NPROC
as the job's limiter. This preserves an upper bound no greater than the current
16 guest tasks; the runsc profile's separate 64-task bootstrap allowance remains
historical. The stricter total ceiling may reject a legitimate workload and must
be tested with the real pilot and concurrent jobs. If insufficient, report the
required policy decision rather than increasing it automatically. Do not make
the guest privileged to manage its own cgroup or change daemon user mappings.

## Implementation and validation sequence

1. Schema-first backend/profile/readiness revision in `qfr_eval.sandbox.models`,
   generated private contracts and immutable execution-bundle references. Add
   offline tests for explicit selection, unsupported backends and legacy identity.
2. Separate Docker request construction, actual-state verification and lifecycle
   from the backend-specific checks in `qfr_eval.sandbox.runner`. Test adversarial
   specs, unexpected runtime, partial create, oversized output and uncertain
   cleanup without calling Docker. Keep the existing backend behavior unchanged.
3. Implement the bounded trusted controller/staging lifecycle and private
   evaluator integration. Review the exact Compose diff and Docker API grant
   before deployment. No API or mount is added to research/MCP/artifacts.
4. Implement native cgroup/guest checks, pinned seccomp identity and resource
   admission. Add failure and concurrency regressions; then run the approved
   bounded actual-engine tests on the Mac.
5. Keep the reviewed Compose overlay opt-in until actual acceptance; reconcile
   runbooks and plan references with the approved boundary. Do not mutate original profiles,
   measurement policy, goldens, records, exposure or feedback budgets.

## Acceptance evidence; no existing gate removed

| Requirement | Required evidence on the actual Mac deployment |
|---|---|
| SBX-01 | Planted lookahead fails both prefix and future-perturbation checks with the prescribed code |
| SBX-02 | Bounded network, filesystem, process, memory, CPU, output and timeout failures; no private/control access; verified cleanup |
| SBX-03 | Native host/engine/image/backend identities and all effective controls; disabled/unavailable/mismatched backend refuses execution |
| SBX-04 | Exact deterministic rerun and nondeterministic rejection under the frozen numerical runtime |
| SBX-05 | Research, MCP and artifact containers have no Docker socket, privileged flag or writable host mount; controller inaccessible from those zones |
| Registry pilot | All four real P0/P1 sandbox execution/measurement/reproduction cases; unchanged original oracle and exact structural results |
| Additional native risks | Concurrent jobs do not share resource quotas or inputs; staging is sealed before execution; interrupted creation/cleanup/restart cannot leak inputs or return success |
| Deployment | Real Compose initialization/restart, DB boundaries, host/container suites and both image variants; native Linux AMD64 acceptance remains separately deferred |

Passing this matrix establishes the specified operational controls, not immunity
to unknown kernel exploits. Residual shared-kernel risk must remain explicit in
the approval and deployment record. All new runtime gates are UNRUN today.

## Decisions and blockers

- **Security decision approved:** ordinary Docker shared-kernel risk is accepted;
  no claim of gVisor equivalence.
- **Deployment grant approved:** only the trusted controller may access the
  existing Docker API. No persistent credential, TCP API, host group/mode change,
  privileged container or extra capability is authorized.
- **Engineering evidence pending:** native resource enforcement and concurrency,
  tmpfs handoff/cleanup, pinned seccomp compatibility and full Registry pilot.
- A backend/profile selection and equivalent tests need a recorded amendment to
  the implementation contract. The financial protocol, stage order and required
  security properties do not change. Stage 3 remains incomplete.

## Primary sources checked

- [Docker security and daemon authority](https://docs.docker.com/engine/security/).
- [Container creation and resource controls](https://docs.docker.com/engine/containers/run/).
- [Docker's warning about per-user nproc limits](https://docs.docker.com/reference/cli/docker/container/run/#for-nproc-usage).
- [Linux RLIMIT_NPROC semantics](https://www.man7.org/linux/man-pages/man2/getrlimit.2.html).
- [Docker Desktop local tmpfs volume support](https://docs.docker.com/reference/cli/docker/volume/create/#driver-specific-options--o---opt).
- [Docker seccomp policy](https://docs.docker.com/engine/security/seccomp/).
- [Existing QFR isolation contract](../SANDBOX.md) and [deployment matrix](../DEPLOYMENT_TARGETS.md).
