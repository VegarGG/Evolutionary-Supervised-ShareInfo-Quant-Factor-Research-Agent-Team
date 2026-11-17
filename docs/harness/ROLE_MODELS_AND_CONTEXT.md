# Role models, Agent Teams and bounded market context

Owner direction, 12 November 2026: support different models/providers by research
role; give researchers limited market evidence; keep evaluation and publication
under script control. The owner identified DSH's experimental **Agent teams**
feature as the relevant upstream interface. This design is accepted for staged
development. It does not authorize live calls to any new provider.

Update, 13 November: the owner separately authorized
[GLM Coding Plan Pro](GLM_CODING_PLAN_2026-11-13.md), Flash first, replacing the
scheduled trial until 18:00 Beijing. New trials freeze a uniform provider route
for all three roles. Simultaneous mixed-provider roles remain future work; this
amendment does not rewrite the earlier authorization or experiment evidence.

## What the pinned DSH implementation actually provides

Reviewed source: DSH `e8f7b93a344964de3dca1ace9e72b6e4d6de87cb`, runtime 0.2.2rc2.
[Agent Teams](https://github.com/deepseek-ai/deepseek-harness/blob/e8f7b93a344964de3dca1ace9e72b6e4d6de87cb/packages/team/agent-team/README.md)
adds a durable task board to the native subagent tree. It provides task dependency,
ownership and revision checks; the browser displays the board alongside the
ordinary child-session navigator. New roots normally start with Team mode off;
the QFH trial preset enables it by default.

Model/provider overrides are implemented by the
[subagent layer](https://github.com/deepseek-ai/deepseek-harness/blob/e8f7b93a344964de3dca1ace9e72b6e4d6de87cb/packages/subagent/tool-subagent/README.md)
used by teams. `agentOptions` supplies a child's provider, model, effort and token
cap; model selection has a separate owner-controlled allowed-route policy.
The native `startActivation` interface supports reserved child identities,
independent presets, recursion limits and caller-owned result delivery. QFH uses
these interfaces; it does not implement another model loop or task board.

The trial's `research_worker` tool is a bounded application adapter: it admits one
researcher and one reviewer, starts native child sessions, records their native
Team tasks and validates their reports. QFH's small local registry records
research permissions, budgets and provenance, not an alternative DSH membership
or messaging system. Workers run sequentially for the initial experiment.

Team mode alone is not a security boundary or a multi-provider billing system.
Upstream write scopes are advisory; members share a process and filesystem; task
updates do not start idle agents; interrupted work does not automatically release
task ownership. QFH keeps general shell/file/network tools outside this preset.

## Planned role-routing module

1. Keep a versioned role configuration with `supervisor`, `researcher`, `reviewer`
   and later routine analysis roles. Each route specifies provider, exact model,
   effort, input/output limits, tool permissions and a price-version reference.
2. Let the owner select from configured, authenticated DSH routes. Credentials
   remain in the local credential service and transport process. Store the resolved
   mapping before the first request and include it in every trial manifest.
3. Map each role to native `agentOptions` and presets. Bind the allowed routes
   before delegating. A model cannot expand the list, switch credentials or choose
   a cheaper unapproved fallback; unavailable routes fail visibly.
4. Add transport-specific budget adapters before enabling additional providers.
   Account for cached/uncached input, reasoning/output, helper calls, retries and
   provider tools. Convert other billing currencies with a versioned conservative
   rate. All routes debit the same cumulative ledger atomically.
5. Test mixed-role quality, latency and total cost against the same-evidence
   DeepSeek baseline. Different providers may not share a cache; measure reuse
   separately for each route. No claim that a smarter supervisor is necessarily
   more effective until measured.

The first trial has explicit per-role configuration but deliberately accepts only
the currently priced DeepSeek route. The owner's Kimi/OpenAI/GLM examples inform
the later module; availability and pricing must be verified when it is built.

## Bounded market evidence

Researchers should see enough permitted observations to formulate and challenge
ideas. That can reduce pressure to work around an uninformative interface, but
access controls must still hold independently of their behavior.

Use two separate contexts:

- **Historical development context:** a frozen research snapshot, its calendar,
  selected features and dated documents. All observations and text must have been
  available by the artifact's declared as-of time. Record publication, ingestion
  and retrieval times separately; current downloads are not vintage archives.
- **Current context for prospective research:** bounded recent prices, market
  summaries and dated news, used only for artifacts evaluated on subsequent data
  after an embargo. Present-day news cannot be injected into a historical trial
  while describing that trial as blind to later events.

An operator-defined manifest will set the allowed universe, dates, fields,
document sources, lag/embargo, per-call limits and cumulative exposure limits.
`max_research_fraction` must be explicit in the protocol. A small initial proposal
is 10% of eligible development observations, counted by unique security/date/field
cells, with separate document/byte quotas. This is a proposed starting value, not
permission to expose 10% of the final holdout. Repeated reads, overlapping queries
and derived statistics must not expand the union of exposed observations.

The final holdout remains wholly outside the research process. Its metrics,
labels and selection decisions cannot be reconstructed through an on-demand
evaluation tool. Every official gate remains deterministic and independently
scheduled; research can neither invoke it nor alter its protocol. Only the
existing released-feedback boundary returns permitted decision/reason codes.
Market text is cited evidence, never an instruction or authority to change scope.

Implementation progression: scoped prices and descriptive arithmetic now; frozen
market-context manifests and exposure accounting next; dated news/report metadata
and entitlement checks after that; full-content extraction only with source terms,
timestamp quality and prompt-injection tests. BaoStock's present adapter supplies
daily closes only, so this trial does not pretend to provide live news or market
breadth. None of these research tools is an official backtest or publication gate.

## Acceptance checks for the later modules

Require route/price/credential mismatch refusal; shared-budget races and unknown
charges across providers; no silent fallback; source pinning; date and cumulative
exposure checks; news after cutoff rejected; no holdout or evaluator capability;
full citation/contribution traces; and equal-evidence comparisons. Preserve failed
attempts and report capability limits alongside successes.
