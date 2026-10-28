# Stage 2 — Independent evaluator core

Deployment scope clarification: [macOS/Apple Silicon first, then Linux AMD64](DEPLOYMENT_TARGETS.md).
The historical Stage 2 source, test and image records below retain their original
scope. Linux ARM64 container or emulated-image results do not validate the Apple
host deployment or complete native Linux AMD64 production acceptance.

The Stage 2 evaluator runs the preserved P0/P1 and six frozen diagnostic neighbors
as trusted built-ins. It has no research-facing evaluation endpoint, registry
intake scheduler, untrusted-code runner, feedback release, confirmation-query
execution or model access. The forward-account tables remain schema only.

Stage 2 starts from merged credential repair `3c528beedb8307539cc6bb3d788e58e23c0598a9`.
The original Stage 1 evidence and the later complete Compose repair verification
remain separate. A passing unit suite does not establish complete Compose or
image-matrix acceptance.

## Approved protocol and original oracle

`configs/evaluation/pilot_p0_p1_verification_v1.yaml` records the evaluation owner's
approved v0.1.0 proposal. Canonical protocol SHA256:
`860d667bedf81b0fed68fff6807f35f11fd2287dc7175d07eec4e8bb71b40021`.
Proposal SHA256:
`dcd5e30d6c21491ab293b823185265459c93caddf2602dd29f3119abcf1bfc6a`.
See decisions S2-01 and S2-04 for provenance.

Development 2020–2022, validation 2023–2024 and locked confirmation
2025–2026-10-16 apply only to this P0/P1 verification. Every window is
previously seen. They are not global defaults or evidence of unseen-data testing.
The owner CLI accepts development or validation requests only. A one-query
confirmation allowance is not authorization to spend it.

Original package replay settings remain in separate oracle profiles. PIL-02 reads
the original machine ledgers at their original windows, seeds, draw counts and
costs. Those historical parity tests neither consume nor release a new official
confirmation query. Licensed inputs and private outputs stay outside Git.

Official uncertainty uses 10,000 paired circular-block draws, the frozen automatic
block rule and half/double sensitivity checks. The family calculation retains
Romano–Wolf step-down adjusted p-values and uses a conservative full-family
max-T simultaneous confidence envelope from the same draws (S2-12). Missing,
constant or incomplete evidence cannot become a passing interval.

The P95 turnover frequency rule retains exact approved thresholds, strict
exceedance and integer `20 * exceedances <= eligible_decisions`. Initial
construction is excluded once from turnover only. Monthly/quarterly turnover is
explicitly not applicable; no threshold is invented for those profiles.

## Owner-only commands

Install the locked workspace with `uv sync --locked --all-packages`. Evaluation
requires a full verified `pilot_industry_v1` snapshot, private evidence directory
and real PostgreSQL initialized with the production roles. The role boundary is
unchanged: research and MCP have no evaluation credential or admin command.

Supply `QFR_EVAL_DSN` without a password and `QFR_EVAL_PASSWORD_FILE` pointing to
the appropriate private secret file. Migration uses the PostgreSQL owner;
ordinary commands use `eval_rw`. Never put credentials in command arguments,
request JSON, logs or repository files.

```sh
qfr eval-admin migrate
qfr eval-admin protocol-hash configs/evaluation/pilot_p0_p1_verification_v1.yaml
qfr eval-admin protocol-create configs/evaluation/pilot_p0_p1_verification_v1.yaml \
  --principal OWNER --request-id UUID
qfr eval-admin protocol-activate pilot_p0_p1_verification_v1 0.1.0 \
  --expected-hash 860d667bedf81b0fed68fff6807f35f11fd2287dc7175d07eec4e8bb71b40021 \
  --principal OWNER --request-id UUID
qfr eval-admin evaluate --request /private/request.json \
  --snapshot /private/full/SNAPSHOT_ID --evidence-root /private/evidence \
  --principal OWNER --request-id UUID
qfr eval reproduce RECORD_ID --snapshot /private/full/SNAPSHOT_ID \
  --evidence-root /private/evidence --principal OWNER --request-id UUID
qfr eval-admin cluster-trials --request /private/request.json \
  --evidence-root /private/evidence --principal OWNER --request-id UUID
```

`UUID`, `OWNER`, paths and record/snapshot identities above are explicit operator
inputs, not defaults. `EvaluationRequest.schema.json` is a private contract under
`qfr_eval/private_contracts`. Its example is a schema fixture, not a runnable
production request. Pin the actual evaluator Git SHA, built image digest,
the version-2 identity returned by `runtime.capture_runtime(evaluator_git_sha=...,
image_digest=...)` from the runtime being used. The trusted operator must verify
Git/image identity. The evaluator compares installed code, numerical package
versions, host OS/CPU, effective Polars and observable BLAS/OpenMP pools, loaded
library hashes and the closed startup-control set before measurement. This freezes
the observed settings on Linux. The native Apple Accelerate profile explicitly
selects and verifies single-threaded BLAS/LAPACK through Apple's public APIs;
see [numerical runtime details and acceptance limits](NUMERICAL_RUNTIME.md).
No numerical tolerance changes. Unobservable or incompatible execution fails explicitly.

