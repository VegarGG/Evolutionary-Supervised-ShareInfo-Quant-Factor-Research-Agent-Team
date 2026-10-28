# Stage 4 — Blackboard, release policy, MCP front door and delivery export

Implementation is in progress on `stage-4-blackboard-delivery`. Its base is the
accepted Stage 3 checkpoint `3f42451e3b58524ae814184b426ef15a3aff564a`, on the
unmerged `wip/stage-3-mac-validation` branch. This document is not an exit-gate
pass or a production-deployment claim.

## Entry and work order

Stage 3's Apple-scope gate is recorded in [STAGE_3_ACCEPTANCE.md](STAGE_3_ACCEPTANCE.md).
The owner already approved the exact P0/P1-only release intent in
`configs/evaluation/pilot_p0_p1_verification_v1.yaml`: three feedback versions per
lineage/generation, scalar plus flags, the frozen bootstrap-SE Ladder step, and
one separately authorized confirmation query. No query or provider spend is
authorized by Stage 4 implementation.

Implement in plan §10 order: P4.1 research persistence; P3.5 release engine;
P3.6 GET-only feedback; signing and independent delivery checker; P3.8 on-demand
import; P4.9 Research API/MCP; portable intake and actual two-client acceptance.
There is no LLM research loop in this stage. The owner permits checkpoint draft
PRs without waiting for predecessor review or merge; keep the stacked dependency
explicit and do not merge it.

## P4.1 persistence

The research-only Alembic migration extends the unchanged Stage 0 reservation
tables. Typed IDs, relationships, state and hashes are columns; stage-specific
research detail remains JSON payload rather than implementing later agent loops.
Composite foreign keys prohibit cross-program references. Newly required columns
use `NOT VALID` checks so old reservation rows are retained unchanged while new
writes must satisfy the schema. Immutable records and audit events retain their
existing database protection.

Each service write supplies authenticated principal and request attribution in
its transaction. Triggers preserve original row attribution and write a separate
append-only metadata event. Nested operations restore the enclosing context;
rollback removes both mutation and event. This mechanism is not an authentication
boundary for a holder of the research database credential.

Queue tasks and logical research jobs have separate records. Explicit admission
is required; only an active program and ready/running parent permit a claim.
`SKIP LOCKED`, database-clock leases and monotonically increasing fencing tokens
support concurrent workers and recovery. Pause prevents the next task; cancellation
prevents a worker from finishing or renewing a cancelled parent. A data deferral
returns the task to the queue. None of these operations completes the research job.

Frozen intent includes the brief, input bundle, configuration and exit-gate hash.
The database refuses completion without a matching independent passing receipt
reference. P4.9 must verify the actual signed receipt before inserting that
reference; a database flag alone is not cryptographic evidence.

The research package now declares the already locked Alembic/Psycopg dependencies.
No dependency version changed. New sandbox profile revisions pin the resulting
lockfile and preserve every security/resource setting: `sandbox_pilot_v3.json`
and `sandbox_docker_native_v2.json`. Earlier profile files, records and accepted
Stage 3 evidence are unchanged. Final-source Mac acceptance must use fresh
runtime identities and images; a changed lock is not silently relabelled as the
previously accepted runtime.

## P4.1 package verification

On the cloud Linux implementation host, `just check` passed all seven commands.
`just test` with required real PostgreSQL passed **735 tests**, with **81 explicit
skips** and one existing Starlette/httpx deprecation warning (93.69 seconds).
The focused research persistence plus database-boundary run passed **39 tests**.
The ordinary test process peaked at 311,228 KiB RSS; the fresh PostgreSQL service
was bounded to 512 MiB and one CPU. Apple-native, licensed pilot/oracle and actual
sandbox checks were not run here. Full final-source Mac acceptance remains required.

## P3.5 release engine

The two typed release policies are separate from the older draft YAML files.
The pilot policy binds the approved protocol hash, exact fixed Ladder step and
three-version lineage/generation budget. Six-hour UTC batches and frozen-family
midrank tertiles are recorded operational choices. Stock rounding, rolling family
limits, UTC day/week limits and seven-day deferral expiry follow local §9.
No stock campaign or confirmation query is activated.

