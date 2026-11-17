# Updated semantic guards and the fixed/adaptive rerun

The owner requested a fresh pair using GLM 5.3 at maximum effort under the updated
semantic guards. This is a development workflow test on the same previously seen
186 BaoStock rows, not an unseen case, performance backtest or official acceptance.
The preceding results remain immutable in `STRUCTURED_REPORT_2026-11-17.md`.

## Frozen protocol and acceptance rubric

- Run `semantic-guards-fixed-01`, then `semantic-guards-adaptive-02`, using identical
  source snapshots, data, baseline, question and native root prompt. DSH owns the
  model loop, supervisor and fresh analyst/designer/reviewer child tasks.
- Pin native `zai-coding-cn`, Coding Plan Pro, `glm-5.3`, maximum effort and a 32768
  output-token limit on every request. No provider fallback or new data requests.
- Keep 36 aggregate requests per arm, six work requests per worker, twelve
  supervisor work requests and separate reserved terminal acknowledgements inside
  that aggregate. Retention is valid; do not force an alternative to make a pass.
- The new runtime includes the recorded ambiguous-dispersion and heterogeneous-unit
  guards, plus independent specification-hash and changed-row-count checks. These
  bounded checks do not prove general semantic truth. Record each rejection and
  independently review final and intermediate interpretations separately.
- Before the second arm, require settled usage, native termination and arithmetic
  and evidence integrity. Preserve semantic failure as an experimental outcome.
  Never inject the first arm's results or operator review into the adaptive prompt.
- Record exact request/response usage, output settings, cache counters, per-agent
  work, rolling 60-second dispatch/completion TPM/RPM, native task events, report
  hashes, independent arithmetic, semantic review and sampled machine resources.
- Stop on new unknown usage, quota exhaustion or integrity failure. This authorization
  covers one fresh pair, without an automatic extra pair, old-turn replay, evaluation,
  publication, pool changes or official acceptance.

Before the pair, the original **200 CNY** ledger contains **76.938368 accounted**,
**14.090240 reserved** and **108.971392 unreserved**. The official 20.35 CNY baseline
and the exact old timeout/401 reservations are unchanged. The historical request
allowance is 407 (335 carried plus at most 72 new), and the local conservative-credit
allowance is 9000. The local historical exposure ceiling remains 100 CNY within the
original total. The previous 7500-credit allowance, less 6178.406360 used/reserved
and 802.160640 for a full request reservation, left only 519.433000 usable, below
the last pair's 1042.544430 credits. These estimates are not account quota readings
or incremental Coding Plan invoices.

The native UI flow under test is: fresh DSH chat → submit the frozen prompt once →
native task completion or explicit stop → exact final report tool card → reload.
Browser plugin is unavailable; installed Chrome/Playwright exercises that flow.
Desktop and mobile screenshots are observations, not full mobile acceptance.

Preparation and final checks pass **294 offline tests**, lint/format, JavaScript
syntax and MIT notices. The initial format-check failure is preserved; formatting
was corrected before any live request. Both arms freeze identical **144-file**
snapshots containing the updated guards; no runtime change occurs between arms.

## Fixed arm

The fixed workflow completes in 17 real calls, with 440875 tokens and 4.252920 CNY
conservative exposure. The analyst submits four findings. The designer inspects the
baseline and one volatility-normalized alternative with a ten-observation window,
then retains the baseline. All three native tasks and all acknowledgements complete;
the final report binds zero changed rows. Independent 50-digit Decimal arithmetic,
specification hashes, complete report binding, units, timing and provenance pass.

The longer-window alternative has 52 eligible rows and 51 next-close observations
per symbol, versus 57 and 56 in the baseline. Its maximum-minus-minimum sample-SD
range is 0.6829952553, versus 0.0148334876; its maximum/minimum sample-SD ratio is
1.8045144659, versus 1.5308354614. Both support the direction of the report's claim
that spread did not compress. However, the report names neither aggregate measure.
The explicit-comparison-definition checkpoint remains unmet. This is a specification
clarity gap, not an arithmetic contradiction. The longer window also changes eligible
dates, so these are each-specification sample summaries, not an equal-date test that
isolates normalization. Native model approval does not resolve that gap.

An intermediate finding states “62 - 6 = 57.” The correct formula subtracts five
warmup rows, or adds one after subtracting the six-close window. The host final
counts are correct and do not repeat the false equation, but the designer adopts
the finding as exact warmup accounting without explicitly correcting it. The
independent review preserves this finding/provenance error separately. Neither the
observed new phrase nor the equation triggers the narrow existing grammar guards;
no rejected submission occurs in this arm.

## Adaptive arm

The adaptive workflow completes in 19 real calls, with 561935 tokens and 5.360880 CNY
conservative exposure. Its supervisor assigns design using all four observed finding
references. The analyst proposes the same five-observation normalization window but
incorrectly expects that it will lengthen required history and reduce coverage.
The designer executes one inspection of that exact alternative and compares it with
the existing frozen baseline receipt. Reading that receipt is not a second worker
calculation. The inspection shows unchanged coverage, and the adopted rationale and
finding disposition explicitly correct the earlier expectation.

The adopted candidate changes all 171 non-null scores; the 15 warmup rows remain
excluded. All three native tasks and terminal acknowledgements complete. Independent
arithmetic, report identity and descriptive review **pass with limits**. Both raw
and normalized returns remain dimensionless, the exact denominator includes sample
daily-return SD times sqrt(lookback), and no improved comparability, alpha or
systematic-risk removal is claimed. The phrase “units of its own recent daily-return
dispersion” is statistical rescaling, not a physical-unit change; the same hypothesis
explicitly states that both scores are dimensionless. All inspected data are development
data. Neither an unseen-case result nor an investment result is established.

