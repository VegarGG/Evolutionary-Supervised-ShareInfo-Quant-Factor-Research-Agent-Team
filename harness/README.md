# Quant Factor Harness prototype

DSH owns the native chat, Models editor, Agent Teams and child sessions. QRH adds
bounded evidence, shared accounting and deterministic calculations without forking
the model loop. Start with the [approved plan](../docs/harness/PLAN.md) and
[interactive guide](../docs/harness/INTERACTIVE_TRIAL.md).

The [earlier verified native GLM trial](../docs/harness/LIVE_GLM_NATIVE_2026-11-13.md)
completed both workers, both Team tasks and an immutable draft: 15 actual Flash
requests, 180,678 tokens, 57.47% input cache hits and zero tool failures. Both workers
executed the full 121-row BaoStock sample; the host result is inconclusive.
That source passed 169 offline tests and GitHub checks; the current module package
passes 180 offline tests. Quantitative audit passed; the
separate qualitative audit flags overly categorical interpretation of the estimate.

Credentials now use **Settings → Models → Z.ai Coding (China) · guarded research**.
The native `zai-coding-cn` route works; the duplicate model settings panel is removed.
See [native Models integration](../docs/harness/NATIVE_MODELS_2026-11-13.md).
The original 401 keeps its full reservation, and both the failed first team and
zero-dispatch package refusal remain in history.

The owner completed the eighth fixed-scope trial. Development now follows the
[modular work package](../docs/harness/MODULAR_DEVELOPMENT_2026-11-13.md).
DeepSeek is disabled at the shared ledger. GLM Coding Plan Pro / GLM 5.3 Flash
continues without the previous 18:00 cutoff, subject to bounded work packages,
subscription exhaustion and the original 200 CNY total ceiling. The unchanged
interactive eight-session pilot is exhausted; module tests use separate explicit
step grants in the same ledger. This is not yet a production-ready research UI.

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
The original 56.256735 CNY / 884-call estimate remains historical evidence. The
owner's later official 20.35 CNY total supersedes covered estimates through the
immutable billing-baseline record; newer conservative debits accumulate under
the same 200 CNY ceiling. See the interactive guide for the current balance.

The historical diagnostic runner used DeepSeek, 12:00–14:00 and 18:00–24:00 Beijing;
current campaign controls refuse DeepSeek dispatch. Historically, an in-flight request
may drain after the window closes. Current concurrency is one, below the authorized
ceiling of 500. `deepseek-flash` is the configured/observed response alias; it is
not an independent identification of the backend model.

## Reproducibility and scope

Raw model requests/responses, native session traces, resource samples, data wires
and credential stores stay private on the operator's machine. Public summaries
include hashes and measurements, not keys or vendor row dumps. The live model
pilot, real data transport checks, synthetic model-loop smokes and offline unit
tests are reported separately. The setup-only profile and the new guarded research
profile use separate launch commands. The latter is a bounded supervisor/researcher/
reviewer prototype; its live validation is recorded separately from these earlier
diagnostic checks.

Upstream: [DSH source pin](https://github.com/deepseek-ai/deepseek-harness/tree/e8f7b93a344964de3dca1ace9e72b6e4d6de87cb)
(MIT), [BaoStock SDK](https://pypi.org/project/baostock/0.9.4/),
[RQData API](https://www.ricequant.com/doc/rqdata/python/manual),
[DeepSeek pricing](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/) and
[Messages usage](https://api-docs.deepseek.com/api/create-message/).
Project-owned code uses the standard [MIT License](LICENSE). Dependencies and
vendor data retain their own terms; see [third-party notices](THIRD-PARTY-NOTICES.md).


## Standalone shared-state / review module

`qfh.shared_state.Board` owns a local, append-only research episode. The operator
provides an explicit initial candidate, frozen source bundle, actor roles and
bounds. `publish` pins a finding to a candidate and checks exact source excerpts;
`revise` atomically checks the current parent and records a disposition for every
finding before committing a child version. `snapshot` returns the current head
with complete versions and unresolved conflicts. Principals come from the host.
Nothing is executed, published to a pool or sent to an evaluator. Structural
acceptance does not certify the scientific truth of model prose.

The native DSH experiment driver uses two SDK sessions per arm and the same
campaign ledger. `peer_review` exposes the review to the author;
`feedback_disabled` computes but withholds it. Both have the same source bundle
and request/output ceilings; actual tokens can differ. Fixtures are explicitly
synthetic diagnostics and answer keys are outside the model workspace.

Explicit operator command (live subscription usage; not part of ordinary tests):

```sh
PYTHONPATH=harness/src python harness/scripts/module_pilot.py \
  --private .qfh-private --case harness/cases/module-timing.json \
  --run-id your-unused-lowercase-id --variant peer_review
```

Use a unique lowercase run id. Existing attempts refuse paid replay, including
failed attempts. Inspect `RESULT.json`, `AUDIT.json`, source snapshots, raw wire
usage and semantic review separately. An interrupted or quota-rejected request
retains its reservation and stops further dispatch. Do not replace live model
failures with synthetic results. The current CLI module is not yet exposed as
an open-ended DSH chat workflow; adaptive supervision is the next integration gate.
