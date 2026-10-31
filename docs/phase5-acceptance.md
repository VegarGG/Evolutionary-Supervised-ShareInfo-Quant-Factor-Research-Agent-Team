# Phase 5 implementation and acceptance record

Status: **implemented; every Phase 5 acceptance check passes in local tests against a
real PostgreSQL 16, with the scripted LLM; the on-machine steps on the Mac Studio are
the owner's next step**. Owner acceptance and merge are not asserted. Phase 5 is stacked
on the Phase 4 branch (PR #15), which is stacked on the Phase 3 branch (PR #14), and it
follows plan v2.2 (immediate release). No Phase 6 work has begun. Design choices are in
[decisions.md](decisions.md#phase-5-decisions).

No test reaches a provider: every model answer is scripted, and the test session sets
`ALLOW_MODEL_REQUESTS = False`.

## Acceptance checks

| Check (plan) | Result | Evidence |
|---|---|---|
| On the planted world with the scripted LLM, the best island fitness improves over 10 generations | Pass | `tests/benchmarks/test_benchmarks.py::test_bm_planted`: the best fitness record across islands rises from 0.820 after generation 1 to 0.838 from generation 3 on (fitness is relative, so the record is what improves; decision 4) |
| ... and a factor with rank correlation of 0.7 or more to A1 or A2 passes W1 (BM-PLANTED: within 10 generations, generations to discovery recorded, the deliverable's iteration history reaches back to the explore hypothesis) | Pass | `test_bm_planted`: 9 published versions with mean W0 rank correlation of at least 0.7 to A1 or A2 pass W1, the first two published in generation 1; the deliverable lists one, and its history's roots are the explore hypotheses that started its lineage |
| Archive coverage stays at or above 25% of cells | Pass | `test_bm_planted`: coverage per generation (read at the start of generations 1 to 10) 0, 12.5, 17.2, 18.8, 21.9, 21.9, 21.9, 23.4, 25.0 and 25.0%; it reaches 25% (16 cells) in generation 9 and stays there (the empty start begins at 0). This passes with no margin: the planted world's passing forms reach only 18 of the 64 cells (decision 18) |
| The null-world W1 pass rate is recorded and documented | Recorded | `test_bm_null`, 50 generations on the null world with the same pool: 26 versions published, all 26 evaluated on W1, none passed (pass rate 0.0) (below). Zero acceptances is a Phase 6 check |
| TRC-03: the iteration history of a delivered version reconstructs every hop across five generations including a crossover | Pass | `tests/research/test_lineage.py`: explore A and P, mutate A into B, cross B with P into C, mutate C into D (with a discarded sibling) and D into E, through the MCP front door, research and the evaluator; every operator application names its parents and an AST diff from each; `qfr.trace.export` reconstructs every hop of every published version's DAG; the deliverable's history of E has 6 hops in generation order, roots at the hypotheses of A and P, the crossover hop from B and P, and D's discarded sibling with its failed pre-screen checks. BM-PLANTED checks the same properties on the 43 versions the unscripted engine published |

Benchmark results with the fixed seeds (`exports/benchmarks/` from `just bench`):

| | BM-PLANTED (10 generations) | BM-NULL (50 generations) |
|---|---|---|
| Published versions | 43 | 26 |
| Evaluated on W1, passed (pass rate) | 43, 12 (0.279) | 26, 0 (0.0) |
| Planted discoveries (W1 pass, mean rank correlation to A1 or A2 of 0.7 or more) | 9, the first two in generation 1 | none expected |
| Best fitness record across islands, after generation 1 and before the last | 0.820 and 0.838 | 0.0 and 0.892 (relative among null factors) |
| Archive coverage before the last generation | 25.0% (16 of 64 cells) | 6.25% (4 of 64 cells) |
| Operator applications | 96 llm_mutation, 36 crossover, 59 syntactic | recorded in the results |
| Deepest lineage | 4 generations; the deepest with a crossover spans 2 generations and 3 hops | |
| Test-clock span (1 hour per generation, then 6-hour drain steps) | 40 hours | 158 hours |

## Delivered scope

| Task | Delivered | Main tests |
|---|---|---|
| P5.1 | Islands and population members (official, provisional, archived, with source, expression, metrics, fitness detail), initialization from the pools, seeds and a parent job, the empty start, the 64-cell MAP-Elites archive, lineage edges and families for children; research_db migration 0003 (insert-only `bandit_outcomes`) | `tests/research/test_engine.py`, `tests/research/test_evolution_units.py` |
| P5.2 | Official fitness on released W1 values and provisional fitness on W0 metrics, exactly the Section 12.2 formula, multipliers, the empty-library rule, island or global percentiles, tie-breaks | `test_evolution_units.py` (formula, basis, empty library, complexity, multipliers, ties), `test_engine.py` |
| P5.3 | Parent selection (tournament or archive elite), deterministic syntactic mutation (five rules) and subtree crossover, each with its rule, seed and AST diff in the trace | `test_evolution_units.py`, `test_lineage.py`, BM-PLANTED |
| P5.4 | llm_mutation, crossover and repair prompts with flag-targeted instructions, the mode bias, and the context assembler (parents, elites, diverse archive members, knowledge, seeds, what the lineage tried) | `test_evolution_units.py`, BM-PLANTED |
| P5.5 | The publication pre-screen, canonical and behavioral dedup, ranking by provisional fitness plus novelty (Section 11.6) with per-island fairness up to the quota, each decision traced with its values | `test_evolution_units.py`, `test_lineage.py` (a discarded sibling), BM-PLANTED |
| P5.6 | The Thompson-sampling slot allocator with forgetting, floor and cap, stagnation (reseed or pause), migration around the ring, and the diversity guardrail; the plan validator's evolution rules | `test_engine.py`, `test_evolution_units.py` |
| P5.7 | The iteration history over DAG lineages (a crossover hop has two parents) with discarded siblings, and `qfr.trace.export` (trace.json and iteration_history.md under `exports/traces/`, owner-grade records joined into the owner's copy only) | `test_lineage.py`, `tests/research/test_traces.py`, `tests/mcp/test_server.py` |
| P5.8 | The BM-PLANTED and BM-NULL harness at W1 level, driven through the MCP front door with a scripted client and a scripted LLM drafting from a 300-expression test pool; `just bench`; a nightly workflow keeping the results as an artifact | `tests/benchmarks/` |

The default charter is version 2: it adds the evolution settings (fitness weights and
multipliers, archive descriptors, variation rules and targeted instructions, the
context sampler, bandit and selection details). Every value is a Section 12 value or a
documented choice in the decisions. The engineer prompt is engineer/2 and the repair
prompt is new. The MCP catalog gains `qfr.trace.export` (31 tools). Nothing is
preloaded: no factors, strategies, seeds, sample briefs or prices. The benchmark pool is
test data under `tests/benchmarks/`.

## Checks executed

- `ruff check`, `ruff format --check`, `mypy` (fresh cache), all four import contracts,
  schema and public-card generation (no diff after regeneration) and the license check
  pass.
- `pytest -n 4` against PostgreSQL 16 with the Phase 0 roles and all migrations
  (`QFR_REQUIRE_DB_TESTS=1`): **1099 passed, 0 skipped** in about three minutes.
  Phase 5 adds 40 tests (34 unit, 5 engine, TRC-03). research_db is empty after
  the run. The benchmarks are not part of this run.
- `pytest -m benchmark tests/benchmarks` (what `just bench` runs): both pass in 24
  minutes on the merged branch. Two more BM-PLANTED runs gave the same generations, draws,
  operator applications, published versions, discoveries and lineages. Only the
  version ids and the number of interpretation reviews (12 and 13) differed: the audit
  sample of the analyst's interpretations hashes each interpretation's fresh id
  (Phase 4), and no review changed a result.
- An earlier run on the Phase 3 batch release (before plan v2.2 and the novelty
  ranking) also discovered in generation 1, with 27% coverage, and BM-NULL published 23
  versions with no W1 pass.

Not executed here: Docker image builds, `just up`, `just doctor`, and any provider call.

## On-machine steps (owner)

1. **Update and build.** `git fetch origin`, then
   `git checkout -B claude/project-thread-l7m6rq origin/claude/project-thread-l7m6rq`,
   `uv sync --locked`, `just check`, `just build`. The research image now carries the
   v2 charter and the new prompts; the migrate service applies research migration 0003
   at the next `just up`.
2. **Benchmarks.** With Docker running, `just bench` (it starts the disposable test
   database, like `just test-db`). It takes about 25 minutes on this sandbox. Send
   back `exports/benchmarks/bm_planted.json` and `bm_null.json`, or just their
   `summary` blocks.
3. **A real evolutionary job.** On the throwaway stack from the Phase 3 and Phase 4 tests
   (`export COMPOSE_PROJECT_NAME=qfr-dry QFR_EPOCH=synthetic_001 QFR_INGEST_SOURCE=off`,
   `just data-build --source synthetic`, `just up`, `just doctor`), submit a brief of
   your own through the host agent with `budget.max_generations: 3` and a small
   `budget.max_cost` (for example 60 CNY). Generation 1 explores; generations 2 and 3
   should run llm_mutation, crossover and syntactic tasks once the first W1 reports are
   in. Afterwards ask for `qfr.job.get`, `qfr.ops.costs` with
   `group_by: ["provider", "role"]`, and `qfr.trace.get` on one generation 2 or 3
   publication.
4. **Trace export.** Ask the host agent to call `qfr.trace.export` on a generation 3
   publication. It should write `exports/traces/<version_id>/trace.json` and
   `iteration_history.md` on the Mac, with the lineage hop by hop and the owner-grade
   records in a section labelled owner_only.
5. **Clean up.** `just down`, `docker compose -p qfr-dry down -v`, and
   `unset COMPOSE_PROJECT_NAME QFR_EPOCH QFR_INGEST_SOURCE`.

Send back: the benchmark summaries, `qfr.job.get` and `qfr.ops.costs` for the job, the
operators each generation ran (from `qfr.job.events` or `just logs tail`), and anything
unhealthy or unexpected.