This is a real correction of a peer's mistaken expectation during design. It is not
a failed-review/repair/re-review cycle: the real topology remains analyze/design/review.
No rejected tool submission occurs in either arm. The existing semantic guards are
present in both live runtimes, but no known guard rejection is triggered. Their
offline counterexample tests pass; these runs do not prove that the grammar catches
all equivalent claims.

## Visible usage reporting and UI checks

Both model final chat summaries incorrectly say **eight of twelve work requests
used**. The settled supervisor ledger contains **nine work requests plus one terminal
acknowledgement** in each arm. The number eight comes from the last `case_board`
snapshot, before the subsequent `finalize_case` work request. The models repeat the
stale value after completion, expanding beyond the requested final ID/status text.
The shared budget admission and independent post-drain totals remain correct.
This is a visible reporting error, recorded separately from the pinned research report.

The native footer is also root-session-only: 245352 fixed and 267761 adaptive tokens,
versus 440875 and 561935 for their full teams. A reliable owner summary must be rendered
from the settled host ledger, explicitly distinguishing work, acknowledgement and team
totals. Asking the model to restate a prior snapshot cannot ensure current accounting.

Installed Chrome at 1440×1000 and 390×844 verifies page identity, meaningful content,
no framework overlay or console errors, the one native submission per arm, completion
and reload. Read-only reopening confirms both full rendered reports equal their host
text byte for byte. Screenshots show the report in a compact scrollable tool card;
report discovery and full mobile navigation remain open. One read-only inspection
initially opened an empty root page because session selection is not encoded in that
URL; it timed out without a submission, then succeeded by selecting the existing
sidebar session. An early second-server preflight also ran before its asynchronous
manifest existed; a later read verified both snapshots before adaptive submission.
These operator attempts remain in the evidence, with no paid resubmission.

## Measurements and budget

| Arm | Calls | Tokens | Exposure CNY | Input cache | Peak dispatch RPM / TPM | Wall time | Peak shared RSS |
| - | -: | -: | -: | -: | -: | -: | -: |
| Fixed | 17 | 440875 | 4.252920 | 68.48% | 5 / 157996 | 691.31 s | 642.5 MiB |
| Adaptive | 19 | 561935 | 5.360880 | 71.17% | 5 / 175478 | 736.10 s | 610.0 MiB |

All **36 requests settled**, totaling **1002810 tokens**, **69.99% input cache hits**,
**9.613800 CNY** conservative exposure and **827.996760** conservative credits.
Every request/response is GLM 5.3, with max effort, enabled thinking and the frozen
32768 output cap. There are no new unknown charges, DeepSeek/fallback calls or new
data requests. The rates assign whole-call tokens to dispatch/completion timestamps,
not per-token arrival. Peak completion totals are 5 RPM / 219417 TPM across the pair.

The measured shared guard/DSH/data process tree peaks at **642.5 MiB RSS** and
**0.2106 sampled CPU cores**, with zero swap. Mean CPU is 0.0280 fixed / 0.0368 adaptive
cores; minimum host available RAM is 10.36 GiB and Work free space is 334.71 GiB.
The Mac has 18 logical CPUs and 36 GiB RAM. Host readings include concurrent work;
short-lived children and boundary intervals may be missed. This is not a capacity
benchmark. Full per-agent work, costs, TPM/RPM, cache and resource windows are in
[METRICS.md](evidence/semantic-guards-2026-11-17/METRICS.md).

The original **200 CNY** ledger now reconciles to **86.552168 accounted**,
**14.090240 reserved** and **99.357592 unreserved**. The official 20.35 CNY baseline,
5.242880 CNY old 401 reservation and 8.847360 CNY exact unknown timeout reservation
remain unchanged. Historical GLM use is 371 attempts (369 settled and the two old
reserved attempts), with 7006.403120 conservative used/reserved credits against
407 attempts / 9000 credits. Exposure estimates are not incremental subscription
invoices or account-quota readings. The pair is complete; no further paid retry is
scheduled.

Adaptive uses 27.5% more tokens in this pair and makes more evidence-page reads.
Its reviewer uses four requests versus two in the fixed arm. The arms inspect
different alternatives and reach different decisions; this single sequential,
previously seen case does not identify a causal workflow-efficiency difference.

## Evidence and next checkpoint

[SUMMARY.json](evidence/semantic-guards-2026-11-17/SUMMARY.json) reconciles usage,
budgets, source/input equality and outcomes. Each arm preserves request/response
hashes, native task evidence, exact reports, comparison calculations and independent
arithmetic/semantic review. The binding audit verifies immutable task targets and
unchanged model content. Exact-ID isolation finds none of 23 first-arm event/child
IDs in adaptive requests; no operator review was injected. That is a concrete
isolation check, not proof against every semantic leakage mechanism.

The **complete clean-pair checkpoint remains open**. Native completion, correct
calculations and a clean model verdict are insufficient: the fixed final comparison
is undefined, one accepted finding has wrong arithmetic, and both visible summaries
reuse a stale request count. The adaptive final research artifact passes with limits;
that does not validate every preceding or surrounding model sentence.

Next move comparison definitions and derived finding counts into typed records:
bind left/right inspection IDs, name the statistic and observation cohort, and render
the supported comparison from those records. Findings should reference host-derived
count facts instead of re-deriving arithmetic in prose. Add a host-generated team
usage summary after final settlement. Verify these focused contracts before another
clean-pair check, then isolate parent-child evolution and released-report/version
matching. No production or official acceptance is claimed. Keep PR 22 draft and
unmerged; broader unseen cases, recovery, role routing, market context, independent
evaluation/release gates, deployment/load/security and owner UX remain separate work.
