# Stage 3 — Registry, execution contracts and sandbox

Work starts from the verified Stage 2 commit
`57fae27c956a0954f2347e203435a30883a42d09` on `stage-3-registry-sandbox`.
The branch was created without merging the predecessor. Stage 3 does not implement feedback release,
blackboard services, agents, provider calls or confirmation-query execution.

## Target-host preflight

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
| SBX-01–04 | PASS for bounded fixtures on cloud Linux x86_64 with actual runsc | Independently prove the Mac Linux backend for the full pilot |
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
