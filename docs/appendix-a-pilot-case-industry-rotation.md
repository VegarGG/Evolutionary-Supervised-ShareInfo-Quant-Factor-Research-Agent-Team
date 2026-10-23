# Appendix A — Pilot case: the P0 / P1 industry-rotation packages

This appendix describes the first preservation/reproduction fixture the hybrid v1 system must handle. It is a case profile, not the only accepted input format. PLAN_ALIGNMENT.md governs generic intake, deployment, provider configuration and exit gates. It is written so that a coding agent can use it as the specification of the pilot fixture without re-reading the two ZIP deliveries. Every number below was read from the delivery documents or data files dated October 22, 2026 (data frozen through October 16, 2026).

Companion documents: the main plan (`HYBRID_V1_DEVELOPMENT_PLAN.md`) and the research notes (`appendix-b-research-notes.md`).

---

## A.1 What the packages are

Two self-contained offline deliveries of the same A-share **industry-rotation** research system:

- **P0** (internal name `baseline`): the original three-cycle model. Weekly, monthly and quarterly rankings of the 31 Shenwan level-1 industries, each cycle selecting a top group of 7 (top 20%, rounded up) and implicitly a bottom group of 7. Three "preference groups" p60 / p80 / p100 differ only in a monthly trend-preference parameter (0.6 / 0.8 / 1.0); they are compatibility labels, not confidence levels.
- **P1** (internal name `P1_reversal_momentum`): the "simple tuning" that was accepted as the frozen research model. A fixed rule with no fitted coefficients: `0.5 × reversal percentile + 0.5 × 120-session momentum (skip 20) percentile`, computed as full-31 cross-sectional percentiles of industry index prices. Weekly uses a 5-session reversal, monthly and quarterly a 20-session reversal. Falls back to the P0 score for any row where the six price features are not all available.

Both packages replay byte-for-byte. Neither establishes skill. The headline result that triggered this project:

| Window | Model | Weekly | Monthly | Quarterly (monthly review) |
|---|---|---|---|---|
| 2026 YTD (39 / 9 / 9 periods), top-7 hit rate | P0 | 25.64% | 20.63% | 25.40% |
| 2026 YTD, top-7 hit rate | P1 | 30.40% | 31.75% | 34.92% |
| 2026 YTD, mean Rank IC | P0 | 0.0116 | −0.0286 | −0.0047 |
| 2026 YTD, mean Rank IC | P1 | 0.0651 | 0.1183 | 0.1214 |
| 2024–2026 primary window, mean extreme-group recall (143 / 33 / 33 periods) | P0 | 24.98% | 24.89% | 25.11% |
| 2024–2026 primary window, mean extreme-group recall | P1 | 25.87% | 25.97% | 27.49% |
| P1 − P0, 12-comparison-adjusted interval (pp) | | [−3.68, +5.34] | [−9.67, +12.92] | [−8.66, +12.70] |

Random-selection reference for a 7-of-31 group is 22.58%. Every adjusted interval contains zero. All history 2022–2026 had already been inspected when P1 was chosen, so there is no clean holdout anywhere in these packages.

---

## A.2 Anatomy of the "chaotic folder"

The delivery is 150–190 files per package. The intake agent (Codex or another host MCP client) must classify a folder like this into five classes before anything reaches the research system. The table maps this delivery to those classes; the same taxonomy should drive the intake skill for future folders.

| Folder / file | What it actually is | Intake class |
|---|---|---|
| `run_snapshot/` (6 files) | The only inputs needed to recompute signals: features panel, raw industry panel, daily index prices, stock financials, trading calendar, evaluation prices | **Data (primary)** |
| `original_delivery/runtime/data/ifind/` | Stock constituent snapshot (5,548 rows, current membership) and the provider update manifest | **Data (auxiliary)**, PIT-weak |
| `original_delivery/runtime/outputs/` | Caches and business CSVs produced by earlier runs (older as-of dates, Sept 4–11) | **Derived outputs**, do not use as inputs |
| `runtime/*.py`, `runtime/research*/`, `runtime/evaluation/` | 38 frozen code files, about 6,100 lines, four generations of research code (`research`, `research_v3`, `research_v4`, `evaluation`) | **Code (baseline definitions + evaluator conventions)** |
| `runtime/config/*.json` | Model weights, eligibility thresholds, protocol toggles, Chinese operator notes | **Config (baseline parameters)** |
| `docs/*.md`, `docs/*.html`, `*.csv` label maps | Operating manual, model description, glossary, 31-industry English labels, data inventories | **Docs (business rules, glossary)** |
| `validation/`, `integrity/`, `SHA256SUMS.json`, `交付清单.json`, `reference_outputs/` | Evaluation ledgers, audit protocols and receipts, hashes, reference CSVs | **Evidence (golden numbers, protocols, hashes)** |
| `original_delivery/runtime/deployment/prediction_tracking_service_v1/` | A Windows scheduled-task "prediction tracker" with SQLite schema | **Ops precedent**, informs the simulated-tracking design |
| `run_p0.py` / `run_p1.py` | Offline replay entry with audit-hook guards (blocks network, subprocess, secrets, out-of-bundle writes) | **Reference oracle** for byte-exact reproduction |

