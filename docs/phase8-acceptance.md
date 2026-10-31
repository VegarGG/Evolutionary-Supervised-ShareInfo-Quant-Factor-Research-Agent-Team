# Phase 8 implementation and acceptance record

Status: **implemented; every check that can run without Docker passes. The sandbox
service, backups with verification and the restore drill's audit check run on the Mac
Studio and are the owner's next step**. Owner acceptance and merge are not asserted.
Phase 8 is stacked on the Phase 7 branch (PR #18), which is stacked on PR #17, #16, #15
and #14, and follows plan v2.2 (every report is released as soon as it is recorded). It
depends on none of the open owner decisions. Design choices are in
[decisions.md](decisions.md#phase-8-decisions).

No test reaches a provider: every model answer is scripted, and the test session sets
`ALLOW_MODEL_REQUESTS = False`.

## Acceptance checks

| Check (plan) | Result | Evidence |
|---|---|---|
| Sandbox escape tests (network, filesystem, fork bomb, timeout) fail safely | Pass here; the container layer is the owner's step | `tests/eval/test_sandbox.py`: network (a socket and `__import__`), file reads and writes, a fork bomb, a subprocess and introspection are refused by the static check before anything runs; the runtime layer alone (audit hook and resource limits, with the static check bypassed) blocks the same escapes; a CPU-bound loop ends at the CPU limit, a sleeping one at the wall clock, a memory bomb at the memory limit; raised errors and wrong shapes become a code without detail. `tests/test_pyfactor.py` covers the static rules. `tests/boundary/test_compose.py`: eval-sandbox has `network_mode: none`, no URL, token, key or secret, a process limit, and mounts only its log folder and the exchange volume. On the Mac, `just doctor` adds `sandbox_isolation` |
| EVL-03 passes for Python factors | Pass | `test_sandbox.py`: the prefix probe catches a Python lookahead, the window probe a dishonest lookback, and a Python factor's values equal the same factor's in the DSL; `tests/eval/test_python_factors.py`: lookahead and a dishonest lookback fail screening through the evaluator, a Python factor is screened and measured on W1 through the sandbox, can be a strategy component, and `qfr eval reproduce` re-runs it through the sandbox with the same results hash (EVL-04) |
| A rollover dry run preserves every record link and every trace link | Pass | `tests/eval/test_rollover.py`: on a synthetic world, every official record, run, series file, ledger row, released report, trace step and registry row made before the rollover is unchanged afterwards and still resolves; old records still reproduce; in-flight versions restart, queued jobs are cancelled and a job running across the rollover writes nothing; the proposal follows Section 10.6 and each broken rule is named |
| All invariant tests still pass unchanged | Pass, with three widened expectations | The whole suite passes. Three earlier tests changed, each because Phase 8 adds something they enumerate: EVL-01's list of eval-admin-api write routes gains `/v1/epochs/rollover` (the owner-approved rollover; still nothing enqueues or evaluates a version on request), MCP-02's catalog gains `qfr.ops.rollover_epoch` and `qfr.acceptance.override`, and a scheduler test's one-job-per-version rule now reads one job per version and epoch |

## Delivered scope

| Task | Delivered | Main tests |
|---|---|---|
| P8.1 | qfr-python/1 factors: the static check (registry, pool import, evaluator); the eval-sandbox service with no network, database, snapshot or secrets; a fresh child per pass with resource limits and an audit hook; inputs without dates or instrument ids, columns in a seeded order; prefix and window probes; reproduce through the sandbox | `test_sandbox.py`, `test_python_factors.py`, `test_pyfactor.py`, `test_pool_import.py`, `test_compose.py` |
| P8.2 | qfr-strategy/2: long-short with a daily borrow cost, position caps with trims, industry caps, industry neutralization, shared by the backtester and the sim-engine; owners ask through `strategy_spec.rules` or a pool import. Research notes: a third artifact kind with output-quality checks, a released `note` report, one note per research generation | `tests/metrics/test_portfolio_rules.py`, `tests/eval/test_strategy_rules.py`, `tests/test_strategy_manifests_v2.py`, `tests/eval/test_research_notes.py`, `tests/research/test_note_builder.py`, `tests/research/test_research_e2e.py` |
| P8.3 | `w2_mode: thresholdout` in a release policy (`docs/examples/release_policy_thresholdout.yaml`): per-epoch state pinned at the first query, every draw logged and reproducible from the private seed, a burn alert when the budget is spent | `tests/eval/test_thresholdout.py` |
| P8.4 | `just epoch-propose`, `just epoch-plan`, `qfr.ops.rollover_epoch` (dry run, or the rollover with a `ROLLOVER R-<epoch_id>` approval); the synthetic dry run | `test_rollover.py`, `tests/eval/test_approval_tools.py` |
| P8.5 | Hash chains over the audit tables in registry_db, eval_db and control_db, sealed and checked by every backup; `just verify-backups` and `backups/VERIFIED.json`; the ops-nightly verification alert; the restore drill's AUDIT check. Separate Postgres instances are not done (decision 14) | `tests/test_audit_chain.py`, `tests/test_backup_script.py`, `tests/mcp/test_nightly.py`, `tests/mcp/test_restore_drill.py` |
| P8.6 | Point-in-time industry classification in snapshots (synthetic sectors, an owner CSV for CN with a coverage check, BND-06 on the research copy); the market adapter interface with CN and a US-equities adapter that states its requirements and refuses to build | `tests/data/test_industry.py` |
| P8.7 | CUSUM decay monitoring next to the v1 rule, each with its own alert; `qfr.acceptance.override` with a 200-character rationale, a 24-hour cooling period and a second confirmation, enforced in the tables too | `tests/eval/test_monitoring.py`, `tests/eval/test_override.py`, `test_approval_tools.py`, the BM-DECAY benchmark |

Migrations: eval_db 0004 (queue jobs per epoch, rollover records), 0005 (overrides),
0006 (Thresholdout state and queries), 0007 (short positions), 0008 (research notes) and
0009 (audit chain); registry_db 0003 (research notes) and 0004 (audit chain); control_db
0005 (override approvals) and 0006 (audit chain). New Compose service: `eval-sandbox`
(the eval image) with the `sandbox_exchange` volume. New settings, all optional
(decision 1): the protocol's `python`, `strategy_rules`, `research_note` and
`monitoring.cusum`, `eval.yaml` `sandbox`, the CN ingest `industry_coverage_min`, and
research `analyst.publish_notes`. New examples: `docs/examples/pool_import_phase8.yaml`
and `docs/examples/release_policy_thresholdout.yaml`. Nothing is preloaded.

## Checks executed

- `ruff check`, `ruff format --check`, `mypy`, all four import contracts, schema and
  public-card generation (no diff after regeneration) and the license check pass.
- `pytest -n 4` against PostgreSQL 16 with the Phase 0 roles and all migrations
  (`QFR_REQUIRE_DB_TESTS=1`): **1315 passed, 0 skipped** in about four minutes.
  Phase 8 adds 161 tests.
- The Phase 6 benchmarks on the final code, one at a time: BM-NULL (23 minutes) still
  accepts nothing over 50 generations, now with research notes in the loop;
  BM-STRATEGY (8 minutes) still delivers; BM-DECAY (under a minute) passes, with the
  CUSUM alarming 18 trading days after the switch-off and the v1 rule 69 (the
  benchmark allows 80 while Phase 6 decision 12 is open). BM-PLANTED was not rerun: it
  waits on the owner's DSR calibration (Phase 6), and BM-NULL already runs the same
  research loop with notes.
- The backup script against the test databases (pg_dump 16): a sealed and verified
  chain, a chain that no longer holds the previous backup's head
  (`extends_previous: false`), and a corrupted dump caught by `verify` (exit 1).

Not executed here: Docker image builds, `just up`, `just doctor`, the eval-sandbox
container, `just backup`, `just verify-backups` and `just restore-drill` in Docker, and
any provider call.

## On-machine steps (owner)

Use the throwaway stack, as in Phases 6 and 7. The real stack that ran the Phase 3 CN
test must be recreated before Phase 6 or later code runs on it (Phase 6 decision 1); a
recreated stack gets the Phase 8 settings.

1. **Update and build.** `git fetch origin`, then
   `git checkout -B claude/project-thread-jut2r1 origin/claude/project-thread-jut2r1`,
   `uv sync --locked`, `just check`, `just build` (the eval image now also runs
   eval-sandbox). The migrate service applies the migrations above at the next `just up`.
2. **Start and check (DEP-01).** `export COMPOSE_PROJECT_NAME=qfr-dry
   QFR_EPOCH=synthetic_001 QFR_INGEST_SOURCE=off`, `just data-build --source
   synthetic`, `just up`, then `just doctor`. Expect PASS with `service:eval-sandbox`
   healthy and `sandbox_isolation` passing; the `container_memory` observation now
   includes eval-sandbox. Then check that the sandbox has no network:
   `docker compose --env-file .env -f infra/docker-compose.yml exec -T eval-sandbox
   python -c "import socket; socket.create_connection(('1.1.1.1', 443), timeout=3)"`
   must fail with a network error (`Network is unreachable`).
3. **A Python factor and a long-short strategy.** `cp
   docs/examples/pool_import_phase8.yaml imports/`, then ask the host agent to import
   `pool_import_phase8.yaml` into the raw pool (`qfr.pool.import`). After a few minutes
   ask for the reports of `momentum_py` and `momentum_reversal_ls`
   (`qfr.report.list`): each should have a screening report and, once screening
   passes, a W1 report; `just logs tail --service eval-sandbox --n 20` shows
   `sandbox_job_finished` lines with `"status": "ok"`. Pass or fail on W1 does not
   matter here; a screening reason such as `RUNTIME_LIMIT`, `INTERNAL_ERROR`,
   `FORBIDDEN_CONSTRUCT` or `COMPONENT_INVALID` does.
4. **Backups, verification and the drill.** `just backup` (its SHA256SUMS now lists
   `AUDIT_CHAINS.json` and `AUDIT_HEADS`; in `backups/<date>/AUDIT_CHAINS.json` every
   chain has `"status":"ok"`), then `just verify-backups`: expect `"status":"PASS"`,
   also written to `backups/VERIFIED.json`. Then `just restore-drill`: expect PASS with
   `AUDIT:registry_db`, `AUDIT:eval_db` and `AUDIT:control_db` next to the BND-01,
   REG-01 and EVL-04 checks (run it after step 3 so EVL-04 has an official record).
5. **Rollover tooling.** `just epoch-propose synthetic_002`. Expect a
   `ROLLOVER_TOO_EARLY` refusal: the synthetic data ends with W3, and a rollover needs
   new data after W3 for W2 and W3 (with the real CN epoch, that is about eight months
   after W3 ends). The rollover itself is covered by the synthetic dry run above.
6. **BM-DECAY with CUSUM.** `just bench -k bm_decay`. In
   `exports/benchmarks/bm_decay.json`, the `cusum` block should alarm about 18 trading
   days after the switch-off, and the v1 alert about 69 days after it.
7. **Clean up.** `just down`, `docker compose -p qfr-dry down -v`,
   `rm imports/pool_import_phase8.yaml` and `unset COMPOSE_PROJECT_NAME QFR_EPOCH
   QFR_INGEST_SOURCE`. The drill removes its own project.

Not needed now, for later:

- **Turning Phase 8 on in a database that stored an earlier v1 protocol.** Copy
  `configs/protocols/cn_csi300_daily_v1.yaml` to `imports/`, change `version: '1'` to a
  new string such as `'1.8'`, and ask the host agent to activate it
  (`qfr.ops.activate_protocol`). Until then Python factors, qfr-strategy/2 rules,
  research notes and the CUSUM stay off there (decision 1).
- **Thresholdout.** Follow the comments in
  `docs/examples/release_policy_thresholdout.yaml` (a private seed, then
  `qfr.ops.activate_policy`). The shipped policy stays in Ladder mode.
- **CN industry data.** Put a point-in-time classification CSV under `data/raw/` and set
  `industry_file` and `industry_scheme` in `configs/data/cn_ingest_v1.yaml`; industry
  rules on CN strategies need it.
- **The owner override.** Only for an acceptance case with a failed gate that you want
  to accept anyway: tell the host agent, write the rationale (at least 200
  characters), and confirm 24 hours later with `CONFIRM OVERRIDE C-nnnn`.

Send back: the doctor, verify-backups and restore-drill output, the reports of step 3
(or anything unhealthy or unexpected), and `bm_decay.json`.
