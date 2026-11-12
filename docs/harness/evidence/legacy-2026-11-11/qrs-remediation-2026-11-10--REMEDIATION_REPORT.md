# QRS acceptance remediation

The engineering defects have been repaired and tested locally. **Overall acceptance
remains withheld because SC1 and SC2 still fail**; this is not a release approval. The original
review is preserved at `../qrs-review-2026-11-10/`. Changes are in `checkout/`,
branch `codex/qrs-acceptance-fixes`, based on
`759772b1705d53951b42bee3aab2816dca7aad35`. The tested functional revision is
`4c05d6fe230821ea38dad2b157ace3018fce02b7`. Nothing has been pushed.

## Budget enforcement first

R01/R02/R14 now commit a conservative PostgreSQL reservation before every model
request, including probes, tool continuations, structured-output retries and
fallbacks. A database lock serializes admissions. Unknown requests remain reserved
across restarts and UTC-day boundaries; settlement is append-only and idempotent.
DeepSeek receives the supported `max_tokens` field. Streaming is refused until it
has a settlement path; the SDK performs no hidden retries.

Research migration 0005 adds the reservation table and settlement reference.
Historical ledger rows remain in spending calculations. Admission uses configured
upper-bound tariffs, conservative UTF-8 message/schema byte counts plus configured
protocol overhead, and a positive output cap. Missing prices or invalid usage fail
closed. Accurate configured prices and request bounds remain operating assumptions;
invoices and unknown provider outcomes need reconciliation.

Forty-nine focused tests and 113 research regressions passed with zero skips. Two
real database connections competing for a 0.35 CNY cap admitted only one 0.20 CNY
request. Tiny-cap refusal, restart/day-boundary, timeout, retry, invalid usage and
duplicate settlement checks passed.

A populated revision-0004 database was then upgraded to 0005 in an isolated schema.
All 15 checks passed: the historical 0.25 CNY test charge survived unchanged, blocked
a request that would exceed the 0.35 CNY test cap, and remained counted after a new
0.02 CNY settlement. Duplicate settlement, repeated upgrade and application-role
update/delete/truncate refusals passed. These are simulated ledger amounts; the
upgrade test made no provider calls.

One new live **DeepSeek Flash** request exercised the production wrapper with a
128-token cap. The transport verified a committed reservation before HTTP, exactly
one settlement, and zero dispatches under both a tiny cap and a cap equal to settled
spending. Production cost was estimated at 0.000781 CNY with cache hits; the separate
campaign guard estimated 0.001032 CNY using cache-miss prices for all input tokens.

The original five calls plus this one total **six calls, estimated 0.014883 CNY
of the original 200 CNY, with zero unresolved reservations**. Invoices remain
unverified. No other provider was called. An earlier `NoPrice` refusal dispatched
nothing. Verified rates were supplied only to the isolated test configuration;
repository price placeholders were not silently populated.

