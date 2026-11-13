# Completed-output review and adaptive follow-ups — 13 November 2026

Both targeted unit counterexamples are repaired in new, attributed versions. The
native DSH supervisor requested an author follow-up after a failed review and a
fresh reviewer task for the amended output. A clean-output control finalized after
one reviewer task, with no author rewrite. **This is a bounded diagnostic result,
not production readiness or general research acceptance.**

The work made **53 real GLM 5.3 Flash requests**, with
**565,131 tokens**, **45.97% aggregate input-cache hits**
and a **1.590600 CNY conservative exposure debit**.
All new usage settled. Three output-cap failures and one false model pass are
retained. The latter is a material finding: two model reviews accepted a rationale
that still contradicted its correct formula. Independent review withheld semantic
acceptance, and the new deterministic unit-prose check now blocks that failure.

## What changed and why

- Completed-output reviews pin the exact artifact and inspect its rationale,
  hypothesis, contribution reasons, citations and limits as well as its formula.
- Explanation-only amendments preserve computational definition fields and original
  contribution identities. Every issue receives an attributed resolution; the old
  version remains immutable. A clean review on a stale version cannot finalize a new one.
- DSH keeps the model loop, Models editor, native subagents and Agent Teams tasks.
  The host binds native session identities to bounded role grants and immutable
  events. It does not implement another inference loop. Re-review uses a fresh
  reviewer activation, so a repaired episode has three worker tasks across two roles.
  Later reviewers see prior findings; this is separate task execution, not blinded replication.
- A restricted arithmetic parser verifies the unit expression and reciprocal scale
  claims from the frozen dictionaries. A limited English grammar checks explicit
  raw/target equalities and magnitude-direction statements throughout current output.
  Correct structured claims cannot excuse a recognized contradictory sentence.
  Unknown wording still needs semantic review; this is not a general prose proof.
- Missing structured fields can be reported by exact JSON-pointer/value evidence
  (`/unit_claims`, `null`), without pointing at unrelated text. Rejected submissions
  remain recorded and can be repaired inside the same bounded worker task.
- The supervisor receives coordination state; only reviewers receive the review
  schema and only authors receive the amendment schema. The earlier redundant
  schemas contributed unnecessary context. This change is not a controlled performance claim.
- The native Models guard now explains that a finished chat turn alone does not
  establish a reviewed artifact. The native DSH Completed indicator previously also
  appeared on token-cap stops; workflow status comes from artifact/task records.

The scale relationship is **target = raw / 10,000** and **raw = target × 10,000**.
For nonzero ratios, “overstates” refers to magnitude; signed algebra is unchanged,
zero remains zero, and division requires nonzero capitalization. This corrects both
“understated” in a contribution reason and “raw equals target times 10^-4” in a rationale.
Neither correction changes the factor's computational definition or establishes alpha.

## Staged attempts

All times below are Beijing on 13 November. Every attempt used native
`zai-coding-cn` and `glm-5.3-flash`, with thinking enabled and no provider/model fallback.
The evidence was synthetic and frozen. No BaoStock, iFind, RQData, news, evaluation
or publication request was made by this diagnostic profile.

| Attempt | Requested effort / output cap | Beijing activity | Calls | Tokens | CNY debit | Input cache | Outcome |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| final-peer-001 | high / 8,192 | 15:05:21–15:08:35 | 2 | 14,875 | 0.079196 | 22.19% | Supervisor cap failure |
| final-peer-002 | high / 8,192 | 15:11:30–15:15:14 | 4 | 31,194 | 0.126432 | 26.20% | Reviewer cap failure |
| final-peer-003 | high / 16,384 | 15:17:37–15:26:12 | 13 | 217,415 | 0.600826 | 48.50% | Peer explanation repaired |
| final-control-001 | high / 16,384 | 15:28:18–15:34:20 | 4 | 35,081 | 0.183766 | 28.14% | Reviewer cap failure |
| final-control-002 | low / 16,384 | 15:38:46–15:40:56 | 12 | 109,376 | 0.248842 | 49.61% | False model pass — rejected |
| final-control-003 | low / 16,384 | 15:53:02–15:55:29 | 12 | 117,848 | 0.264574 | 48.18% | Control explanation repaired |
| final-clean-001 | low / 16,384 | 15:57:37–15:58:30 | 6 | 39,342 | 0.086964 | 39.11% | Clean output; no rewrite |

