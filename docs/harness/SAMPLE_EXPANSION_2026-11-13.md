# Staged BaoStock sample expansion — 13 November 2026

Status: preparation stopped at the fourth stage with 121 real observations and
118 aligned cases. The [real native GLM Flash team trial](LIVE_GLM_NATIVE_2026-11-13.md)
now passes: both workers independently executed the frozen definition, matching
the independent bootstrap audit. The outcome is inconclusive. Earlier plans and
preparation checkpoints below remain historical; the owner-authorized GLM route
replaced the planned DeepSeek run until 18:00 Beijing on 13 November.

Authority: "Please gradually expand the BaoStock sample and rerun the supervisor
plus two-worker trial with enough data for statistical inference. Keep
DeepSeek-flash only, the original 200 CNY budget and time windows, and record
everything."

## Fixed design before new downloads

Keep `000001.XSHE`, unadjusted daily closes, and the research cutoff of 30 October
2026. Expand backward; do not expose later dates or an independent holdout. Freeze
the previous trial's exact candidate before the first new query: specification
`7e17282889186a991f6e04470173f50cd9d6977b7769634a0c3d246a8304e5ec`, lookback one,
strictly negative trailing return, ties to control, next-observation execution,
one-observation forward label, expected direction lower and effect margin 0.001.
This is a retained exploratory candidate, not a new default factor or a claim of
preregistration. Workers cannot change it after seeing the larger sample.

The operator executes one additional chunk per command. Each actual BaoStock
request remains limited to one stock and at most 61 calendar days. Existing data
and every new source record remain immutable; adjacent nonoverlapping queries
are composed with explicit parent hashes. No silent deduplication or synthetic
substitution is permitted.

| Stage | Additional requested dates | Composed requested range | Calendar days |
|---|---|---|---:|
| Existing | Cached 19–30 October | 19–30 October | 12 |
| 1 | 30 September–18 October | 30 September–30 October | 31 |
| 2 | 31 August–29 September | 31 August–30 October | 61 |
| 3 | 1 July–30 August | 1 July–30 October | 122 |
| 4 | 1 May–30 June | 1 May–30 October | 183 |
| 5, only if needed | 1 March–30 April | 1 March–30 October | 244 |

Stop at the first stage with **at least 100 aligned cases, 40 in each group and
20 complete blocks**. These preparation targets exceed the unchanged calculator
floors of twenty cases per group and eight blocks. Stopping uses quality and
support counts only: no conditional-mean effect, confidence interval or significance
is inspected while expanding. More observations do not certify statistical power
or coverage. No candidate, threshold or method is tuned to obtain a preferred result.

The frozen primary protocol remains a nominal 95% moving-block percentile interval,
block length five, 2,000 replicates and the existing fixed seed. The independent
audit will reproduce the calculation and report block-length sensitivities at
ten and twenty as separate diagnostics, without selecting a preferred interval.
Known-truth synthetic calibration, if run, is reported separately from market data.
The primary result remains exploratory; historical unadjusted prices can include
corporate actions, regime changes and selection effects.

## Data and budget boundaries

`sample-expansion-2026-11-13.yaml` freezes the sequence and support targets.
`data-expansion-2026-11-13.yaml` permits at most five additional BaoStock business
queries/logins, raising cumulative limits from four to nine and estimated cells
from 21 to 253. Every prior failure remains counted. Paid-source allowances,
cutoff, fields, response-size limit and per-query duration remain unchanged.
Only the operator preparation command uses this expanded policy. Workers read the
selected immutable composed sample from cache and cannot download additional data.

Preparation may fetch free BaoStock data while model admission is closed. All
DeepSeek inference and account-balance reads still wait for the established
12:00–14:00 or 18:00–24:00 Beijing window. One supervisor and two workers use
`deepseek-flash` only, at most eight/six/six calls and twenty total. No pilot-session
extension is made: four of six sessions were already used before this work.

The same budget ledger retains the owner-reported 20.35 CNY baseline and all
subsequent estimates. Before this package, 21.608190 CNY is accounted and
178.391810 CNY remains under the original 200 CNY cap, with 78 settled harness
calls and no unknown reservations. Data preparation makes no model request.

## Validation and retained evidence

Core quality checks cover source identity, cutoff, adjustment mode, positive
finite prices, unique dates, query adjacency, range membership and weekend rows.
Returns above the predeclared warning magnitude stop expansion for inspection;
they are not automatically labelled errors or removed. Calendar gaps are recorded,
but completeness against an exchange calendar and point-in-time availability are
not independently established. Unadjusted prices are not a total-return series.

An operator-only append-only activation gives new trials their expanded scope.
Each trial freezes its sample in the start event; old trials retain their original
scope and drafts. The host recomposes the selected artifact from verified source
chunks before activation. The budget, original research policy and previous records
are not reset. A changed plan, protocol, failed/unknown download or interrupted
attempt stops execution instead of automatically repeating the request.

