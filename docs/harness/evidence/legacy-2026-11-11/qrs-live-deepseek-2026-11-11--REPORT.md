# Real DeepSeek end-to-end campaign

**Bounded live pilot completed on 11 November 2026.** Sixteen real generation
executions are retained: eight PASS, six PARTIAL, one FAIL and one RECOVERED.
The final three consecutive generations passed execution checks on source
`6de2fad3570b25d80d3fbceda64e16b02635e34b`, meeting the predeclared pilot target.
All six roles performed real DeepSeek inference, and the final export passed
all 23 accounting/evidence checks. Earlier failures remain in the record.

| Final measurement | Observed result |
|---|---:|
| New DeepSeek chat requests | 878, including 24 startup probes and five focused replay requests |
| Input / output tokens | 7,013,359 / 1,130,183 |
| Total tokens | 8,143,542; reported reasoning is already included in output |
| Input cache hit rate | 69.90% (4,902,144 cached input tokens) |
| Peak rolling RPM | 32 |
| Peak rolling TPM, dispatch / completion attribution | 289,044 / 287,368 |
| Configured concurrency ladder / actual peak overlap | 1 → 2 → 4 / 3 |
| Cumulative conservative budget charge, including six earlier calls | **56.256735 CNY / 200 CNY** |
| Remaining allowance / unresolved reservations | **143.743265 CNY / zero** |
| New-call tariff estimate with reported cache and price window | 19.96343224 CNY; excludes six earlier calls; not invoice verified |
| Peak sampled simultaneous campaign-container memory within generation windows | 1.634 GiB on the small synthetic fixture |

The research job was paused through its normal interface after the pilot target
was reached. All owned test services and the resource monitor are stopped; data
and volumes are preserved. The interactive architecture preview remains available.
The job's requested five qualifying factors were not achieved. This pilot establishes
live software execution, not full scientific release acceptance or production capacity.

Final machine-readable state is in `STATE.json`; the measured generation and
resource tables are in `RESULT_TABLES.md`. `METRICS.json`, `GENERATIONS.json`,
`PHASES.json`, `LOCAL_TOOL_EVIDENCE.json` and `SCIENTIFIC_RESULTS.json` retain
the distinctions between calls, software outcomes and research outcomes.

## Scope and evidence

The owner authorized DeepSeek for all six roles, including the critic, within the
original cumulative **200 CNY** API budget. Six earlier calls account for 0.014883
CNY of that budget. The concurrency ceiling is 500; the measured ladder starts at
one and increases only after review. This is a live model pilot on a small synthetic
market-data snapshot, not a test of 500 simultaneous requests or a claim of alpha.

The production research worker, generation runner, role runners, provider classes,
research tools, registry, independent evaluator and released-feedback API are used.
The private harness adds schedule admission, an independent spending guard and
observation. It supplies no scripted hypotheses, candidates, criticism or final
answers. Offline tests use their usual mock models and are counted separately.

The worker first admitted paid work after 12:00 Beijing on 11 November 2026. The
14:00–18:00 pause was observed: the preceding generation ended at 13:57:53, and the
next paid request began at 18:00:32. The pause audit, request log and budget snapshots
are retained. Current generations may drain after an admission pause; a pause never
manufactures an incomplete request's cost or silently discards its reservation.

Research sees the 77-instrument, 389-date, 29,450-row snapshot ending 2011-06-30.
The evaluator's full synthetic fixture has 80 instruments, 700 dates and 52,684
rows. Snapshot IDs, source revisions, profile/prompt hashes, commands, container
images, UTC timestamps and Beijing timestamps accompany the raw evidence.

The engineer uses DeepSeek V4 Flash with thinking disabled; the other five roles
use V4 Pro with high reasoning. Flash still performs model inference. The test's
same-provider critic exception is explicit and isolated; the normal diversity rule
remains the default. Inactive provider catalog entries are not active routes or
evidence that another provider was called.

## What a generation means in this test

A real generation is a persisted sequence greater than zero with execution start
and end timestamps and actual recorded model calls. Empty seed bookkeeping at
sequence zero is excluded. A generation can contain several research tasks; each
task can invoke multiple roles, and each role can make several model requests and
tool calls. Counts of generations, agent runs, HTTP requests, tool calls and
publications therefore differ. Focused paid regression replays are counted as API
requests but never as new generations or publications.

