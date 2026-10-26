# Development kickoff prompt

Two prompts live here. The **initiation prompt** starts development at Stage 0. The **stage continuation template** starts every later stage. Both are written for a coding agent working in this repository (Codex or any comparable agent); nothing in them depends on a particular vendor. Paste the text between the fences, replacing the placeholders in angle brackets.

Before pasting the initiation prompt, the owner provides two things: the local path of the extracted P0 and P1 packages (they are licensed and must never be committed), and the target CPU architectures if different from both `linux/amd64` and `linux/arm64`.

---

## 1. Initiation prompt (Stage 0)

```text
You are the implementing coding agent for the Hybrid v1 quantitative factor research system (QFR) in this repository. Your job in this session is Stage 0 of the plan. Do not start later stages.

READ FIRST, IN THIS ORDER
1. docs/PLAN_ALIGNMENT.md — the owner's requirements (R1–R6), the reconciliation decisions, the provider, intake, MCP, lifecycle and Docker contracts, and the acceptance checklist AC-01–AC-14. It wins when documents disagree.
2. docs/HYBRID_V1_DEVELOPMENT_PLAN.md — the ordered build plan. Read sections 0–5, 8, 9 and Stage 0 in section 10, then skim the rest.
3. docs/LOCAL_IMPLEMENTATION_REFERENCE.md — sections 3 (invariants), 4 (architecture), 5 (stack, layout, roles, configuration), 7.7 (factor manifest), 13 (data model and APIs), 15.2 (named tests), 16 Phase 0 (work packages P0.1–P0.7), 17 (defaults), 18.1 (AGENTS.md block).
4. docs/appendix-a-pilot-case-industry-rotation.md — sections A.2, A.3, A.5, A.6 and A.9.
5. docs/examples/llm-profiles.example.json — the illustrative provider/model/role/task configuration.

WHAT YOU ARE BUILDING IN STAGE 0
A repository skeleton in which every later stage has a place, with the contracts defined and the trust boundary already enforced at the database level. Nothing in this stage computes a factor, evaluates anything or calls an LLM.

WORK PACKAGES (implement in order; each ends with green `just check` and `just test`)
P0.1 Create the uv workspace with packages qfr_core, qfr_registry, qfr_research, qfr_eval and qfr_mcp, Python 3.12, pinned lockfile; configure ruff, mypy (strict for qfr_core), pytest and hypothesis; add a justfile with check, test, up, down and build-images targets.
P0.2 Add the import-linter contracts from plan section 9.1 (qfr_research and qfr_eval never import each other; qfr_registry imports neither; qfr_core imports no other qfr package; qfr_mcp imports qfr_core only and calls APIs over HTTP) and wire them into `just check`.
P0.3 Write infra/docker-compose.yml with PostgreSQL 16 and init SQL that creates research_db, registry_db and eval_db, the roles registry_app, research_rw, eval_rw and feedback_ro, the grants from the local reference section 5.4, and triggers that raise on UPDATE and DELETE for insert-only tables. Map any published port to 127.0.0.1 only. Add placeholder service definitions for mcp-api, research-api, research-worker, registry-api, eval-scheduler, eval-worker, release-worker, feedback-api, eval-admin-api and data-ingest with per-service networks and no shared superuser credential; they may be stubs that exit cleanly.
P0.4 Implement configuration loading (pydantic-settings plus YAML) for protocols, release policies, quotas, charters, epochs, provider endpoint / model capability / role / task profiles, and jobs. Commit the defaults for both profiles under configs/: pilot_industry_v1 values from Appendix A.4 and plan section 7.9, and stock_daily_v1 values from the local reference section 17. Every tunable lives in configs/; no magic numbers in code.
P0.5 Define the public Pydantic v2 schemas in qfr_core: InputBundle (plan 4.1), research brief and job record including the exit-gate specification (plan 4.2), dataset manifest with physical and logical hashes and the separate timing, vintage and membership quality labels (plan 4.3), common artifact manifest with kinds and implementations (plan 4.4 and local 7.7), released report, reason-code and flag enums (local 9.2), provider/model/role/task configuration (plan 4.7 and the example JSON), delivery receipt and export manifest (plan 4.8). Define the private official-record and trial-ledger schemas in qfr_eval only. Generate JSON Schema for every public contract and write one valid example document and one invalid example per contract.
P0.6 Set up CI (GitHub Actions) that runs lint, type checks, import-linter and tests against a Postgres service container, and builds the images for linux/amd64 and linux/arm64, recording per-platform digests as artifacts. Build success is not runtime acceptance; say so in the workflow summary.
P0.7 Create AGENTS.md from the local reference section 18.1 block reconciled with plan section 9.2 (fifteen rules), create docs/decisions.md with the decision-log format, and write fixtures/pilot/: a manifest for each of the six run_snapshot inputs and the industry label map with SHA-256, row count, column names and date range taken from Appendix A.3, plus the golden evidence file extracted from the original machine-readable ledgers and reference CSVs identified in Appendix A.6. Raw licensed data stay at the owner-provided local path and are gitignored; tests read them from an environment variable and skip with a clear message when absent.

EXIT GATE FOR STAGE 0 (report each item PASS or FAIL with the test name and a one-line evidence summary)
- Every public schema validates its valid example and rejects its invalid example.
- `just up` starts Postgres with the three databases and four roles.
- BND-01: the research_rw role cannot connect to eval_db and eval_rw cannot connect to research_db.
- BND-04: import-linter contracts pass.
- The pilot fixture test checks hash, row count, columns and date range for each input against Appendix A.3 when the local data path is set, and skips explicitly otherwise.
- CI is green, including both image builds with digests recorded.

RULES THAT APPLY TO THIS AND EVERY SESSION
- Follow AGENTS.md once it exists; until then, follow plan section 9.2.
- The evaluator side never imports research code and never holds LLM credentials. Research code never constructs official-record schemas.
- Do not install or reference any Claude or Anthropic SDK, local model runtime, or always-on scheduler. LLM access, when it arrives in Stage 5, is OpenAI-compatible and configurable; this stage only defines its configuration schemas.
- Do not invent provider names, model identifiers, endpoints, prices or capabilities. Unknown values stay null and are documented as unresolved.
- Do not commit licensed pilot data, credentials or secrets. Secrets are references only.
- Do not weaken a test, loosen a tolerance or edit an expected value to make something pass. If a specification is ambiguous, pick the reading that preserves the invariants, record it in docs/decisions.md, and continue. If a choice would change scope or goals, stop and ask the owner.
- Do not pull work from later stages forward, even if it looks easy.

HOW TO FINISH THE SESSION
1. Run `just check` and `just test` and paste the summary.
2. List each exit-gate item as PASS or FAIL with evidence.
3. List decisions recorded in docs/decisions.md.
4. List open questions for the owner and anything deferred to Stage 1, without implementing it.
5. Commit on a branch named stage-0-foundation with a message that lists the work packages completed. Do not merge.
```

