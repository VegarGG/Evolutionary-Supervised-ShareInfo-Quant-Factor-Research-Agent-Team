# Modular development after the owner trial

The owner completed the guarded DSH pilot and directed development to continue
under the approved [modular plan](https://chatgpt.com/space/page_5ff299fdf2208191ade3872b9916998a).
The prototype is not production ready. Its fixed definition and fixed worker
sequence demonstrate execution and accounting, not adaptive research.

## Authority and provider change

Owner instruction: “Cancel the scheduled DeepSeek run. Continue the design and
development based on the modular development plan. You should continue to use
GLM models to test until the usage is empty or I tell you to switch.”

This replaces the earlier GLM end time of 18:00 Beijing. Use Coding Plan Pro,
`glm-5.3-flash` first, with no automatic provider or metered fallback. Preserve
the original cumulative 200 CNY ceiling, official 20.35 CNY baseline, every prior
call and unresolved reservation. Local request/credit caps are work-package
limits, not a claim about the account's remaining subscription quota. Exhaustion
or uncertain provider usage stops dispatch; do not retry blindly.

No pending Codex automation, user crontab, or separate scheduled DeepSeek test
process was found at the cancellation check. Enforce cancellation at the shared
ledger as well, so an old launcher cannot dispatch DeepSeek at its former window.

## Current work package

- [x] Freeze and independently audit the owner's completed trial.
- [x] Add an append-only campaign provider restriction, checked atomically with
  every reservation; continue settlement of already dispatched requests.
- [x] Activate a bounded GLM development allowance without the old clock cutoff.
- [x] Implement a standalone shared-state module: source-linked findings,
  immutable candidate versions, explicit review decisions and stale-write refusal.
- [x] Test missing citations, unauthorized actors, stale parents, conflicting
  findings, cross-episode references, restart and concurrent writers offline.
- [x] Run a small real GLM author/reviewer/revision demonstration on a labeled
  diagnostic fixture. Keep the answer key outside the model workspace and prompt.
- [x] Compare a feedback-enabled revision with a feedback-disabled control from
  the same initial candidate and evidence, with equal request/output ceilings.
- [x] Record actual evidence → contribution → decision → revision, unsuccessful
  cases, costs, tokens, cache, dispatch/completion rates and machine usage.
- [x] Update capability limits, roadmap and README; preserve a draft, unmerged PR.

## Next modules and progression gates

| Module | Contract / demonstration required | Current boundary |
| --- | --- | --- |
| Shared state | Versioned source-linked findings and an unambiguous candidate head | Standalone first; no official factor pool |
| Review | Findings pinned to the reviewed version; adopted/rejected/deferred decisions | Structural checks do not certify factual truth |
| Coordination | Supervisor chooses a targeted follow-up after a new constraint | Current fixed worker sequence does not demonstrate this |
| Evolution | Child of a frozen parent with a substantive declared change | No automatic publication or acceptance |
| Parallel / composition | Distinct branches, pinned constituents, duplicate handling | After one lane works |
| Released feedback | Exact candidate/report matching and a justified next question | GET-only released feedback; no evaluator control |
| Role models / market context | Native DSH role selection plus bounded evidence manifests | Existing staged design remains; GLM-only live testing now |

Integrate one demonstrated module at a time. Retest earlier cases and include
open-ended A-share cases; a diagnostic success alone does not establish general
discovery capability, investment value or production readiness.

## Recording rubric

For each attempt retain the clean commit or dirty diff hash, module/config/case
hashes, real inference versus synthetic evidence labels, UTC/Beijing timestamps,
principal and request ids, evidence actually available, parent and child hashes,
review decisions, rejected operations, all provider responses privately, settled
and reserved usage, per-agent TPM/RPM/cache, resource-sampling scope and errors,
deterministic acceptance checks, qualitative limitations and the next gate.


## Verified results of this work package

Recorded on 13 November 2026. **180 offline tests pass**, together with lint,
format, JavaScript and MIT-notice checks. The real native DSH adapter also passed
a synthetic-stream smoke test without accessing a provider. Browser validation
of the corrected native Models/Research data text passed on local Chrome at
1440×1000; page identity, content, interaction and console checks passed. Existing
mobile clipping remains outside acceptance. Browser plugin was unavailable, so
the installed Playwright/Chrome fallback was used.

The owner trial at **13:24–13:30 Beijing** completed three roles and an immutable
draft with fifteen actual GLM requests, 163,355 tokens and 0.438382 CNY of
conservative exposure debits. Researcher/reviewer/supervisor made six/four/five
requests. Its independent wire, data and full calculation audit passes. A stale
server manifest was initially included in the export; it was removed based on
absence of resource samples in the trial interval. The original export and failed
audit remain private. Full role measurements are in
[OWNER_TRIAL.json](evidence/modular-2026-11-13/OWNER_TRIAL.json).

The new module tests made **eleven real GLM 5.3 Flash requests**, with synthetic
diagnostic evidence and **zero data-provider requests**. They use separate native
DSH SDK author/reviewer sessions, not a new three-role Agent Teams UI trial. All
eleven wire usages settled and were independently checked against the shared
ledger. Total usage: **69,923 tokens**, **0.463528 CNY** conservative exposure and
**46.83208** upper-estimated subscription credits. These amounts are not an
incremental subscription invoice.

| Attempt | Calls | Independent outcome | Tokens | Conservative CNY | Seconds |
| --- | ---: | --- | ---: | ---: | ---: |
| timing-control-001 | 2 | diagnostic_pass | 11,846 | 0.081004 | 158.1 |
| timing-peer-001 | 2 | incomplete | 10,469 | 0.063100 | 124.5 |
| timing-peer-002 | 2 | diagnostic_pass | 16,170 | 0.109116 | 222.9 |
| units-control-001 | 2 | formula_correct_explanation_failed | 8,509 | 0.053984 | 114.7 |
| units-peer-001 | 1 | contract_failure_with_correct_substantive_finding | 6,702 | 0.047838 | 114.6 |
| units-peer-002 | 2 | formula_correct_explanation_failed | 16,227 | 0.108486 | 235.5 |

The first timing attempt exhausted the 4,096 output-token ceiling in the author
turn. The retry and both matched comparisons use 8,192 per call. A separate
export defect used `MANIFEST.json` alongside `manifest.json`; these collide on
case-insensitive APFS. The exporter now uses `ARTIFACT_HASHES.json`. The first
export was repaired offline without replay.

The first units review derived the correct scale but invented `candidate` as a
source id. The host rejected it before the author ran. The next version enumerates
the actual source ids in the output schema. No invalid source was silently
accepted, and this did not require a model upgrade.

## Capability findings and limits

**Shared state and provenance work in these bounded demonstrations.** Findings
pin an immutable candidate version; exact excerpts link to frozen sources; the
author records adopt/reject/defer decisions; a child retains its parent and peer
contributions. Offline checks cover concurrent stale writes, cross-episode refs,
conflicting findings, unauthorized actors, missing/forged citations, tampered
history, state limits, restart and paid replay refusal. These are local host-owned
files with locks; no multi-host storage claim is made.

**The timing correction is supported, but no collaboration accuracy advantage
was demonstrated.** Both arms corrected period-end availability to actual release
and selected the first eligible close (6 May) and next execution close (7 May).
The feedback arm explicitly adopted four findings, of which two describe the
substantive timing defects and the others are scope/definition clarifications.
It used more tokens and time than the control. This is one paired diagnostic per
case, not a general effect estimate. The disabled arm still computes a review and
withholds it; it is a mechanism ablation, not an optimized single-agent cost baseline.

**The units formulas are correct; both explanations fail independent review.**
The intended ratio is `(profit_reported / capitalization_reported) * 0.0001`.
The peer author says the initial value was “understated”; it was **overstated**.
The control author says the raw ratio equals the intended ratio times `10^-4`;
the correct relation is times `10^4`. The peer reviewer had stated this relation
correctly, so its error arose during synthesis. The paired arms also disagree on
the strict/inclusive publication-time boundary; the fixture's “after”/“by” wording
does not justify declaring a proved additional timing discovery.

Neither units explanation is accepted for production or an official report. The
original outputs remain unchanged, with separate source-based semantic reviews.
A schema pass and a matching formula cannot stand in for a review of the final
explanation. These results do not establish profitable alpha, broad discovery
capability, or a completed Hybrid v1. They also do not yet establish that GLM Flash
must be replaced: both arms found the intended unit conversion, while interface
and synthesis defects are now explicit counterexamples for the next module gate.

## Actual agent usage and machine observations

RPM/TPM are peak rolling sixty-second counts, attributing each call's total tokens
to dispatch/completion. They are not instantaneous streamed-token rates. An author
with zero calls has no cache observation. Role-specific resource intervals are
in the JSON record. All completed module calls reported zero cache hits.

| Attempt / role | Calls | Tokens | Conservative CNY | Dispatch RPM / TPM | Completion RPM / TPM | Input cache |
| --- | ---: | ---: | ---: | --- | --- | --- |
| timing-control-001: author | 1 | 5,165 | 0.033430 | 1 / 5,165 | 1 / 5,165 | 0.0% |
| timing-control-001: reviewer | 1 | 6,681 | 0.047574 | 1 / 6,681 | 1 / 6,681 | 0.0% |
| timing-peer-001: author | 1 | 6,560 | 0.037696 | 1 / 6,560 | 1 / 6,560 | 0.0% |
| timing-peer-001: reviewer | 1 | 3,909 | 0.025404 | 1 / 3,909 | 1 / 3,909 | 0.0% |
| timing-peer-002: author | 1 | 9,486 | 0.061500 | 1 / 9,486 | 1 / 9,486 | 0.0% |
| timing-peer-002: reviewer | 1 | 6,684 | 0.047616 | 1 / 6,684 | 1 / 6,684 | 0.0% |
| units-control-001: author | 1 | 4,300 | 0.026348 | 1 / 4,300 | 1 / 4,300 | 0.0% |
| units-control-001: reviewer | 1 | 4,209 | 0.027636 | 1 / 4,209 | 1 / 4,209 | 0.0% |
| units-peer-001: author | 0 | 0 | 0.000000 | 0 / 0 | 0 / 0 | unreported |
| units-peer-001: reviewer | 1 | 6,702 | 0.047838 | 1 / 6,702 | 1 / 6,702 | 0.0% |
| units-peer-002: author | 1 | 7,700 | 0.046294 | 1 / 7,700 | 1 / 7,700 | 0.0% |
| units-peer-002: reviewer | 1 | 8,527 | 0.062192 | 1 / 8,527 | 1 / 8,527 | 0.0% |

| Attempt | Peak RSS MiB | Mean CPU cores | Peak sampled cores | Samples | Host swap bytes |
| --- | ---: | ---: | ---: | ---: | ---: |
| timing-control-001 | 564.67 | 0.0594 | 0.7576 | 155 | 0 |
| timing-peer-001 | 558.64 | 0.0584 | 0.7640 | 122 | 0 |
| timing-peer-002 | 566.59 | 0.0564 | 0.7650 | 218 | 0 |
| units-control-001 | 563.36 | 0.0511 | 0.7644 | 113 | 0 |
| units-peer-001 | 556.25 | 0.0511 | 0.7734 | 112 | 0 |
| units-peer-002 | 569.89 | 0.0428 | 0.7881 | 230 | 0 |

Resource sampling covers the module runner, local guard and its DSH child
processes at one-second intervals. CPU/host readings are observations, not
production sizing or isolated per-agent allocations. The separate web UI is
outside this process tree. Low local CPU use and long provider calls point to
inference/interaction cost as the immediate bottleneck; additional CPUs would
not resolve the observed synthesis errors. No cache-efficiency claim is made.

## Budget, evidence and next gate

After all attempts: **23.566904 CNY** accounted baseline plus conservative debits,
**5.242880 CNY** still reserved for the earlier authentication rejection, and
**171.190216 CNY** unreserved under the original 200 CNY ceiling. The official
20.35 CNY baseline is unchanged. Across the campaign, GLM has 58 recorded requests,
209.79563 upper-estimated settled credits and 555.74528 credits retained as reserved.
The current local work package permits 100 aggregate requests and 1,500 credits;
these are not the actual account quota, which can also be used in another harness.
No pending or unknown requests remain; the reviewed 401 is still reserved.

[MODULE_RESULTS.json](evidence/modular-2026-11-13/MODULE_RESULTS.json) contains
per-role measurements, immutable candidate changes and separate semantic reviews.
Each private run has raw native sessions, request/response records, artifact
hashes, exact source snapshots and an independent `AUDIT.json`. All 83–86 source
files per attempt match the hashes recorded at launch, including attempts started
from a dirty tree. The original source versions were recovered by exact hash,
not inferred from a later successful implementation. A final ledger backup is
retained in `.qfh-private/integration/modular-001/`.

The next development gate is **native adaptive coordination with review of the
final synthesis**: expose this board through narrowly scoped DSH tools, let a
supervisor request a targeted follow-up when a worker finds a constraint, and
require corrections to reach a new attributed record without rewriting history.
Replay these timing/unit counterexamples before moving to a previously unseen
BaoStock research case. Broader market context, heterogeneous role models,
evolution/composition, official evaluation and production operation remain staged.
The fixed eight-session UI pilot remains exhausted; existing results and settings
remain readable. This standalone CLI module is not yet an open-ended chat workflow.
