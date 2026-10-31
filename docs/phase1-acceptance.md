# Phase 1 implementation and acceptance record

Status: **implemented; every Phase 1 acceptance check passes in local tests; ready
for owner review**. Owner acceptance and merge are not asserted. No Phase 2 work has
begun. Design choices and findings are in [decisions.md](decisions.md#phase-1-decisions).

## Acceptance checks

| Check (plan, Phase 1) | Result | Evidence |
|---|---|---|
| Every operator matches its reference implementation, and prefix-invariance property tests pass for all operators | Pass | `tests/operators` (644 tests): each operator against a naive reference in `tests/reference_ops.py`; Hypothesis prefix-invariance for single operators and random expressions |
| On the planted world, the RankIC of A1 and A2 is within 0.005 of the calibrated target | Pass | `tests/ingest/test_synthetic.py::test_acceptance_planted_rank_ic_is_within_0005_of_target` on the default world (300 names, 2,600 days): A1 0.0339 against 0.035 and A2 0.0266 against 0.025. The null world gives -0.0015 and 0.0003 |
| Hand-computed fixtures pass for metrics, PSR, DSR, PBO, the backtester and the composite | Pass | `tests/metrics` (24 tests): hand-computed IC, RankIC, quantiles, turnover and Newey–West; PSR and DSR against worked values; PBO against an enumerated S = 4 case; backtests with blocked buys and sells; composite weights, signs and hash |
| BND-06 passes for a built research snapshot | Pass | `tests/data/test_snapshot.py` (the research snapshot ends at the cutoff; a forged manifest is caught from the data), `tests/ingest/test_cli.py` (`qfr data verify --zone research` passes and refuses the full snapshot), `tests/test_workbench.py` (the workbench refuses the full snapshot), `tests/boundary/test_compose.py` (mount isolation) |

## Delivered scope

| Task | Delivered | Main tests |
|---|---|---|
| P1.1 | Dense canonical panel, manifest, content-addressed ids, atomic writes, verified reads | `tests/data` |
| P1.2 | Planted, null and decay worlds; calibrated alphas; ground truth in the full snapshot only | `tests/ingest/test_synthetic.py` |
| P1.3 | Qlib binary reader; CN ingest with checksum before extraction, safe extraction, point-in-time membership, tradability flags, raw prices, sanity checks | `tests/ingest/test_cn.py` |
| P1.4 | Zone builder; `qfr data build --source synthetic\|cn` and `qfr data verify`; Compose data-ingest service and `just data-build` | `tests/ingest/test_cli.py`, `tests/boundary/test_compose.py` |
| P1.5 | `qfr-dsl/1`: Lark grammar, type checker, static limits, canonicalizer and hash, complexity, AST similarity, AST diff | `tests/dsl` |
| P1.6 | Polars operator library with the calendar-based validity rule; naive references | `tests/operators` |
| P1.7 | Preprocessing, IC, RankIC, IR, Newey–West t, decay, quantiles, long-short gross and net, turnover, autocorrelation, coverage, library correlation, fingerprints | `tests/metrics` |
| P1.8 | PSR, DSR, PBO (CSCV) | `tests/metrics/test_statistics.py` |
| P1.9 | TopK-dropout backtester with tradability, costs and the contribution table | `tests/metrics/test_backtest_fixture.py` |
| P1.10 | Strategy composite and its canonical hash | `tests/metrics/test_composite_fingerprint.py` |
| P1.11 | W0-only workbench for factors and composites on the research snapshot, with the evaluator's code | `tests/test_workbench.py` |

Nothing is preloaded: no factors, strategies or pool entries. The planted signals
exist only as test infrastructure in the full synthetic snapshot's ground-truth file.

## Checks executed

- `just check` passes: ruff, formatting, mypy (strict for core and MCP), all four
  import contracts, schema and public-card generation with no diff.
- `pytest`: 825 passed, 3 skipped. The skips are the PostgreSQL integration tests,
  which need the CI or `just test-db` database; CI runs them. The default-size
  planted-world acceptance test is marked `slow` (about a minute) and runs by default.
- Default synthetic build: about 42 seconds and 0.7 GB peak. CN-sized ingest on a
  fake release (6.9 million rows): 24 seconds and 2.3 GB peak (decision 15).

Not executed here: Docker image builds and `just doctor`, which need Docker (CI
builds the new `eval` image target for both architectures), and a real CN ingest,
which needs network access to the investment_data release.

## Reproduction

```sh
uv sync --locked
just check
just test
uv run --locked qfr data build --source synthetic          # writes data/snapshots/
uv run --locked qfr data verify data/snapshots/research/<id> --zone research
just data-build --source synthetic                          # inside Compose
just data-build --source cn --release-tag <tag>             # downloads, verifies, builds
```
