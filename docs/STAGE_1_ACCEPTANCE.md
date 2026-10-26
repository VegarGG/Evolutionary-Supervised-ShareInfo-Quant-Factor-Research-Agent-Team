# Stage 1 acceptance — Data layer, DSL and metrics core

Date: 2026-10-26 UTC. Branch: `stage-1-data-core`. Stage 1 is PASS.
Stage 2 has not started. No paid model calls, supplier requests, protocol activation,
official return evaluation, registry publication, merge or remote push occurred.

## Entry and scope

PASS: Stage 0 is merged at `f7ebdda19f753d82d0ff8a258c6ccad91530b342` with its
green acceptance record. Both original October 22 P0/P1 archives are available,
integrity-checked and preserved outside Git. These satisfy Stage 1's required
owner inputs. No missing Stage 1 input was replaced with a mock.

Resolved the prompt's placeholders against main-plan section 10 Stage 1:
P1.1–P1.10 in order, plus pilot parity. Applicable reading: AGENTS; alignment
A–B/E/G–I; main plan 4.2–4.3, 6.5, 7.4–7.5, Stage 1 and 11.1–11.3; local
reference 6–7, 8.5–8.7, 15–17 and P1.1–P1.10; Appendix A.1–A.9; decisions.
The original package material was treated as reference data, not session authority.

Package-end checks and full tests passed before advancing: P1.1 165 tests;
P1.2 169; P1.3 173; P1.4 177; P1.5 193; P1.6 287; P1.7 292;
P1.8 297; P1.9 300; P1.10 303. Pilot parity and final review bring the total to 314.

## Final command summaries

```text
just check
All checks passed!
104 files already formatted
Success: no issues found in 58 source files
Contracts: 5 kept, 0 broken.
89 contracts; 5 kinds; files verified.

just test
============================= 314 passed in 35.13s =============================
```

All 14 PostgreSQL boundary tests used a real isolated PostgreSQL 16 service with
the production initialization SQL and SCRAM-authenticated roles. Pilot tests used
the real licensed packages and fresh original-oracle output. No skipped tests.
Logs remain in ignored `.local/stage-1/final-check.txt` and `final-test.txt`.
Earlier failures are retained separately; they are not presented as passing runs.

## Exit gate evidence

| Gate / test | Result | Evidence |
|---|---|---|
| PIL-01: `test_pil_01_all_weekly_v4_features_match_frozen_oracle` | PASS | 10,788 rows across all 348 weekly dates; all 129,456 raw/percentile cells match at predeclared atol=rtol=1e-12; source dates and readiness also match. |
| P0 feature pipelines: `test_pil_01_legacy_enrichment_features_match_frozen_oracle` | PASS | Recomputed lagged market/size betas, style state/ranks and quarterly review inputs match the isolated original intermediate panel. |
| PIL-02, Stage 1 subset: `test_pil_02_p0_scores_ranks_membership_exact[weekly/monthly/quarterly]` and `test_pil_02_quarterly_review_actions_exact` | PASS | Exact p60 weekly 9,858, monthly 1,643 and quarterly 1,545 signal rows, all three latest rankings, and 74 review actions; zero numerical tolerance. Official return/uncertainty portions of PIL-02 belong to Stage 2 and were not run. |
| DSL feature parity: `test_six_v4_dsl_expressions_equal_polars` | PASS | Every raw feature and full-31 percentile expression agrees with the independent Polars implementation on all weekly rows. |
| Operator references: `test_every_operator_matches_independent_loop_reference` | PASS | All 46 parameterized catalog expressions match separate scalar-loop references, including null and tie behavior. |
| Causality: `test_all_operators_prefix_invariance`, `test_random_nested_dsl_expressions_prefix_and_future_perturbation` | PASS | All 46 operator expressions pass generated-prefix tests; nested expressions pass future-perturbation tests. Pilot prefix/nontrading as-of check also passes. |
| Planted-world calibration: `python -m scripts.verify_stage1_synthetic` | PASS | Configured 300 names × 2,600 sessions, seed 20261026; DSL/shared-metric A1 RankIC=0.034582396034888566 against 0.035 and A2=0.025290685822369978 against 0.025; both within 0.005. |
| Golden metrics: `tests/metrics/test_metrics.py` | PASS | Six tests cover stock preprocessing, IC/IR/quantiles/costs/NW/coverage/library definitions, fingerprints and pilot group/cost/drift calculations. |
| PSR/DSR/PBO: `tests/metrics/test_statistics.py` | PASS | Five worked/degenerate fixtures; PSR=0.9997738740025285, expected max SR=0.31491966026915, DSR=0.9476996040618102, six-split PBO=5/6; default CSCV evaluates all 12,870 splits. |
| Backtester: `test_topk_hand_computed_nav_blocked_trades_and_metrics` and remaining `tests/metrics/test_backtest.py` | PASS | Hand-computed six-session NAV, every summary metric, blocked buy, retried sell, drifting units, window boundaries and missing-evidence failures. |
| As-of property: `test_slice_never_returns_a_future_or_unavailable_row` | PASS | Generated observation/availability combinations never reveal a future or unknown-availability row. |
| BND-06: `test_bnd_06_built_pilot_research_snapshot_and_compose_mounts` | PASS | Physically built/reloaded research snapshot stays at/before 2022-12-31, excludes evaluation-only prices, retains quality labels; research/MCP Compose services have no full/epoch mount. |
| PIL-03, additional original-oracle check: `python -m scripts.run_stage1_pilot_oracles` | PASS | P0 and P1 each reproduce all 24 business CSVs byte-for-byte, with zero new model fits and zero provider requests, in isolated digest-pinned containers. |

