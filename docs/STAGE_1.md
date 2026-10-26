# Stage 1 implementation

Entry: merged Stage 0 (`f7ebdda19f753d82d0ff8a258c6ccad91530b342`), with its
recorded green gate and both original October 22 delivery archives available.
Scope is main plan section 10 Stage 1, local P1.1–P1.10. Stage 2 stays deferred.

## P1.1: canonical data and snapshots

`dense_panel` inserts missing calendar observations between each instrument's
first and last observation. Missing prices remain null, and no return bridges
a missing observation. Snapshot files are staged and atomically renamed to a
content-addressed directory. Repeated writes verify existing bytes. Every write
records principal, request ID and UTC time in an append-only filesystem event log;
event timestamps are outside deterministic snapshot identity.

Physical SHA-256 hashes check exact Parquet bytes. Logical hashes include the
schema, grain and rows sorted by grain, with sorted columns, exact float hex
encoding, normalized signed zero, and nulls. NaNs normalize to null; infinities
and duplicate/null keys fail. Text, including Chinese labels, is unchanged.
The snapshot ID covers the canonical manifest excluding its self-referential ID,
including physical and logical hashes, profile, exposure and data conventions.
Different Parquet encodings can retain logical identity while producing distinct
snapshot IDs and physical hashes. Panel files are partitioned by year.

Validation: `tests/data_layer/test_snapshots.py` covers dense calendars, hash
semantics, immutable reuse, tampering, research cutoffs and provenance events.

## P1.2: synthetic worlds

The generator uses fixed innovations, Student-t idiosyncratic returns, market and
industry components, causal price/volume signals, suspensions and annual universe
churn. Coordinate bisection calibrates alpha coefficients against the realized
RankIC on eligible names, including price limits. Calibration failure is an error.
The null world has exactly zero planted coefficients; decay disables A3 halfway
through its configured synthetic W2. Ground truth is returned separately for the
evaluation/benchmark harness, never as a research panel column.

## P1.3: optional stock import

Qlib binary reading uses little-endian float32 calendar offsets without installing
Qlib. Local archive imports require an authorization reference, a release tag and
verified SHA-256, and reject archive traversal, links and oversized expansion.
Missing required fields fail. The reader retains membership intervals, densifies
the calendar, derives raw prices, checks price/volume conventions and flags likely
corporate-action mismatches. The benchmark's equal-weight fallback is recorded
explicitly when SH000300 is absent, as required by local section 6.2. ST limits
and unverified source vintages remain limitations. No supplier fetch is enabled.
Tests use synthetic binary-format fixtures; real CN-source acceptance is not claimed.

## P1.4: pilot adapters, as-of slices and physical zones

The pilot adapter verifies the seven pinned source hashes (six input files plus
the label map) against both Stage 0 metadata and the original package inventory.
It creates calendar, universe, daily prices, weekly panel, features, fundamentals
and backfilled membership tables. Evaluation-only prices stay in the full zone.
The six input values and original text are preserved. Semiannual financial
availability follows the documented September 1 / following May 1 rule; missing
or unsupported dates cannot acquire invented availability.

Weekly market rows remain available on their observation date; their original
financial availability is retained separately, and values with unknown financial
availability are rejected. This preserves market warm-up rows without treating
missing fundamentals as known. As-of slicing filters both observation and
availability dates and excludes unknown availability. Each zone is physically
written with its own ID. Synthetic ground truth is full-zone-only.

`qfr data build` requires an explicit source, config, cutoff, output, principal,
request ID and build-code version. Pilot imports additionally require the package
and pinned fixture metadata. CN ingest additionally requires the supplied release
archive, hash, tag and authorization reference. It does not download data or run
research/evaluation jobs. Example:

```sh
qfr data build --source pilot --config configs/data/pilot_import.json \
  --package /authorized/P1_English_Delivery_20261022 --fixtures fixtures/pilot \
  --output /authorized/snapshots --cutoff 2022-12-31 \
  --principal operator --request-id explicit-request --build-code-version COMMIT
```

The cutoff above reproduces a draft research-zone example; it does not activate
or approve the draft evaluator protocol. BND-06 checks the physically built pilot
snapshot and the existing Compose mount boundaries. Property tests check arbitrary
observation/availability pairs. CLI tests prove ground truth stays out of research.

## P1.5: typed closed DSL

The Lark parser admits only numeric expressions, whitelisted fields/operators and
literal allowed windows. It enforces arity, constant precision/range, AST size,
depth, field/constant counts, explicit window-path budgets and Corr/Cov nesting.
No dates, identifiers, strings, variables or executable Python are available.
Canonicalization sorts commutative operands, removes double negation/nested Rank
and folds constants only when the exact result remains representable. Hashes use
the canonical string. AST similarity uses the largest identical subtree.

EMA retains the specified recursive, unadjusted semantics. Its reported window
budget is its declared smoothing window; `recursive_history=true` explicitly
records that its influence is not a finite mathematical lookback. Consumers must
retain its complete authorized prefix, never truncate it to the smoothing window.
Pilot and stock operator policies are separately versioned: the pilot requires
complete windows to preserve its frozen price-feature definitions; stock uses
the specified 80% rule for windows of at least five observations. Rank is average
rank divided by valid count, matching the original full-31 pilot percentiles.

## P1.6: causal operators

The operator compiler materializes each AST node before applying the next grouped
window, so nested time-series/cross-sectional operators keep their correct grain.
Native Polars rolling statistics and small rolling regression/weighted callbacks
run over the dense calendar. Pairwise statistics use complete pairs; zero/invalid
denominators and non-finite results become null. Cross-sectional operations use
the declared eligible mask. Extremum ties use the most recent observation.
Skewness and excess kurtosis use finite-sample bias correction.

