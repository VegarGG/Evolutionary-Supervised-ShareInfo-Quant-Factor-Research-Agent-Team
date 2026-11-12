# Quant Factor Harness: approved capability experiments

Status: implementation started on 12 November 2026 (Beijing). This is the current
development direction in the existing QFR repository. The earlier implementation,
plans and test outcomes remain historical evidence; they are not silently accepted
or erased. The owner subsequently selected the standard MIT License on
12 November 2026. DSH retains its own copyright and MIT notice; see
[the licensing record](../LICENSING_REVIEW.md).

Authority: owner's approval of [Workflow capability experiments and modular
development](https://chatgpt.com/space/page_5ff299fdf2208191ade3872b9916998a), followed
by instructions to retain this repository, close previous PRs, use daily China
A-share research, add iFind alongside RQData with DSH credential entry, and prepare
worker report/news tools. The later instruction adds a free testing source, selected
as BaoStock after bounded comparisons; only one provider is used per session.

## First work package

1. Preserve the prior deployed experiment and close superseded PRs with an index.
2. Install a pinned DSH SDK/runtime in an isolated local home. Disable optional
   session uploads, package inventory uploads and general shell/file tools.
3. Enforce the original cumulative 200 CNY allowance at the actual provider wire,
   including retries, helper requests and unknown outcomes. Prior conservative
   spending is 56.256735 CNY across 884 calls; it is not reset for this project.
4. Build bounded read-only iFind, RQData and BaoStock adapters. RQData also
   provides the initial report/disclosure/news discovery seams. No credentials or licensed rows are committed. Credential/entitlement
   failures are recorded as unavailable, never replaced by synthetic real data.
5. Freeze diagnostic cases and a separate withheld answer key. First compare a
   single agent with blackboard collaboration on equal evidence and allowances.
   Add independent aggregation, self-revision, iterative review and debate as
   separate treatments. Preserve every attempted run, including failures.
6. Record initial and final definitions, source ids, peer contributions, decisions,
   revisions and unresolved claims. Independently check support, not agreement.
7. Repeat selected cases and include unseen open-ended A-share cases using frozen
   selected-provider evidence. Write capability cards and counterexamples before choosing
   a minimal supervisor/two-worker core.

The later stages remain gated: minimal core; isolated shared-state/review/evolution/
parallel/composition modules; progressive Hybrid v1 integration; then v2 lanes and
production/forward validation. No early capability test establishes profitable alpha,
production sizing, official acceptance, or a universal advantage for multiple agents.

## Experiment rubric

Each record includes source revision and dirty diff hash; runtime/dependency
versions; configuration, prompt and case hashes; real/mock label; UTC and Beijing
timestamps; role/session/step/request ids; evidence seen by each agent; input/output
and cached tokens; dispatch/completion RPM and TPM; resource samples and scope;
reserved and settled CNY; retries and unknown usage; final validation and reasons.

Hold combined evidence, model/settings and maximum aggregate requested output
allowance equal. Report actual requests and compute explicitly: the first pilot
uses one single-agent call versus three collaborative calls, not equal call counts.
Add compute-matched controls when estimating a collaboration effect.
The answer key never enters the runtime workspace, prompts, MCP tools or provider
wire. Diagnostic and open-ended results are separate. Diagnostic fixtures are not
production factors and are never imported into a pool.

Live admission remains DeepSeek-only, sequential initially, within the original
schedule: 12:00–14:00 and 18:00–24:00 Beijing. At a closed window, stop admitting
new work and let an already dispatched request finish; checkpoint unfinished work.
500 is the authorized concurrency ceiling, not an experimental target. A smaller
per-package budget is a further ceiling, never a renewed total allowance.

## Architecture and scope

DSH owns model/tool loops, sessions and later the frontend. Small Python modules
own bounded data retrieval, experiment state, budget enforcement and evidence.
Use documented profile/plugin extension points; do not fork the agent loop.
The owner MCP and research-tool MCP are distinct privilege scopes. The latter
cannot control evaluation, publish official results or access private holdout data.
An independent evaluator stays outside DSH. A workflow script is not a durable job
scheduler; saved experiment steps must prevent accidental paid replay on resume.

BaoStock is the free testing default. iFind and RQData remain selectable, with
credentials entered through DSH Settings and no provider request on save. Each
session is pinned to one provider, and quotas are separate per provider. Start with one symbol and a short date
range, then increase only after verifying quota, schema, availability timestamps
and data-quality checks. Worker credentials stay in the data adapter process.
Reports/news are untrusted evidence, not operational instructions. Retrieved text
cannot expand tool privileges or select a credential/host/path.

## Current checklist

- [x] Same repository and current main baseline, separate worktree/branch.
- [x] Superseded open PRs closed; source branches preserved.
- [x] Pinned DSH boot and exact request routing verified locally.
- [x] Budget concurrency, retry and unknown-charge tests pass.
- [x] DSH credential UI and native tool bridge verified with dummy credentials.
- [x] BaoStock anonymous live data and exact-query cache check pass.
- [ ] Paid iFind/RQData authenticated checks (await owner-entered credentials).
- [ ] Live report/news entitlement and full-content extraction checks.
- [x] One-case equal-evidence diagnostic live comparison completed (24 real calls).
- [ ] Repeats, other mechanisms and open-ended cases completed.
- [ ] Capability card supports progression to the minimal core.

Current evidence and gate assessment: [first pilot](FIRST_PILOT.md),
[data-source record](DATA_SOURCES.md), [legacy deployment archive](LEGACY_EXPERIMENTS.md).
The minimal-core gate remains open: no measured collaboration advantage has yet
been demonstrated. Repeats are complete only for single/blackboard on the first case.
