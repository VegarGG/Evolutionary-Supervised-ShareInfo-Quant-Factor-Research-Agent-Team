# GLM Coding Plan Pro integration — 13 November 2026

Current status: the [real native GLM Flash/BaoStock trial](LIVE_GLM_NATIVE_2026-11-13.md)
passed with fifteen calls, both workers/tasks and a draft. Native Models and
`zai-coding-cn` work with the saved key; 169 offline tests pass. The original
Anthropic 401, first failed team and zero-dispatch package refusal remain retained.
Active bounds: 60 aggregate GLM requests, 1,500 local credits, a 20 CNY GLM package
sublimit within the original 200 CNY ceiling, and eight cumulative pilot sessions.
32 requests and seven sessions are used. One bounded owner trial remains until
18:00 Beijing. Details: [native integration](NATIVE_MODELS_2026-11-13.md).

## Owner authority and model choice

The owner first authorized GLM during DeepSeek peak hours, then specified:

> a GLM Coding Plan, we shall use GLM 5.3 Flash first, and if there's very clear
> evidence that GLM 5.3 Flash is not smart enough, we switch to GLM 5.3

The owner confirmed eligibility with the provider:

> Don't worry. I've confirmed with Zhipu official that DSH is allowed.

The owner then replaced the planned noon DeepSeek run:

> I propose to use GLM replace the scheduled work. Before Beijing Time today 18:00,
> we use GLM to test and polish the QRH first.

Finally: "btw, the GLM coding plan is Pro level". This is recorded as owner-reported
provider confirmation; no message to Zhipu was sent by this agent. It resolves the
earlier eligibility question. Current execution uses **`glm-5.3-flash` only** with
one supervisor, researcher and reviewer. Different models simultaneously in
different roles remain a separate development stage.

## Route, time and budget controls

`glm-coding-2026-11-13.yaml` admits GLM calls until **18:00 Beijing on 13 November
2026 (10:00 UTC)**. An in-flight response is drained and accounted for; a later
request is refused. No DeepSeek request is scheduled for noon. Later DeepSeek
admission retains the existing 12:00–14:00 and 18:00–24:00 windows; this GLM route
does not widen them or silently switch providers at expiry.

The replacement `glm-coding-native-2026-11-13.yaml` route uses DSH's native
`zai-coding-cn` Chat Completions adapter and the fixed Coding Plan endpoint.
The original Anthropic route is retained as failed history. DSH owns all model
and subagent loops; native transport points to the loopback guard. The guard forwards only the configured Flash model and permitted
tools. It does not retry, redirect, select another model or fall back to a metered
endpoint. Workers cannot activate routes. An append-only route activation is
frozen into each new trial; earlier DeepSeek trials retain their original routes.

Start with a short text probe and one tool-call probe, inspecting each before the
next. Then run one full native team trial on the already frozen BaoStock sample.
The initial route allowed 24 requests. Recorded native repair amendments now
allow 60 aggregate requests and eight cumulative pilot sessions, including all
failed attempts. One concurrent request and the 1,500-credit allowance remain
unchanged. The team retains twenty calls split eight/six/six. A separate frozen
route raises only the GLM package sublimit from 10 to 20 CNY; the original
200 CNY cumulative check and saved budget policy remain unchanged. Pro's account
quota may also include activity outside this experiment, so the local allowance
does not claim to measure available account quota.

The **same 200 CNY ledger** retains the official 20.35 CNY baseline, previous call
records and package limits. Every GLM request also reserves the existing
full input capacity plus its enforced output cap and debits its conservative token allowance after usage
is known. This is an exposure allowance, **not an assertion that the subscription
incurred incremental cash billing**. Subscription purchase cost is not allocated
to individual calls. At the pre-live checkpoint, cash accounting was
21.608190 CNY with 178.391810 CNY remaining and 78 settled harness requests.

