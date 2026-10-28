# Stage 3 — Registry, execution contracts and sandbox

Work starts from the verified Stage 2 commit
`57fae27c956a0954f2347e203435a30883a42d09` on `stage-3-registry-sandbox`.
The branch was created without merging the predecessor. Stage 3 does not implement feedback release,
blackboard services, agents, provider calls or confirmation-query execution.

## Deployment target correction — October 27, 2026

The first deployment target is macOS on Apple Silicon (ARM64), using the Mac
Studio's existing Docker Desktop. Linux AMD64 remains the separately validated
follow-on target. Linux ARM64 containers inside Desktop are implementation
details; they do not establish Apple host acceptance. The authoritative amendment
is PLAN_ALIGNMENT H and development-plan sections 10–11; the evidence checklist
is [DEPLOYMENT_TARGETS.md](DEPLOYMENT_TARGETS.md), decision S3-18.

The historical checkpoints below retain their source, counts and environment.
Cloud runsc probes are not Apple validation or full Linux production acceptance.
The Mac backend required by the current runsc-only implementation remains
unvalidated; required Apple SBX and Registry pilot execution are blocked/unrun.
This documentation change does not modify settings, run tests on the Mac, select
another backend or complete Stage 3. Native Linux AMD64 release validation remains
required later, but does not gate the first Apple release.

## Cloud development preflight (historical)

The existing cloud Linux x86_64 host has gVisor `runsc release-20260413.0`
registered with Docker 28.4.0. Runtime binary SHA256:
`c97966a7bce00a6ce6de2f931b2b4cf0cbe979d5f47d9feda75f5bbbce0d93ad`.
A bounded trusted Python probe used the existing pinned Python image, explicit
`--runtime runsc`, no network, a read-only root, UID 1000, all capabilities
dropped, no new privileges, 128 MiB memory, half a CPU, a 3-second CPU rlimit,
64 tasks, 1 MiB tmpfs, capped files/logs and an external 20-second timeout.
It verified `PR_GET_NO_NEW_PRIVS=1`, zero capabilities, `EROFS` outside tmpfs,
no external network route and no visible host/evaluator/secret/socket paths.
Temporary probe containers were removed after each attempt.

The initial 16-task ceiling prevented runtime bootstrap; the same trusted probe
passed with 64 tasks. A local log-driver compression setting was corrected before
the runtime test. Neither change relaxed isolation or changed host configuration.
No runtime installation, daemon registration/restart, sysctl, security or network
policy change was made. These smoke results do not replace the complete SBX gate.

## Registry storage

The registry has its own online Alembic environment. Migrations require a separate
owner connection to `registry_db`; application connections have no DDL authority.
The Stage 0 bootstrap SQL and historical payloads remain unchanged. Typed metadata
constraints apply to new rows; historical reservation rows remain nonpublic.

Families, versions, parents, payload references and idempotency receipts are
append-only. Database triggers atomically record each insertion with its principal,
request ID and timestamp. Sequence assignment holds a transaction-scoped advisory
lock before allocating a value, so polling cannot advance past a publication that
has not committed. Lineage references must point backward within one program.

## Publication contract

`ArtifactDefinition` is the client-owned part of the existing manifest. A publication
request supplies a profile, a retry key, the definition and explicitly declared
base64 payloads. The server assigns UUIDv7 identities, family revision, sequence,
publisher and timestamp. An optional client content hash is ignored. The published
manifest remains the complete artifact identity; submission requires no fake IDs.

The `qfr-publication/1` content hash covers canonical sorted JSON containing the
definition without its assigned family ID, the explicit profile and the pinned DSL
configuration hash. The definition includes payload digests and lineage. Retry keys,
claims about the hash and server metadata are outside content identity. Implementation
and canonical DSL fingerprints remain separate. A metadata revision still creates a
version; downstream exact/behavioral dedup decides whether it warrants evaluation.

`configs/registry/publication_v1.json` bounds request, file and archive sizes. These
are ingestion resource controls, not pilot financial or screening thresholds.
Declared package metadata is checked without executing source, extracting archives
or unpickling weights. Paths, symlinks, special members, expansion and undeclared
payloads are rejected. Source inspection/execution requires the sandbox. Publication
alone never establishes executable readiness or schedules evaluation.

The HTTP app denies access unless an explicit authorizer is configured.
Its only artifact mutation is `POST /v1/artifacts`. No persistent token was created.