Immutable official records and append-only intake transitions are queued by hash;
mutable progress never changes an earlier release decision. Real PostgreSQL tests
cover quota concurrency, idempotency, explicit deferral/expiry, restart recovery,
policy freeze and audit rollback. A stock producer must reserve quota before its
measurement. Pilot attempts reuse the existing economic-lineage reservations;
budget-excess attempts remain counted and produce no outcome-dependent payload.

Preparation holds the queue and Ladder scope locks inside the eventual publication
transaction. It produces a private unsigned object, never a feedback row or a new
Ladder best. The signing integration must atomically publish the verified report,
update the Ladder and record numeric disclosure; a saved preparation is not an
authoritative result. Absolute primary recall carries no invented Registry
baseline ID; the frozen protocol retains its paired P1 comparison identity.
Withheld results clear scores, sample counts, reasons and diagnostic flags.

The initial v1 policy withheld MDE and secondary numeric diagnostics. Decision
S4-10 below reconciles planning MDE with §7.9; secondary performance metrics and
the generation-end family summary remain Stage 6 work. Stock W1/W2 projection and quota tests use declared synthetic adapter inputs;
they are not stock financial acceptance. Signing, public API visibility and the
real elapsed-batch P0/P1 flow still require subsequent integration and Mac evidence.

P3.5 package verification on the cloud Linux host: all seven `just check`
commands passed; required-PostgreSQL `just test` passed **798 tests**, with
**81 explicit skips** and the existing Starlette/httpx warning (105.39 seconds).
Focused quota/preparation/database-boundary tests passed **35 tests**. Peak test
RSS was 304,548 KiB. The first full run exposed missing owner-level delete guards
on mutable release history; a forward migration and regression test fixed it.
No skipped Mac, licensed-input or actual sandbox check is counted as acceptance.

## P3.6 released-only feedback

The GET-only service, audience/program bearer scopes, bounded cursor reads,
released artifact timelines and public cards are implemented. See
[FEEDBACK_API.md](FEEDBACK_API.md). Its database role is explicitly checked and
all requests use a read-only transaction. Published views exclude unsigned rows
and future batches. These checks do not substitute for the subsequent signing
integration or actual MCP/deployment acceptance.

Package verification: seven `just check` commands pass; required-PostgreSQL
`just test` **818 passed / 81 explicit skips**, with the existing deprecation
warning (100.16 seconds; 304,616 KiB peak RSS). The focused API/auth/database
suite passed **27 tests**. Joined views initially changed PostgreSQL's refusal
SQLSTATE for writes; explicit read-only view guards preserve the existing boundary
test and prohibit mutation independently of view shape.

Existing locked HTTP libraries are now declared where used: HTTPX by core clients,
FastAPI/Uvicorn by the feedback service. No dependency version changed. New
`sandbox_pilot_v4.json` and `sandbox_docker_native_v3.json` pin the lock, retaining
all controls and prior profiles. No production token grant was deployed.

Release-policy revision 2 reconciles §7.9 with the scalar/flags boundary. Its
planning-only MDE uses the existing closed-form null variance at t=2, explicitly
conditional on independent mature matched decisions. Inputs are the public metric
identity and the released scalar origin's period count, never current-child
outcomes or private diagnostics. Withheld results disclose no MDE or sample count.
This does not alter the frozen measurement protocol or its statistical gates.
Earlier policy/card payloads and hashes retain their original serialization; new
protocol-card references bind the release-policy hash to avoid overwriting cards.

Planning reconciliation verification: seven check commands pass; required-PostgreSQL
ordinary suite **825 passed / 81 explicit skips** (99.24 seconds). The six new
planning/card tests pass. The frozen protocol and dependency lock are unchanged.

## Signing and atomic publication checkpoint

