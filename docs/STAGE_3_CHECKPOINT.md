> Historical checkpoint. The [current acceptance reconciliation](STAGE_3_ACCEPTANCE.md)
> records the later Docker-native implementation and reported passing Apple SBX
> and Registry pilot tests. The following report retains its original source,
> counts and then-blocked gates. It does not describe the current implementation.
> The subsequent acceptance record closes those evidence gaps. This historical
> checkpoint is not the current Stage 3 gate assessment.

# Stage 3 checkpoint — October 28, 2026

**DRAFT — NOT MERGE-READY. Stage 3 has not passed its exit gate.** Actual Apple
sandbox readiness, required sandbox tests and Registry P0/P1 sandbox execution
remain blocked/unrun. Hosted CI passing would not remove these blockers. Stage 4
is not started; this checkpoint does not authorize a merge or waive a gate.

The implementation verified below is
`416a4342d1cd49e22ae4eec487b3bbf364b94fbd`. This report is a documentation-only
follow-up. The PR targets `main` from `wip/stage-3-mac-validation`; the verified
base is `2a752b06619c92829fbdf7a9a6606309c3abd18b`. Its tree equals the common
ancestor `0ff588b1ddcadba7ff720c9ff5a71b3d1e3ef485`; approved licensing is preserved.

## Implemented scope

- Immutable Registry publication, version/family assignment, idempotency,
  authenticated reads and writes, lineage, append-only audit and database grants.
- Evaluator-owned polling, deduplication, bounded screening, five kind adapters,
  atomic private records/trials/budget reservations, and frozen Registry evidence
  for subsequent measurement and reproduction.
- A runsc-only execution contract and tests that fail closed when isolation is
  unavailable. Cloud development evidence is retained with its original scope.
- PostgreSQL prerequisite diagnostics and portable permission fixtures; numerical
  runtime identities, pre-import replay bootstrap and verified per-worker Apple
  Accelerate initialization without automatic drift repair.

## Verified evidence and limits

The Mac validation session reported these results on the exact implementation
commit above, using real PostgreSQL and private original inputs. No datasets,
credentials, private paths or raw execution logs are included in this repository.

| Check | Result and scope |
|---|---|
| Native macOS/Apple ARM64 static checks | PASS: all seven `just check` commands |
| Native runtime and EVL-04 | PASS: 25 tests with Polars pool 4; 25 with the normal default; strict reproduction hashes retained |
| Registry concurrency, thread initialization and drift | PASS: 3 tests; one immutable record/trial/budget slot on retries; deliberate drift refuses writes |
| Full native suite before oracle materialization | 612 passed, 27 skipped; zero failures |
| Docker Desktop Linux ARM64 CI | 606 passed, 33 skipped; static checks passed; this is container evidence, not macOS host acceptance |
| Native original-oracle parity follow-up | PASS: all 9 previously blocked oracle cases; complete parity file 10 passed |
| Bounded cloud checks on the same implementation | `just check` PASS; offline `just test`: 471 passed, 168 skipped, one unchanged warning in 59.13 seconds |
| Full acceptance on the final PR source | UNRUN: requires final-source workflow/deployment evidence; this report does not combine separate runs into an invented full-suite total |

The native full-suite skips were 18 sandbox-dependent cases and 9 original-oracle
cases. The separate parity run closes the latter evidence gap. The container run
also skipped five native Apple checks and one UID-specific case. Skips never
satisfy their gates. The cloud run peaked at 297,252 KiB process RSS and
893,218,816 bytes environment memory, with no OOM or resource guard event.

## Historical oracle provenance

The Mac recreated historical oracle evidence privately using the unchanged
[original-source harness](../scripts/run_stage1_pilot_oracles.py), its unchanged
[capture observer](../scripts/capture_pilot_features.py), and the
[pinned runtime](../configs/pilot/oracle_runtime.json). That harness invokes each
original package's runner and observes its existing feature output; it does not
derive expected values from the new QFR implementation.