`GENERATIONS.json` joins every completed execution to its actual requests, role
outcomes, task summary, publication IDs and resource samples. It preserves failed
executions. `METRICS.json` gives cumulative and per-stage, job, generation, role and
model measurements. The per-rung `RESULT.json` files join those figures to released
reports and the database export used to establish them.

## Failures, changes and retests

| Finding | Action and evidence | Interpretation |
|---|---|---|
| Deployed research snapshot root was not resolved to the pinned snapshot | Source `5f69cc9`; snapshot-boundary and hash validation plus deployment retest | Preparation defect repaired before live research |
| An interrupted brief submission could remain stranded | Source `ab9fe6c`; stable IDs, persisted seed manifest and resumable initialization | Original brief recovered through the normal API; no database row edits |
| Host/Linux access to the campaign SQLite ledger caused an I/O error after a successful response | Worker-only SQLite access, explicit connection closure, DELETE journal and atomic JSON observations; exact saved usage reconciled | First generation remains failed; its cost was recovered, not erased |
| Reasoning exhausted a 4,096-token output cap before a structured answer | Private draft and review caps increased to 8,192 after drain; plan and interpretation remain 16,384 | Real profile limitation; failed attempts retained |
| Research tools could consume all request allowance before an answer | Sources `d9d22b5`, `67961d8`, `3f9197d`; explicit finishing instructions and answer/validation slots within the original request cap | A one-call paid replay still failed; a later bounded replay succeeded in two calls |
| Tool-to-prompted-output fallback reset per-role usage | Source `1661cc6`; one shared `RunUsage` across modes | Live critic overruns of its role request cap were reproduced offline and repaired; the independent monetary cap still accounted for every request |
| A stale proposed tool batch after 20 used tools aborted a role before final output | Source `7d5c2e5`; preserve explicit unexecuted tool refusals, close research tools and finish within remaining original request allowance | Paid replay reproduced two stale calls, refused both, then returned two valid drafts; two new API requests, no new tool executions |
| Agent summaries labelled conservative peak charges with the wall-time off-peak period | Source `0908902`; use the same upper-bound quote policy for accounting metadata | Peak control passed and off-peak regression failed before correction; 17 focused and 1,367 full offline tests plus static checks passed afterward |
| A valid 1,631-character draft change summary exceeded the manifest's 600-character contract and stranded publication | Source `6b8ef55`; bound the manifest excerpt with an explicit full-trace reference, retaining the original evidence | Factor and strategy failures reproduced; 10 focused and 1,370 full offline tests plus static checks passed; real publication retry succeeded with zero additional API calls |
| Best-effort delivery claimed zero qualifying versions while listing an advanced factor | Source `6de2fad`; count included versions at or above the requested tier and state the minimum | 3 pre-fix failures reproduced; 29 focused and 1,374 full offline tests plus static checks passed; saved-live-record rendering passed with no API calls or historical edits |

The tool-batch change passed **32 focused tests**, the complete Linux ARM64
nonbenchmark suite (**1,365 passed, zero skips; six benchmarks deselected**) and the
repository static checks. The pre-fix reproduction failed in five cases as recorded.
These results test the code and invariants; they are not live model generations.
Detailed before/after evidence is in `private/fixes/`, immutable command records in
`private/runs/`, and source/harness/profile snapshots in `private/revisions/`.

The 18:00 paid tool-limit replay restored the failed engineer's seven saved model
responses and 20 completed tools. It used the production role runner, original
limits and the cumulative campaign spending guard. Its result ended at nine of
twelve requests and twenty of twenty tools. The 0.048678 CNY conservative charge
is included in campaign spending. It produced schema-valid drafts only; it did not
publish a factor, modify the failed original run or prove scientific quality.

## Measurement definitions and limits

The independent guard reserves each request at the configured full input context
and peak cache-miss/output prices before network dispatch. Settlement conservatively
prices all reported input tokens as peak cache misses. Pending or unknown charges
remain reserved. A separate tariff estimate uses reported cache hits and the
applicable price window. Production accounting, the conservative campaign charge
and the tariff estimate are distinct. **None is an invoice-verified account balance.**

