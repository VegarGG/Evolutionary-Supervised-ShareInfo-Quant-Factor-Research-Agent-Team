# Quant Factor Harness

Current development is a small research harness built on **DeepSeek Harness (DSH)**
in the existing [QFR repository](https://github.com/VegarGG/Evolutionary-Supervised-ShareInfo-Quant-Factor-Research-Agent-Team).
DSH owns sessions and model/tool loops; QFH adds bounded data access, evidence,
budget enforcement and controlled workflow experiments. The independent evaluator
and its research/holdout boundaries remain separate.

Start with the [approved plan](docs/harness/PLAN.md),
[first live pilot report](docs/harness/FIRST_PILOT.md), and
[data-source selection](docs/harness/DATA_SOURCES.md).
The [validation record](docs/harness/VALIDATION.md) includes test scope and UI checks.
This is a prototype, not a completed Hybrid v1 system or an accepted alpha engine.

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
  and cost more. More diagnostic/open-ended work is required before the core gate.

Conservative cumulative model spending is **57.084913 CNY**, including the earlier
56.256735 CNY. The new pilot used 0.828178 CNY, with 22.64% input cache hits. These
figures are not invoice verified. Free-data and browser checks added no paid calls.

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
It is not yet the complete interactive research-chat frontend.

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

Copyright 2026 Ziwei Huang. This is source-available software under the unchanged
[PolyForm Noncommercial License 1.0.0](LICENSE), with a separate
[additional permission](ADDITIONAL-PERMISSION.md) for individuals researching and
trading their own funds in personal accounts, including for personal financial
gain. It is not offered as OSI-approved open-source software. The additional
permission does not cover running a business, work for employers or clients,
managing others' money, or paid products, signals, advice, or services; it does
not withdraw broader rights already granted by the PolyForm license.

For uses outside the public license and additional permission:
Commercial use requires a separate written license from Ziwei Huang.
Separately authorized companies may use the software within their written
license's scope. These grants cover only rights Ziwei Huang owns or is authorized
to license; [third-party materials retain their own licenses](THIRD-PARTY-NOTICES.md).

This system was originally developed for research purposes only; it provides no guarantee of investment performance, and, to the extent permitted by law, Ziwei Huang accepts no liability for gains, losses, or other consequences arising from its use.