Mixed-language reality: industry and company names, some JSON notes and some filenames are Chinese; the English docs are companions. Industry codes (`801xxx.SL`) are the stable keys; `docs/industry_labels.csv` maps all 31 codes to English names one-to-one. The system should key on codes and treat names as labels.

---

## A.3 Data assets

All figures from the P1 package's `run_snapshot/` (identical in P0).

| File | Rows | Grain | Columns | Range | Notes |
|---|---|---|---|---|---|
| `outputs/sw1_ifind/index_prices.csv` | 55,862 | daily × code | date, code, close | 2020-01-02 → 2026-10-16 | 31 industry indices + 3 benchmarks (000300.SH, 000905.SH, 000852.SH). Price indices, no dividend reinvestment. History before 2025-10-20 comes from delivery caches, later history from retrieved data; the splice is documented, with 7,548 overlapping observations matching exactly. |
| `data/ifind/evaluation_prices.csv` | 8,194 | daily × code | date, code, close | 2025-10-20 → 2026-10-16 | Evaluation-only prices; overlap with model prices verified to 1e-10. |
| `data/ifind/trading_calendar.csv` | 2,483 | daily | date, is_open | 2020-01-01 → 2026-10-18 | Authoritative exchange calendar. |
| `outputs/sw1_ifind/industry_signal_panel.csv.gz` | 10,788 | weekly × industry | 16 (ret1, ret4, breadth, amount, turnover, stock_count, report_date, available_date, revenue_yoy, profit_yoy, roe, cash_quality, inventory_gap, financial_stock_count) | 2020-01-03 → 2026-10-16 | Weekly snapshots, Friday-anchored. Fundamentals are half-year aggregates joined as-of an approximate `available_date`. |
| `outputs/factor_upgrade_v1/features.csv.gz` | 10,788 | weekly × industry | 71 | same | The panel plus every engineered P0 factor, percentile ranks, crowding, eligibility flags and scores per cycle. This is the baseline feature set. |
| `outputs/sw1_ifind/stock_finance.csv.gz` | 72,124 | stock × report period | 12 (revenue, profit, roe, cfo, inventory, yoy fields, inventory_gap) | report_date 20200630 → 20260630 | Half-year and year-end only; no Q1/Q3; no announcement dates; current industry membership mapped backward. |
| `original_delivery/runtime/data/ifind/ifind_sw_constituents.csv` | 5,548 | stock snapshot | 23 | as of 2026-09-04 | Current constituents with latest market and financial fields. Not a membership history. |

Total size is about 10 MB. Everything fits in memory; the evaluator can be a single process.

**Point-in-time (PIT) quality, as stated by the packages themselves and graded with the plan's scheme (plan section 4.2):** price observation/calendar dates are explicit, but historical revision vintages are unverified. Record timing, value-vintage and membership quality separately instead of assigning a blanket clean-PIT label. Financial availability dates are approximations set by rule rather than by announcement; the latest `available_date` of 2026-09-01 for the June 30 report matches the Chinese regulatory interim-report deadline (two months after June 30) plus one day, so the fundamentals are grade B, usable with an extra-lag sensitivity run. Index membership is current membership mapped backward, grade D. Historical index revisions are not verified, and the 31-industry Shenwan scheme was published in 2021 with the current indices launched in December 2021, so pre-2021 index-vintage reconstruction is a concern recorded as unverified in Appendix B; retain `vintage_status=unknown` with that concern rather than claim the data lineage has been proved. Only half-year financials exist. Prefer price/volume hypotheses while retaining the stated limitations; breadth may inherit current-membership bias and is not automatically PIT-clean.

**Licensing and quota:** data are licensed iFinD caches; the packages made zero new supplier requests and the research system must not fetch anything new in the pilot. New data is a separate, human-authorized step that creates a new dataset version.

---

## A.4 Business rules the evaluation protocol must encode

These come from the operating manual, the configs and `research/evaluation.py`. They become the pilot's frozen protocol; later cases will supply their own.

