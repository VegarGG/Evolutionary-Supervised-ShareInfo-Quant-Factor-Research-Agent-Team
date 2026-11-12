# Quant Factor Harness

Current development is a small research harness built on **DeepSeek Harness (DSH)**
in the existing [QFR repository](https://github.com/VegarGG/Evolutionary-Supervised-ShareInfo-Quant-Factor-Research-Agent-Team).
DSH owns sessions and model/tool loops; QFH adds bounded data access, evidence,
budget enforcement and controlled workflow experiments. The independent evaluator
and its research/holdout boundaries remain separate.

Start with the [approved plan](docs/harness/PLAN.md),
[first live pilot report](docs/harness/FIRST_PILOT.md), and
[data-source selection](docs/harness/DATA_SOURCES.md).
The [interactive trial guide](docs/harness/INTERACTIVE_TRIAL.md) covers the new
supervisor/two-worker workflow and its small limits.
The [initial validation record](docs/harness/VALIDATION.md) and
[native-team validation](docs/harness/INTERACTIVE_VALIDATION.md) distinguish each test scope.
This is a prototype, not a completed Hybrid v1 system or an accepted alpha engine.

The [first real native-team trial](docs/harness/LIVE_TRIAL_2026-11-12.md) ran at
18:01 Beijing on 12 November: seven Flash requests, real BaoStock data and 31,074
tokens. It stopped at a fenced-JSON report mismatch before the reviewer or draft.
The boundary repair passes offline; a complete real three-role pass is still
required before owner-trial readiness is accepted.

## Current deliverable

- Pinned DSH SDK/runtime 0.2.2rc2 and a native Research data settings/tool plugin.
- **BaoStock** as the anonymous free testing default; iFind and RiceQuant RQData
  adapters remain selectable. One data source per session, no automatic fallback.
  Paid-source credentials are entered in DSH, never in model prompts.
- Persistent data quotas, immutable evidence, exact-query reuse and worker tools
  for daily bars plus entitlement-gated RQData report/disclosure/news metadata.
- An atomic DeepSeek wire guard carrying the original 200 CNY budget forward,
  preserving unknown charges and enforcing Beijing admission windows.
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
The failed interactive round adds a 0.115572 CNY conservative debit, leaving
**179.534428 CNY** under the original cap. Its tariff estimate is 0.04310952 CNY;
two balance snapshots did not resolve the actual billed amount.

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
