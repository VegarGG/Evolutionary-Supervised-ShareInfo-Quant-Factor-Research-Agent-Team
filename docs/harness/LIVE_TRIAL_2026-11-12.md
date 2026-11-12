# First real native-team trial — 12 November 2026

**Result: failed at the researcher-report boundary. DSH is available for
inspection, but the complete three-role workflow is not yet accepted for owner
research trials.** This was actual DeepSeek inference and a real BaoStock query.
The reviewer never ran and no draft was recorded. The failed trial has not been
relabelled as a success after the offline fix.

Scheduled continuation woke at 18:00:19 Beijing. The first model request started
at **18:01:22.844**; the last finished at **18:02:32.620**. The 69.78-second run
used the exact `deepseek-flash` ID for every request. All seven provider requests
settled within the authorized window. No second paid trial or worker replay ran.

## What each agent actually did

| Agent | Observed work | Outcome |
|---|---|---|
| Supervisor | Read the scope, assigned a researcher, received a rejected-report error and stopped | Three model requests; no reviewer assignment, adoption decisions or draft |
| Researcher | Read the scope; fetched ten daily BaoStock closes; called the deterministic descriptive-metrics tool; proposed a five-lag reversal idea and described limitations | Four model requests; an 8,998-character final report was retained but rejected because it was wrapped in a Markdown JSON fence |
| Reviewer | Not activated | Zero requests, tokens or cost; no independent critique occurred |

The researcher did real work. A report-format failure does not mean inference or
data access was absent. The supervisor's final statement that no market data or
arithmetic occurred is contradicted by the worker events and retained data wire.
Its claim of a 20-request *market-data* allowance also confused the model-request
cap with the separate data quota. Host records, not the model's recap, determine
usage and completion.

## Inference, cache and cost

| Agent | Requests | Uncached input | Cached input | Output, including reasoning | Total tokens | Input-cache hit | Tariff estimate, CNY | Conservative debit, CNY |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Supervisor | 3 | 2,804 | 4,992 | 2,211 | 10,007 | 64.03% | 0.01174784 | 0.033280 |
| Researcher | 4 | 4,390 | 9,984 | 6,693 | 21,067 | 69.46% | 0.03136168 | 0.082292 |
| Reviewer | 0 | 0 | 0 | 0 | 0 | N/A | 0 | 0 |
| Team | **7** | **7,194** | **14,976** | **8,904** | **31,074** | **67.55%** | **0.04310952** | **0.115572** |

Cache hit rate is cached input divided by total input, weighted by tokens. Cache
creation was zero. These are provider-reported usage counts, not the fixture
values from earlier software tests or the selected-session DSH footer.

| Agent | Peak dispatch RPM | Peak dispatch TPM | Peak completion RPM | Peak completion TPM |
|---|---:|---:|---:|---:|
| Supervisor | 3 | 10,007 | 2 | 5,235 |
| Researcher | 4 | 21,067 | 4 | 21,067 |
| Reviewer | 0 | 0 | 0 | 0 |
| Team | **7** | **31,074** | **6** | **26,302** |

Rates are maxima over rolling 60-second windows, assigning each whole request's
token count to its dispatch or completion timestamp. They are not measurements
of individual token-arrival throughput or a saturation benchmark. Execution was
sequential, with at most one provider request in flight.

The tariff estimate uses measured tokens and the
[official Flash off-peak rates](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/),
rechecked on the trial date: CNY 1/M uncached input, 0.02/M cached input and 4/M
output. It is **not an invoice**. The separate ledger deliberately charges a
conservative estimate against the original cap.

