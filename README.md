# Quant Factor Harness

Current development is a bounded quant research harness built on **DeepSeek
Harness (DSH)** in the existing [QFR repository](https://github.com/VegarGG/Evolutionary-Supervised-ShareInfo-Quant-Factor-Research-Agent-Team).
DSH owns sessions, model/tool loops, the Models editor and native Agent Teams.
QRH adds bounded data access, evidence, accounting and deterministic research
calculations. The independent evaluator remains separate.

The [latest real GLM Flash/BaoStock trial](docs/harness/LIVE_GLM_NATIVE_2026-11-13.md)
passed at **12:12–12:20 Beijing on 13 November**: one supervisor, two workers,
15 actual settled calls, 180,678 tokens and an immutable draft. Both workers
independently executed the frozen specification on all 121 real observations.
The result is **inconclusive**, with model-prose caveats recorded separately.
Input cache hit rate was 57.47%; 169 offline tests and both GitHub check suites pass.

Use **Settings → Models → Z.ai Coding (China) · guarded research** for the
Coding Plan Pro key. The native `zai-coding-cn` route works with the saved key;
the duplicate Research models panel is removed and light/dark select readability
is repaired. See the [native integration record](docs/harness/NATIVE_MODELS_2026-11-13.md).
The original 401, first team failure and a zero-call package refusal remain recorded.

The owner completed the eighth bounded trial and directed continued modular
work. **This is a development prototype, not production ready or completed Hybrid
v1.** The scheduled DeepSeek run is canceled; the shared ledger now permits only
GLM Coding Plan Pro, using GLM 5.3 Flash until quota exhaustion or an explicit
owner switch. There is no 18:00 provider switch. The original 200 CNY ceiling and
all reservations remain intact.

The next work package implements and independently tests a versioned shared-state
and review module: source-linked findings, explicit review decisions, immutable
candidate revisions and stale-write refusal. Live module demonstrations are
separate from the fixed BaoStock UI pilot. See the [development record](docs/harness/MODULAR_DEVELOPMENT_2026-11-13.md).

Read the [approved plan](docs/harness/PLAN.md),
[trial guide](docs/harness/INTERACTIVE_TRIAL.md),
[staged data expansion](docs/harness/SAMPLE_EXPANSION_2026-11-13.md), and
[role models / market context design](docs/harness/ROLE_MODELS_AND_CONTEXT.md).
Earlier [DeepSeek trial results](docs/harness/LIVE_SPECIFICATION_TRIAL_2026-11-12.md),
[diagnostic pilot](docs/harness/FIRST_PILOT.md),
[data-source comparison](docs/harness/DATA_SOURCES.md) and deployment evidence
remain unchanged and are not presented as GLM results.

## Current deliverable

- Pinned DSH SDK/runtime 0.2.2rc2 and a native Research data settings/tool plugin.
- **BaoStock** as the anonymous free testing default; iFind and RiceQuant RQData
  adapters remain selectable. One data source per session, no automatic fallback.
  Paid-source credentials are entered in DSH, never in model prompts.
- Persistent data quotas, immutable evidence, exact-query reuse and worker tools
  for daily bars plus entitlement-gated RQData report/disclosure/news metadata.
- An atomic wire guard carrying the original 200 CNY budget forward, preserving
  unknown charges and enforcing each authorized route's admission window. GLM
  Coding Plan also retains a separate bounded subscription-credit reservation.
- Ten real-model diagnostic runs across six workflow variants, 24 new API calls.
  All passed the one known-answer case; collaboration showed no accuracy advantage
  and cost more. Those diagnostics are separate from the interactive trial.
- A guarded DSH chat preset with one supervisor and two native child sessions,
  the native Agent Teams task board, cited worker reports and immutable research
  drafts. See the trial guide for the current live validation status.

The owner reported an official cumulative API charge of **20.35 CNY** on
12 November 2026, superseding the earlier 57.084913 CNY conservative estimate.
That observation is now the billing baseline; subsequent requests add conservative
estimates under the unchanged **200 CNY** ceiling. The raw call history and old
estimates are preserved. The first diagnostic pilot's input cache hit rate was 22.64%.
The interactive-trial export reports each role's token usage, cache hits, TPM/RPM,
tariff-estimated cost and shared-process resource observations separately.
After the owner trial, the accounted baseline plus conservative debits was
**23.103376 CNY**, with **5.242880 CNY reserved** and **171.653744 CNY unreserved**.
Subsequent module-test usage is recorded in the development record. The GLM trial's
0.498666 CNY is a conservative exposure debit; 54.60039 prepaid credits is an
upper estimate. Neither is an incremental cash invoice. Full per-role accounting
and every retained failure are in the latest report.

## Local setup and checks

Use Python 3.12, uv, Node and pnpm. From the repository root:

```sh
uv sync --project harness --locked
just harness-check
just harness-test
just harness-ui
```

`harness-ui` installs the local plugin and opens a loopback DSH web service on
port 3080. Use its authenticated bootstrap link printed locally. In Settings →
Research data, select BaoStock, iFind or RQData. Saving a credential sends no
provider request. This setup profile has model providers disabled; guarded live
experiments use the separate SDK runner, as described in [harness/README.md](harness/README.md).
The current trial uses **`deepseek-flash` only for all three roles**.
For the guarded chat/Agent Teams profile, use `just harness-research-ui --private
.qfh-private --key-file /operator/deepseek-key-file --install-plugin`. The real key
stays in the parent relay. Follow the [trial guide](docs/harness/INTERACTIVE_TRIAL.md);
the existing setup-only command remains available.

`just harness-data-plan` prints the tiny initial data test without contacting a
provider. Execution requires the explicit `--execute` argument. The current pilot
is one stock, three dates and unadjusted close only. Paid-source allowances remain
one query each; BaoStock's recorded failed attempts and successful retry are counted
in its separate allowance. Exact completed queries reuse local evidence.

All harness runtime homes, keys, raw responses and data stay in ignored
`.qfh-private/`. Use external-volume cache/runtime paths on storage-constrained
machines. No normal check/test target contacts a model or market-data provider.

## Previous implementation and deployment

The existing `packages/`, original [v2.1 plan](docs/QFR-Implementation-Plan-v2.1-EN.html)
and phase documents are retained as historical QFR work. The harness does not wrap
that entire orchestration stack. Read the [preserved deployment evidence](docs/harness/LEGACY_EXPERIMENTS.md)
for real generations, failures, resource measurements and scientific acceptance
limits. Old PRs 14–19 were closed without merging; their branches are preserved.
Legacy commands (`just check`, `just test`, Compose operations) still apply to that
code; the harness has separate dependency and test targets.

## License and use

Copyright (c) 2026 Ziwei Huang. Project-owned code is open source under the
standard [MIT License](LICENSE), including commercial use, modification and
redistribution subject to its copyright and permission-notice requirements.
There is no separate personal-trading exception or commercial-license restriction.

[Third-party materials retain their own licenses](THIRD-PARTY-NOTICES.md),
including DeepSeek Harness's MIT copyright and permission notice. Market-data
access and redistribution remain subject to each provider's terms.
See the [licensing record](docs/LICENSING_REVIEW.md) for scope and package checks.