[EVIDENCE_SIGNING.md](EVIDENCE_SIGNING.md) specifies the canonical signature
boundary, private receipt wrappers and scoped evaluator CLI. Reports, Ladder
updates, publication accounting and audit commit together; concurrent retries
return one immutable signed report. Future batches, untrusted keys, corrupted
private evidence and interrupted publication fail closed. Feedback now verifies
signatures before returning reports. Historical receipts, hashes and labels are
unchanged; private wrappers never enter the public schema or export catalog.

All seven check commands pass. Required-PostgreSQL ordinary tests passed
**838 / 81 explicit skips** (101.02 seconds; 313,956 KiB peak RSS), including
**31 focused signing/API/database tests**. One existing Starlette/httpx warning
remains. These use synthetic measurements, ephemeral keys and explicit fixture
source clocks; they do not claim the actual elapsed-batch pilot acceptance.

The lock adds cryptography 50.0.2, CFFI 2.1.1 and Pycparser 3.12, with no changes
to previously locked dependency versions. Notices are retained. New profiles
`sandbox_pilot_v5.json` and `sandbox_docker_native_v4.json` change only revision,
identity and dependency-lock hash; all resource/isolation controls are unchanged.
Final Mac images and evidence must use the new lock and fresh runtime identities.
No persistent key or production grant was created. Independent delivery,
on-demand import, Research API/MCP and final acceptance remain in progress.

## Independent delivery checkpoint

[DELIVERY_CHECKER.md](DELIVERY_CHECKER.md) describes the implemented pilot gate,
independent evaluator HTTP pull, immutable attempts and signed receipts. The
checker verifies actual committed releases, original private receipt files,
Registry payload hashes and the existing exact-replay audit. It supports a
declared negative result without treating missing/insufficient evidence as a
pass. Proposal retries are idempotent; a failed receipt cannot be rewritten.
Feedback exposes only the signed, program-scoped public receipt through GET.

All seven `just check` commands pass. Required-PostgreSQL `just test` passed
**873 tests / 81 explicit skips**, with the existing Starlette/httpx warning
(116.90 seconds; 322,252 KiB peak RSS). Focused delivery/database tests passed
**44 tests**. These tests use declared synthetic measurement/replay evidence and
ephemeral signing keys, including real HTTP pull, transactional rollback,
concurrent retry, conflicting proposals, tampering and program-scope denial.
The first full run exposed a stale migration assertion and a test cursor filled
by other programs' retained rows. The assertion now names migration 0008 and the
release test uses its own policy/program scope, retaining exact batch-time and
unsigned-visibility assertions. No existing evidence was deleted.

The approved measurement protocol and dependency lock are unchanged. P4.9's
Research API must bind receipt verification to completion/export, and the final
Mac acceptance must supply actual pilot replay and elapsed batch evidence.
P4.9, client demonstrations and the complete Stage 4 gate remain pending.

## P3.8 authorized on-demand ingest

The evaluation-side CLI now requires enabled authorization for an exact local
build plan. Sources are bounded original-pilot inputs, verified snapshot replay
or an explicit synthetic recipe; no supplier request, scheduled ingest or
prospective campaign starts implicitly. Immutable requests/outcomes and audit
records precede atomic research-only catalog publication. Retry verifies the
original snapshots and recovers a catalog-publication interruption without
regenerating evidence. Private full-snapshot metadata never enters the catalog.
See [AUTHORIZED_INGEST.md](AUTHORIZED_INGEST.md) and decision S4-13.

All seven `just check` commands pass. The required-PostgreSQL ordinary `just test`
run has **892 passed, 82 explicitly skipped**, one existing dependency warning,
109.63 seconds test time and 328,924 KiB peak child RSS. Focused ingest/snapshot
checks have **26 passed, 2 licensed-input skips**. Synthetic concurrency, failures,
crash recovery, real CLI persistence and a read-only output root are exercised.
The private pilot test remains unrun here; new container volume/image evidence
and the complete human-driven flow remain for Mac acceptance. The measurement
protocol, dependency lock and original evidence are unchanged.

## P4.9 Research API, exports and transport checkpoint

