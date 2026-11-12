# Bounded interactive research trial

Status: the [real Flash/BaoStock trial](LIVE_TRIAL_2026-11-12.md) started at 18:01
Beijing on 12 November and stopped after the researcher's fenced JSON report was
rejected. Seven requests settled; the reviewer never ran and no draft exists.
The presentation boundary is repaired and passes native offline tests, but a full
real three-role pass is still required before owner-trial readiness is accepted.

The owner has authorized that rerun after arithmetic/reporting repairs. New
reports use the [measurement contract](MEASUREMENT_CONTRACT.md): deterministic
statistics and alignment, worker-observed fact references, host-derived numerical
draft facts and activity summaries. The original failed record remains unchanged.

## What you can test

Enter a research brief in DSH. The supervisor assigns one researcher and one
reviewer, each in a native DSH child session. They fetch the permitted BaoStock
sample, can request deterministic descriptive statistics, and return cited reports.
The supervisor records adoption/rejection decisions and one immutable draft.
The **2 subagents** panel exposes child sessions and completed Agent Teams tasks;
the normal trajectory view shows tool calls and intermediate work.

This is one research round with read-only evidence. Draft checks establish schema,
source provenance, role completion and explicit decisions. They do not prove the
formula is economically useful, executable, free of every semantic timing error,
or accepted by an evaluator. No official backtest, publication, factor pool or
simulated account is controlled by this profile.

## Start and use

Use the same Work-volume Python/Node/pnpm environment as the setup profile:

```sh
just harness-research-ui --private .qfh-private \
  --key-file /operator/deepseek-key-file --install-plugin
```

The key-file path is an operator argument; key values are never printed or passed
to DSH or workers. The parent guard owns the real key and provides DSH a temporary
local relay credential. The existing `.qfh-private/campaign/spend.sqlite3` remains
the budget authority. Do not substitute a fresh ledger for owner trials.

Open the private bootstrap URL printed by the local server on port 3080. Use the
`qfh-research` preset and **DeepSeek · guarded research** model. **Use Agent Teams**
starts enabled for new roots; leave it enabled for the worker workflow. In a new
session, describe a falsifiable price-only daily A-share idea within the displayed
sample. Each new model-using session counts as one trial. Merely viewing settings,
history or the team panel makes no model request.

The research UI has its own local home, `research-ui-home`, and a default workspace
under `.qfh-private/research-workspace/`. On first launch it copies any existing
setup-UI credentials into its credential store without making provider requests.
Further saves/removals affect the research UI store. Paid-source credential forms
remain available for preparation, while this trial's active source is BaoStock.

## Fixed first scope

| Boundary | Limit |
|---|---|
| Model routes | `deepseek-flash` only for supervisor, researcher and reviewer; other model IDs are rejected |
| Team | Supervisor + researcher + reviewer, one activation each; sequential workers |
| Requests | At most 8 supervisor, 6 researcher and 6 reviewer; 20 per trial including retries |
| Trials | Three small sessions: this integration trial and two owner trials |
| Data | `000001.XSHE`, 2026-10-19..30, unadjusted daily closes |
| New BaoStock access | One additional business query and one login; later reads reuse its exact cache |
| Data history | Prior 3 business attempts/3 logins/9 estimated cells retained; new cumulative caps 4/4/21 |
| Paid data | No iFind or RQData call in this research profile; original quotas unchanged |
| Time | New model wire requests only 12:00–14:00 and 18:00–24:00 Beijing |
| Budget | Original 200 CNY cumulative cap; additional 10 CNY harness-package ceiling retained |

The guard checks each wire admission, including tool continuations. A request
already sent can finish after a window closes; the next request is refused. There
is no hidden outside-window retry. DSH's automatic model retries are disabled for
this profile; any explicitly permitted repeated call still consumes its allowance.
Unknown usage retains its full provider-maximum reservation and blocks further
work in that trial pending reconciliation.

The immutable ledger policy still has its original one-call default for historical
diagnostics. New research conversations receive explicit, immutable host grants
before their first dispatch. Grants never reset costs, enlarge the total cap or
extend an already used diagnostic step. Root and worker calls are attributed by
native DSH session headers, not model-authored tool arguments.

## Accounting correction and evidence