RPM counts real chat-completion dispatches in rolling 60-second windows. TPM counts
reported input plus output tokens, attributed to either request dispatch or response
completion; both series are retained. Nonstreaming responses do not provide the
time at which each token was generated. Reasoning tokens are a subset of output
tokens and are not added twice. Cache hit rate is cached input tokens divided by
total input tokens, weighted by tokens rather than averaged across requests.

Resource summaries distinguish host activity, simultaneous sampled campaign
container memory, and per-container lifetime cgroup peaks. Host activity can include
unrelated applications and recorded offline CI runs. `GENERATIONS.json` restricts
samples to actual generation start/end windows; rung totals can include idle and
scheduled waiting. A manually stopped container's exit 137 alone is not proof of
an OOM; cgroup evidence must support that conclusion.

The research worker is capped at one CPU and 768 MiB; the evaluator at one CPU and
1.5 GiB. The actual Mac has 18 CPUs and 36 GiB, and its shared Docker VM has 18 CPUs
and about 7.75 GiB. These small-fixture observations do not establish a whole-VM
minimum, full-CN memory needs, simultaneous maintenance capacity or throughput at
the 500-request ceiling. The earlier full-CN resource ladder remains separate.

The supervisor request beginning 18:02:25 completed in 219.33 seconds with HTTP 200:
9,237 input tokens and 14,063 output tokens, including 12,587 reasoning tokens.
The succeeding generation then continued into development and critic review.
This is observed latency and usage, not a provider throughput guarantee.

## Scientific acceptance remains separate

Published factors are evaluated by the independently polling evaluator. Research
reads only released feedback. Critic rejection, zero publications and failed W2
results are legitimate recorded outcomes; no gates were lowered to obtain a pass.
No owner approval, pool promotion, acceptance decision or trade is fabricated.

The earlier offline SC1 and SC2 failures are retained in
`../qrs-remediation-2026-11-10/REMEDIATION_REPORT.md`. Real inference in this campaign
does not convert the earlier scripted 50-generation null fixture into a live run or
satisfy its missing 500-publication exposure. This pilot must not be described as
full release acceptance or completion of every scientific benchmark.

## Interactive architecture

The source-checked interactive map is saved in `private/architecture/` and opened
in the app's browser. Its four views cover system boundaries, a generation, data
and evaluation, and budget controls. Selecting a component highlights related
connections and explains its role. Its displayed run figures are explicitly a
14:14 Beijing snapshot; the map performs no API calls or system-control actions.

## Completed generation: 18:18 Beijing

J5 generation 2 completed in 984.03 seconds on source `7d5c2e5`. All six tasks
and twenty agent runs completed successfully: one supervisor, three hypothesis,
eight engineer and eight critic runs. The supervisor produced the accepted plan
without deterministic fallback. There were 77 real HTTP requests, 682,117 tokens
(570,583 input, 111,534 output), 74.52% token-weighted input-cache hits, 14 peak
rolling RPM and 131,837 peak dispatch-attributed TPM (134,274 at completion).
There were no truncated responses, role request overruns or unresolved charges.

It produced eight hypotheses and nine candidates. Seven candidates were rejected;
the two critic-approved candidates failed the existing deterministic prescreen:
similarity 0.97355 against a maximum 0.9, and RankIC 0.01447 against a minimum 0.015.
There were no publications. This is a successful execution with no qualifying
scientific output. Its conservative API charge was 4.665120 CNY; the separate
cache/off-peak tariff estimate was 1.7100896 CNY. Cumulative conservative spending
was 22.908666 CNY including the six original requests.

During its actual execution, 197 host/container samples recorded a simultaneous
campaign-container memory peak of 1.589 GiB and zero host swap use. Host CPU median
was 3.32%, maximum 10.94%; these percentages include other host activity. Raw
samples and per-container counters are preserved in the generation evidence.