The first supervisor exhausted 8,192 output tokens before delegation. Removing
role-irrelevant schemas enabled delegation; the next reviewer hit the same ceiling.
At 16,384 tokens, the peer-output repair completed, including one rejected issue
reference corrected inside the reviewer task. The second counterexample still hit
16,384 tokens at high effort. Low effort completed quickly but produced a false pass:
the author added correct claims while preserving the original wrong equality.
The strengthened parser was then tested offline and the exact false-pass artifact
was imported into a new episode. Its wrong clause was replaced, re-reviewed and
finalized. No failed or false-pass record was overwritten or relabelled as a success.

The low-effort route amendment extends the local aggregate request allowance from
100 to 120. It retains the 1,500-credit cap, 20 CNY package sublimit and original
200 CNY campaign ceiling. These are operator bounds, not an account quota reading.
The results do not establish that low effort is generally better: the false pass
shows why speed and a completed model turn are inadequate acceptance criteria.

## Each agent's actual work

In `final-peer-003`, the supervisor assigned an independent completed-output review,
read the two issues, requested the author correction, asked a fresh reviewer to check
the repaired version, and finalized its exact ID. Reviewer-1 identified the reversed
direction and absent typed claims. Author-2 changed the incorrect contribution reason
and supplied the source-derived claims. Reviewer-3 checked the whole amended artifact.

In `final-control-002`, both model reviews missed the contradictory original clause.
The author appended correct claims, and the native finalization occurred. The separate
source-based audit marked this **false acceptance**, not a successful repair.
In `final-control-003`, the host explicitly identified that same contradiction, the
reviewer recorded it, the supervisor assigned a targeted repair, and the author replaced
the clause with the correct equality. A new reviewer checked the amended output.
In `final-clean-001`, the supervisor accepted the clean review and skipped the author.
The output content is identical to the already corrected peer artifact.