**Universe and benchmarks.** 31 Shenwan level-1 industries (codes `801xxx.SL`); benchmarks CSI 300, CSI 500 (primary), CSI 1000. Industry names and codes must map one-to-one; benchmarks may never enter cross-sectional ranks.

**Cycles and signal dates.** Weekly uses each weekly snapshot date. Monthly and quarterly use the last weekly snapshot inside a completed calendar month or quarter, so the signal date need not be the last trading day.

**Publication and execution.** A signal is "published" on the first weekly snapshot date at which it could have existed (weekly: same day; monthly/quarterly: first snapshot after month or quarter end). Execution is the first trading close after publication. The holding interval runs to the next decision's execution date. Intervals whose exit is not yet observable are "immature", kept in the ledger and excluded from the denominator. Decisions executing outside a requested window stay in the ledger but outside the denominator.

**Selection.** Top group = top 20% of eligible industries, rounded up (7 of 31), equal-weighted; ties broken by industry name. Bottom group = the mirror 7, evaluated as a long price-index proxy, never as an executable short.

**Eligibility.** Market indicators must satisfy warm-up requirements; monthly and quarterly need at least 60% nonmissing fundamental-weight coverage; fewer than 10 eligible industries prevents normal candidate generation. Missing factor values are filled with 0.5 (neutral) at scoring time. An `eligible_pool_hash` (order-independent SHA-256 of eligible codes) is recorded per decision and must match between baseline and challenger for a paired comparison.

**Quarterly review.** At quarter end select top 20% and freeze the full ranking. At intervening month ends replace a held industry only when its index is below its 4-week moving average and its 4-week return is below the mean CSI 500 / CSI 1000 4-week return; a replacement must come from the frozen top 50%, remain eligible, be at or above its moving average, with nonnegative 4-week relative return; fill in frozen-rank order; without a qualified replacement hold rather than go to cash; a replacement resets equal weights at the next close.