The official Python 3.12.14 image index is pinned to
`sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e`.
Registry metadata verifies that its available Linux ARM64 child manifest is
`sha256:eb5be8e5b4d0a159c237946bbdd06356dda5d19c30fc4f7843e8046d3a590333`.
Original requirements pin NumPy 2.3.5 and pandas 3.0.1; the Mac used separately
hash-verified dependencies, outside the QFR runtime. Existing Stage 1 receipts
and their hashes remain unchanged in [Stage 1 evidence](evidence/STAGE_1.json).
New replay receipts retain their own provenance and are not relabelled as the
historical files.
The selected local image/platform and dependency artifacts belong to the new
private replay record; index membership alone is not native execution evidence.

All 339 original inputs remained unchanged. P0 and P1 each matched 24 original
business CSVs byte-for-byte: 48 in total, with zero model fits and zero provider
requests. This is historical parity evidence, not Registry artifact execution,
sandbox acceptance, an unseen holdout result or a confirmation query.

## Remaining gates and next steps

| Requirement | Status / next evidence |
|---|---|
| REG-01–04 and AUD-01 | Development checks are covered by the real Mac suites; retain final-source CI evidence before final stage acceptance |
| EVL-01, EVL-03, EVL-05 | Implemented and component-tested; sandbox-dependent integration remains unrun on the Apple target |
| SBX-01–04 and actual Apple backend readiness | BLOCKED/UNRUN: the historical runsc backend lacks Apple evidence; S3-26 now approves the native design, whose actual Mac gates remain UNRUN |
| SBX-05 deployment boundary | Static/Compose boundary checks exist; retain actual final deployment evidence; static success cannot substitute for runtime isolation |
| Registered six-feature DSL parity | Component test included in the native suite: `test_registry_six_v4_dsl_features_equal_independent_polars`; this does not execute the P0/P1 packages in a sandbox |
| Registry P0/P1 sandbox reproduction | BLOCKED/UNRUN: run the four full-package cases in `tests/registry/test_pilot_execution.py` with real inputs, the declared core-only image and a ready approved backend |
| Final local workflow and image matrix | UNRUN on final PR source: reconcile exact-commit host/container, Compose restart/boundary and image-digest evidence on the Mac |
| Hosted CI | Observe the final PR commit's checks; public CI omits licensed/private inputs and cannot close those local gates |

Keep strict protocol settings, numerical hashes and immutable evidence. New code
changes implementation identity: create fresh test contexts without rewriting
older records or resetting economic lineage/budget exposure. Heavy validation
remains on the Mac. No merge, Stage 4, paid provider call, confirmation query,
host/runtime/security change or workaround is authorized by this checkpoint.

## Decisions for review

The full rationale and limits remain in [decisions.md](decisions.md).

| Decision | Resolution |
|---|---|
| S3-14 | Withheld projections expose no outcome-derived reasons; preserve the historical cloud screening evidence with its original scope |
| S3-15 | Bind Registry measurement and replay to exact immutable publication/screening evidence, rather than relabelling built-in output |
| S3-16 | Resolve PostgreSQL prerequisites before HTTP/thread fixtures; required CI database failures remain failures |
| S3-17 | Test actual UID read denial inside Linux tmpfs; preserve production secret handling and host permissions |
| S3-18 | Apple macOS/ARM64 first; Linux AMD64 remains a separately accepted deployment target |
| S3-19 | Pin numerical execution and restore frozen controls before CLI imports; retain exact hashes and legacy serialization |
| S3-20 | Continue authorized checkpoint work without waiting for review/merge; real stage gates still govern continuation |
| S3-21 | Verify Apple Accelerate using public calling-thread APIs and loaded-code evidence; no empty-pool acceptance |
| S3-22 | Correct child test initialization while retaining explicit drift refusal |
| S3-23 | Initialize each trusted worker once and verify before work; reused workers cannot repair drift automatically |
| S3-24 | Publish this explicitly incomplete draft checkpoint with scoped evidence and unresolved Apple sandbox gates |