| Attempt / native actor | Calls | Tokens | CNY debit | Peak dispatch RPM / TPM | Peak completion RPM / TPM | Input cache | Peak RSS MiB during activity |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| final-peer-001 / supervisor | 2 | 14,875 | 0.079196 | 2 / 14,875 | 1 / 13,335 | 22.19% | 589.94 |
| final-peer-002 / reviewer-1 | 1 | 14,132 | 0.077416 | 1 / 14,132 | 1 / 14,132 | 0.00% | 593.31 |
| final-peer-002 / supervisor | 3 | 17,062 | 0.049016 | 2 / 10,566 | 2 / 10,566 | 36.87% | 699.92 |
| final-peer-003 / author-2 | 2 | 31,058 | 0.092194 | 1 / 17,004 | 2 / 31,058 | 0.00% | 603.55 |
| final-peer-003 / reviewer-1 | 3 | 55,121 | 0.188134 | 2 / 38,852 | 2 / 38,852 | 38.58% | 585.95 |
| final-peer-003 / reviewer-3 | 2 | 31,973 | 0.096976 | 1 / 16,766 | 2 / 31,973 | 42.07% | 581.77 |
| final-peer-003 / supervisor | 6 | 99,263 | 0.223522 | 2 / 61,849 | 2 / 61,849 | 67.97% | 608.62 |
| final-control-001 / reviewer-1 | 1 | 20,933 | 0.140170 | 1 / 20,933 | 1 / 20,933 | 0.00% | 600.44 |
| final-control-001 / supervisor | 3 | 14,148 | 0.043596 | 2 / 8,332 | 2 / 8,332 | 39.18% | 610.50 |
| final-control-002 / author-2 | 2 | 17,807 | 0.043528 | 2 / 17,807 | 2 / 17,807 | 11.26% | 575.45 |
| final-control-002 / reviewer-1 | 2 | 12,143 | 0.032710 | 2 / 12,143 | 2 / 12,143 | 5.96% | 590.86 |
| final-control-002 / reviewer-3 | 2 | 17,384 | 0.041032 | 2 / 17,384 | 2 / 17,384 | 51.31% | 577.97 |
| final-control-002 / supervisor | 6 | 62,042 | 0.131572 | 3 / 50,357 | 3 / 50,357 | 67.27% | 603.58 |
| final-control-003 / author-2 | 2 | 19,146 | 0.046560 | 2 / 19,146 | 2 / 19,146 | 44.30% | 594.50 |
| final-control-003 / reviewer-1 | 2 | 13,274 | 0.035248 | 2 / 13,274 | 2 / 13,274 | 0.00% | 587.00 |
| final-control-003 / reviewer-3 | 2 | 17,590 | 0.039632 | 2 / 17,590 | 2 / 17,590 | 11.02% | 566.66 |
| final-control-003 / supervisor | 6 | 67,838 | 0.143134 | 3 / 54,901 | 3 / 54,901 | 67.18% | 599.28 |
| final-clean-001 / reviewer-1 | 2 | 13,066 | 0.030734 | 2 / 13,066 | 2 / 13,066 | 5.20% | 595.08 |
| final-clean-001 / supervisor | 4 | 26,276 | 0.056230 | 4 / 26,276 | 4 / 26,276 | 55.36% | 737.20 |

RPM/TPM are maxima over rolling 60-second windows, attributing whole call totals to
request dispatch or completion. They are not per-token arrival measurements or provider
capacity benchmarks. Provider cache counters were explicit for every new call. Coding
Plan amounts are conservative exposure debits and credit upper estimates, not incremental
subscription invoices; cached input is not discounted in the cash guard.

## Machine and evidence usage

The measured host is `arm64`, 18 logical CPUs,
36 GiB RAM, running the pinned DSH SDK/runtime 0.2.2rc2.
Sampling every two seconds covers the shared local guard and DSH process tree.
Role windows describe shared process activity, not isolated per-agent allocations.
Host readings include other work; short-lived processes and interval boundaries can
be missed. Browser automation is outside the measured server process tree.

| Attempt | Wall seconds | Peak RSS MiB | Mean CPU cores | Peak sampled cores | Samples | Hashed evidence MiB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| final-peer-001 | 193.9 | 589.94 | 0.0374 | 0.0997 | 96 | 2.92 |
| final-peer-002 | 223.6 | 699.92 | 0.0368 | 0.1347 | 110 | 3.75 |
| final-peer-003 | 514.7 | 608.62 | 0.0358 | 0.1362 | 254 | 10.07 |
| final-control-001 | 362.4 | 610.50 | 0.0387 | 0.0996 | 179 | 6.39 |
| final-control-002 | 130.3 | 603.58 | 0.0384 | 0.0839 | 65 | 2.33 |
| final-control-003 | 147.4 | 599.28 | 0.0360 | 0.0885 | 73 | 2.31 |
| final-clean-001 | 52.1 | 737.20 | 0.0361 | 0.1190 | 26 | 0.86 |

No swap was observed. Hashed evidence sizes cover the exported artifact/wire set;
they do not claim to measure all DSH storage or host disk I/O. JSON includes free-disk
and available-RAM observations, every role's activity window and measurement limits.
Low local CPU use does not certify production sizing; inference and growing review
context dominate these small diagnostic runs.

## Accounting and validation