**Costs and accounting.** One-way costs 0 / 10 / 30 bps on traded notional (the manual's main case is 10 bps; sensitivity 0 and 20 bps). Costs are deducted before the holding return. Portfolio weights drift between events and the next target is compared with the drifted weights to compute turnover. First construction trades 1, full replacement trades 2. No terminal liquidation unless explicitly requested. Returns omit dividends, slippage and borrowing.

**Metrics per period.** top/bottom precision and recall (equal here because predicted and actual groups are both 7), `extreme_macro_recall` (mean of the two recalls, the primary metric), three-class accuracy and balanced accuracy, directional accuracy vs CSI 500, `rank_ic` (Spearman of score vs realized return), `action_rank_ic`, top/bottom/equal-31 returns, top-bottom spread, excess vs CSI 500 and vs equal-31, net returns at each cost level, traded notional and one-way turnover.

**Uncertainty.** Paired circular moving-block percentile bootstrap on per-period deltas; blocks 4 (weekly) / 2 (monthly) / 2 or 3 (quarterly review) / 1 (fixed quarter); display settings 2,000 draws with seed 20260101, formal settings 4,000 draws with seed 20261020; small-sample warning when fewer than 10 valid periods or fewer than 5 approximate independent blocks. Family-wise control in the original work: 12 candidate-by-cycle comparisons, 99.5833% individual intervals. The audit explicitly notes this did not cover earlier human exploration.

**Splits (from `research/evaluation.py`).** development 2020-01-01 to 2023-12-31; validation 2024; confirmation 2025; diagnostic 2026. Intervals crossing a boundary are purged from statistics but their portfolio state is carried. These are the package's splits and the golden-number tests reproduce them. The research protocol for the agent run uses different windows (development 2020–2022, validation 2023–2024, confirmation 2025 to data end) for the detectability reasons in plan section 7.10; the evaluator must support both because the first is a test and the second is the pilot.

**Diagnostics the audit used and the evaluator should offer.** Leave-one-year-out paired differences; fixed six-neighbour parameter sensitivity frozen before evaluation; whole-cross-section circular calendar-shift placebo with minimum distance 4 / 2 / 3 periods, reporting percentiles (not p-values); annual and rolling two-year tables; fixed-quarter holding as a separate convention never mixed with monthly review.

**Lookahead defence.** Prefix consistency checks: rebuild the full model state from data truncated at several historical cutoffs (the package used 2021-12-31, 2022-05-06, 2023-05-05, 2024-01-05, 2024-07-05, 2024-12-27) and assert exact equality with the corresponding rows of the full-history run. Any difference means a future observation leaked into a past signal. Fundamentals must satisfy `available_date ≤ observation date` for every row.

---

## A.5 Baseline artifacts to register at version 0

Register frozen P0 and P1 so official reproduction reports match the source and the worker has preserved baselines. P2–P4 below are historical provenance only; the standalone packages prohibit executing/fitting other models. Any later use requires a separate contract and authorization.

| Artifact | Definition (as in the delivery) | Cycle |
|---|---|---|
| `p0_weekly_style` | relative breadth change 25%, 12-week momentum 12.5%, trend persistence 12.5%, size-style sensitivity 10%, crowding adjustment 40% applied as `0.4 × (1 − crowding)` | weekly |
| `p0_monthly_m20_c40` | fundamentals 40% (cash quality, inventory gap, revenue acceleration, profit acceleration, ROE floor), market 20% (moderate-trend preference at position 0.6 / 0.8 / 1.0 by group, breadth change), crowding 40% | monthly |
| `p0_quarterly_review_v2` | fundamentals 60%, crowding 40%, quarter-frozen ranking with the monthly replacement rule | quarterly |
| `p1_reversal_momentum` | `0.5 × percentile(−5 or −20 session return) + 0.5 × percentile(P[t−20]/P[t−120] − 1)`, fallback to P0 where not ready | all |
| Historical P2/P3/P4 definitions (optional provenance) | dormant comparison code; not required baseline executions and not authorization for new fits | not run by this fixture |

The six frozen price features in `research_v4/features.py` are the natural first operator vocabulary for the factor DSL: `reverse5`, `reverse20`, `momentum120_20`, `momentum250_20`, `lowvol60`, `drawdown120`, each as raw value and full-31 percentile, joined as-of with a backward fill of at most the latest price date.

Crowding, breadth and style features from the P0 manual (participation Z-scores over 52 weeks with at least 26 observations, breadth of members above their 4-week moving average, 52-week regression size beta) are the second vocabulary tier. They depend on stock-level data with weaker timing guarantees and should be labelled as such in the artifact metadata.

---

## A.6 Golden numbers for acceptance tests

Phase 2 reproduction uses the original machine-readable ledgers/CSV outputs as the oracle (exact hit counts/ranks; numerical tolerances declared before comparison). The tables below are rounded explanatory summaries and cannot supply 1e-9 expected values. An accounting/protocol change is a new comparison, not permission to overwrite the original oracle.

**Primary window 2024-01-01 → 2026-10-16, group p60, matched entry/exit:**

| Cycle | Periods | P0 mean recall | P1 mean recall | P1 Rank IC | P1 top net excess vs equal-31 per period at 10 bps |
|---|---|---|---|---|---|
| Weekly | 143 | 24.98% | 25.87% | 0.042366 | −0.067% |
| Monthly | 33 | 24.89% | 25.97% | 0.041933 | +0.067% |
| Quarterly / monthly review | 33 | 25.11% | 27.49% | 0.064075 | +0.404% |

**2026 window (Jan 1 – Oct 18 requested; completed entries Jan 5 – Oct 12), p60:** P0 weekly top 25.64% / bottom 23.81%, 39 periods; P1 weekly top 30.40% / bottom 22.71%; P1 monthly 31.75% / 25.40%, 9 periods; P1 quarterly 34.92% / 25.40%, 9 periods. Expected slots 40 / 10 / 10 with one immature each.

**Fixed-neighbour ranges (primary window, mean recall):** weekly 24.63%–25.72% (all six below P1); monthly 23.16%–27.92% (three above, three below); quarterly 27.27%–28.57% (four above, one below, one equal). Leave-2026-out monthly difference −1.24 pp. Calendar-shift placebo percentiles for P1 − P0: 58.09% / 48.33% / 66.07%.

**Byte-exact oracle:** `python run_p1.py run --output <fresh dir>` regenerates 24 business CSVs that must match `reference_outputs/` byte for byte (UTF-8 BOM included). Use it as the oracle for the Phase 1 parity test of signals and ranks, not as code to import into the new system.

**Bootstrap reproduction:** with 2,000 draws, seed 20260101, blocks 4/2/2, the P0 weekly top-recall 95% interval is 20.88%–30.40% and the P1 weekly top-recall interval 26.64%–34.29%. Matching these confirms the block-bootstrap implementation, including NaN slot handling for immature periods.

---

## A.7 Lessons from the packages that shape the system design

1. **Selection by a human is still a search.** P1 has no fitted coefficients, yet the audit treats the choice of lookbacks, weights and candidate among many as a multiple-testing problem. The system therefore counts every evaluated artifact version, human- or agent-authored, in its family-wise accounting.
2. **"Already inspected" history is never a holdout.** Sealing previously inspected history does not restore an unseen holdout. The evaluator can restrict access for a new controlled experiment but must retain the prior-exposure label; only genuinely prospective evidence can support an unseen-performance claim.
3. **Hit rates and after-cost returns disagree.** Weekly P1 improves hit rate while its 10 bps net excess is negative. Objectives must be cost-aware and the report must show both.
4. **Small universes give wide intervals.** With 31 names, a single period's hit rate has a no-skill standard deviation of about 14 percentage points and a single period's Rank IC about 0.18. With 33 monthly periods a 1 pp improvement is far inside the noise, and even the full 2020–2026 history can establish P1-sized effects for the weekly cycle only (plan section 7.10). The release policy must coarsen feedback, the search must avoid reacting to noise, and the brief must say which cycle the success criterion applies to.
5. **Year concentration is a real failure mode.** Monthly P1's edge disappears without 2026. Leave-one-year-out is a mandatory diagnostic, not an optional appendix.
6. **Robust protocol engineering already exists here.** Frozen protocol hashes, receipts, prefix checks, eligibility hashes, paired decisions with explicit `pair_status`, immature-slot preservation. Carry these conventions into the new evaluator rather than inventing new ones.
7. **Fundamental factors are blocked on data, not ideas.** The manual's own backlog ranks announcement dates, membership intervals and quarterly statements as priority zero. Until a PIT-clean fundamentals table exists, the research system should mark fundamental hypotheses as "blocked on data" and focus the pilot on price, volume and breadth.
8. **Guards inside the Python process are not a security boundary.** The replay entry uses `sys.addaudithook` to block network and subprocess; the new evaluator needs OS-level or container isolation for untrusted generated code.

---

## A.8 What the intake agent should emit for this folder

The host intake agent reads the folder and produces three objects (field lists, not code):

**Research brief**

| Field | Value for the pilot |
|---|---|
| objective | Improve cross-sectional ranking skill of 31 Shenwan L1 industries over weekly, monthly and quarterly decision cycles, measured primarily by extreme-group recall and secondarily by Rank IC and 10 bps net excess vs equal-31 |
| universe | 31 industry codes from `industry_labels.csv`; benchmarks 000300.SH, 000905.SH, 000852.SH |
| decision cycles | weekly, monthly, quarterly with monthly review (rules in A.4) |
| baseline artifacts | frozen P0 and accepted P1 only; P2–P4 optional historical provenance, not automatic executions |
| constraints | no new data fetches; price/volume/breadth features preferred; fundamentals flagged PIT-weak; costs 0/10/30 bps; no shorting assumption |
| windows | development 2020-01-01 to 2022-12-31 (research-visible), validation 2023-01-01 to 2024-12-31 (official, Ladder-released), confirmation 2025-01-01 to 2026-10-16 (sealed, one human query), no diagnostic window; minimum detectable effects per cycle stated from plan section 7.10 |
| success criteria | weekly cycle primary: an artifact whose paired improvement over P1 on validation has a family-wise-adjusted interval excluding zero at 10 bps, positive incremental Rank IC after controlling for P0 and P1, improvement in a majority of yearly folds with leave-one-year-out point estimates all positive, placebo percentile above 90, maximum correlation to the pool below 0.7, turnover within cap; monthly and quarterly candidates report consistency flags only |
| budget and exit | explicit spend/token/query limits; no default job elapsed-time or generation ceiling; frozen research-delivery gate and permitted conclusions |

**Dataset manifest**: one entry per file in A.3 with path, physical and logical hashes, rows, columns, date range, grain, licence note and separate timing, value-vintage and membership quality. Record explicit observation/calendar dates, B for the fundamentals' stated availability rule, D for backfilled membership, and unknown historical revision/index vintages with the reconstruction concern. Do not turn an observation date into a blanket clean-PIT claim.

**Baseline artifact package**: the definitions in A.5 with their configs and the golden numbers from A.6 as expected results.

---

## A.9 Pilot-specific do-nots

- Do not import the frozen runtime as a library. Re-implement the needed features in the new canonical layer and prove parity against the oracle.
- Do not silently repurpose the original audit's diagnostic periods. Keep original replay windows distinct from a newly approved research protocol, and label all already inspected pilot periods as previously seen.
- Do not merge fixed-quarter and monthly-review conventions in one statistic.
- Do not treat repeated p60 / p80 / p100 rows as independent samples.
- Do not fetch provider data or query account quota during the pilot.
- Do not describe a sealed query on already inspected pilot history as unseen out-of-sample confirmation. A logged query changes access/exposure accounting, not the historical fact of prior inspection.