At 07:05:53 UTC on 12 November, the existing ledger was reconciled to the owner's
reported official total of **20.35 CNY**, covering the 884 historical calls and
24 harness calls already recorded, with no unresolved charges. The earlier
57.084913 CNY estimate remains in the records. The reconciliation stores the
owner's verbatim statement and a digest of the covered call IDs. It does not
claim that Codex independently downloaded an invoice. Subsequent charges use
conservative peak cache-miss input and output rates, with the remaining cap
calculated from the official baseline plus those newer estimates/reservations.

The first interactive round adds 0.115572 CNY conservatively, leaving 179.534428 CNY.
Its published-tariff estimate is 0.04310952 CNY. Two private balance observations
returned no displayed change and did not establish the actual charge. The failed
round occupies one of the three slots; two owner slots remain. No paid replay ran.

Private evidence includes raw request/SSE records, event timings, native DSH
session archives, append-only research events, source hashes, role assignments,
worker outputs, data wire records, evidence hashes and resource samples. Export a
finished trial with `harness/scripts/summarize_research.py`; it snapshots mutable
ledgers and logs before hashing them. Public summaries exclude API credentials and
raw vendor-row dumps. DSH's footer describes the selected session; the exported
trial report includes **all three roles**.

Resource measurements cover the guard and its DSH/data children, plus separately
labelled host RAM/CPU/swap/free disk readings. They do not establish VM sizing or
500-concurrency throughput. TPM/RPM use rolling 60-second call totals attributed
at dispatch/completion, not per-token streaming rates.

The export breaks usage down by supervisor, researcher and reviewer: actual wire
requests, cached/uncached input, output, weighted cache-hit ratio, peak rolling
TPM/RPM, contribution decisions and observed backend operations. It also records
each role's wire/session file sizes. Worker activity spans their start/finish
events; supervisor activity excludes its waits for those workers. CPU/RAM readings
describe the shared local process tree during those spans. They are not isolated
per-agent allocations, and CPU samples crossing a role boundary are excluded.
Missing measurements remain null, with coverage reported.

Cost has two separate calculations. The original guard keeps its conservative
debit. Reporting uses measured token counts and the versioned
[official DeepSeek tariff](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/):
for this off-peak Flash trial, CNY 1 per million uncached input tokens, 0.02 per
million cached input tokens and 4 per million output tokens, verified on
12 November. This is a tariff estimate, not a downloaded invoice. Unknown usage,
unpriced cache-creation tokens and intervals crossing possible peak hours do not
receive an invented cost. The configured alias is not proof of the backend version.

The operator can make one read-only
[balance observation](https://api-docs.deepseek.com/zh-cn/api/get-user-balance/)
before and one after the trial using `harness/scripts/balance_snapshot.py`.
Those two administrative GET requests are counted separately from inference.
Absolute balances stay private; the report may compare their difference with
the tariff calculation. An account balance change can include other account
activity and is not allocated to individual agents or used to reset the ledger.
Pass both files to the exporter with `--balance-before` and `--balance-after`.

Owner-trial readiness requires a real completion by all three roles, two valid
worker reports and native tasks, one cited draft with contribution decisions,
settled usage under the original bounds, captured resources, and usable desktop
history after reload. Failure of those checks must remain visible before declaring
the workflow ready. A successful small trial still does not validate alpha quality
or production capacity.

## Recovery and remaining work

Completed workers and drafts are not automatically rerun. Failed or interrupted
workers keep their task, raw result or start marker; the trial stops for inspection.
Reports now accept bare JSON or one complete JSON/unlabelled code fence. The
contents still pass the same size, schema and citation checks; text outside the
object/fence is rejected. Failure messages include completed-operation counts,
and a rejected/uncertain settlement is not sent twice. These repairs do not alter
the failed live round or verify the arithmetic in a model-authored report.
There is no production job scheduler or automatic cross-window recovery in this
first UI. A stopped native task can remain in progress on the Team board; that
must not be mistaken for successful research. Reopen history to inspect, and
reconcile uncertain requests before authorizing another attempt.

[Per-role providers and bounded market/news context](ROLE_MODELS_AND_CONTEXT.md)
are explicit next modules. Full Hybrid v1 evolution, repeated open-ended controls,
paid data checks, point-in-time archives and independent gate integration remain
separate work. Desktop is the primary tested interface; native DSH's narrow mobile
layout has visible horizontal clipping at 390 px and is not yet accepted for use.
