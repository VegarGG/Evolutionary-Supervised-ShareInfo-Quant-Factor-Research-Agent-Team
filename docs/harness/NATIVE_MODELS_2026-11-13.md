# Native DSH Models integration — 13 November 2026

The owner reported that the same key works in another DSH under the China Coding
Plan provider and requested guard extensions in the native Models page. The
upstream provider ID is `zai-coding-cn`. The temporary Research models tab is
removed; API-key entry now belongs to DSH's built-in provider editor.

## Architecture and scope

DSH's pi-ai adapter owns model serialization, streaming, model selection and key
resolution. QRH contributes a Models footer explaining active limits, host
configuration checks, and a request-header extension that verifies the resolved
provider/model/endpoint and adds trusted session attribution. Every inference
request still crosses the existing loopback cash/quota guard. Native Agent Teams
and subagents continue to own worker activation and task state. No loop was forked.
Different models per role remain planned; this test pins GLM 5.3 Flash for all roles.

The fixed remote endpoint is
`https://open.bigmodel.cn/api/coding/paas/v4/chat/completions`, with bearer auth.
DSH's native editor writes `ZAI_CODING_CN_API_KEY`. The host migrates the existing
custom credential through the native store once, preserving owner-only mode and
removing the legacy copy. A native key already present takes precedence. Keys,
relay credentials and authentication headers are excluded from wire evidence.

The first real request used the Anthropic-compatible endpoint and returned 401.
This establishes rejection, not which of endpoint, header or credential caused it.
Its 5.242880 CNY and 555.74528-credit reservations remain until billing is verified.
Operator review of an intact, hashed 401 record permits one explicit repair probe
without classifying it as zero-cost or removing it from the 24-request limit.
Other unknown responses continue to block. Both protocol routes share all existing
cash accounting and aggregate subscription limits. No paid provider fallback exists.

New requests reserve the full 1,048,576-token input capacity and the actual enforced
output cap after native serialization. The relay forwards that exact body without
an SDK changing the cap later. Tiny native probes allow 512 then 1,024 output tokens;
the team remains at 8,192 per call. GLM 5.3 Flash requires thinking enabled, including
for probes. Existing requests, official baseline and the 200 CNY ceiling are unchanged.

## Repairs and evidence

- The old custom select mixed inherited light text with an OS-native white popup.
  That GLM dropdown was removed with the duplicate panel. Remaining research-data
  selects pair Canvas/CanvasText foreground and background in light and dark modes.
- Native Models settings validation rejected nested deferred endpoint expressions.
  Startup now emits a concrete, non-secret provider patch in each server's evidence
  directory. Normal key edits work; endpoint edits are refused by the host.
- Native pi-ai attribution differs from the Messages adapter. A private relay header
  now binds native session IDs to the existing role grants.
- Native GLM sends `tool_stream`; the guard accepts its boolean form. Chat usage
  requires a completed stream, finish reason, matching model and consistent totals.
  Cached prompt tokens are subtracted once; thinking is already in completion tokens.
- Early browser checks reloaded when Apply became Applying; corrected checks wait
  for the editor to close. Failed checks, rejected local requests and successive
  offline fixtures 012–018 remain under private `integration/expansion-005`.

167 offline tests pass after the evidence-access repair below. The native synthetic team completed 15 responses, both
workers and a draft. Synthetic usage is not real inference or provider spending.
Desktop browser checks pass for native key save/reload, endpoint refusal, removal
of the duplicate tab, and light/dark readable options. Headless Chrome does not
capture OS-native popup windows; expanded option lists and computed colors were
inspected. Native DSH settings remain clipped at 390px width; mobile is not accepted.

## Real native verification and bounded repair

Two real native probes passed: a short READY response (68 tokens, 4.05 seconds)
and a function call with the required argument (234 tokens, 6.05 seconds). The
same saved credential works through the native Coding Plan route. This does not
isolate the original header as the sole cause of the earlier 401.

The first full native GLM trial used 14 actual requests over 697.88 seconds.
The researcher completed. The reviewer initially used the supplied evidence ID
without obtaining its own session grant. Six operations were rejected; it then
fetched the frozen sample, calculated the full metrics and specification and
submitted a valid report. Its final acknowledgment exceeded the unchanged
six-request cap, so native completion failed and no draft was accepted. Both
workers' full calculation artifacts exactly match the independent reference.
Retain this as a failed workflow, not a passing team trial.

The repair gives each worker an explicit first-tool instruction with the exact
allowed query. Tool descriptions state the dependency; denied evidence reads now
return an actionable grant instruction instead of an opaque DataUnavailable.
The permission check remains enforced. A regression verifies that a shared hash
and scope read grant no access, and that recovery uses cache without a vendor query.

An append-only operator amendment permits one repair rerun and one bounded owner
trial: aggregate GLM request allowance rises from 24 to 60, and cumulative pilot
sessions from six to seven. All earlier calls and failed trials remain counted.
The 200 CNY ceiling, 1,500 prepaid-credit cap, 18:00 Beijing expiry, one concurrent
request, 20 calls per trial and eight/six/six role limits are unchanged. The first
401 retains both full reservations. Reviewed rejected requests can coexist with
an allowance amendment, but pending and unknown responses still block it.

After the two probes and first full trial, settled cash allowance accounting is
22.166328 CNY; 5.242880 CNY remains reserved, leaving 172.590792 CNY unreserved.
The new GLM allowance debits are conservative exposure, not incremental cash
invoices. Detailed failed-run metrics: [retained first native trial](evidence/expansion-2026-11-13/NATIVE_GLM_FIRST_LIVE.json).
The separate repair trial remains pending.

Required checks pass: 167 tests. An initial sandbox run denied six loopback socket
tests; rerunning with local sockets permitted passed all tests. Both logs remain.


## Primary references

- [Pinned DSH provider defaults](https://github.com/deepseek-ai/deepseek-harness/blob/e8f7b93a344964de3dca1ace9e72b6e4d6de87cb/packages/llm/llm-pi-ai/src/provider-data.generated.ts).
- [Models extension slots](https://github.com/deepseek-ai/deepseek-harness/blob/e8f7b93a344964de3dca1ace9e72b6e4d6de87cb/packages/client/ui-settings-models/src/client/slot-contract.ts).
- [Native request-header extension](https://github.com/deepseek-ai/deepseek-harness/blob/e8f7b93a344964de3dca1ace9e72b6e4d6de87cb/packages/llm/llm-pi-ai/src/index.ts).
- [GLM 5.3 Flash parameters](https://docs.bigmodel.cn/cn/guide/models/vlm/glm-5.3-flash).
- [Zhipu streamed tool calls](https://docs.bigmodel.cn/cn/guide/capabilities/stream-tool).
