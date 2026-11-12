# Quant Factor Harness prototype

Read the [current plan](../docs/harness/PLAN.md),
[measured first pilot](../docs/harness/FIRST_PILOT.md), and
[data-source protocol and limits](../docs/harness/DATA_SOURCES.md).
This module uses DSH through its SDK and native plugin APIs. It does not fork the
agent loop or claim that the original multi-agent framework is complete.

## Install and verify

From the repository root, with Python 3.12, uv, Node and pnpm available:

```sh
uv sync --project harness --locked
just harness-check
just harness-test
just harness-ui
```

The standalone lockfile pins SDK/runtime 0.2.2rc2, rqdatac 3.8.2 and BaoStock 0.9.4.
For this Mac's existing Work-volume environment, checks can also use
`.qfh-private/venv/bin/python -m pytest -c harness/pyproject.toml harness/tests -q`.
Set `UV_CACHE_DIR` and `UV_PYTHON_INSTALL_DIR` to the chosen external volume before
installing when local storage placement matters. DSH plugin installation also
uses pnpm's configured store. Its platform-native executable needs a compatible
runtime wheel; the measured environment was macOS ARM64.

The local setup UI listens on 127.0.0.1:3080. Its bootstrap token is private.
In Settings → Research data, BaoStock requires no personal token. iFind accepts
one refresh or access token; RQData accepts its license. Saving/removing is local
and never validates against a paid provider. Models, uploads, inventory telemetry,
ordinary shell/file tools and automatic title calls are disabled in this web
profile. Live model experiments use the separate guarded SDK runner below.

## Research tools and first data test

| Tool | Current adapter support |
|---|---|
| `market_daily_bars` | Bounded unadjusted daily close: BaoStock, iFind, RQData |
| `research_reports` | RQData broker summaries, entitlement required |
| `company_announcements` | RQData disclosure metadata and original links |
| `research_news` | RQData news metadata; rqdatac_news and entitlement required |
| `read_research_evidence` | Session-granted, hash-verified paginated evidence |

Reports/news are disabled by the first pilot policy. Full article/PDF extraction
is not implemented. The optional `qfh.mcp_server.create_server` factory uses the
same guarded boundary with a host credential callback; it has no credential-file
CLI. Owner/evaluator MCP privileges are never added to these research tools.

```sh
just harness-data-plan
# Explicit live data execution, only after reviewing the printed scope:
just harness-data-plan --provider baostock --run-id my-data-check --execute
```

The fixed first query is `000001.XSHE`, 2026-10-28..30, close only. The operator
policy bounds requests, dates, symbols, estimated price cells, bytes and time.
Counters are persistent per provider. A new session cannot reset them. Exact
successful results can be reused across same-account sessions; source switching
within a session is refused. Unknown/failed queries are not silently retried.
The campaign has already consumed BaoStock's three-attempt cap (two failures,
one verified result); this exact query is cached. Paid-source caps are untouched.
New dates or larger scope require a recorded policy revision before dispatch.

The DSH plugin passes stored credentials only through a trusted child's stdin;
model arguments cannot choose keys, arbitrary paths, hosts or policy limits.
Historical downloads are not a point-in-time archive. Corporate actions and
historical-universe construction need explicit protocols before factor measurement.

## Live diagnostic runner

`qfh.experiment` accepts explicit config, fixture, variant, run ID, private campaign
directory and an operator-only DeepSeek key reference. It uses the real DSH SDK
and DeepSeek Messages endpoint. The authorized existing campaign is
`.qfh-private/campaign`; do not create a new ledger to evade its accumulated usage.
No live command runs as part of pytest or the normal just targets.

```sh
PYTHONPATH=harness/src uv run --project harness --locked python -m qfh.experiment --help
PYTHONPATH=harness/src uv run --project harness --locked python harness/scripts/summarize_pilot.py \
  --private .qfh-private/campaign --output docs/harness/evidence/diagnostic-2026-11-12
```

The current diagnostic runner supports single, blackboard, independent,
self_revision, review and debate. Role prompts receive frozen evidence and explicit
peer contributions. Output is schema-checked and citations must identify available
sources/contributions. The withheld answer key is never included in the runtime
workspace or prompts. These diagnostic fixtures are synthetic and cannot be
represented as vendor observations, production factors or official acceptance.

Every actual provider request reserves the documented context/output maxima at
peak prices before dispatch. API compatibility can raise a requested output cap,
so reservation uses provider maxima. Retries consume the same step's call allowance;
unknown outcomes keep their reservation across restart. All input is conservatively
settled at peak cache-miss prices; cache savings are reported separately. A completed
step is loaded without paid replay; an interrupted step requires reconciliation.
The original 56.256735 CNY / 884 calls carry forward into the same 200 CNY total.

Admission is DeepSeek-only, 12:00–14:00 and 18:00–24:00 Beijing; an in-flight request
may drain after the window closes. Current concurrency is one, below the authorized
ceiling of 500. `deepseek-flash` is the configured/observed response alias; it is
not an independent identification of the backend model.

## Reproducibility and scope

Raw model requests/responses, native session traces, resource samples, data wires
and credential stores stay private on the operator's machine. Public summaries
include hashes and measurements, not keys or vendor row dumps. The live model
pilot, real data transport checks, synthetic model-loop smokes and offline unit
tests are reported separately. The local UI is currently a credential setup surface;
a budget-guarded interactive research-chat profile and the minimal supervisor/two-
worker core remain gated work, not features established by these tests.

Upstream: [DSH source pin](https://github.com/deepseek-ai/deepseek-harness/tree/e8f7b93a344964de3dca1ace9e72b6e4d6de87cb)
(MIT), [BaoStock SDK](https://pypi.org/project/baostock/0.9.4/),
[RQData API](https://www.ricequant.com/doc/rqdata/python/manual),
[DeepSeek pricing](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/) and
[Messages usage](https://api-docs.deepseek.com/api/create-message/).
Project-owned code uses the standard [MIT License](LICENSE). Dependencies and
vendor data retain their own terms; see [third-party notices](THIRD-PARTY-NOTICES.md).
