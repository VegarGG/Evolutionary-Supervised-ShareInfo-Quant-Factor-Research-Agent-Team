# Measured observations and truthful activity reporting

The first real trial exposed wrong hand-calculated returns, a five-lag indexing
error and a supervisor recap that confused report rejection with absence of work.
The second trial used `measured-observations-v2` to address those concrete failures.
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

The second live trial reached both workers but the reviewer returned nine findings
against the eight-item schema limit. Its report was rejected and no draft recorded.
The `submitted-reports-v3` contract now validates reports inside each active native
worker via `submit_worker_report`. A rejection returns precise field/type/message
diagnostics, without echoing the submitted content. The worker can correct its own
submission within the same turn and unchanged model-call cap. The host does not
truncate, silently repair, or relax the schema. Acceptance freezes an append-only
report and hash; the native turn must also complete normally. Final acknowledgment
text cannot replace that report. This is not replay of a completed or failed worker.

Historical trials retain their original bare/fenced JSON completion contract and
raw outputs. Existing failed trials, ledger charges and immutable drafts are not
rewritten. After a final worker failure, host operations permit status reads and
settlement only; the supervisor cannot continue data work or submit a partial draft.

`research_scope`, worker completion and draft submission return a host activity
snapshot with completed-operation counts, report states and model-request counts
so far. Data operations and model quotas are labelled separately. A native turn
completion is distinct from report validation. A rejected report can still have
completed data and arithmetic operations. Final token/cost totals come from the
post-turn exporter, because a mid-turn snapshot cannot include later requests.
Native chat prose remains model-authored commentary, not an authoritative numerical
report. The host-validated report and attached measurement facts are the record.

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

After adding active-worker submission validation, 108 offline tests passed. The
native synthetic correction test rejected then accepted each worker's report without
restarting either worker. The [real rerun](LIVE_RERUN_2026-11-12.md) then completed
both workers and a draft; the reviewer corrected the same array-limit error within
its existing call cap. All 44 measured facts and 28 draft references passed the
independent post-run audit. That draft's statistical/specification findings motivated
the [executable contrast contract](STATISTICAL_SPECIFICATION.md). New v4 reports
reference a worker-executed specification ID and require `proposed_formula: null`;
the supervisor selects a reviewer-executed definition and the host renders the
formula/timings/statistical state. The earlier free-form fields remain historical.
All 135 offline tests and native synthetic correction checks pass before the new
live verification. Validated numbers and executable definitions alone do not
establish research validity. The [new live verification](LIVE_SPECIFICATION_TRIAL_2026-11-12.md)
completed fifteen Flash calls, two worker calculations/specifications and a draft
with seventeen fact references. All forty-four facts, dates, support counts and
hashes passed independent checks. The new reports/draft correctly distinguish
endpoint contact, untested independence and insufficient support. One speculative
researcher sentence remains separately flagged; numerical validation does not
make all model prose authoritative.