The drained export passed the independent HTTP/ledger audit. All 396 new dispatches
plus the six prior calls reconcile to the cumulative charge. Five new calls are
focused paid replays; 391 correspond to production model requests. Production also
has one zero-usage, zero-cost refusal that never reached HTTP and is not counted as
an API request. The first failed generation's saved response remains explicitly
marked as recovered: its exact usage is known, but original latency and HTTP status
were not recorded. It is not silently treated as a normal successful generation.

Evidence: `private/rung3/generation2-after-tool-fix/`,
`private/exports/20261111T101832Z-rung3-generation2/reconciliation.json`, and
`private/runs/AUDIT-20261111T102247880616Z-rung3-generation2-reconciliation/`.
The initial audit helper assumed every request had `measurement.json`; its first
invocation stopped on the already documented recovered request. It now explicitly
validates `measurement-recovered.json` and the saved response hash for that case.

## Completed generation: 18:28 Beijing

J5 generation 3 completed in 567.41 seconds on source `7d5c2e5`: three tasks and
fifteen agent runs completed successfully. One hypothesis response reached its
output cap; the configured recovery completed the role within its original limits.
There were 63 real requests and 666,984 tokens, 67.56% input-cache hits, 17 peak
rolling RPM, 171,534 peak dispatch TPM and 185,050 peak completion TPM. Conservative
cost was 3.942337 CNY, bringing the cumulative charge to 26.851003 CNY with no open
reservations. The separate tariff estimate for this generation was 1.35449394 CNY.

The generation published version `01a1ca27-3f49-70c6-93b6-74484fd449bf`. Independent
evaluation completed and recorded `W1GateFailed`; the released feedback flags
`COST_DOMINATED` and `WEAK_SIGNAL`. It does not proceed to W2. The other eight
candidates were rejected or not selected. Scientific gates remain unchanged.

All 21 independent reconciliation checks passed for the drained export:
`private/exports/20261111T103006Z-rung3-generation3/`. Per-generation results are in
`private/rung3/generation3-before-cost-label-fix/`. The next normal generation uses
the corrected cost-period label and can consume this program's released feedback.

## Recovered generation: 19:03 Beijing

J5 generation 4 completed all twelve agent runs across all six roles, then failed
its first deterministic publication attempt because a selected candidate's valid
draft explanation was longer than the manifest contract allowed. Its first plan
also required the configured repair: it proposed an unavailable repair task and
an ineligible parent; the second plan passed validation. Four tasks completed,
including one deterministic syntactic variant and three tasks that invoked LLMs.

The manifest repair resumed the same generation's PUBLISHING stage. It published
factor `01a1ca46-c320-76ab-b8dd-600df9557e3a` and note
`01a1ca46-c32d-719c-9336-e398ef53a6d8`, with zero further API calls. The original
candidate payload, engineer record and all 158 preceding trace steps matched their
saved pre-retry contents. The registry manifest holds a 600-character excerpt with
an explicit reference to the full 1,631-character explanation in the trace.

The factor independently passed W1 and W2; released W2 status is `PASS`, ladder
status `IMPROVED`, followed by `ADVANCED`. The note passed with all twelve claims
matched to its released citation. These are outcomes on the synthetic fixture;
there is no owner pool approval or real-money activity.

This recovered generation used 43 real requests and 574,144 tokens, 58.92% input
cache hits, 18 peak rolling RPM and 179,935 peak dispatch TPM (199,541 completion
TPM). Conservative cost was 5.291568 CNY; the separate tariff estimate was
1.87444576 CNY. The first active attempt lasted about 14.45 minutes. The full
persisted generation span was 26.86 minutes, including the offline repair pause;
its attempt-level resource window is preserved separately to avoid attributing
that repair time to model performance. Inference used `0908902`, and the successful
deterministic publishing retry used `6b8ef55`.

The drained reconciliation passed, including checks that persisted agent token
counts match HTTP usage and that the corrected cost-period labels match actual
settlement labels. Cumulative conservative charge remained **32.142571 CNY**,
with 502 new requests plus the original six and no pending reservations. Evidence
is in `private/rung3/generation4-publication-retry/`,
`private/rung3/generation4-recovered/`, and
`private/exports/20261111T110418Z-rung3-generation4-recovered/`.

## Completed generation and job: 19:24 Beijing

