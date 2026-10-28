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

## Required exit evidence

REL-01–06, BND-03, MCP-01–06, JOB-01–03 and DLV-01–03 remain **UNRUN** as complete
Stage 4 gates. These require the real no-LLM P0/P1 flow, signed released-only
reports, a supported negative-result receipt, actual Codex and independent MCP
client lifecycles, and full final-source local/hosted CI. Bounded cloud unit and
database checks are reported separately; heavy deployment/pilot validation stays
on the Mac. No Stage 5, merge, provider call or confirmation-query use is implied.
