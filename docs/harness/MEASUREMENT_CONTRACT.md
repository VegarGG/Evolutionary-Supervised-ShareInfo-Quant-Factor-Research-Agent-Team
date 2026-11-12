# Measured observations and truthful activity reporting

The first real trial exposed wrong hand-calculated returns, a five-lag indexing
error and a supervisor recap that confused report rejection with absence of work.
The second trial uses `measured-observations-v2` to address those concrete failures.
This changes the report contract, not the data allowance, model route, budget or
independent evaluator boundary.

`research_metrics` computes daily close-to-close returns, count/mean/median/sample
standard deviation, sign counts, sample return, extrema and configured lookback
series. It enumerates each signal's lookback start, next observation execution
date and label end. Lags count returned observations; the tool does not claim to
verify exchange-calendar completeness. Ten observations and a five-observation
lag yield five signal dates and three cases with next-close execution and a
subsequent label close. Returns use fractional units, not percentages.

The arithmetic protocol is versioned in `harness/configs/research-metrics.yaml`.
Decimal precision is fixed locally. The calculator checks distinct dates, one
symbol, finite positive closes and valid lookbacks. A measurement ID hashes the
source evidence ID, protocol, calculator source hash, facts and alignment. No
network, strategy P&L, portfolio, official evaluation or publication is involved.

Workers still form hypotheses and critique each other through actual native DSH
sessions. Each worker must fetch/read its permitted evidence, call the metrics
tool itself, and return `measurement_refs`: a measurement ID and selected fact
keys. The model supplies no numerical values in these references. The host resolves
values and units from that worker's recorded tool result. References to unobserved
measurements, missing keys, duplicates or extra model-authored value fields fail.

Report prose is qualitative. Numeric literals and percentage signs are rejected
outside the formula field, where symbolic definitions may contain parameters.
Dates, counts, stock identifiers and measured values belong in evidence/host
metadata, not hand-calculated prose. Drafts inherit the verified facts from both
workers, attributed by role; the supervisor cannot substitute numerical values.
All proposals are labelled `post_observation_exploration`. There is no mechanism
here that can establish preregistration. Qualitative arguments and formula meaning
still require review; this contract is not proof of scientific or economic merit.

The report parser retains bare JSON or a single JSON/unlabelled fence and all raw
output. The new fields default empty only to allow historical report parsing;
new worker completion requires valid measurement references. Existing failed
trials, raw reports, ledger charges and immutable drafts are not rewritten.

`research_scope`, worker completion and draft submission return a host activity
snapshot with completed-operation counts, report states and model-request counts
so far. Data operations and model quotas are labelled separately. A native turn
completion is distinct from report validation. A rejected report can still have
completed data and arithmetic operations. Final token/cost totals come from the
post-turn exporter, because a mid-turn snapshot cannot include later requests.

Offline regressions cover the originally observed off-by-one and return errors,
constant/nonconstant and short series, invalid prices/dates, deterministic precision,
fabricated values/references, other-worker references, unsupported numeric prose,
host-derived draft facts and truthful activity counts. The native scripted flow
and a fresh real Flash-only run are recorded separately; a synthetic pass does
not establish real readiness.

Verification before the paid rerun: 105 offline tests and all harness checks pass.
Native DSH with synthetic inference/data completed both workers, recorded six
host-derived facts in one draft and produced no tool failures. The exporter
preserved verified facts for each worker. See the
[native fixture record](evidence/interactive-2026-11-12/MEASUREMENT_OFFLINE.json).