## Registry reads

Manifest, family, sequence-listing and bidirectional lineage reads enforce program
scope. Global sequence listing requires a reader or evaluator role. A publisher
can retrieve authorized individual artifacts, families, lineage and payloads.
An inaccessible identifier returns the same 404 response as an absent identifier.

`configs/registry/read_v1.json` pins page-size, byte, lineage-depth, node and edge
bounds. Sequence pages are strictly ordered; the next cursor is the final returned
publication, and an empty poll preserves its input cursor. Byte-limited pages do
not skip remaining entries. Family reads default to the first page at the configured
size and expose the same continuation cursor. Lineage results explicitly mark a
depth-truncated graph; resource-limit overflow fails instead of returning an
apparently complete graph.

Reads verify canonical manifest bytes against content-addressed storage. The
additional GET-only payload route resolves only an asset declared in an authorized
manifest, verifies its digest, and serves it as an attachment with a digest ETag
and `nosniff`. Client input never becomes a filesystem path. Missing read policy
is an explicit readiness failure. Reads do not notify or control the evaluator.

## Authentication and attribution

`RegistryAuthenticationConfiguration` declares versioned bindings from named
principals to explicit program IDs, registry roles and `env:` secret references.
`StaticTokenAuthorizer` resolves only those references from a supplied environment
mapping. Missing, malformed or reused token values prevent initialization. Bearer
authentication requires exactly one Authorization header; query-string tokens do
not authenticate. Comparisons use constant-time digest comparison over every binding.
The authorizer retains digests instead of credential values.

The committed `configs/registry/authentication_v1.json` is disabled with no bindings.
It creates no credential or grant. Production credentials and their deployment need
the separately required operator approval. Tests generate ephemeral synthetic values
in memory, including a real loopback HTTP publication/read/retry against PostgreSQL.

Every HTTP request records a UTC timestamp, request ID, authenticated principal
(or `anonymous`), route template, method and status. Logs omit Authorization headers,
query strings, raw paths, payloads and exception text. Invalid or duplicate request
IDs are rejected. Publication passes the same validated request ID and server-resolved
principal into the existing atomic append-only audit mechanism. Client claims cannot
replace publisher attribution. Denials, retries and server failures remain explicit.
The default structured stderr sink emits without relying on an embedding
application to lower Python's default logging level.

## Private pull intake

`IntakeScheduler` has no HTTP listener or inbound trigger. An evaluator owner supplies
an immutable campaign pinning explicit programs, protocol, snapshot, runtime,
screening policy, allowed kinds and a server generation. An inactive campaign does
not poll, register itself or claim work. The manifest's research generation is never
the authority for an evaluation budget. Creating a campaign is an explicit private
operation; starting idle application containers creates none.

Registry pages are fetched through the authenticated core HTTP client. Each page,
its cursor and fair dispatch commit together under a transaction lock. Transport
failure propagates and leaves the cursor unchanged. Repeated or concurrent polls
do not duplicate intake or jobs. The versioned intake resource policy permits one
ready/running screening job per campaign, round-robin across families and FIFO
within a family. Capacity waits remain deferred. Expiry is unset in the pilot;
an explicitly configured expiry rejects instead of reporting successful completion.

The evaluator independently verifies publication and parsed DSL hashes. Exact
dedup requires matching semantic, program, protocol, snapshot, runtime and policy
scope. Behavioral comparison checks every declared cycle's eligible keys, null
masks, ranks, membership and actions exactly; only declared score columns use the
approved tolerances. Empty or unavailable comparison evidence cannot establish a
duplicate. Behavior files are private content-addressed evidence. Actual runner
execution and recording of new behavior evidence belong to the screening worker.

First economic roots require evaluator-owner bindings. Descendants inherit all
parent roots, including crossover roots; canonical renamed clones inherit earlier
bindings. Missing root input remains deferred, and an existing root cannot be
rebound to obtain a fresh allowance. The owner-frozen server generation identifies
the budget boundary; a restart, new campaign ID or research manifest cannot reset
an existing `(program, economic lineage, server generation, version)` reservation.
The approved allowance is three feedback-bearing versions. Later unique attempts
still run and must be recorded, with feedback marked `withheld:budget`. Reservation
requires the caller's active transaction so the screening worker can commit it
with official evidence and the trial ledger. This package does not release feedback
or authorize a confirmation query.

