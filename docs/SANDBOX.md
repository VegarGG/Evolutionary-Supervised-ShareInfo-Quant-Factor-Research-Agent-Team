# Artifact execution boundary

Deployment acceptance is macOS/Apple Silicon first on the Mac Studio's existing
Docker Desktop, then native Linux AMD64; see [the target matrix](DEPLOYMENT_TARGETS.md).
The Linux ARM64 engine inside Desktop is not Apple host acceptance. The retained
runsc-only runner has no validated Mac backend yet, so Apple isolation and full
Registry pilot execution remain blocked/unrun. Cloud probes below are development
evidence only. No new VM, alternative backend or runtime/security change is
authorized by this deployment correction.

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

`configs/evaluation/sandbox_pilot_v1.json` records implementation resource limits,
separately from the approved measurement and financial screening policies. The
pilot profile currently allows one CPU, 1 GiB memory, 64 container tasks, 16 guest
processes, 120 CPU seconds and a 180-second execution deadline. These settings
require validation with the actual pilot runner image; small stdlib probes do not
establish that acceptance. `Dockerfile.sandbox` installs only public core and its
locked dependencies into the final image and rejects private QFR packages during
the build. Its image build and full pilot replay are pending.

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