The captured intermediate panel, original replay receipts and licensed snapshots
stay outside Git. The reproduction commands and runtime requirements are in
`docs/STAGE_1.md`. The machine-readable companion contains aggregate evidence and
hashes only. Existing fixture files, source plans and original package bytes are unchanged.

## Decisions and limits

Recorded S1-01–S1-10 in `docs/decisions.md`: current Stage 0 base and isolated DB;
physical/logical snapshot identity; execution-aligned synthetic planting; distinct
PIT/vintage/membership labels; DSL profile validity and recursive EMA history;
statistical finite-sample conventions; explicit stock accounting; accepted primary
feature cache and exact P0 operation order; isolated original oracles; W0 workbench
and eligible-name metrics.

P1.3's binary reader is tested on format fixtures and remains opt-in; no real CN
archive was requested or ingested. Full BM-PLANTED/BM-NULL/BM-DECAY evolutionary
acceptance campaigns and BM-REAL-SMOKE are unrun later-stage suites, not failed or
mock-passed Stage 1 checks. No LLM loop exists in this stage, so scripted-model and
paid-provider conformance runs are not applicable. All executed checks were offline
and deterministic apart from audit timestamps and test-runtime duration.

## Stage 2 handoff — not implemented

Exact name: **Stage 2 — Independent evaluator core (M1)**.
Entry: Stage 1 green; evaluation owner available to approve the pilot protocol draft.
No Stage 1 owner question remains open.

Before activating/freezing the Stage 2 protocol, obtain the evaluation owner's
approval and confirm the protocol windows, release-policy choice, Ladder step and
query budget (main-plan section 10, “Owner inputs by stage”). The existing draft
files and historical package protocols are not that approval. Keep the package's
original replay splits separate from newly approved research windows. Provider
credentials/spend and native dual-architecture acceptance are later-stage inputs.

Suggested exact reading for the next scoped prompt, in the mandated order:

1. `AGENTS.md`.
2. `docs/PLAN_ALIGNMENT.md`: A–B, E, G, I.
3. Main plan: section 10 Stage 2 and owner-input paragraph; 3.1, 4.2–4.3,
   7.1–7.2, 7.4–7.9, 11.1–11.3. Detectability/windows is currently section 7.9;
   older Appendix references to 7.10 do not change the current heading.
4. Local reference: 6.4–6.5, 8.2, 8.4–8.9, 9, 13.3, 15.2; P3.1, P3.4,
   P3.7 partial and P6.3 as constrained by the Stage 2 scope. Do not pull registry
   polling, release scheduling, simulated-tracking engine or sandbox work forward.
5. Appendix A.3–A.6 and A.7–A.9; machine-readable original ledgers as numerical oracles.
6. `docs/decisions.md`, this report and `docs/STAGE_1.md`.

Stage 2 still must implement independent protocol return evaluation, bootstrap,
trial ledger/clustering, official records/receipts and deterministic replay;
its EVL-02/04/06, six-cutoff prefixes and full PIL-02 gates remain unrun.