The approved pilot screening policy is separate from the measurement protocol and
the unactivated stock defaults. It preserves the P0/P1-only scope, original
eligibility and warm-up, complete eligible output, the all-cross-sections constant
scorer rule, fixed-position strategy exemption and unchanged `1e-12` score tolerances.
No stock correlation, coverage or degeneracy threshold is imported. The existing
0.7 statistical clustering threshold and frozen measurement hash are unchanged.

Migration `0002_registry_intake` adds immutable campaign, lineage, behavioral-evidence,
transition and reservation tables. Application grants are SELECT/INSERT only;
owner-level UPDATE/DELETE/TRUNCATE also fail through insert-only triggers. Cursor and
intake state updates retain transactional audit events. Feedback cannot read these
private tables. P3.2 tests use real loopback HTTP and PostgreSQL, with synthetic
behavior fixtures explicitly distinguished from sandbox or financial acceptance.

## Screening execution and kind adapters (in progress)

`ScreeningWorker.run_once` claims one durable evaluator job. Operational leases are
renewed independently of research deadlines; a stale fence cannot complete a job.
It computes development output first, then holds a database semantic lock across
behavior comparison and subsequent screening. A behavioral duplicate never requests
validation inputs, creates an official record/trial or reserves a feedback slot.
Missing runtime readiness explicitly returns `BACKEND_UNAVAILABLE` and leaves the
job queued. Failed development coverage/degeneracy does not open validation data.

Screening records, quality trials, feedback reservations, audit events and fenced
completion share one transaction. Quality trials use eligible observations or
documents, not invented return samples. Receipts bind actual output, exact input
slices, adapter/execution policies and evaluator identity. They are private and
unsigned; they neither release feedback nor constitute delivery acceptance.

Each of factor, model, strategy, research note and data product has an eligibility
function, ordered stage interface, screening function and fixed status projection.
Only screening is currently enabled. Numeric financial release remains Stage 4.
The synthetic adapter profile is expressly limited to contract fixtures; it is not
a new financial protocol or a default for future jobs. The pilot profile keeps
the original eligibility and business rules and validates submitted scores,
rankings, quarterly actions and derived snapshots against those rules.

DSL factors execute their published expression in the interpreter. Declared model
packages must bind JSON weights to matching immutable payload assets; unsupported
serialization or fitting interfaces fail explicitly. Constrained Python receives
only numeric fields and anonymous series/observation indices. The evaluator
restores original keys after checking the returned anonymous grid. All Python
execution uses the accepted sandbox, including the kind-specific adapters.

Strategies replay their submitted target weights at declared next-close prices,
including cash and drift in turnover and preserving immature decisions. The
synthetic fixture's zero cost is an explicit separate policy, not a pilot default.
Data-product JSON/CSV/Parquet documents receive bounded schema, original-key and
temporal/value checks; the supported fixture is explicitly `identity-prices/1`.
Unknown strategy/data-product semantics require another declared adapter rather
than an invented interpretation.

Research-note numeric claims use `ResearchNoteDocument` and explicit released
report/field/value references. Numeric prose is unsupported by this deterministic
checker and must be moved into the typed claim array. Citations are resolved only
against immutable released rows in the same program; private official records are
never searched. Known release-policy granularity is required for numeric claims.
Stage 3 does not create releases or invent missing granularity. Plain notes without
numeric claims remain valid documents. These checks do not certify prose truth.

The private owner commands are `qfr eval-admin intake-poll --configuration FILE
--principal PRINCIPAL` and `qfr eval-admin screen-one --configuration FILE
--principal PRINCIPAL --snapshot PATH --evidence-root PATH`. The configuration uses
`ScreeningSessionConfiguration`; schema examples contain synthetic placeholders
and are not deployment credentials or accepted runtime evidence. The commands are
one-shot, have no HTTP trigger and are never invoked by idle container startup.
No public publication API gained an evaluation-control route.

