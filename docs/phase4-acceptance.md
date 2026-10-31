# Phase 4 implementation and acceptance record

Status: **implemented; every offline Phase 4 acceptance check passes in local tests
against a real PostgreSQL 16; the manual, owner-authorized check (one real generation
per provider on the Mac Studio) is the owner's next step**. Owner acceptance and merge
are not asserted. Phase 4 is stacked on the Phase 3 branch (PR #14). No Phase 5 work
has begun. Design choices are in [decisions.md](decisions.md#phase-4-decisions).

No test reaches a provider: every model answer is scripted, and the test session sets
`ALLOW_MODEL_REQUESTS = False`.

## Acceptance checks

| Check (plan) | Result | Evidence |
|---|---|---|
| Offline end to end: a brief submitted through MCP produces a job and a generation with hypotheses, candidates, reviews and at most 12 publications; reports sync back; interpretations are written; a w1_pass deliverable with an iteration history and owner-grade evidence is fetched through `qfr.deliverable.get` | Pass | `tests/research/test_research_e2e.py::test_offline_brief_to_deliverable_through_mcp`: `qfr.job.submit` → generation 1 (plan, hypothesis, two candidates, reviews, 1 to 12 publications) → the evaluator screens and runs W1 and releases the reports at once → generation 2 starts because generation 1's feedback is complete, syncs the reports and writes interpretations → the monitor reads w1_pass → `qfr.deliverable.get` returns `deliverable/1` with the manifest, `iteration_history/1`, released reports, caveats, costs, owner-only evidence and the evaluator's tier confirmation; the job becomes DELIVERED |
| BND-02: the research tool registry matches its snapshot; no tool can affect evaluation, pools or jobs | Pass | `tests/research/test_boundaries.py::test_bnd_02_research_tool_registry_snapshot` (tool → roles snapshot, namespaces, only read, search, validate, explain and evaluate tools reach a model; `registry.publish` is the packager's alone) |
| BND-05: research holds no evaluation-admin or control access | Pass | `test_boundaries.py::test_bnd_05_research_configuration_holds_no_evaluation_or_control_access` (configs and Compose environments), `::test_bnd_05_research_code_reaches_only_the_registry_and_feedback_api` (no evaluation or control names or URLs in the code, no `qfr_eval` or `qfr_mcp` import) |
| MCP-01: every MCP call is audited and its request id reaches the backend's log | Pass | `test_research_e2e.py::test_log_03_and_mcp_01_one_job_id_joins_every_service` |
| MCP-02: the tool catalog is the Phase 4 catalog | Pass | `tests/mcp/test_server.py::test_mcp_02_catalog_is_the_phase_four_catalog` (30 tools, read, write and control annotations, resources, templates and prompts), `::test_schema_resources_and_prompts_hold_no_defaults` |
| MCP-03 (Phase 4 half): `qfr.job.submit` and `qfr.job.steer` reject text containing owner-only values of referenced versions | Pass | `test_research_e2e.py::test_mcp_03_submit_and_steer_reject_owner_only_values_of_referenced_versions` (a value at full precision and at the release step, in a brief and in a steering note; nothing reaches research, the log never holds the number, the clean brief is accepted with the comparison count); `tests/mcp/test_scan.py` (18 matching rules). The approval half is Phase 6 |
| TRC-01: the packager refuses a candidate whose trace lacks a required step for its operator, and records the refusal | Pass | `tests/research/test_traces.py::test_trc_01_publication_is_refused_when_a_required_step_is_missing` (failed TRACE_CHECKED naming the missing step, candidate `not_selected` with `TRACE_INCOMPLETE`, no publication, a WARNING line), `::test_trc_01_the_required_steps_depend_on_the_operator`, `::test_trc_01_a_complete_trace_was_checked_before_each_publication` |
| TRC-02: every LLM step has an agent run with full request and response, and a log line with the same run id | Pass | `test_traces.py::test_trc_02_every_llm_step_has_a_full_agent_run_and_a_log_line` (the first user prompt in each stored request hashes to the run's prompt hash; response text and parsed output stored; the MODEL_RESPONDED step and the `llm_call_completed` line carry the same run and step ids) |
| LOG-03: one job id joins every service's log lines | Pass | `test_research_e2e.py::test_log_03_and_mcp_01_one_job_id_joins_every_service` (`qfr.logs.correlate` finds the job id in qfr-mcp, research-api, research-worker, registry-api, eval-scheduler, eval-worker and release-worker, in time order) |
| No generation or job exceeds its cost cap in tests | Pass | The end-to-end test checks every generation's ledger total against the generation cap and the job's cost against its `max_cost`; `tests/research/test_operations.py::test_the_job_cost_cap_stops_research_and_closes_the_job` refuses the next call before it is sent and closes the job as `budget_exhausted` with its cost at or under the cap |
| Manual, owner-authorized: one real generation with each provider as primary; costs recorded; `qfr llm probe` green for every configured model | **Owner** | The steps are below. Nothing in this branch has called a provider |

## Delivered scope

| Task | Delivered | Main tests |
|---|---|---|
| P4.1 | research_db migration 0002: jobs, events, programs, charters, islands, generations, tasks, hypotheses, candidates, reviews, population, archive, bandit state, lineage, report cache and links, feedback cursor, interpretations and challenges, knowledge, budget ledger, agent runs, trace steps, deliverables, queue, control, probes, events; insert-only REVOKEs and triggers | `tests/research/test_generation.py`, every research test |
| P4.2 | Provider layer over PydanticAI's DeepSeek, Moonshot and Z.ai classes; providers.yaml and roles.yaml; thinking policy, explicit max tokens, timeouts; tool-then-`json_object` output; fallback chains; peak and off-peak prices; the no-price-no-run rule; `qfr llm probe` at setup, daily and job start | `tests/research/test_providers.py`, `tests/research/test_roles.py`, `test_operations.py` (probe) |
| P4.3 | Tool layer with role allow-lists, call logging and trace steps | `test_boundaries.py`, `test_traces.py` |
| P4.4 | Feedback sync into report_cache and report_links with a per-program cursor | `test_research_e2e.py` |
| P4.5 | Six PydanticAI agents with versioned prompt files, per-role models, the cross-provider critic, full request and response persistence | `test_traces.py`, `test_roles.py` |
| P4.6 | The DSL reference card generated from the operator registry, versioned by hash and recorded in engineer steps | `tests/research/test_dsl_card.py` |
| P4.7 | Packager: trace completeness check, manifest with full provenance, publication with the publisher token, lineage | `test_traces.py` |
| P4.8 | Generation state machine with persistence, resumable states, queue retries and leases, parallel tasks, plan validation with a deterministic fallback, a trace step per transition | `test_generation.py`, `test_operations.py` |
| P4.9 | Budget ledger in CNY: admission before every call, run token limits, generation, daily, program and job caps, the hard stop | `test_operations.py`, `test_research_e2e.py` |
| P4.10 | Jobs: brief validation, the owner-only scan verdict, seed publication, charter derivation, the job state machine, the monitor, deliverable and iteration-history assembly, research-api | `test_research_e2e.py`, `test_operations.py`, `tests/research/test_job_lifecycle.py` |
| P4.11 | MCP tools `qfr.job.submit`, `list`, `get`, `events`, `wait`, `steer`, `pause`, `resume`, `cancel`, `qfr.deliverable.list` and `get`, `qfr.trace.get`, `qfr.lineage.get`, `qfr.ops.costs`; resources for cards, pools, jobs, deliverables, traces and schemas; prompts `qfr.brief` and `qfr.report_deliverable`; providers in `qfr.status` and `qfr.setup.status` | `tests/mcp`, `test_research_e2e.py`, `test_job_lifecycle.py` |
| P4.12 | Scripted `FunctionModel` scenarios and an MCP client over ASGI; real model requests disabled in the suite | `tests/research/scripted.py`, `tests/research/rig.py`, `tests/conftest.py` |

Compose runs research-api and research-worker from a new `research` image target
(`qfr-v2-research:phase4`) with the prompts, an HTTP healthcheck and a heartbeat file.
`just llm-probe` runs the probe inside research-worker, `just trace-export <version_id>`
writes a trace and iteration history to `exports/traces/`, and `just doctor` expects
both research services. CI builds the research image for both architectures.

Nothing is preloaded: no factors, strategies, seeds, sample briefs or prices.

## Checks executed

- `ruff check`, `ruff format --check`, `mypy` (fresh cache), all four import contracts,
  schema and public-card generation (no diff after regeneration) and the license check
  pass.
- `pytest -n 4` against PostgreSQL 16 with the Phase 0 roles and all migrations
  (`QFR_REQUIRE_DB_TESTS=1`): **1055 passed, 0 skipped** in about three and a half
  minutes; Phase 4 adds 68 tests. research_db, registry_db and eval_db are empty after
  the run (control_db keeps the audit row the Phase 0 boundary test writes on purpose).
- Two Phase 3 tests depended on the release order of reports due at the same time
  (about one run in four failed). The fix, ties broken by queue id and the
  library-vacuity check on the first W1 record, is part of the Phase 3 branch (Phase 3
  decision 16). Both tests pass repeatedly.
- The research image layout was checked without Docker: with only the files the
  Dockerfile copies, research-api and research-worker build their environments, and
  `qfr llm probe` with no keys and no prices prints a failing report without sending a
  request.

Not executed here: Docker image builds, `just up`, `just doctor`, `just llm-probe` with
real keys and any provider call.

## On-machine test (owner)

These steps spend real money on three providers. Keep each job small; the caps below
are suggestions for a smoke test, not product defaults. Run them on the synthetic
throwaway project from the Phase 3 test, so the real epoch's W1 trials are not spent on
smoke-test candidates (every publication is evaluated on W1 and counts as a trial).

1. **Update and build.** `git fetch origin`, then
   `git checkout -B claude/project-thread-6u818y origin/claude/project-thread-6u818y`,
   `uv sync --locked`, `just check`, `just build`.
2. **Keys.** In `.env`, set `DEEPSEEK_API_KEY`, `MOONSHOT_API_KEY` and `ZHIPU_API_KEY`.
   Only research-worker receives them.
3. **Models, prices and the Moonshot tier.** In `configs/research/providers.yaml`:
   - check each model id against the provider's console and keep the China base URLs
     unless your accounts are international (the alternative URLs are in comments);
   - fill in every `price_cny_per_mtok` value (CNY per million tokens: `in_miss`,
     `in_hit`, `out`, and `cache_write` for kimi-k3) from each provider's current price
     page, and keep DeepSeek's `offpeak_factor` and peak windows if they still apply;
   - set `providers.kimi.account.concurrency_limit` from the Moonshot console's rate
     limits page (it must be at least `request.concurrency`, 4).
   Then `just build` again, because configuration is part of the image.
4. **Throwaway stack.** As in Phase 3:
   `export COMPOSE_PROJECT_NAME=qfr-dry QFR_EPOCH=synthetic_001 QFR_INGEST_SOURCE=off`,
   `just data-build --source synthetic`, `just up`, then `just doctor` (expect research-api
   and research-worker healthy, and a `providers` observation).
5. **Probe.** `just llm-probe setup`. It exits 0 only when every role's primary model is
   listed, priced and accepts both requests with its thinking setting, and Moonshot's
   concurrency and balance check pass. Each failing check is named in the report; fix
   providers.yaml, `just build`, `just up`, and probe again. The probe's calls are tiny
   and recorded under the role `probe`. Ask the host agent for `qfr.setup.status`: the
   providers step should be `ok`.
6. **Three generations, one per provider as primary.** For each provider in turn, edit
   `configs/research/roles.yaml` so the supervisor, hypothesis, engineer, analyst and
   interp_review primaries are that provider's models (its strong model for every role
   but the engineer, its fast model for the engineer), keep the fallbacks, and leave the
   critic as it is: the critic never runs on the engineer's provider, so it uses
   another provider by design. Then `just build` and
   `docker compose --env-file .env -f infra/docker-compose.yml up -d research-worker`.
   Ask the host agent to read the `qfr.brief` prompt and submit a brief of your own with
   `budget.max_generations: 1` and a small `budget.max_cost` (for example 30 CNY).
   Follow it with `qfr.job.wait` or `just logs tail`; a generation takes minutes to
   tens of minutes depending on thinking.
7. **Record the costs.** After each job, ask for `qfr.ops.costs` with
   `group_by: ["provider", "role"]` for that job, and `qfr.job.get`. Check that the
   cost is under the job's `max_cost`, and compare the ledger with each provider's
   console for the same period. Optionally run `just trace-export <version_id>` on one
   publication and read `exports/traces/<version_id>/iteration_history.md`.
8. **Clean up.** `git checkout configs/research/roles.yaml`, keep your providers.yaml
   changes (prices and ids are your configuration; do not commit keys), `just down`,
   `docker compose -p qfr-dry down -v`, and
   `unset COMPOSE_PROJECT_NAME QFR_EPOCH QFR_INGEST_SOURCE`.

Send back: the probe report (or its failing checks), each job's `qfr.ops.costs` by
provider and role, `qfr.job.get` for each job, `just doctor`, `docker stats --no-stream`
during a generation, and anything unhealthy or unexpected in `just logs tail`.