Every operator is compared with an independent Python scalar-loop reference.
Property tests recompute historical prefixes for every operator and perturb the
future for nested expressions. These are causality tests, not certification of
historical source vintages or investment performance.

## P1.7: shared metric definitions

Stock metrics use execution at close t+1 and labels ending at close t+1+h; both
decision and label endpoint must lie inside the supplied measurement window.
The library implements preprocessing, Pearson/rank IC, per-period IR, Bartlett
Newey–West t, decay, equal-count quantiles, gross/net long-short returns, turnover,
autocorrelation, coverage, size-neutral diagnostics and library correlations.
The first basket entry has turnover one; later entries use set overlap. Missing
or degenerate statistics carry an explicit `insufficient_data` reason.

Pilot primitives keep top/bottom recall, three-class and directional accuracy,
raw/action Rank IC, basket returns and drift/cost accounting separate from stock
hit ratio. They accept already-mature period inputs; no evaluation protocol is
run or activated. Cost is deducted before the holding return, initial notional
is one, full replacement two, and liquidation is explicit.

Behavioral fingerprints use only W0 dates and require an explicit frozen seed;
the unresolved production seed is not silently filled. Golden tests use five
instruments across eight dates, plus hand-computed covariance, Newey–West,
percentile, basket-cost and drift examples.

## P1.8: statistics primitives

PSR uses per-period Sharpe and raw Pearson kurtosis. DSR accepts the complete
caller-supplied trial vector and effective count, reporting both counts and sample
Sharpe variance. No trial ledger or clustering job is implemented in this stage.
CSCV enumerates every half-block split (12,870 with the versioned S=16 default),
uses ascending average OOS rank divided by N+1, and returns a missing measurement
if any split has undefined Sharpe. Tests pin independently calculated moments,
normal probabilities and all six ranks of a small CSCV example. Missing or
degenerate observations cannot turn into a passing statistic.

## P1.9: reference stock strategy and P1.10: workbench

The stock strategy executes decision-t ranks at t+1 close, retains drifting
units, retries blocked sells, skips blocked buys, and funds costs from cash.
Turnover is half traded notional/pre-trade NAV; completed positions supply the
average holding period in trading sessions. Suspended missing quotes retain the
last known mark with an explicit carried-mark count. Missing tradable quotes or
benchmark returns fail. Tests pin the six-session NAV and every summary metric.

The workbench verifies a research-zone snapshot, rejects a W0 end beyond its
cutoff, truncates all data before computing labels, uses shared metric functions,
and labels results `official=false`, `in_sample_optimistic`. Its pilot helper
accepts an explicitly supplied mature W0 interval; it does not implement a
protocol, publication schedule, official evaluation or forward campaign.

## Pilot feature and P0 parity

Appendix A.2–A.3 explicitly designate `run_snapshot`'s six files, including the
71-column engineered feature cache, as primary inputs. The new P0 pipeline uses
that accepted cache, recomputes lagged size-style regressions and quarterly
review inputs, then independently computes weekly/monthly/quarterly scores,
rankings, frozen-quarter membership and monthly replacement actions. It neither
imports the original runtime nor reads reference scores to produce its results.
It does not claim to rebuild unavailable pre-package stock/breadth histories.

The weekly formula retains the delivered sequence of substitutions and additions:
algebraic simplification changes low floating-point bits and fails exact parity.
All parameters live in `configs/pilot/p0_scoring.json`. P0 p60 histories and latest
rankings must match every reference cell with zero tolerance. Six independent
Polars price features and their full-universe percentiles must match the isolated
P1 replay's captured intermediate panel at the predeclared 1e-12 absolute/relative
tolerances. Every feature also has a DSL expression with identical values.
`assert_parity` stops at and identifies the first differing cell.

## Reproducing Stage 1 checks

Set `QFR_PILOT_ROOT` to the directory containing both original extracted packages,
`QFR_TEST_POSTGRES_DSN` to the isolated PostgreSQL 16 test service, and
`QFR_PILOT_ORACLE_ROOT` to the oracle output root. Without either pilot variable,
the licensed-input tests explicitly skip; such a run is not Stage 1 acceptance.
The acceptance run has no skipped tests.

Run the original oracles explicitly with:

```sh
uv run --locked --all-packages python -m scripts.run_stage1_pilot_oracles \
  --packages "$QFR_PILOT_ROOT" \
  --dependencies /path/to/separate-original-dependencies \
  --output /path/to/fresh-oracle-output
```

The original dependency directory must contain NumPy 2.3.5 and pandas 3.0.1;
it is separate from QFR's locked runtime. The command requires the locally cached
digest-pinned Python 3.12.14 image in `configs/pilot/oracle_runtime.json`; it does
not download dependencies or choose another image. Containers have no network,
run as the invoking non-root UID, have a read-only root and read-only package,
dependency and harness mounts, dropped capabilities, process/CPU/memory limits,
and only a fresh output directory writable. A timeout fails and removes that
task-owned container. This is a task-local original-oracle harness, not the Stage
3 execution sandbox or a production isolation certification.

The package itself verifies all 24 business CSVs and forbids other-model fitting.
The harness captures the single existing price-feature return after the replay;
it does not modify source files. Captured data and receipts stay outside Git.

```sh
just check
just test
uv run --locked --all-packages python -m scripts.verify_stage1_synthetic
```

The last command runs the configured 300-name, 2,600-session planted world through
the DSL and shared stock metrics, independently of the generator's internal
calibration measurements. Its JSON evidence goes to ignored `.local/stage-1/`.
BM-PLANTED/BM-NULL/BM-DECAY acceptance/evolution campaigns remain later-stage work.