Targeted evidence so far includes nine real PostgreSQL scheduler/screening tests,
28 kind/document/causality tests and two new actual gVisor kind-adapter tests.
The ordinary P3.3 working-tree regression passed 587 tests with zero skips in
656.53 seconds (one unchanged dependency warning). Peak process RSS was 662 MiB;
the external resource guard recorded no stop or executor OOM. A subsequent review
made the inert status projection omit all outcome reasons for budget-withheld
records; its focused 54-test run and `just check` pass. The resulting checkpoint
`f4e0f4c589855916e0d0b10c01be955f7836e8e7` then passed `just check` and all
588 tests without skips in 666.67 seconds. Peak process RSS was 678,084 KiB;
peak environment memory was 3,241,672,704 bytes, with no guard stop or executor OOM.
The test log SHA256 is
`ea0e09bac7e74419901e269c1083fc3a2185a12f4b8dad498432d1afefd66bf8`.

## Registry measurement bridge (replay acceptance pending)

A passing executable screen now freezes its immutable publication, verified
payload bytes, execution/adapter policies and actual backend-readiness evidence
in the private content-addressed store. These files are not public exports.
Financial requests carry the screening record/receipt and bundle hashes. Existing
built-in request serialization and hashes remain unchanged. The private
`request_from_screen` helper derives artifact identity, runtime, generation,
economic lineage and feedback disposition from evaluator-owned evidence; the
owner still supplies the epoch, cohort, window and cycle. It does not reserve
another feedback version. Composite lineage labels retain every original
reservation rather than creating a fresh allowance.

Registry pilot models execute their frozen package again for development
fingerprints and the requested unlocked window. The exact input slices must match
screening, and validation output must match its screened hash. Independent
measurement consumes the actual validated scores with original business rules;
the original built-in baseline remains separate. Missing isolation raises an
explicit readiness error. Reproduction executes the package again without
Registry transport and compares runner input/output evidence as well as numerical
results, fingerprints and clusters. No model/strategy input is replaced with a
built-in scorer. This financial bridge supports the declared pilot model adapter;
generic kind checks remain screening-quality records, not invented financial
metrics.

The registered six v4 DSL definitions passed independent Polars feature parity
on the original inputs in 40.79 seconds (413 MiB peak process RSS). Four actual
P0/P1 package cases are explicitly unrun without
`QFR_TEST_PILOT_SANDBOX_IMAGE`. When supplied, missing runtime readiness fails the
test rather than skipping it. The cases cover original-oracle preservation and
screening through official measurement/reproduction; original historical replay
does not activate the new protocol's locked confirmation window.

## Outstanding gate checkpoint

| Check | Current evidence | Remaining work |
|---|---|---|
| REG-01–04, identical-definition identity, registry AUD-01 | PASS at the 588-test checkpoint; real PostgreSQL/HTTP and concurrent publication tests | Carry forward on the final source |
| EVL-01/03/05 | PASS at that checkpoint; pull-only intake, actual bounded lookahead probes and duplicate-before-validation tests | Final-source regression |
| SBX-01–04 | PASS for bounded fixtures on cloud Linux x86_64 with actual runsc; no Apple acceptance | Prove isolation through the actual macOS/Apple Silicon deployment with existing Docker Desktop, including the full pilot; backend readiness remains blocked |
| SBX-05 | Runtime controls passed; stronger Compose no-privilege/no-host-write assertions added | Final-source checks and actual Compose topology |
| Registered v4 DSL feature parity | PASS against independent Polars on original inputs | Final-source regression |
| Registry P0/P1 original oracle and official reproduction | UNRUN: four full-package cases require the core-only image and approved local host | Run `tests/registry/test_pilot_execution.py` on the Mac with original inputs |
| Full local workflow CI | UNRUN on final Stage 3 source | Compose init/restart/boundaries, host/container suites, eight application plus two sandbox images |
| Hosted CI / draft PR | UNRUN | Publish only after the stage is verified clean, or separately approved WIP transport; neither is implied here |

Image scripts build the core-only sandbox separately from the eight application
images and retain platform digests. A build does not prove isolation or native
runtime acceptance. Heavy runs remain on the Mac; no image build, runtime
installation, host security change, live provider call or confirmation query has
been performed for this handoff. Stage 3 is not complete and Stage 4 remains paused.

## PostgreSQL harness follow-up

The published WIP checkpoint is `09246b17504a4fcafe8034d9ac2ec2eac5598cb3`.
An independently reproduced missing-DSN HTTP test hung in Starlette's TestClient
until its external timeout. Database-marked tests now resolve that prerequisite
before HTTP/thread setup. CI requires PostgreSQL explicitly; a configured invalid
DSN still fails, with its exception chain suppressed to prevent credential output.

