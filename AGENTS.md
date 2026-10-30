# AGENTS.md: rules for every coding session

Project: QFR, the owner-driven Multi-Agent Quantitative Factor Research and Evolution System.
Source of truth: docs/PLAN.md. Decision log: docs/decisions.md. Build only what PLAN.md says.

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