Separately retain prepaid quota reservations and a conservative credit estimate.
The frozen Flash coefficients are 2.3 for input and 8 for output per 10,000 tokens;
the local bound ignores all cache and off-peak discounts. Unknown usage retains
both reservations and blocks more calls on this route. Provider cache counters
are reported only when present; omitted counters produce a null cache hit rate,
not a measured zero. Capture TPM/RPM by dispatch and completion, actual response
model identifiers, native agent work and shared machine resource samples.

Sources checked on 13 November: [Coding Plan quota and coefficients](https://docs.bigmodel.cn/cn/coding-plan/overview),
[Messages endpoint](https://docs.bigmodel.cn/cn/guide/develop/claude/introduction),
[separate subscription key types](https://docs.bigmodel.cn/cn/coding-plan/tool/claude),
and [standard API pricing](https://docs.bigmodel.cn/cn/guide/start/pricing).
The existing cash rates of 2/8 CNY per million input/output tokens conservatively
exceed the observed Flash standard rates of 0.8/2.8; neither is represented as a
subscription invoice.

## Credential entry

In DSH, open **More → Settings → Models → Z.ai Coding (China) · guarded
research → Edit**. The native API-key field saves to `ZAI_CODING_CN_API_KEY`.
Saving makes no provider request. The legacy custom form and Research models
tab are removed. The host migrates the old local credential once, through DSH's
credential service, then removes the legacy reference so deleting the native key
cannot revive it. No secret is read back into the browser or committed.

Guard information is a documented `settings.models.footer` extension. Provider
edits are checked at the host; resolved model/endpoint/session metadata is checked
again before dispatch. Both roles use DSH's existing Agent Teams and subagents.

## Verification and acceptance rubric

The earlier 155-test checkpoint passed, including concurrent quota reservation, retained unknown
usage across restarts, route expiry, prevention of model/endpoint substitution,
shared cash-ceiling enforcement, preservation of old trial scopes, immutable
activation, missing-cache reporting and credential error redaction. No SQLite
schema migration or historical record rewrite was needed.

The final native DSH synthetic run completed all three roles and both Team tasks
with fifteen scripted responses. Both workers executed the same full synthetic
sample and produced an accepted draft. The exporter identified GLM Coding Plan,
subscription quota and the unchanged shared ledger. The credential form passed
dummy save, clear, reload and removal checks. A QA-script ordering mistake in an
earlier pass was corrected; both attempts are retained. Chrome desktop passed
without console errors or external browser requests. The upstream 390px mobile
clipping remains a known limitation.

For real execution, record every probe and trial once, including failures. Require:

- One exact Flash model, admitted dispatch times, complete usage and no automatic retry.
- Two completed native workers/tasks, independent source reads, independently
  executed fixed specification and a validated supervisor draft.
- All 121 frozen real observations used by deterministic calculations; preview
  wording must not claim full row inspection. Preserve full artifacts and lineage.
- Independent arithmetic/bootstrap agreement and explicit exploratory limitations.
  An inconclusive interval is a valid statistical result, not a software failure.
- Per-role work, request/token/cache/rate records, cash exposure and credit
  estimates, plus CPU/RAM/swap/disk samples and exact measurement limits.
- Credential values absent from publishable outputs and raw request bodies.

An upgrade to GLM 5.3 requires concrete reasoning or specification failures after
tooling defects, truncation and insufficient data are ruled out. Preserve the
failed prompt, available evidence, expected result and feedback response. A
connection error, rate limit, schema integration bug or inconclusive financial
result is not evidence that Flash lacks intelligence. No upgrade is enabled by
the present model whitelist.

Private integration records: `.qfh-private/integration/expansion-005/`; immutable
campaign wire and usage remain in their original locations. The completed real results, retained failures and current readiness are in
[LIVE_GLM_NATIVE_2026-11-13.md](LIVE_GLM_NATIVE_2026-11-13.md).