The reported Mac run subsequently reached healthy PostgreSQL and passed the 31
previously failing database-dependent cases. Its startup delay remains unexplained.
The separate UID negative fixture had assumed that a host-mounted 0600 file was
unreadable to the PostgreSQL UID. The Mac showed that assumption was false even
though the displayed ownership differed. The corrected fixture establishes and
checks actual read denial in Linux tmpfs; production startup, host permissions,
SCRAM and grants are unchanged. The corrected real-container case and full Mac CI
remain unrun on this follow-up source. See `POSTGRES_STARTUP.md` for its isolated
diagnostic command. No alternate sandbox backend was implemented or enabled.

Follow-up verification: `just check` passed (228 formatted files, 127 mypy source
files, five import contracts, 108 public contracts, private contracts and five
package license checks). The bounded offline `just test` run passed 447 tests,
with 162 explicit skips and one unchanged dependency warning in 49.02 seconds.
It includes real pytest subprocess regressions for missing, invalid, refused and
unresponsive PostgreSQL configuration, plus a real unreadable-file bootstrap test
under an unprivileged UID. No successful database connection is claimed by those
negative fixtures. Peak child-process RSS was 286,060 KiB, peak environment memory
2,435,682,304 bytes, and the 240-second/5-GiB/512-MiB-growth guard did not trigger.
This offline result does not replace the outstanding live and platform gates.

## Numerical runtime and reproduction follow-up

Mac validation isolated the yearly-mean hash difference to unequal effective
Polars pools (parent 4, CLI child 18). The difference was
1.734723475976807e-18 in the 2023 yearly delta; series, fingerprints and clusters
matched. No statistical computation or hash comparison is rounded or weakened.

Runtime identity v2 records effective numerical execution. The CLI restores only
its frozen allowlisted startup settings before numerical imports, then verifies
actual pools, software and implementation. Programmatic calls reject an
incompatible initialized runtime. Screening also checks before claiming work.
Legacy identities remain byte-equivalent on serialization and are explicitly
refused as unpinned by new execution; old records and campaigns are not rewritten.
See Stage 2 operations and decision S3-19 for the compatibility boundary.

The added threadpoolctl dependency changes the workspace lock. Sandbox profile v2
binds that lock while preserving every v1 backend/security/resource value; the v1
file remains unchanged. This is not permission to install or change a host backend.
Only bounded offline checks run in cloud for this fix. Exact-commit Mac tests,
licensed reproduction and final images must be revalidated before acceptance.

Resumed verification on October 28: the unchanged code at `2021ee3` passed
68 focused runtime/contract/adapter tests in 6.53 seconds. `just check` passed:
233 formatted files, 130 mypy source files, five import boundaries, 108 public
contracts, private contracts and five package license checks. Offline `just test`
passed 458 tests, with 162 explicit skips and one unchanged dependency warning in
52.24 seconds. The skipped checks comprise 95 database checks, 44 licensed-input
checks, 14 actual sandbox checks and nine original-oracle checks. They provide no
acceptance evidence. The full offline process peaked at 304,404 KiB RSS; environment
memory peaked at 862,007,296 bytes. The 180-second/5-GiB guards did not trigger and
there were no OOM events. The nine earlier lock-binding failures are resolved.

The original Stage 1 captured panel and P0/P1 receipts were located and their
recorded hashes verified privately. No replacement goldens were generated or
licensed data published. The original-source replay recipe remains unchanged;
running it on the Mac requires its pinned image and architecture-compatible
original dependencies. That trusted historical replay is separate from the
still-required Registry artifact sandbox execution.

For the Mac follow-up, first install the changed locked workspace, preserve its
existing test database and private input configuration, and run the numerical
runtime tests plus
`tests/evaluator/test_records.py::test_evl_04_cli_reproduces_frozen_record_despite_later_trials`
with `--require-postgres`. Run the latter with parent `POLARS_MAX_THREADS=4` and
with the normal Mac default; its sanitized child deliberately begins with a
different value and must restore the frozen effective pool before computation.
Capture the observed numerical identity and exact result/series/fingerprint/cluster
hash comparisons. Native host and Linux container runs are distinct evidence.
Final-source live suites, rebuilt images and the blocked Apple sandbox gates
remain outstanding; this checkpoint does not complete Stage 3.