J5 generation 5 ran from 19:05:32 to 19:22:41 on source `6b8ef55`: four tasks
and twenty agent runs across all six roles succeeded. It made 93 real requests,
used 957,603 tokens, achieved 68.46% input-cache hits and observed two concurrent
requests, 17 peak rolling RPM, 183,056 dispatch TPM and 183,956 completion TPM.
Two capped responses recovered within the original role limits; no request
overruns, HTTP errors or unresolved charges remained. Conservative charge was
5.734833 CNY; the separate tariff estimate was 2.14523026 CNY.

Eight candidates were rejected by review. The two remaining candidates failed
the unchanged prescreen similarity ceiling (both about 0.987 versus 0.9); one also
failed originality. No factor was published. The note passed, with all twelve
claims matched against two released-report citations. Its 205 resource samples
showed a 1.566 GiB simultaneous campaign-container memory peak, host CPU median
3.17% / maximum 9.94%, and no host swap use.

A subsequent normal monitor tick used no model calls and closed the job after
its five-generation cap, assembling a best-effort deliverable. The requested four
qualifying factors were not achieved: one factor reached advanced and the other
failed W1. The existing close-decision enum is `budget_exhausted`, encompassing
the generation budget here; the monetary budget was not exhausted. A reporting
defect incorrectly described this partial success as zero versions meeting the
tier. The original immutable deliverable is retained, and its corrected rendering
is separately recorded under `private/fixes/deliverable-summary/`.

Both drained exports reconciled successfully. Cumulative conservative spending
was 37.877404 CNY for 595 new requests plus the original six, with no open
reservations. Evidence: `private/rung3/generation5-reviewed/` and
`private/exports/20261111T112520Z-rung3-final/`.

The earlier J4 note `01a1c90f-8e59-720f-8187-af4b31f61a97` failed independent
note validation with `UNDISCLOSED_WINDOW`, despite all twelve individual claims
matching its citations. It remains a failed note; the two later notes passed.
Claim matching alone is therefore not reported as note acceptance.

## Larger concurrency rung: first generation

J6 generation 1 completed at 19:42:17 Beijing on `6de2fad`, in 605.86 seconds.
Four tasks and 20 agent runs succeeded; 95 chat requests (including four startup
probes) used 841,149 tokens. Configured concurrency was four, while the largest
observed overlap was three. Peak rolling RPM was 32; dispatch TPM 289,044 and
completion TPM 287,368. Cache hits covered 70.18% of input tokens. There were no
output truncations, failed HTTP requests, role overruns or unresolved charges.

It produced six hypotheses and eleven candidates: nine rejected, one not selected,
and one published. Factor `01a1ca6a-76a1-75c4-9461-490ca0b9fafa` failed independent
W1 with COST_DOMINATED, DECAYS_FAST and WEAK_SIGNAL. No W2 was run for it.
The unchanged gates prevented an out-of-sample failure from advancing.

The 121 execution-window resource samples showed a 1.592 GiB simultaneous container
memory peak and no host swap use. Conservative charge was 4.522813 CNY, with a
separate 1.5561905 CNY tariff estimate; cumulative conservative charge 42.400217 CNY.
All 23 accounting/evidence checks passed. Evidence: `private/rung4/generation1-reviewed/`
and `private/exports/20261111T114317Z-rung4-generation1/`.

This is a natural research workload with changing task mix and candidate limits;
it is not a controlled speedup benchmark or a 500-concurrent-request capacity test.
The predeclared pilot target was three consecutive clean executions, maximum ten,
with review between admissions (`private/rung4/REVIEW_CRITERIA.json`).

## Larger concurrency rung: final two generations

J6 generation 2 completed at 19:57:48 Beijing in 825.66 seconds. Four tasks and
21 agent runs across all six roles succeeded. Its 83 requests used 838,595 tokens,
with 67.95% input-cache hits, peak overlap three and 23 peak rolling RPM. It
published three factors: two failed W1 and one passed W1 but failed W2. The note
passed all eleven claims against its released citation. Conservative charge was
5.269176 CNY. The 165 resource samples showed a 1.596 GiB simultaneous container
memory peak, host CPU median 3.39% / maximum 8.92%, and zero host swap use.

