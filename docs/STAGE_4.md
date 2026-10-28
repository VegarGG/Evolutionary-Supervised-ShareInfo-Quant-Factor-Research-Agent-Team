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

## Required exit evidence

REL-01–06, BND-03, MCP-01–06, JOB-01–03 and DLV-01–03 remain **UNRUN** as complete
Stage 4 gates. These require the real no-LLM P0/P1 flow, signed released-only
reports, a supported negative-result receipt, actual Codex and independent MCP
client lifecycles, and full final-source local/hosted CI. Bounded cloud unit and
database checks are reported separately; heavy deployment/pilot validation stays
on the Mac. No Stage 5, merge, provider call or confirmation-query use is implied.