[Budget evidence](BUDGET_RESULTS.json) ·
[Live run](private/runs/LIVE-20261110T165254112786Z-repaired-budget-verified-prices/run-record.json) ·
[Verified pricing](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/) ·
[DeepSeek request contract](https://api-docs.deepseek.com/api/create-chat-completion/)

## Repairs and verification

| Finding | Change | Result |
|---|---|---|
| R01/R02/R14 | Durable reservation, serialized admission, idempotent settlement and supported output cap | PostgreSQL regressions and one real DeepSeek request passed. |
| R21 | Redact nested credentials at trace and agent-run database sinks | 26 logging, trace and lineage checks passed; sanitized full text remains available for reconstruction. |
| R22 | Fence completion, retry, database results and artifact writes by active attempt | 33 dependent checks passed. Stale fingerprint and W1 file corruption reproduced before correction. File writes now occur under the ownership row lock; calculation remains outside the transaction. |
| R13 | Match sandbox PID limits at 64 | Exact shipped Compose validation passed. |
| R24 | Authenticate Feedback OpenAPI using the existing in-container reader token | Final two-worker doctor passed all 156 checks. Earlier one-worker doctor passed 149, including a fresh verified backup. |
| R20 | Accept upstream `archive_sha256` and verify named archive matches | 40 focused checks passed; both real CN profiles ingested through the release manifest without a manual digest override. |
| R19 | Start and wait for the restored Python sandbox before replay | Populated backup restore passed 45 checks, zero skips, including exact W1 hash reproduction. |
| R23 | Write `COMPLETE` only after verified mirror completion; detect partial attempts and allow retry | Nine PostgreSQL recovery checks passed, including obstruction, retry and corruption cases. |
| R18 | Process local evaluator completions every second; reduce idle worker polling to one second | Final 1/5/10/30 ladder produced 30 W1 records and exact sampled replays; SC5 passed on the tested profile. Registry pulls remain independent at 60 seconds. |
| R25 | Use cgroup OOM evidence to distinguish memory kills from CPU limits | 22 focused checks passed; a real 256 MiB cgroup OOM was correctly reported as memory. |
| R17 | Update standalone smoke assertions to Phase 8 MCP catalog | Deployed loopback transport and audit smoke passed. |
| R05 | Apply the documented 60-day deadline to the first monitoring alert visible through MCP | Passed: CUSUM 18 days, rolling rule 69. No detector or scientific threshold changed. |
| R15/R16 | Correct README and document the supported Linux test environment | Native macOS RLIMIT_AS and Bash 3.2 limitations remain; Linux ARM64 is verified. No native-macOS pass is claimed. |
| R03/R04 | Preserve scientific gates and enforce SC2 publication exposure | Both remain failed: planted has no accepted factor; null50 has no publications against the required 500. Details below. |

The complete final functional-source Linux suite passed **1,338 tests, zero
failures, errors or skips**, with six benchmarks deselected for separate serial
execution. Static checks passed lint, format, typing, import boundaries, generated
schema/card consistency and licenses. Tests used pinned dependencies, real isolated
PostgreSQL, a 2-vCPU/3-GiB ARM64 container and `pytest -n 0`. Fixtures reject external
network calls and real PydanticAI requests.

The restored Python record reproduced
`850d2791cc65446598aaf0975f55c9b188f6faa0f36ed5443f965b777dc68c4b`.
Final deployed W1 records identify code `4c05d6f` and image
`sha256:288b7e9f91d5e56223d3c24fd7b076a883db69262316b9634c1234b4578f0800`.

## Scientific acceptance

The final 50-generation null run completed in 1,378.141 seconds. All 1,787 drafts
failed the RankIC and RankIC-IR prescreen; there were no publications, W1 trials,
W2 passes or acceptances. SC2 requires at least 500 publications, so this remains
**FAIL**, and no false-positive-rate conclusion can be drawn from zero exposure.
The original assertion passed vacuously; the repaired test fails explicitly.
This preserves the production prescreen and the original acceptance requirement.

The ten-generation planted acceptance rerun completed in 447.889 seconds: 44
publications, 16 W1 passes, 11 W2 passes and 11 holdout passes. All 11 cases reached
acceptance review and were rejected. DSR failed in all 11 (maximum 0.633932 against
0.90); HLZ also failed in three. Best planted rank correlation was 0.987112, so the
failure concerns acceptance after discovery. SC1 and BM-PLANTED remain **FAIL**.
An independent standard-library calculation reconstructed the sample variance,
expected maximum Sharpe, DSR and raw-trial-count DSR from the captured trial moments.
All 11 cases matched to within **5.6 × 10⁻¹⁷**, below the 10⁻¹² tolerance. This verifies
the recorded arithmetic and units; it does not independently validate clustering or
the underlying return series. [Arithmetic evidence](ACCEPTANCE_ANALYSIS.json)

The strategy benchmark passed in 172.933 seconds. Its passing strategy had W1/W2
net Sharpe of 1.138494/1.847355 and information ratio of 1.081681/2.010023, using the
scripted fixture's existing single-A1 path. The W1-only planted fixture also passed:
48 evaluations, 10 W1 passes and 28.125% archive coverage. The W1 null50 fixture passed
with 26 publications and zero W1 passes; that smaller exposure does not satisfy SC2.
[Benchmark results and exact revisions](BENCHMARK_RESULTS.json)

These are empirical acceptance failures, not a reason to lower a gate until the
fixture passes. Phase 6 decision 26 already records DSR calibration as pending the
owner. A changed DSR threshold or variance definition requires an explicitly chosen
protocol and renewed null-exposure evidence. SC2 requires either a compliant search
fixture with the specified exposure or an explicit revision of that benchmark
requirement. Bypassing prescreening or treating imported null factors as the original
50-generation search would change the question being tested. No such change was made.

## Capacity and latency

All workloads ran serially, starting small and increasing scale. Worker concurrency
was a measured capacity rung, not parallel independent tests.

| 80-instrument × 700-day profile, 30 W1 records each | Median overhead outside fingerprint/evaluation | Median decision to visible | SC5 |
|---|---:|---:|---|
| Local scheduler fix, one worker, 5-second idle poll | 65.220 s | 1.301 s | Fail |
| Same, two workers | 60.958 s | 0.810 s | Fail |
| One worker, 1-second idle poll | 61.936 s | 1.190 s | Fail |
| Two workers, 1-second idle poll | 59.250 s | 1.147 s | Pass |
| Final file-fence revision, two workers | **59.426 s** | **1.107 s** | **Pass** |

Each worker had 1 vCPU and 1.5 GiB. The final 11-container stack's sampled simultaneous
memory reached about 1.24 GiB at roughly two-second intervals; this is not a true peak.
SC5's 0.57-second margin is small and applies only to this tested synthetic workload.

The real manifest route built 4,536,682 rows / 948 historical instruments for CSI300,
then 9,339,616 rows / 2,029 instruments for CSI300+500. Both verified archive SHA-256
`7c796f66efb54053ec84d747cb8cb7612188d4f9c7a8efde6fcf6d3c55260d1c`.
At 1 vCPU and 2/3 GiB respectively, both completed without OOM kills. Both cgroup
peaks reached their caps with reclaim/max events; these limits do not establish
comfortable headroom. Full/research snapshots occupied about 409/270 MiB in the
full run, plus 847 MiB extracted raw files.

Ingest does not replace the original full-CN evaluator ladder: 4.5 GiB was the first
tested cap supporting repeated exact fresh-process replays, with a largest measured
peak of 4.41 GiB. The configured 6 GiB worker cap leaves more room. The earlier
8-vCPU / 8-GiB / 200-GiB serial offline pilot estimate remains provisional, with
ingest and replay staged separately. The VM had 18 vCPUs and 7.75 GiB; it was not
resized to establish whole-VM performance at eight vCPUs. The production two-worker,
live research and maintenance peak is unmeasured. The production 24-GiB planning
expectation remains separate from the measured pilot.

[Latency calculations](LATENCY_latencyfinal.json) ·
[Resource retest](RESOURCE_RETEST.json) ·
[Original resource ladder](../qrs-review-2026-11-10/RESOURCE_RECOMMENDATION.md)

## Evidence and limits

[Run index](RUN_INDEX.md) and [JSON index](RUN_INDEX.json) distinguish assertion
failures, harness failures, successful checks and interrupted attempts. No failed
attempt was discarded. Three early benchmark assertions passed but their report
copier failed on absolute pytest symlinks; clean reruns are retained. The first
restore harness used the wrong backup mount path. A post-rebuild doctor found old
containers referencing removed image metadata; recreating containers resolved it.
The first OOM fixture did not touch its allocated pages; the corrected fixture
triggered a real OOM. A null run was stopped after nine observed generations to
repair the newly discovered file race; it has no acceptance verdict.

The fresh final doctor observed unavailable provider roles and no backup in its
new project, as expected for a keyless fixture. Paid research readiness was not
established; populated backup verification was a separate test. Scripted owner
confirmations occur only in disposable offline fixtures and are not the owner's
real approval. DeepSeek-only authorization does not cover the multi-provider
critic, live 20-generation CN benchmark or live host-agent acceptance workflow.
Provider names, request counts and CNY amounts inside offline benchmark exports are
scripted FunctionModel fixtures, not billed requests; they do not enter the campaign's
six-call live ledger.

The committed patch, source archive and provenance are delivered as
[SOURCE.patch](SOURCE.patch), [SOURCE.tar.gz](SOURCE.tar.gz) and
[SOURCE_PROVENANCE.json](SOURCE_PROVENANCE.json). They preserve the original plan,
scientific formulas, protocol gates, synthetic fixture and dependency lockfile.
[Evidence checksums](EVIDENCE_SHA256SUMS) and
[verification result](EVIDENCE_VERIFICATION.json) cover the reports, raw runs,
private harnesses, copied recovery backup and cumulative live ledger. Pytest symlinks
are recorded without following them. [Cleanup](CLEANUP.json) records stopped owned
containers; volumes and images are retained.