J6 generation 3 completed at 20:29:53 Beijing in 1,744.61 seconds. Four tasks and
27 agent runs across all six roles succeeded. Its 105 requests used 1,099,129 tokens,
with 60.93% input-cache hits, peak overlap three and 23 peak rolling RPM. Two output
truncations recovered within the original allowances; there were no request-cap
overruns or unresolved charges. Nine candidates were rejected, one was not selected,
and one was published. The factor passed W1 and failed W2; the note passed all
36 claims against four released citations. Conservative charge was 8.587342 CNY.
The 349 resource samples showed 1.634 GiB simultaneous container memory, host CPU
median 3.53% / maximum 10.76%, and zero host swap use.

Both generations passed all 23 accounting/evidence checks. Their reviews are in
`private/rung4/generation2-reviewed/` and `private/rung4/generation3-reviewed/`.
The final quiescent export includes the last five released reports, which arrived
after generation 3 closed. Research had consumed 37 of the 42 final released
reports before pausing; these final five were not consumed by another generation.

## Performance findings and sizing limits

The last generation spent 682.42 seconds in feedback synchronization, 204.72 seconds
planning and 857.40 seconds developing. Source inspection confirms that feedback
is grouped by artifact version and each analyst/reviewer pair runs sequentially.
The three pairs here handled three different earlier artifacts; they were not
three revisions of one interpretation. Raising the provider concurrency ceiling
alone does not parallelize this phase. A future optimization should preserve the
deterministic merge and evidence boundaries before changing this order.

Flash accounted for 545 requests and 5,057,280 tokens; its observed median/p95
latency was 1.91/8.13 seconds. Pro accounted for 333 requests and 3,086,262 tokens;
its observed median/p95 was 32.14/96.32 seconds. Roles, prompts, output sizes and
thinking settings differed, so this is not a controlled model comparison. The
observed workload did not approach the authorized 500-request ceiling.

The monitor retained 6,170 samples from first dispatch through shutdown. No OOM
events or kills appeared in the 31 observed container-instance counters, and host
swap remained zero. The overall sampled simultaneous container peak was about
1.635 GiB, versus 1.634 GiB inside actual generation windows. These sampled working
sets differ from lifetime cgroup peaks: the final worker reached 238,194,688 bytes
and the evaluator 292,294,656 bytes. Five-second sampling can miss brief spikes.
CPU throttling and disk I/O counters remain in the raw resource evidence.

Host CPU reached 99.04% at one point across the entire observation period, which
also included offline CI and other applications; it cannot be attributed to the
live pilot. The generation-window measurements are the useful comparison. At the
12:32 UTC disk snapshot, the campaign directory allocated 839,294,976 bytes,
including about 559 MB of repeated evidence exports. This excludes shared Docker
images and volumes; nested directory totals must not be added twice.

The earlier full-CN ladder remains the relevant large-data evidence: 4.5 GiB
evaluator caps completed three identical fresh W1 replays, with cgroup peaks
4.41/4.11/4.17 GiB, while smaller tested caps failed. The prior provisional serial
allocation remains **8 vCPUs, 8 GiB RAM and 200 GiB disk**, with the configured
6 GiB per-evaluator headroom. This live test did not resize the shared VM to eight
vCPUs or validate two full-CN evaluators plus maintenance. The draft's 24 GiB
production expectation remains unverified under combined load. See the separate
`../qrs-review-2026-11-10/RESOURCE_RECOMMENDATION.md` for the complete ladder.

## Final outcomes and remaining acceptance work

Ten factors were published: six passed W1, one passed W2 and reached Incubating,
five ended W2Failed, and four ended W1GateFailed. Five research notes were
published: four passed independent note checking and one failed. Incubating is
not owner acceptance. No pool entries were approved, no acceptance cases were
fabricated, and no real-market trades were made. This factor-mode pilot did not
exercise live strategy publication.

The final code passed **1,374 Linux ARM64 nonbenchmark tests, zero failures or
skips, with six benchmarks deselected**, plus repository static checks. The changes
are committed locally on `codex/qrs-live-deepseek`; nothing was pushed or merged.
Scientific acceptance SC1 and SC2 remain FAIL in the earlier remediation report.
Long-run incubation, the null benchmark's required exposure, live strategy research,
and combined production-load sizing remain open. The three clean executions do
not establish those results.