The typed Research API, scoped durable manual jobs, registrations, human checkpoints,
independent-receipt completion and immutable export/download are implemented; see
[RESEARCH_API.md](RESEARCH_API.md). The new delivery checker v2 signs the complete
input/admission binding, preserving all v1 evidence and measurement settings.
[QUARANTINE_TRANSPORT.md](QUARANTINE_TRANSPORT.md) describes the separate data-only
intake service: durable bounded upload, mapped regular-file import, checksum and
archive checks, immutable history and metadata-only reference verification. It
has no evaluator credentials/control or raw-source download. Runtime service
wiring, standard MCP adapter and actual two-client evidence are still pending.

All seven `just check` commands pass. The required-PostgreSQL ordinary suite has
**967 passed, 82 explicit skips**, in 104.72 seconds (108.45 seconds including the
wrapper), peak child RSS **331,552 KiB**. The focused research/delivery/export/
transport suite has **93 passed** in 15.06 seconds. HTTP cancellation, lost-response
retry, service recreation, real database transactions, ephemeral signatures,
conflicting intent, malicious ZIPs, links/FIFOs and interrupted chunks are tested.
The synthetic signed evidence remains labelled as such, not pilot acceptance.
A test-client startup wait in the restricted execution harness was diagnosed
before application entry; running with the local networking permission used by
other HTTP/database tests passed. No application isolation setting was changed.

The maintained MCP SDK and new dependencies are pinned and notices retained;
previous dependency versions are unchanged. New sandbox profiles v6 (runsc) and
v5 (Docker-native) differ only in identity, revision and the dependency-lock hash.
Final Mac evidence must use that lock and fresh runtime identities. The approved
measurement protocol file remains SHA256
`a234bcc99af5c6c34b8fb585eb0701dca614d55048629418030876ff6dc752fb`.

## P4.9 MCP transport checkpoint

The standard Streamable HTTP adapter is implemented with the maintained SDK;
see [MCP_FRONT_DOOR.md](MCP_FRONT_DOOR.md). Its only QFR dependency is core.
Per-request scopes, idempotent durable jobs, bounded resources, separate binary
file transport and independent official-evidence verification are enforced.
The adapter exposes no evaluator control, direct database or source execution.

All seven `just check` commands pass. The ordinary required-PostgreSQL suite has
**984 passed, 82 explicit skips**, in 131.84 seconds (135.60 seconds including
the wrapper), peak child RSS **361,224 KiB**. The focused MCP suite has
**13 passed** in 19.69 seconds, using real loopback HTTP and PostgreSQL, the SDK
and a separate JSON-RPC test client, plus explicitly synthetic financial evidence.
It covers disconnect/reconnect, lost acknowledgement, conflict, cancellation,
app recreation, scope refusal, signatures, verified export, upload recovery,
mount confinement and protocol generations 2025-03-26/2025-06-18/2025-11-25.

No dependency lock, measurement protocol, sandbox profile or real credential
grant changed in this checkpoint. Actual Codex, real pilot/release timing,
container restart, service deployment and final Mac CI remain required.

## P4.9 service launch and client checkpoint

Explicit launch modules now serve Research, Registry, Feedback, quarantine and
MCP using typed, bounded configuration. The opt-in Compose overlay preserves
database identities and data separation; startup performs no migration, grant,
ingest, evaluation, release or job admission. Source quarantine has no PostgreSQL
credentials or evaluator network. The independent SDK CLI connects without a
model. See [service launch](STAGE_4_SERVICES.md), [client instructions](MCP_CLIENTS.md)
and the [portable intake guide](PORTABLE_INTAKE_GUIDE.md).

All seven `just check` commands pass: formatting/lint, typing (215 source files),
five import boundaries, 165 public contracts, private evaluator contracts and
licensing consistency. Required-PostgreSQL `just test` has **1,005 passed and
82 explicit skips**, in 138.90 seconds (143.53 seconds including the wrapper),
peak child RSS **364,408 KiB**. Focused service/client/Compose checks have
**15 passed** in 10.97 seconds. They exercise missing-credential refusal, bounded
configuration parsing, real database startup identity, authenticated HTTP, idle
startup and independent CLI reconnect. Compose configuration was resolved without
secret environment values; no cloud image build or deployment acceptance ran.