The CLI reads the frozen request (or hash-verified receipt context for reproduce)
before importing numerical libraries and restores only its allowlisted startup
controls. It then verifies the actual initialized runtime before computation.
Direct Python API callers must already match the frozen runtime; changing an
environment label after import cannot repair an initialized pool. The reproduction
test intentionally starts its child with a different Polars setting to verify
restoration and retains exact result/series/fingerprint/cluster hashes.

Legacy runtime identities remain readable and serialize exactly as before, but
have no effective execution pin. They are refused with
`legacy_runtime_missing_execution_identity` by the new execution path. Do not add
fields to old records, receipts or campaigns. Reproduce historical evidence in its
original pinned implementation; new evaluations/campaigns use an explicit v2
identity and remain distinct counted records. Runtime/thread mismatches return
fixed safe reason codes rather than environment dumps or rounded results.

Built-in version UUIDs/content hashes come from `runtime.builtin_definition()`;
they are not Registry publication claims. Registry assignment belongs to Stage 3.
Every request also supplies the program, economic lineage, generation, cohort,
epoch, protocol and snapshot identity. Server-issued lineage/generation and
release-budget enforcement belong to the later registry/release/job stages.

Activation is immutable and hash-checked. Measurement is pure numerical code;
database audit timestamps stay outside the results hash. Runs, metric/series
references, fingerprints, clusters, official records and trials commit atomically.
Failed/withheld/diagnostic attempts remain counted. Duplicate request IDs cannot
change inputs, and a failed transaction cannot leave a committed success record.
Unreferenced private content-addressed files may remain after a transaction rolls
back; they do not establish acceptance.

Receipts are explicitly **internal unsigned integrity receipts**. They bind all
private file hashes and identities; they are not signed released reports,
delivery receipts or investment-promotion decisions. Evidence files require
private filesystem permissions. Replay verifies their physical hashes, recomputes
metrics and logical series hashes, and regenerates the frozen fingerprint/cluster
evidence. Later trials do not change the pinned cohort. A mismatch exits nonzero
and produces an audit event; exact replay creates no additional evaluated version
or feedback query. Historical code/runtime mismatches are refused, not silently
recomputed under the latest implementation.

## Trial clustering

The pilot uses every instrument on the original P0 development grid of 122 mature
weekly decisions (3,782 points), including initial construction. Both entry and
exit must lie inside development. Its grid SHA256 is
`5dfe255578041e00934cf7ae84415be903e3dcc3fcf35bafdba9ecf29863621a`, independently
derived from the preserved original period and weekly-signal ledgers. The frozen
source hashes and definition are in `qfr_eval/builtin_artifacts.json`. No dates
are sampled and no confirmation outcomes are used. The stock profile's 40-date
default is not inherited.

Similarity is the mean of per-date absolute Spearman correlations, using the
shared core implementation and stable date/name ordering. A similarity of at
least 0.7 joins components by single linkage. All attempts remain in the raw
count; deduplicating identical vectors only avoids redundant pair calculations.
Missing or incomparable fingerprints yield `insufficient_data` and no N_eff.
Above 20,000 attempts, the declared fallback counts canonical economic families
and explicitly records that basis, including missing fingerprint coverage.
Display-name changes do not create independent families.

The owner command writes immutable audited cluster snapshots. It is an on-demand
job building block, not an always-running nightly daemon. A later authorized job
scheduler may invoke it. Snapshotting neither releases feedback nor starts new
research. DSR reports raw/effective counts; PBO and per-decision HLZ remain pilot
diagnostics, not stock-profile forward-investment acceptance.

## Verification and limits

Run `just check` and `just test` with `QFR_TEST_POSTGRES_DSN`,
`QFR_PILOT_ROOT` and `QFR_PILOT_ORACLE_ROOT` set to the real local services and
preserved licensed evidence. Missing inputs produce explicit skips; a skip does
not satisfy a local real-input gate. Public GitHub CI has no licensed data and
reports those skips separately.

Stage 2's required checks are full PIL-02, all six historical prefixes,
EVL-02/04/06, STAT-01/02 and identical hashes on replay. The final task/PR report
records the exact tested commit, command summaries and each gate result.
Complete workflow verification additionally covers CI-service bootstrap, actual
Compose initialization/restart/boundaries, the startup regressions, host and Linux
container suites, and all four images for AMD64 and ARM64. Local ARM emulation is
labelled separately; image builds do not establish Stage 7 native runtime or
sandbox acceptance. Check memory, disk and inodes before serial builds; retain
logs/digests and only reclaim this task's recreatable caches when authorized.

Psycopg is now an evaluator runtime dependency, not only a test dependency. Its
LGPL-3.0 obligations and bundled native-library notices remain separate from the
project's own terms. Wheels reference dependencies; Docker images install them
and must retain their license/notice material. This is not legal clearance of
all possible binary redistribution modes.

Stage 3 registry/sandbox, Stage 4 release/signing/Ladder enforcement, Stage 5
providers/MCP/jobs and Stage 7 native/confirmation acceptance remain deferred.
DeepSeek v4.1 Flash must be the first provider model integrated; secret presence
does not authorize a live call. No Stage 2 model request is necessary.