The Mac follow-up of `3fad621` failed before EVL-04: its Accelerate backend returned
an empty threadpoolctl list. The Apple correction introduces a separate numerical
identity revision with public API verification, calling-thread single-threaded
execution, OS/build identity and loaded-code fingerprints. Linux behavior and
legacy serialization are preserved. See [NUMERICAL_RUNTIME.md](NUMERICAL_RUNTIME.md)
and decision S3-21. A cloud pass cannot establish native Apple compatibility; the
new native API/SDK and exact reproduction tests remain required.

Apple correction cloud verification: `just check` passed (235 formatted files,
131 mypy sources, five import boundaries, public/private contracts and five
package license checks). Bounded offline `just test` passed 466 tests with 164
explicit skips and one unchanged dependency warning in 56.59 seconds. Two skips
are the new native Apple API/SDK checks; the other 162 retain their preceding
database, licensed-input, actual-sandbox and original-oracle prerequisites.
Focused parser/runtime/schema/adapter checks passed 75 tests with the same two
native-only skips. Final full-suite process RSS peaked at 304,364 KiB and
environment memory at 894,480,384 bytes; no 180-second/5-GiB guard or OOM event
occurred. These cloud results do not establish Apple or Stage 3 acceptance.

Mac follow-up at `accb9d0`: all eight Apple runtime tests passed, including native
SDK compilation, API read-back and thread-local refusal. EVL-04 passed with parent
Polars pool 4 and with the normal default; all seven static commands passed. The
combined focused suite still had two fixture failures (16 passed, two failed,
zero skipped): its matching-settings and Polars-only mismatch children had not
initialized Accelerate's thread-local mode. Those fixtures now establish the
other frozen controls explicitly and leave the Polars setting under test. A new
native child regression rejects deliberate Accelerate drift after bootstrap.
Production runtime code, strict hashes and protocol are unchanged by this test
correction. Native rerun and broader Mac CI remain required. Original-oracle
replay is still unrun there without its pinned image and separately verified
original dependencies; no new oracle output is claimed.

Cloud verification of this fixture correction: `just check` passed all seven
commands; offline `just test` passed 466 tests with 165 explicit skips and one
unchanged warning in 54.21 seconds. The two runtime test files passed 15 tests
with three native-only skips. Peak process RSS was 303,884 KiB and environment
memory 890,929,152 bytes; no timeout, memory/disk guard or OOM event occurred.
Real database, licensed-input and sandbox gates were not enabled in this bounded
offline run and are not claimed as passed.

## Numerical worker thread follow-up

Mac evidence for `2a1ae03`: focused runtime/EVL-04 checks passed 19 tests with
parent Polars pool 4 and again with the default; native static checks passed.
The full native suite with required PostgreSQL and private inputs reported
603 passed, 27 skipped and one failure. Desktop Linux-container CI reported
600 passed, 31 skipped and passing static checks. The native failure was the
concurrent screening retry: four new executor threads had not initialized their
calling-thread Accelerate mode. Those results are retained as prior evidence,
not relabelled as acceptance of the follow-up.

An explicit trusted worker initializer now sets a fresh thread's local controls
and verifies the complete frozen identity before work. Screening construction
and the concurrent persistence fixture use it. Capture, CLI bootstrap and worker
initialization share a once-per-thread guard, preventing repeat initialization
from repairing deliberate drift. Job and persistence verification remain
observation-only. No process-wide thread pool, host setting, sandbox backend,
statistical protocol, identity serialization or golden evidence changes.

The evaluator implementation hash changes, so tests must create fresh runtime
identities and counted contexts; existing immutable records are preserved. New
tests cover exact hashes on four real worker threads, incompatible process pools,
failed initialization and native drift before claims or database writes. Native
follow-up and broader Mac CI remain required. Sandbox gates and nine original
oracle cases remain unrun, so Stage 3 is not acceptance-ready.

Bounded cloud verification: all seven `just check` commands passed (238 formatted
files, 132 type-checked sources, five import boundaries, public/private contracts
and five package license checks). Offline `just test` passed 471 tests with
168 explicit skips and one unchanged warning in 59.13 seconds. Focused runtime
tests passed 20 with four native-only skips. Process RSS peaked at 297,252 KiB
and environment memory at 893,218,816 bytes, without OOM or timeout/memory/disk
guard events. The actual PostgreSQL concurrency and native drift regressions
remain for Mac validation; offline skips are not gate evidence.