The local tool trace contains **1,367 actual invocations**: 374 DSL validations,
288 workbench evaluations and 705 other research reads/searches/explanations.
There were 1,262 successful outcomes and 105 failed outcomes, including validation
rejections and returned errors. Unexecuted stale tool refusals are not counted as
executions. These local computations and deterministic gates complement the real
model calls; they do not themselves consume model tokens.

## Final reconciliation, provenance and cleanup

Final export: `private/exports/20261111T123213Z-pilot-final/` (93 tables, logs and
a Linux-made independent ledger backup). Its `reconciliation.json` passes all
23 checks, including source/table hashes, DeepSeek-only routing, schedule,
reservations, original spending, token tuples and latest-generation cost labels.

The independent guard contains 884 cumulative calls: 878 new plus six original.
The production ledger contains 874 records: 873 dispatched production requests
and one zero-cost nondispatch refusal. Five focused replay calls appear only in
the independent campaign ledger, and the original six are carried forward there.
Production cost, 39.845085 CNY, uses its conservative peak-price policy with cache;
the independent guard uses peak cache-miss prices for all input and totals
56.256735 CNY including the original six. These different scopes and policies
explain the different amounts. None is an invoice-verified bill.

All new requests have known usage and settled charges. One recovered response
from the initial SQLite failure lacks its original HTTP status and latency;
its saved response hash and exact usage were recovered. The other 877 recorded
HTTP statuses were successful. Fourteen historical responses finished at their
output limit, and all failed executions remain visible.

`SOURCE.tar`, `SOURCE.patch` and `SOURCE_PROVENANCE.json` identify the final tested
source and frozen harness/profile. Per-revision archives preserve the earlier
tested versions. `SECRET_SCAN.json` records the exact authorized-key and local
credential scan; operational `.env`, caches, Git metadata and symlinks are excluded.
It is an exact-value scan, not a general certification that arbitrary secrets
cannot exist. `MANIFEST.sha256` hashes the retained evidence and scan result.

`private/rung4/PILOT_PAUSE.json` records the normal job pause at 20:31 Beijing.
`private/finalization/CLEANUP.json` confirms both owned Compose projects and the
monitor stopped, with all data volumes retained and no pending paid work. Manual
shutdown exit codes are recorded separately from OOM flags. The architecture
preview remains available. Future continuation must retain the original cumulative
budget and paused job history; a restart must not reset either.

## Evidence index

- [Generation and resource tables](</Volumes/Work/Evolutionary Supervised ShareInfo Quant Factor Research Agent Team/qrs-live-deepseek-2026-11-11/RESULT_TABLES.md>)
- [Provider and machine measurements](</Volumes/Work/Evolutionary Supervised ShareInfo Quant Factor Research Agent Team/qrs-live-deepseek-2026-11-11/METRICS.json>)
- [Outcome checklist and limitations](</Volumes/Work/Evolutionary Supervised ShareInfo Quant Factor Research Agent Team/qrs-live-deepseek-2026-11-11/OUTCOME.json>)
- [Phase timings](</Volumes/Work/Evolutionary Supervised ShareInfo Quant Factor Research Agent Team/qrs-live-deepseek-2026-11-11/PHASES.json>)
- [Scientific outcomes](</Volumes/Work/Evolutionary Supervised ShareInfo Quant Factor Research Agent Team/qrs-live-deepseek-2026-11-11/SCIENTIFIC_RESULTS.json>)
- [Source provenance](</Volumes/Work/Evolutionary Supervised ShareInfo Quant Factor Research Agent Team/qrs-live-deepseek-2026-11-11/SOURCE_PROVENANCE.json>)
- [Credential scan](</Volumes/Work/Evolutionary Supervised ShareInfo Quant Factor Research Agent Team/qrs-live-deepseek-2026-11-11/SECRET_SCAN.json>)
- [Evidence checksums](</Volumes/Work/Evolutionary Supervised ShareInfo Quant Factor Research Agent Team/qrs-live-deepseek-2026-11-11/MANIFEST.sha256>)
