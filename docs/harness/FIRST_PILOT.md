# First harness work package — 12 November 2026 Beijing

The DSH SDK and native plugin seams work locally. **This is not yet acceptance of
a multi-agent research architecture.** The first known-answer problem was solved
by the single-agent baseline as well as every collaborative variant; collaboration
added cost and latency without a measured accuracy benefit on this case.
The separate [validation record](VALIDATION.md) lists checks, failures, retests,
skips and UI screenshots.

The work uses the original repository, on `codex/quant-factor-harness`, from main
`5a5c4d035333c9018346da1c500789bb484f75c0`. DSH SDK/runtime is pinned to 0.2.2rc2,
reviewed upstream source `e8f7b93a344964de3dca1ace9e72b6e4d6de87cb`. DSH owns
actual inference loops, role sessions and tool execution. Python owns the budget
boundary, evidence store, data adapters and experiment records. No DSH agent-loop
fork or old QFR orchestrator wrapper is included.

## Real model experiment

Ten runs, 24 actual DeepSeek requests, one synthetic known-answer case about unit
conversion and publication/ingestion/next-close availability. The model response
field was `deepseek-flash` throughout; an alias does not prove the server's internal
model identity. No other paid model provider was used. The full structured outputs,
contribution IDs, manifests and resource/token metrics are in
[RESULTS.json](evidence/diagnostic-2026-11-12/RESULTS.json), with a
[private-artifact hash index](evidence/diagnostic-2026-11-12/RAW_MANIFEST.json).

| Treatment | Runs | Actual calls per run | Mean conservative CNY | Mean provider span |
|---|---:|---:|---:|---:|
| Single agent | 3 | 1 | 0.028440 | 18.34 s |
| Shared blackboard | 3 | 3 | 0.098607 | 54.50 s |
| Independent proposals plus aggregation | 1 | 3 | 0.074812 | 43.51 s |
| Self revision | 1 | 3 | 0.107386 | 54.23 s |
| Iterative review | 1 | 3 | 0.105472 | 58.83 s |
| Debate | 1 | 3 | 0.159368 | 96.09 s |

All ten final answers passed the known answer: first signal 2024-04-30, first
execution 2024-05-06, cash-flow/assets ratio 0.02, and supplied source IDs covered.
That automated check is narrow; citation presence is not general claim verification.
Manual inspection found appropriate limitations rather than a measured-profit claim.

Combined source evidence, model settings and aggregate requested output allowance
(24,576 tokens) were held equal. Call counts and actual compute were **not equal**:
single used one request and collaboration three. All treatments used both sources
directly, so this does not test hidden distributed knowledge. The runs were
sequential, not randomized; later warm caches may confound mechanism comparisons.
Only single/blackboard have three repetitions. One easy case cannot estimate a
reliable effect or rank the other mechanisms. More difficult cases, randomized
repeats and unseen open-ended cases remain required before the minimal-core gate.

## Cost, cache and local resources

- New conservative charge: **0.828178 CNY**. Original carry: **56.256735 CNY**.
  Cumulative **57.084913 / 200 CNY**, unresolved reservations zero, remaining
  **142.915087 CNY**. These are deliberately conservative token-based charges,
  not an invoice-verified account balance. No paid calls were needed for the
  free-data addition.
- 55,121 uncached input, 16,128 cache-read input, zero cache-write and 85,710 output
  tokens: **156,959 total**. Weighted input cache hit rate **22.64%**.
- Peak rolling 60-second dispatch RPM **4**. TPM **32,711** attributed at dispatch
  or **33,878** at completion. This attribution does not measure per-token streaming
  arrival or benchmark the account's maximum throughput.
- Sequential prototype on macOS/Darwin 27.2 ARM64, 18 logical/physical CPUs,
  36 GiB RAM: sampled process-tree RSS peak **556.86 MiB**, host CPU maximum
  **19.1%**, zero observed swap, minimum Work-volume free space **344.75 GiB**.
  Host readings include unrelated host activity. This is not VM sizing or a
  500-concurrency capacity result.

The first two live runs preceded the improved source-hash manifest. Their source
record was captured during the initial pair, not falsely described as a pre-run
freeze. Subsequent runs pin implementation/runtime inputs in their manifests.
Full private wire/session artifacts are retained under `.qfh-private/campaign`.
The public export excludes DSH homes and credentials.

## Data and interface

[BaoStock was selected and tested](DATA_SOURCES.md) as the free data default after
small live BaoStock and AKShare/Eastmoney comparisons. iFind and RQData remain
available with DSH-managed credential entry and independent, persistent quotas.
The native DSH tool loop successfully reads real cached BaoStock evidence using
synthetic model replies. This is distinct from both the 24 live diagnostic model
requests and the real provider transport calls; no combined live-model/live-data
factor-discovery run is claimed.

The local web profile is a **credential/settings setup profile with model providers
disabled**. Paid experiments run through the guarded SDK runner. An interactive
research-chat profile sharing that guard is still future work; entering a data
credential does not yet turn this profile into a complete research frontend.

Offline tests cover budget races, restart/unknown usage, schedules, SSE accounting,
source pinning, quota exhaustion, cache permissions, credential redaction, row
validation and bounded BaoStock transport. Native DSH smoke failures exposed and
fixed three integration details: sdk-minimal needs an explicit local credentials
service; plugins must resolve as installed packages; volatile settings use `.get()`.
The retained smoke directories include these failed attempts and successful retests.

## Capability card and next gate

**Demonstrated:** real DeepSeek role inference; shared/independent/review/debate
step wiring; checkpointed results; persistent budget enforcement; small data
fetches, immutable evidence and a native DSH settings/tool extension.

**Not demonstrated:** improved factor research, production alpha, a stable
general cache-hit target, large/concurrent workloads, paid iFind/RQData live access,
full PDF/news content extraction, or the complete Hybrid v1 system.

Next work should add difficult diagnostic failure cases, counterexamples and
equal-evidence controls; repeat them in randomized order; then use bounded frozen
real-data evidence for open-ended daily A-share cases. Retain initial/final claims,
support checks, rejected peer contributions, resource/cost measurements and failed
attempts. Select only modules with an observed benefit before building the minimal
supervisor/two-worker core. The one-case result does not authorize a complexity
increase by itself.
