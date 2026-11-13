# AGENTS.md: rules for every coding session

Project: QFR, the owner-driven Multi-Agent Quantitative Factor Research and Evolution System.
Current development authority: `docs/harness/PLAN.md`, approved by the owner on
12 November 2026 Beijing. `docs/PLAN.md` and the old phase records are historical
QFR specifications. Preserve them and their evidence. Decision log: docs/decisions.md.

## Approved harness work
- Develop in `harness/` in this same repository. DSH owns research sessions and
  model/tool loops; do not wrap the entire old orchestration engine or fork DSH's loop.
- First establish collaboration capabilities against equal-evidence controls.
  Diagnostic cases and withheld keys belong to tests, never a production factor pool.
- Daily China A-share adapters are iFind, RiceQuant RQData and anonymous BaoStock
  (the free testing default). A research session pins exactly one source; never
  fall back or mix sources automatically. Credentials are entered in DSH Settings.
  Reports/news are read-only cited evidence with publication, ingestion and
  retrieval timestamps kept distinct. Keep paid data pilots narrowly bounded.
- DSH's native DeepSeek Messages transport is authorized for these experiments.
  On 13 November the owner additionally authorized GLM Coding Plan during
  DeepSeek peak hours, using GLM 5.3 Flash first. GLM 5.3 requires clear recorded
  evidence that Flash is insufficient. The owner confirmed DSH eligibility with
  Zhipu. Credentials are entered in DSH Settings; no metered-API fallback is
  authorized. The owner subsequently replaced the scheduled expanded-BaoStock
  trial with GLM 5.3 Flash on Coding Plan Pro until 18:00 Beijing on 13 November.
  Preserve DeepSeek's original admission windows for any later DeepSeek calls.
  Other providers and local models remain unauthorized.
  The owner subsequently identified DSH's working `zai-coding-cn` route and
  requested guard extensions in the native Models page. Use its native pi-ai
  Coding Plan transport, editor and credential reference; preserve the failed
  Anthropic probe and both reservations. Details: `NATIVE_MODELS_2026-11-13.md`.
- Preserve the original cumulative 200 CNY cap and carry-forward evidence. Admit
  every paid wire request atomically; retain reservations for unknown charges.
- Latest verified native GLM trial: `docs/harness/LIVE_GLM_NATIVE_2026-11-13.md`.
  Active route `glm-coding-native-package-2026-11-13` has a recorded 20 CNY
  package sublimit inside the original 200 CNY ceiling; 60 aggregate requests,
  1,500 credits and the same 18:00 Beijing expiry. Seven of eight pilot sessions
  are used. One bounded owner trial remains; never reset history to create slots.
- Run offline checks with `just harness-check` and `just harness-test`. Live
  experiments are separate commands with explicit campaign state and audit records.
  No ordinary test target may call a real model or data provider.
- Current experiments do not publish official results, operate pools, or control
  evaluation. The invariants below continue to govern any reused QFR services.
- End each work package with updated README, decision/experiment records and a
  commit. Do not merge a new PR without authorization.
- The owner now authorizes the bounded interactive supervisor/two-worker prototype
  in `docs/harness/INTERACTIVE_TRIAL.md`. Use native DSH Agent Teams/subagents;
  preserve every earlier trace. Additional role/provider designs are staged in
  `ROLE_MODELS_AND_CONTEXT.md`; the GLM replacement and its bounds are recorded in
  `GLM_CODING_PLAN_2026-11-13.md` without changing prior trial histories.
- The owner-reported official cumulative 20.35 CNY observation supersedes the old
  conservative spending estimate as the budget baseline. Keep the immutable
  reconciliation, covered-call digest and raw usage; charge new calls afterward.

## Non-negotiable invariants (each one has tests; never weaken them)
1. Research code never invokes, configures, prioritizes or cancels evaluation, and never touches simulated accounts or pools. No such tool, endpoint or credential may exist on the research side.
2. Published artifact versions are immutable. Any change creates a new version. Pool changes are append-only events.
3. The evaluator pulls artifacts and pool changes on its own schedule. There is no push or trigger from research or from the front door.
4. Research reads feedback only through the GET-only Feedback API, which serves released reports only.
5. Every official record and released report references the artifact version id, content hash, protocol version, data snapshot id and evaluator code version.
6. W3 holdout numbers never reach research. Only decisions and reason categories leave the evaluation zone toward research. The owner reads them through the eval admin API only.
7. Every evaluated version is written to the trial ledger, including failures.
8. Official measurement has no LLM, no network and no wall-clock dependence. Results are reproducible bit for bit.
9. Research processes read only the research-zone snapshot (dates on or before the cutoff) and only their own logs.
10. Every write is attributed to a principal and logged in an append-only event table, and every MCP call is audited.
11. Nothing enters a pool and no acceptance case closes as accepted without an approval record created from the owner's verbatim confirmation through MCP. No code path promotes automatically.
12. Released diagnostics are enum codes only. Never release free text produced by executing artifact code.
13. Every published version has a complete, append-only development trace. The packager refuses to publish without it. Agent runs store the full request and response.
14. The MCP front door exposes owner-grade control only: briefs, reads, approvals, pool curation, operations and logs. It never runs research tools, publishes, writes official records, alters runs or holds LLM keys.

## Engineering rules
- Python 3.12 in a uv workspace with packages qfr_core, qfr_registry, qfr_research, qfr_eval and qfr_mcp. import-linter contracts must pass; qfr_mcp imports only qfr_core.
- Every tunable lives in configs/*.yaml with the defaults from PLAN Section 20. No magic numbers.
- There are no default factors, default strategies, demo seeds or reference samples in code or configuration. A fresh deployment is empty until the owner imports a raw factor pool.
- Research LLMs are the Kimi, GLM and DeepSeek online APIs through OpenAI-compatible chat completions, reached through PydanticAI's provider classes and configured per role in configs/research. Never hard-code a model id, endpoint, price or thinking setting. Never force tool_choice. Never add another provider or a local model.
- Every cross-boundary payload is a Pydantic v2 model, validated before it is persisted.
- Timing convention: factor at close t, execution at close t+1, label from close t+1 to close t+1+h.
- Log everything through the shared structlog setup with the mandatory fields and correlation ids. A log line about an entity carries that entity's id. Never log a secret; the redaction processor is mandatory on every sink.
- Every step that changes what happens to a candidate is a trace step written by deterministic code, never by an agent.
- Write tests together with each feature. Tests never call real providers: disable model requests and use FunctionModel or TestModel. Tests never call a real MCP client; use the scripted client.
- Use deterministic seeds everywhere. Hashed outputs use canonical JSON with sorted keys and no unordered iteration.
- Schema changes go through Alembic only. Insert-only tables are protected by triggers.
- Official-record schemas live in qfr_eval and must never be imported by research code or qfr_mcp.
- Images are built for linux/arm64 first; a dependency without an arm64 wheel is not an option.
- When the plan is ambiguous, choose the option that better protects measurement integrity and traceability, record it in docs/decisions.md and continue.
- A task is done when code, tests, logs and docs are updated and the check and test targets are green.
