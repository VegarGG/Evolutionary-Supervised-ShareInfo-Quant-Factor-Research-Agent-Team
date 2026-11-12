# Phase 3 resource measurements

The synthetic pilot ran on the existing native ARM64 Docker VM with 18 vCPUs and
7.75 GiB RAM. Each test evaluator used one vCPU and a 1.5 GiB cgroup limit.
PostgreSQL used one vCPU and a 512 MiB limit. The initial test profiles ran one evaluator
replica. The evaluation, registry and MCP services ran on the Mac through Docker.

| Measurement | Observed |
|---|---:|
| Idle small stack, sampled simultaneous RAM | 1,012 MiB |
| 30-factor small-panel rung, sampled simultaneous RAM | 1,207 MiB |
| Full synthetic ingest, cgroup peak | 769 MiB |
| Full synthetic ingest wall time | 14.06 s |
| Full synthetic snapshot and research snapshot together | 60.6 MiB |
| Full-panel DSL factor, sampled simultaneous RAM | 1,128 MiB |
| Full-panel Python factor, sampled simultaneous RAM | 1,628 MiB |
| 1-vCPU full-panel DSL reproduction | 2.88 s wall time and 663 MiB cgroup peak |
| 2-vCPU full-panel DSL reproduction | 3.53 s wall time and 862 MiB cgroup peak |
| Docker backing filesystem during ingest | 452 GiB total and about 349 GiB available |

Both CPU replays matched the same result hash. Each had one observation,
including one-shot container overhead. One vCPU is a reasonable starting limit
for this evaluator workload. The results do not establish the faster
configuration across cold caches or concurrent workloads.

The deployment configuration sets an 8-vCPU and 200-GiB disk minimum. For a
synthetic pilot, retain the measured RAM class of roughly 8 GiB and the existing
one-worker profile. Eight VM vCPUs remains a provisional allocation based on the
deployment minimum. The campaign did not resize Docker Desktop or establish
whole-VM performance at eight vCPUs. Use the configured 200 GiB disk floor
pending CN snapshot growth, retention and overlapping backup measurements.

The 80 × 700 workload accumulated 1, 5, 10 and 30 factors and evaluated every
factor on W1. The 300 × 2,600 workload established native ingest and single
DSL/Python factor operation. It did not establish capacity for a long CN
campaign. Resource readings distinguish sampled simultaneous RAM from cgroup
peaks. The JSON evidence records raw timestamps and worker job durations.

SC5's decision-to-visible component passed on the measured sample. Across 31
DSL factors, the median import-receipt-to-visible-W1 lower bound was 103.25 s.
Subtracting fingerprint and evaluation job durations left 102.15 s, above the
60 s scheduler allowance. Faster worker CPU alone would not remove that delay.

See [Phase 3 measurements](PHASE3_METRICS.json),
[latency calculations](PHASE3_LATENCY.json) and [run index](RUN_INDEX.json).

## Verified CN release and disk growth

The independent release is `2026-11-09`. The 570,765,642-byte archive matched
the upstream SHA-256. Both runs use the documented explicit digest because
the manifest parser rejects the release's `archive_sha256` field. Both CN
profiles pin every service to CPUs 0–7 in the existing VM.

| CN ingest measurement | CSI 300 diagnostic | Configured CSI 300 and CSI 500 |
|---|---:|---:|
| Panel rows | 4,536,682 | 9,339,616 |
| Distinct instruments over history | 948 | 2,029 |
| Calendar dates | 6,505 | 6,505 |
| Run wall time including one-shot overhead | 20.11 s | 30.10 s |
| CPU cap | 1 vCPU | 1 vCPU |
| Memory limit | 2 GiB | 3 GiB |
| Ingest cgroup peak | 2.00 GiB | 2.91 GiB |
| `memory.events` maximum-limit events | 1,934 | 0 |
| OOM events or kills | 0 | 0 |
| Full snapshot | 199 MiB | 409 MiB |
| Research snapshot | 133 MiB | 270 MiB |
| Extracted raw files | 847 MiB | 847 MiB |
| Raw close share in accepted range | 99.9944% | 99.9892% |

