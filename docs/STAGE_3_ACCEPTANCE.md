# Stage 3 acceptance reconciliation — October 28, 2026

**NOT YET MERGE-READY.** The Mac validation report for the source below closes the
previous sandbox and Registry pilot failures. Required deployment evidence is
still incomplete in this review: actual Compose restart and socket boundaries,
and the final local image matrix. These are evidence gaps, not newly observed
test failures. Stage 4 has not started. GitHub mergeability is not gate acceptance.

## Source and evidence scope

- Tested implementation: `b3506b69f1aa3347fe1347cf1e671bf198c67677`.
- Tree: `6ed3770f63529d15f78312ba719aeabd85e874dc`.
- WIP branch: `wip/stage-3-mac-validation`; [draft PR #7](https://github.com/VegarGG/Evolutionary-Supervised-ShareInfo-Quant-Factor-Research-Agent-Team/pull/7).
- Verified PR base: `2a752b06619c92829fbdf7a9a6606309c3abd18b`.
- Dependency lock SHA256:
  `4dfe02856d7494878a23b419fdb17b10e8a5aecb5781a01c22923569daa78b9d`.
- Approved evaluation YAML SHA256:
  `a234bcc99af5c6c34b8fb585eb0701dca614d55048629418030876ff6dc752fb`.
- Native sandbox profile canonical SHA256:
  `d359c8de0dd585558c224e0c3f3a3abc59813b8759b23ef8431b52760cfc2026`.

`PASS (Mac report)` below means the existing Mac validation session reported the
test passing on this exact source with real PostgreSQL, private pilot inputs and
the historical oracle. The implementation session reviewed the named assertions;
it did not rerun those heavy checks in cloud or independently obtain the latest
private Mac logs. `UNVERIFIED` means the required operational evidence was not
supplied in that report; it does not mean that a check ran and failed, nor that it
definitely has not run. Earlier failed/unrun checkpoints retain their original
source and scope in [STAGE_3.md](STAGE_3.md) and
[STAGE_3_CHECKPOINT.md](STAGE_3_CHECKPOINT.md).

| Verification | Result on the tested implementation |
|---|---|
| Native macOS/Apple ARM64 suite | PASS (Mac report): **790 passed, zero skips**; actual OOM/fork/SIGKILL and all four registered P0/P1 cases passed |
| Native static checks | PASS (Mac report): static checks green; full seven-command cloud `just check` also passes |
| Docker Desktop Linux ARM64 CI suite | PASS (Mac report): **765 passed, 25 explicitly reported skips**, static checks green; exact skip categories still requested |
| Compose controller startup | PASS (Mac report): readiness succeeds; container-side socket GID 0 grant audited with no material unrelated permission gain |
| Cleanup and database health | PASS (Mac report): task cleanup complete, PostgreSQL healthy; this does not prove controller restart recovery |
| Bounded cloud `just test` | **621 passed, 169 prerequisite skips**, one unchanged warning, 111.17 s; this offline result does not satisfy real-service, licensed-input or sandbox gates |
| Bounded cloud focused checks | **191 passed**, 1.70 s; resource-event, socket, native-network and Compose-contract regressions |
| Exact-source hosted CI | PASS: [run 40715488584](https://github.com/VegarGG/Evolutionary-Supervised-ShareInfo-Quant-Factor-Research-Agent-Team/actions/runs/40715488584); **709 passed, 81 skipped**, eight real-container PostgreSQL startup regressions, 15 live database boundary tests and all ten image builds |

Hosted builds ran on native Linux AMD64 and Linux ARM64 runners: four application
images plus one core-only sandbox image per architecture. Those builds and their
digests do not replace Apple host acceptance or demonstrate later native Linux
AMD64 deployment acceptance. Container-suite skips cannot be counted as passes;
the reported native zero-skip run supplies the actual Apple execution evidence.

This reconciliation changes documentation only. Fresh `just check` passes all
seven commands; local links and all 20 named test references above/below resolve.
Code, tests, contracts, workflows, locks, profiles and the files copied by all
three Dockerfiles are unchanged from the tested implementation. The full suites
were not needlessly repeated for this prose change: their results remain
attributed to `b3506b6`, and earlier image revision labels are not rewritten.

## Plan section 10 gate mapping

All statuses in this table refer to the implementation above. Test names identify
the assertions supporting each gate, rather than treating a suite total as a
substitute for coverage.

| Gate | Status | Named evidence and assertion |
|---|---|---|
| REG-01 | PASS (Mac report) | `test_reg_01_insert_only_grants_and_owner_triggers` in [database boundaries](../tests/boundary/test_database.py), plus `test_new_registry_tables_preserve_grants_and_owner_triggers`: actual role grants and owner triggers reject mutations |
| REG-02 | PASS (Mac report) | `test_reg02_reg04_identical_publication_and_server_identity` in [publication tests](../tests/registry/test_publication.py): identical published content returns the same version |
| REG-03 | PASS (Mac report) | `test_reg03_revision_new_hash_same_family_and_retry_conflict`: changed content receives a new hash/version while retry conflicts are rejected |
| REG-04 | PASS (Mac report) | `test_reg02_reg04_identical_publication_and_server_identity`: server-derived identity is independent of the supplied client hash |
| Identical definitions | PASS (Mac report) | `test_concurrent_identical_definitions_get_one_id`: concurrent publications converge on one immutable version |
| EVL-01 | PASS (Mac report) | `test_evl01_idle_does_not_poll_and_public_registry_has_no_trigger` and `test_cursor_polling_is_concurrent_idempotent_and_audited` in [intake tests](../tests/registry/test_intake.py): evaluator cursor pull, no inbound trigger |
| EVL-03 | PASS (Mac report) | `test_prefix_harness_rejects_injected_future_lookahead` in [prefix tests](../tests/evaluator/test_prefix.py), supplemented by actual sandbox causality probes below |
| EVL-05 | PASS (Mac report) | `test_evl05_canonical_duplicate_never_queued_reserved_or_counted` and `test_screening_worker_behavior_duplicate_never_reads_validation_or_counts_trial`: exact/behavioral duplicates produce no trial or budget reservation; behavioral comparison uses development only |
| Registry P0/P1 parity | PASS (Mac report) | Both variants of `test_registry_p0_p1_original_oracle_is_reproduced_from_actual_outputs` and `test_registry_p0_p1_screen_measure_and_reproduce_without_registry_network` in [pilot execution tests](../tests/registry/test_pilot_execution.py): exact ledger outputs, Stage 2 result hashes across four cycles, and independent replay without Registry access |
| DSL v4 feature parity | PASS (Mac report) | `test_registry_six_v4_dsl_features_equal_independent_polars`: six published DSL definitions agree with the independent feature reference |
| SBX-01 | PASS (Mac report) | `test_sbx_actual_output_drives_causality_gate[lookahead]` in [sandbox tests](../tests/evaluator/test_sandbox.py): actual output fails both prefix and perturbation checks with `failed:lookahead` |
| SBX-02 | PASS (Mac report) | `test_sbx_actual_bounded_negative_fixtures` and `test_sbx_actual_resource_exhaustion_is_bounded`: network, private-file/root writes, timeout, capped output, symlink result, fork, memory and CPU controls; genuine OOM/PID evidence classified correctly, plain SIGKILL remains runtime failure |
| SBX-03 | PASS (Mac report); readiness identity receipt requested | Actual Apple host / Docker Desktop backend readiness and `test_sbx_actual_controls_determinism_single_result_and_cleanup`; unavailable-backend and missing-sandbox intake tests fail closed. Preserve the actual host, engine, runtime, image and profile identities in the evidence handoff |
| SBX-04 | PASS (Mac report) | `test_sbx_actual_controls_determinism_single_result_and_cleanup` yields identical result hashes; `test_sbx_actual_output_drives_causality_gate[nondeterminism]` rejects the nondeterministic fixture |
| SBX-05 | PASS (Mac report), configuration-test scope | `test_compose_trust_zones` and `test_native_overlay_grants_only_controller_and_private_evaluator_channel` in [Compose tests](../tests/boundary/test_compose.py): no engine socket, writable host mount or privileged flag in research/MCP/artifact roles; deployed-role evidence remains separately listed below |
| AUD-01 (Registry) | PASS (Mac report) | `test_registry_aud01_principal_request_time_and_rollback` in [Registry database tests](../tests/registry/test_registry_database.py), authenticated HTTP/retry audit tests: principal, UTC time and request identity; rollback does not leave a false success |

Required implementation coverage also includes all five kind adapters, frozen
model weights and constrained Python, original pilot eligibility/coverage,
owner-approved exact behavioral-duplicate and complete-degeneracy screening,
fair polling and lease fencing, and atomic screening record/trial/budget writes.
The full native run includes these tests. It retains three feedback-bearing
versions per economic lineage/generation, with no reset by renaming, branching
or a new campaign. Publication is the only public Registry mutation surface.

Original oracle evidence was recreated privately with the pinned historical
Python image, hash-verified original dependencies and unchanged original-source
harness. All 339 inputs remained unchanged; 48 original reference CSVs matched
byte-for-byte; no model fit or provider request occurred. All nine original
oracle cases are included in the reported zero-skip native run. This does not
spend a confirmation query or generate replacement goldens from current code.

## Required deployment evidence still to reconcile

The following requirements come from the authorized full local CI scope and
controller deployment handoff, in addition to the named section 10 tests. They
are not silently added to, or removed from, SBX-05's configuration-test meaning.
Use existing exact-source evidence where it exists; rerun only missing checks or
checks whose inputs changed. No new privileged setting or backend is required.

| Item | Status | Smallest outstanding verification |
|---|---|---|
| Actual Compose controller restart | UNVERIFIED | Stop/start or recreate the actual controller with its persistent IPC volume; verify stale-socket recovery, non-root 0700 directory/0600 socket, post-restart readiness and no orphan job containers/input volumes. Unit fake-engine restart tests alone do not establish this |
| Deployed socket/trust boundaries | UNVERIFIED | Record effective mounts, UID/groups, capabilities and security options: only the trusted controller can reach the engine; evaluator can use only the private controller channel; research/MCP/Registry/candidates have neither channel. Verify denied access and that the controller has no DB/provider/signing secrets or full-data mount |
| Final local image matrix | UNVERIFIED | Supply each final-source application/core image digest, source/input identity and build mode for Linux ARM64 and AMD64 on the Mac; label AMD64 emulation. Carry forward an older build only with identical build-input proof, preserving its actual revision label |
| Mac PostgreSQL init/restart and live boundaries | UNVERIFIED as a separate startup-script run | Supply the exact-source `verify_postgres_startup.py` result (including incomplete-restart refusal) and live Compose database-boundary result, or verified unchanged-input evidence from its earlier passing Mac run. A healthy server and hosted Linux pass are insufficient substitutes |
| Evidence identity and container skips | UNVERIFIED detail | Supply sanitized commands, host/engine/runtime/profile/image identities, result/log hashes and the 25 container skip categories. The aggregate does not establish what was skipped |

The controller GID correction is restricted to the existing S3-26 grant. UID and
primary GID remain 65532, capabilities remain dropped, root remains read-only,
network remains disabled, and candidate/staging containers receive no
supplemental group. The Mac report explicitly records no material unrelated
access from the controller's container-local GID 0. No host chmod/chown, root
launcher, additional capability or API grant is inferred from this evidence.

## Stage 4 entry review — no implementation authorized by this report

Exact next stage: **Blackboard, release policy, MCP front door and delivery export
(M2)**. The unresolved prerequisite is a fully reconciled green Stage 3 gate.
The pilot release choices have already been approved: scalar plus flags; fixed
Ladder step `0.011239912200318261` (1.123991220031826 percentage points), rounded
down; three feedback versions per economic lineage/generation; one confirmation
query per protocol, requiring separate authorization to spend it. The P0/P1-only,
previously-seen windows remain unchanged. The generic release-policy draft must
be instantiated from this approved exact protocol during Stage 4; its draft
status does not revoke or replace that approval.

Plan order: P4.1 research schema/queue; P3.5 both release policies; P3.6 GET-only
feedback/cards; signing and independent delivery checker (no separate local work
package ID); P3.8 authorized on-demand import/snapshot builds; P4.9 Research API,
MCP and delivery export; portable intake guide and two-client examples. No LLM
research loop belongs to this stage.

Required reading, in order:

1. [AGENTS.md](../AGENTS.md) and applicable runtime guidance.
2. [PLAN_ALIGNMENT.md](PLAN_ALIGNMENT.md) A–C, E–K.
3. [HYBRID_V1_DEVELOPMENT_PLAN.md](HYBRID_V1_DEVELOPMENT_PLAN.md): section 10
   Stage 4 and owner-input table; sections 2, 3.1–3.5, 4.1–4.6, 4.8, 5.1–5.3,
   6.5, 6.7, 7.1–7.2, 7.7–7.9, 11.1–11.3 and 13.
4. [LOCAL_IMPLEMENTATION_REFERENCE.md](LOCAL_IMPLEMENTATION_REFERENCE.md):
   sections 3, 4.3–4.4, 5.3–5.5, 6.4–6.5, 8.8–8.9, 9.1–9.4, 9.6, 11.1,
   11.3–11.4, 13.2–13.8, 14.1–14.3, 15.1–15.2 and the work packages above.
   Stock thresholds remain scoped to their own profile; optional Thresholdout
   is deferred.
5. [Pilot appendix](appendix-a-pilot-case-industry-rotation.md) A.2–A.9,
   especially A.8; original ledgers and the approved evaluation/release intent.
6. [decisions.md](decisions.md), [Stage 2 operations](STAGE_2.md), this acceptance
   review, and the versioned evaluation and release-policy configurations.

Stage 4 exit requires a no-LLM human pilot flow, frozen protocol, signed
released-only P0/P1 reports with no confirmation fields, and a valid delivery
receipt for an allowed negative result. Named suites: REL-01–06, BND-03,
MCP-01–06, JOB-01–03 and DLV-01–03. Both actual Codex and a second independent
client must connect, submit, disconnect/reconnect and export; synthetic protocol
tests alone cannot satisfy that client gate.

No new provider endpoint, model key or spend authorization is needed for Stage 4.
Actual client connection/configuration and evaluator signing/token identities
must be arranged and verified for its end-to-end test. Ephemeral synthetic test
credentials do not authorize real persistent grants or deployment security
changes. Inactive ingest uses existing authorized inputs; new supplier requests,
live providers and confirmation queries remain unauthorized. Once Stage 3 is
green and continuation is confirmed, a dependent branch may start from its
verified commit without merging PR #7, with the base explicitly recorded.