To keep the larger sample within existing model-message limits, bars clearly label
their preview and total row count. Metrics and specification tools compute **all**
permitted rows, retain complete immutable calculation artifacts and return bounded
summary facts plus first/last alignment rows. Workers can cite only the fact keys
actually exposed to them. Export includes full calculations, every parent source
record, data wire records, preparation attempts and the sample amendment.
Expanded drafts use the precise timing label `next_observation_close`.

146 offline tests pass. The native larger synthetic DSH fixture completed two
workers/tasks and a draft with 128 aligned cases, 64 per group, and 2,000 actual
deterministic bootstrap replicates. Both workers corrected an oversized report
within their original call caps. Seventeen model responses were scripted; no real
inference or vendor data was used. All 84 frozen files verified, including complete
calculation artifacts and source lineage. Desktop completion/reload/Team checks
passed; the existing 390px mobile clipping remains.

Record each stage's exact query, source/composed hashes, rows, support, quality
findings, query/cache status, elapsed time, process CPU/RSS, errors and raw wire.
For the paid trial, preserve clean source/dependency/config/prompt hashes; native
session/task IDs and actual work; each role's requests/tokens/cache/RPM/TPM/cost;
sampled process/host CPU/RAM/swap/disk; before/after billing observations; full
statistics; independent audit; limitations; and remaining budget/allowance. Preserve
all failures and distinguish synthetic checks, free data preparation and real LLM
inference. Update this record and the README after execution.

## Operator commands

```sh
PYTHONPATH=harness/src python harness/scripts/expand_research_sample.py \
  --private .qfh-private --plan harness/configs/sample-expansion-2026-11-13.yaml --initialize
# Inspect each completed stage before invoking the next one.
PYTHONPATH=harness/src python harness/scripts/expand_research_sample.py \
  --private .qfh-private --plan harness/configs/sample-expansion-2026-11-13.yaml --next-data
# Only after support and quality targets pass:
PYTHONPATH=harness/src python harness/scripts/expand_research_sample.py \
  --private .qfh-private --plan harness/configs/sample-expansion-2026-11-13.yaml --activate
```

Private preparation records are under
`.qfh-private/research/sample-expansions/baostock-support-2026-11-13/`;
integration checks and the forthcoming trial records use
`.qfh-private/integration/expansion-005/`. No automatic repeat of a paid trial is
authorized by this preparation script.

## Actual preparation and independent calculation

Frozen source commit: `8d6d3f25e0d1c044762534f5618f5af18b68980e`.
Plan hash: `54daf2b5826dbcb5036a662df710f4541356707a5e50be23644c71a47b2d3974`.

| Stage | New rows | Composed rows | Aligned cases | Signal / control | Complete five-case blocks |
|---|---:|---:|---:|---:|---:|
| 1 | 8 | 18 | 15 | 9 / 6 | 3 |
| 2 | 21 | 39 | 36 | 20 / 16 | 7 |
| 3 | 43 | 82 | 79 | 35 / 44 | 15 |
| 4, selected | 39 | 121 | 118 | 59 / 59 | 23 |

Four real bounded queries succeeded. Stage five was not called. Selection used
quality/support counts only; all stage records state `inference_computed=false`.
No weekend observations or predeclared large-return warnings occurred. The
maximum observed date gap was eight calendar days; this is recorded, not claimed
to prove calendar completeness. Actual observations run from 6 May through
30 October; the requested range starts 1 May. Activation preserved four existing
trials, all 78 settled model calls and the unchanged cash accounting above.

Selected composite:
`e1b4e4aad323cd40f3932716fc6cca54ced00af2b2e3e66ec0bde85a93def671`.
Its five parent records include the ten observations retained from the previous
trial. No synthetic observations were introduced.

Only after selection, an independent Decimal/index bootstrap reproduced the
production calculation exactly: oriented mean-return contrast 0.002730989,
nominal 95% interval [-0.001476713, 0.007025561], with 2,000 replicates.
The outcome is **inconclusive** relative to the fixed 0.001 margin. Block length
ten also returns inconclusive, interval [-0.001858362, 0.006813156]. Block length
twenty reports insufficient data under the unchanged eight-block minimum; no
floor was relaxed or preferred interval selected. This is enough for the stated
primary pilot calculation, not evidence of certified coverage or power.

The independent audit also verified all 120 alignment rows, 118 usable labels,
two dropped tail cases, four ties assigned to control, and 117 touching endpoints
with zero positive overlap. Serial independence remains unestablished. Full
audit and reference calculation are retained under `expansion-005`, separately
from the completed native GLM trial linked above.