---

## 2. Stage continuation template (Stages 1–8)

```text
You are the implementing coding agent for the Hybrid v1 QFR system in this repository. Your job in this session is Stage <N>: <stage name from plan section 10>. The previous stage's exit gate is green; do not start Stage <N+1>.

READ FIRST, IN THIS ORDER
1. AGENTS.md.
2. docs/PLAN_ALIGNMENT.md sections <list>.
3. docs/HYBRID_V1_DEVELOPMENT_PLAN.md: section 10 Stage <N> (entry, scope, exit gate, not yet) and sections <list>.
4. docs/LOCAL_IMPLEMENTATION_REFERENCE.md sections <list> and the local work packages <Pn.x ... Pn.y> named in Stage <N>.
5. docs/appendix-a-pilot-case-industry-rotation.md sections <list> when the stage touches the pilot.
6. docs/decisions.md, to inherit earlier decisions.

ENTRY CONDITION
Confirm the Stage <N> entry condition in plan section 10 holds. Owner inputs available for this stage: <list, e.g. provider endpoints and spend authorization, native hosts, protocol approval>. If a required input is missing, stop and list exactly what is needed; do not substitute defaults or mocks for an input the exit gate requires to be real.

WORK PACKAGES
Implement the Stage <N> scope in plan section 10 in the order given, mapping each item to its local work-package ID where one exists. For each: implement, add tests, run `just check` and `just test`, fix until green, then continue.

EXIT GATE
Run every check listed under Stage <N> exit gate and the named suites it cites (plan section 11.2). Report each as PASS or FAIL with the test name and a one-line evidence summary. Paid provider calls happen only with explicit owner authorization in this session; otherwise run the offline scripted-model variant and report it as such.

RULES
Follow AGENTS.md. Preserve invariants and existing golden evidence. Record routine resolutions in docs/decisions.md; surface material scope or goal changes to the owner before proceeding. Never replace a missing provider, an elapsed-time wait, a budget pause or a failed gate with a silent fallback or success state.

HOW TO FINISH THE SESSION
1. Paste the `just check` and `just test` summaries.
2. Exit-gate items as PASS or FAIL with evidence.
3. Decisions recorded this session.
4. Open questions for the owner and items deferred to later stages, without implementing them.
5. Commit on a branch named stage-<N>-<short-name>. Do not merge.
```

---

## 3. Reading lists per stage (fill the template's `<list>` placeholders)

| Stage | PLAN_ALIGNMENT sections | Plan sections | Local reference sections | Appendix A |
|---|---|---|---|---|
| 1 | E, I | 3.5, 4.3, 7.4, 7.5 | 6, 7, 8.5–8.7, 15 | A.3, A.4, A.5 |
| 2 | I | 3.5, 4.5, 7.1–7.9 | 8, 13.3, 15.2 | A.4, A.6 |
| 3 | E, H | 4.4, 7.2–7.4 | 7.6–7.8, 13.1, 13.4, 8.3–8.4 | A.5, A.9 |
| 4 | F, G, I | 2, 4.6, 4.8, 5, 7.7, 7.8 | 9, 13.2, 13.5–13.8 | A.2, A.8 |
| 5 | C, D | 4.7, 6.1–6.5 | 11, 13.2, 13.6 | — |
| 6 | G, I | 6.6, 7.6, 7.7 | 12 | — |
| 7 | H, J, K | 10 Stage 7, 11.4 | 15.3, 16.1 | A.6, A.7 |
| 8 | L | 10 Stage 8 | 10, 14 | — |