Two read-only [account-balance observations](https://api-docs.deepseek.com/zh-cn/api/get-user-balance/)
returned no displayed CNY or USD balance change. This does **not** establish a
zero actual charge or verify the tariff calculation; those observations did not
resolve billing for the run. No additional balance query or reconciliation was
performed. These two administrative GETs are excluded from inference RPM.
Absolute account balances remain private.

The owner-reported **20.35 CNY** baseline plus the **0.115572 CNY** conservative
trial debit gives **20.465572 CNY accounted**, **179.534428 CNY remaining** under
the original 200 CNY cap, and zero unknown/pending charges. The additional
10 CNY harness-package ceiling and every earlier ledger record remain intact.

## Local machine use

Host: macOS arm64, 18 logical CPUs, 36 GiB RAM; native DSH SDK/runtime 0.2.2rc2,
BaoStock 0.9.4. Sampling interval was two seconds.

| Activity | Active seconds | CPU coverage seconds | Mean / peak sampled cores | Peak process-tree RSS | Model wire files | Native session archive |
|---|---:|---:|---:|---:|---:|---:|
| Supervisor, excluding worker wait | 19.41 | 16.18 | 0.066 / 0.117 | 567.2 MiB | 0.591 MiB | 22.7 KiB |
| Researcher | 50.37 | 48.56 | 0.062 / 0.137 | 636.5 MiB | 1.732 MiB | 35.1 KiB |
| Reviewer | Not started | N/A | N/A | N/A | 0 | 0 |
| Whole run | 69.78 | 68.81 | 0.062 / 0.137 | 636.5 MiB | 2.323 MiB | 57.8 KiB |

These are the **shared guard/DSH/data process tree during each activity interval**,
not isolated agent allocations. The browser and Codex are outside that process
tree. Shared libraries can appear in multiple processes' RSS. CPU intervals
crossing role boundaries are excluded; very short child processes may be missed.

There were 35 whole-run resource samples with no measurement errors. Host CPU
peaked at 8.9%; swap use was zero; minimum available host RAM was about 11.5 GiB
and minimum free Work-volume disk space about 336.7 GiB. Host readings include
unrelated activity. The frozen evidence set occupies 3.909 MiB by file lengths,
including shared ledger snapshots and the overlapping server resource log; it is
not a measure of allocated filesystem blocks or incremental application storage.
This small sequential run does not determine production VM sizing or capacity.

## Data and scientific checks

One real BaoStock business query plus one login fetched `000001.XSHE` for
2026-10-19..30, returning ten unadjusted daily closes. The transport also records
the SDK logout message; socket-message counts differ from business-query quotas.
There was one evidence fetch and no cache reuse within this failed round. Future
exact reads can reuse that saved evidence. No iFind, RQData or news call occurred.

An offline arithmetic audit of the retained evidence found:

- The deterministic tool's sample return, extrema and one/five-lag summaries
  agree with the source data. The worker added other calculations in prose.
- Its first daily-return claim was −2.1888%; direct arithmetic gives −1.8026%.
  Its mean and standard-deviation claims were consequently also incorrect.
- Its stated `close_t / close_(t-5)` formula has five computable signal dates,
  beginning 26 October, and three cases with both next-close execution and a
  subsequent close available. The report incorrectly counted six signals and
  four cases, starting the five-lag calculation one observation too early.
- The report claimed a criterion was fixed before looking. The trace shows the
  proposal was written after reading data; no pre-data registration supports it.

These checks diagnose report correctness. They are not an official backtest,
independent evaluator result, alpha finding or trading recommendation. Schema and
citation validity alone cannot establish arithmetic or scientific validity.

## Boundary repairs and verification

The immediate failure was a presentation mismatch: strict JSON parsing rejected
the opening code fence. Removing that single wrapper made the unchanged report
pass its schema and evidence-access checks. The repair accepts either bare JSON
or one entire JSON/unlabelled fence, while rejecting surrounding prose, additional
objects, wrong-language fences, invalid schemas, oversized reports, unfinished
workers and ungranted citations. Original text and the detected format are retained.

The plugin's error handler also attempted a second settlement after the backend
had already saved the rejected report. That caused an additional audit error,
not another paid model request. It now attempts settlement only once. A failure
includes counts of already completed worker operations, so the supervisor can
see that data/metrics work occurred without receiving raw vendor rows.

Verification after the repair:

- **91 offline tests pass**; Ruff, formatting, three JavaScript checks and MIT
  notices pass. No ordinary test called a real provider.
- Native DSH with **fenced synthetic reports**: 11 scripted requests, two completed
  workers/tasks, one draft and successful desktop reload. No live inference/data.
- Native DSH with a **malformed synthetic report**: six scripted requests, one
  failed worker settlement and one failure event; no replay or draft. The error
  reports its completed data and metrics operations.
- The retained real report passes only the offline schema/citation recheck after
  wrapper normalization. Its live failed state, costs and raw records are unchanged.

The original live UI checks passed page identity, nonblank content, no framework
overlay, console health, completion rendering and reload persistence at
1440×1000. The shared task remained in progress, while the native child showed
completed: native generation completion does not mean the research report passed.
The 390×844 native layout still clips content. Fresh-profile preview/workspace
initialization also caused two offline browser-driver attempts to fail before
submission; zero trials/model requests were allocated by those attempts. Their
evidence is retained and the driver now waits for the preview transition before
filling unsent text. Browser plugin was unavailable; installed Chrome was driven
through bundled Playwright.

## Readiness and evidence

**Not yet accepted for the owner's complete research trials.** The guarded UI,
real Flash transport, BaoStock fetch, resource capture, budget settlement and
history work. The formatting repair passes offline, but the real reviewer and
draft paths have not completed together. Arithmetic verification and truthful
failure summaries remain material quality concerns. A fresh bounded real
three-role pass is needed; no automatic paid retry was started. Two authorized
owner session slots remain, using the same cached sample, ledger and time windows.

Live source: `48f3367c3e54da99901fc7c35bcfc76b23777a18`; later Flash-only documentation:
`bab313067ecbb8d88f80ee68a19fa8ba0f68c376`. Trial ID:
`session-c1ec8f89-16a6-40b4-8840-25a01dc18319`.
All 40 frozen-file hashes and seven wire model IDs were verified.

[Aggregate live results](evidence/interactive-2026-11-12/LIVE_TRIAL_RESULTS.json),
[arithmetic and evidence audit](evidence/interactive-2026-11-12/LIVE_TRIAL_AUDIT.json),
[browser checks](evidence/interactive-2026-11-12/LIVE_BROWSER_CHECKS.json) and
[offline repair verification](evidence/interactive-2026-11-12/REPORT_BOUNDARY_FIXES.json)
contain reviewed public metrics. Full requests, SSE, native sessions, market rows,
account observations and immutable snapshots remain in `.qfh-private/integration/`
and `.qfh-private/research/exports/`. Mixed providers, broader market/news context,
independent evaluation and full Hybrid v1 evolution remain separate modules.

### Screenshots

Real failed round: native child completed generation; its research task did not pass.

![Real trial retained a failed research task](evidence/interactive-2026-11-12/live-team-failure.png)

Offline repair check only: two scripted workers and native tasks completed.

![Fenced synthetic reports completed after the repair](evidence/interactive-2026-11-12/offline-fenced-success.png)