Final accounted baseline plus conservative debits: **25.157504 CNY**.
Retained historical reservation: **5.242880 CNY**.
Unreserved balance under the original ceiling: **169.599616 CNY**.
The owner's official 20.35 CNY baseline is unchanged; the older unreconciled estimate
remains history and is not added twice. GLM has 111 aggregate recorded requests,
383.50787 upper-estimated settled credits and
555.74528 retained reserved credits. There are no new pending or unknown calls.
DeepSeek remains canceled and blocked by the shared provider-admission control.

- `just harness-check` and `just harness-test`: **212 tests pass**, plus lint/format,
  JavaScript parsing and MIT checks. Ordinary tests never contact real providers.
- Final offline hardening preserves literal decimal precision and rejects extreme
  numeric exponents before large fraction allocation. All saved accepted unit outputs
  were rechecked unchanged. This last hardening was tested offline after the live runs.
- Native offline smoke: actual DSH UI, subagent activation, Team completion, review,
  amendment and finalization exercised with scripted responses. This is separately
  labelled and never presented as real inference.
- All 53 real calls were checked against raw request/response, model identity,
  requested effort, endpoint, usage, cash/credit arithmetic and role rate calculations.
  Completed runs also verify native Team task completion, output/review identity,
  source snapshot hashes and retained import hashes. The semantic false pass remains separate.
- Initial offline startup failed because DSH patches replace configuration objects;
  supplying complete adaptive-profile configuration fixed it. Initial formatting-check
  failures and the synthetic export's misleading subscription cost-basis label were
  also retained and corrected. The final local check initially used stale interpreter
  and task-runner paths; the recorded retry uses explicit verified paths and passes.
  No provider calls resulted from these offline failures.

Public evidence: [FINAL_OUTPUT_RESULTS.json](evidence/final-review-2026-11-13/FINAL_OUTPUT_RESULTS.json)
[UI_CHECK.json](evidence/final-review-2026-11-13/UI_CHECK.json) and
[RELEASE_CHECKS.json](evidence/final-review-2026-11-13/RELEASE_CHECKS.json).
The final ledger backup, regression log hash and credential/bootstrap scan are
recorded in the release checks. The backup remains private and owner-readable only.
Private source freezes, raw provider/native traces, artifact hash inventories,
resource samples and semantic reports are under `.qfh-private/adaptive/<attempt>/`,
`.qfh-private/research/servers/<timestamp>/` and `.qfh-private/campaign/wire/`.
UI evidence and command logs are under `.qfh-private/integration/adaptive-001/`.
Credentials and browser bootstrap URLs remain private.

## Browser QA and readiness

Flow: authenticated DSH entry → submit the diagnostic through native chat → view
native worker tasks and the finalized artifact → reload and verify persistence.
The Browser plugin was unavailable; installed Chrome via Playwright was used.
The target origin was `http://127.0.0.1:3080`, with 1440×1000 and 390×844 viewports.

| Check | Result |
| --- | --- |
| Correct page identity and nonblank content | Pass |
| Framework overlay and relevant console errors | None observed |
| Native chat interaction and persisted result after reload | Pass |
| Settings → Models → Research data, exact-version and diagnostic status | Pass; read-only, no new model calls |
| Native task completion matched to the audited artifact | Pass on completed episodes |
| Desktop screenshots | Recorded for every attempt |
| Mobile layout | Existing clipping remains; mobile usability is not accepted |
| Workflow vs semantic status | Reported separately; the false model pass remains a failure |

The corrected unit diagnostics and adaptive repair/skip paths are usable for bounded
development tests. General semantic reliability, unseen open-ended BaoStock research,
heterogeneous model roles, market/news context, evolution/composition and production
operation remain open. A completed chat or even a clean model review is insufficient
for broader acceptance. Final acknowledgment prose in chat is model-generated and
is not the reviewed artifact; only the exact finalized board version carries that
review status. The completed package refuses paid replay and new sessions; the
current browser serves the retained result, not an unrestricted new-trial allowance. Installing the Browser plugin would improve future in-app UI inspection.
