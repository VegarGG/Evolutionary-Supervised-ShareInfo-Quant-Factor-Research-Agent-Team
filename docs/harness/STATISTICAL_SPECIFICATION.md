# Executable development contrast and statistical limits

The third live pilot completed its workflow but its prose confused touching label
endpoints with overlapping return intervals, treated non-significance as
disconfirmation, and left alternative thresholds/tests unresolved. The original
draft and quality findings remain unchanged in the
[earlier report](LIVE_RERUN_2026-11-12.md).

New sessions use `executable-contrast-v4`. Each worker calls
`research_specification` on its own permitted evidence and cites the returned
specification ID in its accepted report. The researcher supplies one concrete
definition. The reviewer independently executes the selected definition; the
supervisor selects its ID. The host supplies the draft's formula, timings,
support, geometry and inference state. Free-form formula/timing overrides and
unresolved alternatives are rejected. Earlier v2/v3 sessions keep their contracts.

## What is executable

The initial family is a **close-return group contrast**, not a general factor DSL,
portfolio strategy, official evaluator, backtest or publication interface.
Required model choices are lookback, strict comparison (`lt` or `gt`), threshold,
explicit ties-to-control, label horizon, expected direction and effect margin.
There is no production default candidate. A zero threshold with explicit tie
handling is valid; it is not automatically a specification defect.

At observation i the trailing return uses only closes through i. Execution is the
next returned close; the label ends the specified number of observations later.
Missing tail labels are dropped. The oriented effect is the difference between
mean forward labels in the signal and control groups. The margin is a threshold
for this contrast, **not a transaction-cost or profitability model**. Dates count
returned observations; exchange-calendar completeness and point-in-time data are
not established by this tool. The live data remain unadjusted historical closes.

All protocol settings are in `harness/configs/research-statistics.yaml`: fixed
Decimal precision 28, next-close execution, lookback/horizon bounded at five,
twenty observations per group, at least eight blocks, nominal 95% moving-block
percentile interval, base block length five, 2,000 replicates and seed 20261112.
Effective block length is the maximum of the base length and label horizon.
No worker can lower these floors or change the protocol. The specification hash
includes normalized parameters, evidence, full protocol and calculator source;
the assessment hash also covers the computed output. Equivalent decimal spelling
does not change identity. The runtime/dependency versions are exported separately.

## The statistical corrections

Adjacent one-observation labels share an endpoint but have **zero positive
interval overlap**. Longer horizons may overlap. The tool calculates both
positive-overlap and touching-endpoint counts from actual label dates; neither
result proves serial independence.

When support is sufficient, the implemented bootstrap samples non-wrapping
contiguous blocks of the joint signal/label pairs and takes percentile endpoints.
It does not independently shuffle the labels and signals. If a replicate has an
empty group, it returns `resampling_unavailable` without conditional retries.
The method and percentile distinction follow the documented
[moving-block algorithm](https://bashtage.github.io/arch/devel/bootstrap/generated/arch.bootstrap.MovingBlockBootstrap.html)
and [interval methods](https://bashtage.github.io/arch/devel/bootstrap/generated/generated/arch.bootstrap.MovingBlockBootstrap.conf_int.html).
This implementation does not import that package or claim certified coverage.

The possible states are `insufficient_data`, `resampling_unavailable`,
`interval_above_margin`, `interval_below_margin`, or `inconclusive`. Equality at an
interval boundary is inconclusive. A non-significant or inconclusive result is
not proof that an effect is absent, consistent with the
[ASA statement](https://www.amstat.org/asa/files/pdfs/P-ValueStatement.pdf).
No state means confirmed alpha, economic disproof or evaluator acceptance.

The ten-row live pilot cannot meet the support floors, so it must return
`insufficient_data`, no estimated effect/interval, and zero bootstrap replicates.
Synthetic tests exercise the nontrivial bootstrap branch. Even on larger samples,
nominal coverage requires appropriate dependence/stationarity assumptions. Fixed
block length and minimum sample counts do not establish those assumptions. These
post-observation exploratory choices have no multiplicity/selection correction.
Confirmatory methodology and independent evaluation remain separate work.

## Verification and allowance

All 135 offline tests and harness checks passed before paid execution. Regressions
cover label geometry, interval boundary decisions, insufficient/empty-group
outcomes, seeded sufficient synthetic data, unresolved/bounded parameters,
Decimal-context independence, worker-owned evidence, independent reviewer
execution, host-rendered drafts and allowance integrity.

The native DSH synthetic test completed both workers and tasks, rejected then
accepted each oversized report inside the same active turn, and recorded a draft
with the new specification. Seventeen scripted model responses were used; there
was no real inference or vendor access. Reload and the desktop Team panel passed;
the known narrow mobile clipping remains. See
[the fixture record](evidence/interactive-2026-11-12/SPECIFICATION_OFFLINE.json).

The owner explicitly authorized a pilot extension on 12 November. An operator-only
append-only amendment raises cumulative sessions from three to six: one new repair
verification and two small owner trials. It is not exposed as a model tool.
Reapplying the same amendment is idempotent; changes to its content are rejected.
Pending/unknown charges block an extension. Before/after checks verified unchanged
budget and data ledgers, original policy, prior trials, members and events; exactly
one amendment event was added. The official 20.35 CNY baseline, 200 CNY total cap,
10 CNY package cap, per-role/per-trial calls, provider and Beijing windows remain.
Before the new trial, 21.253244 CNY is accounted and 178.746756 CNY remains.

The operator command is:

```sh
PYTHONPATH=harness/src python harness/scripts/extend_pilot.py \
  --private .qfh-private --amendment harness/configs/pilot-extension-2026-11-12.yaml
```

The immutable original policy still says three; status reads the latest recorded
amendment and reports both original and effective limits. No counter is reset.
The upcoming real trial is separately reported; this offline evidence alone does
not establish live readiness or research quality.
