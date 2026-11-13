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

- [ ] Freeze and independently audit the owner's completed trial.
- [ ] Add an append-only campaign provider restriction, checked atomically with
  every reservation; continue settlement of already dispatched requests.
- [ ] Activate a bounded GLM development allowance without the old clock cutoff.
- [ ] Implement a standalone shared-state module: source-linked findings,
  immutable candidate versions, explicit review decisions and stale-write refusal.
- [ ] Test missing citations, unauthorized actors, stale parents, conflicting
  findings, cross-episode references, restart and concurrent writers offline.
- [ ] Run a small real GLM author/reviewer/revision demonstration on a labeled
  diagnostic fixture. Keep the answer key outside the model workspace and prompt.
- [ ] Compare a feedback-enabled revision with a feedback-disabled control from
  the same initial candidate and evidence, with equal request/output ceilings.
- [ ] Record actual evidence → contribution → decision → revision, unsuccessful
  cases, costs, tokens, cache, dispatch/completion rates and machine usage.
- [ ] Update capability limits, roadmap, README and draft PR; keep it unmerged.

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