The lock, measurement protocol, existing sandbox controls and all old evidence
remain unchanged. Actual Mac service/restart/client/pilot evidence is pending.
Review also identified a delivery-checker question: reference baselines are
currently treated as assessed candidates, so a P1 self-comparison's correctly
insufficient uncertainty cannot support delivery. This is not a failed statistical
gate to bypass; candidate/reference roles need explicit, versioned handling before
the real pilot flow. No measurement rule or receipt was changed in this checkpoint.

## Frozen assessment roles

Checker v3 and exit-gate schema version 2 separate exact assessed candidates from
preserved references before job admission. The P0/P1 demonstration assesses P0
against P1 while retaining both signed reports and exact replay. The reference's
zero-delta self-comparison remains insufficient for candidate inference; it cannot
be shortlisted or support a positive conclusion. All assessed-candidate uncertainty
and resolved-hurdle requirements remain unchanged. Legacy gate serialization,
checker v1/v2 semantics and earlier receipts remain immutable. See
[DELIVERY_CHECKER.md](DELIVERY_CHECKER.md) and decision S4-21.

All seven `just check` commands pass (166 public contracts). The ordinary
required-PostgreSQL `just test` run has **1,034 passed / 82 explicit skips**,
144.90 seconds test time (149.29 seconds with wrapper), peak child RSS
**366,436 KiB**. The initial focused checker/scope suite passed 45 tests; the
broader 71-test run found a test calling an internal status-formatting helper,
corrected to the public status-read method. That regression and the final full
suite pass. Tests cover frozen-role tampering, wrong checker versions, reference
omission/hash/coverage/replay failures, insufficient candidates, and signed
completion/export. Financial/replay fixtures remain explicitly synthetic.

The approved measurement protocol, dependency lock, sandbox policies and original
data/golden evidence are unchanged. No confirmation query, provider call or real
release-clock modification occurred. Follow the
[Mac acceptance handoff](STAGE_4_MAC_ACCEPTANCE.md) on exact reviewed source;
elapsed batch evidence and actual client/pilot/deployment gates remain pending.

## Original-input fixture correction

The initial Mac run on `fa0bb86` reported static checks passing, 212 focused
component passes, and a full native result of **1,115 passed / 1 failed / 0 skips**.
The failure was the ingest test's before/after inventory of the entire directory
containing the original packages. New sibling acceptance evidence changed that
inventory without changing P0/P1 input files. A scoped Mac test-only correction
passed its targeted rerun; that is not a final-source full-suite pass.

The reviewed fixture now hashes every file inside both original delivery
directories, including the checksum manifests, rather than unrelated siblings.
Fifteen lightweight regressions prove that sibling evidence is excluded while
byte changes, additions, deletions, renames, missing packages and non-regular
entries inside either original package remain failures. A read-only inventory of
available originals verified all **339 manifest-listed files** with zero hash
mismatches, plus the two checksum manifests themselves. No original file, golden
value or production source changed; see decision S4-22.

All seven `just check` commands pass. The required-PostgreSQL ordinary suite has
**1,049 passed / 82 explicit skips**, 140.35 seconds (144.60 seconds including the
wrapper), peak child RSS **370,400 KiB**. The 15 new filesystem regressions passed
in 0.37 seconds. The actual original-ingest and full acceptance reruns remain on
the Mac, along with deployed clients, elapsed release, delivery/export and restart
evidence. Application/image inputs, dependency lock and protocol are unchanged.

## Required exit evidence

REL-01–06, BND-03, MCP-01–06, JOB-01–03 and DLV-01–03 remain **UNRUN** as complete
Stage 4 gates. These require the real no-LLM P0/P1 flow, signed released-only
reports, a supported negative-result receipt, actual Codex and independent MCP
client lifecycles, and full final-source local/hosted CI. Bounded cloud unit and
database checks are reported separately; heavy deployment/pilot validation stays
on the Mac. No Stage 5, merge, provider call or confirmation-query use is implied.