The research cut was 2019-12-31. One universe member lacked upstream feature
data in each build. The archive is stored separately on the host and occupies
about 544 MiB. A two-worker synthetic five-factor batch measured 2.07 GiB of
sampled simultaneous stack RAM. Both workers had one vCPU and a 1.5 GiB cgroup
limit. That batch measured a capacity rung with two replicas.

At 409 MiB per full snapshot, a scenario with about 22, 64 and 260 distinct
builds over 30, 90 and 365 calendar days adds roughly **8.8, 25.5 and 104 GiB**
to Docker storage. A full mirror on the backup filesystem adds comparable
space there. The forecast holds compressed snapshot size constant and assumes
roughly weekday releases. Actual files grow with each release. Research
snapshots are rebuilt on epoch changes. The scheduled path retains two raw
archives and the current extraction. Database, series, logs, exports, images,
backup dumps and restore scratch require their own allowance. With 200 GiB of
dedicated Docker storage and a 40 GiB free-space target, this release scenario
leaves about 56 GiB for other Docker use after one year.

Use the tested eight-CPU service set and 8 GiB RAM class for the staged offline
pilot. A 3 GiB ingest cap completed the full panel with 0.09 GiB of measured
headroom. Provisioning 4 GiB for ingest gives additional headroom for larger
releases. The draft's configured memory expectation is 24 GiB for production.
The local campaign did not measure production load from live research,
multiple evaluators and maintenance operating together.

[Verified release](https://github.com/chenditc/investment_data/releases/tag/2026-11-09)

For the 31-factor synthetic latency sample, decision-to-visible median/p95 was
0.93/1.46 s. The import-receipt-to-visible-W1 lower bound was 103.25/110.50 s.
Time outside the measured fingerprint and evaluation jobs was 102.15/109.34 s.
P95 uses inclusive interpolation. These percentiles describe the observed
sample and the acceptance comparison uses the median.

## Full-panel evaluator memory ladder

| Worker / replay limit | Same full-CN factor and snapshot | Outcome |
|---|---|---|
| 1.5 GiB | First fingerprint | Docker OOM-killed the evaluator container, exit 137 |
| 2.5 GiB | Fingerprint, then W1 screening | Fingerprint completed. A screening child was OOM-killed. The draft reported a CPU limit |
| 3.5 GiB | W1 and fresh replay | W1 produced its official record. A fresh replay reached the cap, recorded an OOM kill and returned no result hash |
| 4.5 GiB | Three fresh replays of the same saved W1 record | Exact hash matched in all three. Wall time was 12.54, 12.04 and 12.08 s. Cgroup peaks were 4.41, 4.11 and 4.17 GiB, with zero OOM events |

All these CN evaluator steps use the same eight-CPU service set and one vCPU
per worker. Replay runs use fresh processes. The host's page cache was retained.
The 4.5 GiB replays ran with the idle evaluator paused, and the high-memory CN
ladder paused the separate synthetic project. The draft's 6 GiB per-worker limit
provides headroom above the measured full-panel replay peak. Its default
two-worker production profile and live research remain outside this sizing
evidence. For the serial offline pilot, **8 vCPUs, 8 GiB RAM and 200 GiB disk**
is a starting allocation with one evaluator and staged ingest and replay.

The four additional full-panel candidates all reached W1 at 4.5 GiB. The
worker's cgroup peaked at **4.24 GiB** with zero OOM events, and the sampled
simultaneous CN stack peak was **4.62 GiB**. The batch and its selected hash
replay took 150.13 seconds. This time includes the normal scheduler waits and
the paused-worker replay. The first and four additional candidates together
supply the five-factor full-panel rung.
