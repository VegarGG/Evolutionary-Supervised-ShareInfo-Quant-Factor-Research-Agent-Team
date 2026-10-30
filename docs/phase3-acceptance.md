# Phase 3 implementation and acceptance record

Status: **implemented; every Phase 3 acceptance check passes in local tests against a
real PostgreSQL 16; the on-machine test on the Mac Studio is the owner's next step**.
Owner acceptance and merge are not asserted. Phase 3 is built on the Phase 2 branch
(PR #13), itself on Phase 1 (PR #12); neither is merged yet. No Phase 4 work has begun.
Design choices are in [decisions.md](decisions.md#phase-3-decisions).

One owner decision is open: epoch_001's embargo gaps are 17 and 16 SSE trading days,
not 20 (decision 4). The evaluator refuses to pin epoch_001 on CN data until the
windows are moved or the shortfall is accepted. The synthetic dry run below does not
depend on it.

## Acceptance checks

| Check (plan) | Result | Evidence |
|---|---|---|
| End to end on the synthetic world: 30 seed factors imported through MCP are pulled, evaluated and released at batch time with rounded values, and their owner-grade evidence is readable through `qfr.evidence.get` at full precision | Pass | `tests/eval/test_e2e.py::test_thirty_seeds_flow_from_import_to_released_reports_and_owner_evidence`: 30 seeds through `qfr.pool.import`; the scheduler pulls them, the worker screens and runs W1, nothing is visible before the 6-hour batch, then every report validates and carries its references, every released W1 value is a multiple of its policy step, and `qfr.evidence.get` returns `owner_only` evidence with unrounded metrics, gate values and series |
| EVL-01: discovery only through since_seq polling; no inbound trigger endpoint | Pass | `tests/eval/test_scheduler.py::test_evl_01_discovery_is_since_seq_polling_with_no_inbound_trigger` (cursor paging; the only non-GET routes on feedback-api and eval-admin-api are the owner's configuration routes); `tests/boundary/test_compose.py` (no evaluation service publishes a port) |
| EVL-02: every official record and released report references version id, content hash, protocol, snapshot and code version | Pass | `tests/eval/test_worker.py::test_w1_writes_complete_records_and_a_ledger_row_per_trial` (every reference column set, records validate as `OfficialRecord`); NOT NULL columns in migration `0002_evaluation`; released reports carry the refs block (`test_release.py::test_rel_04_...`) |
| EVL-03 (Phase 3 screening): the prefix-invariance probe catches an injected test-only lookahead operator | Pass | `test_worker.py::test_evl_03_the_prefix_probe_catches_an_injected_lookahead_operator` (`LOOKAHEAD_DETECTED`, no trial) |
| EVL-04: re-running an official record reproduces its results hash | Pass | `tests/eval/test_reproduce.py::test_evl_04_rerunning_official_records_reproduces_their_results_hash` (screening and W1 records); `::test_reproduce_detects_a_changed_input_and_unknown_records` |
| EVL-05: exact and behavioral duplicates are never evaluated or counted | Pass | `test_scheduler.py::test_evl_05_exact_and_behavioral_duplicates_are_never_evaluated` (`DUPLICATE_OF` and `NEAR_DUPLICATE_OF`, no evaluate job, no ledger row) |
| EVL-06: a trial-ledger row for every version evaluated on W1 | Pass | `test_worker.py::test_w1_writes_complete_records_and_a_ledger_row_per_trial` (one row per W1 record, same transaction, burn meter 2); screening failures and internal errors write none |
| REL-01: W1 values rounded to the policy granularity | Pass | `tests/eval/test_release.py::test_rel_01_values_round_half_away_from_zero_to_the_policy_step` (8 cases, decimal half away from zero); the end-to-end test checks every released W1 value |
| REL-02: reports visible only at or after their batch time | Pass | `test_release.py::test_rel_02_reports_become_visible_only_at_their_batch_time` (nothing at 05:59, all three at 06:00), `::test_rel_02_a_report_dated_in_the_future_stays_hidden_from_feedback`, `::test_w1_batches_are_the_next_six_hour_boundary_in_utc` |
| REL-03: quotas defer excess intake, and deferrals expire after 7 days | Pass | `test_scheduler.py::test_rel_03_quota_defers_excess_and_admits_when_room_opens`, `::test_rel_03_deferrals_expire_after_seven_days` (`QUOTA_EXPIRED`) |
| REL-04: every released report validates against the public schema of whitelisted fields and enum codes | Pass | `test_release.py::test_rel_04_every_released_report_validates_and_carries_only_whitelisted_fields` (passing, degenerate and duplicate factors; no timings, probe dates, tracebacks or window dates; an extra field fails the schema) |
| BND-03: the Feedback API OpenAPI document has only GET operations and serves only released reports | Pass | `tests/eval/test_apis.py::test_bnd_03_feedback_openapi_has_only_get_operations`, `::test_bnd_03_feedback_serves_only_released_reports`, `tests/eval/test_eval_database.py::test_feedback_reader_sees_the_views_and_nothing_else`. `just doctor` repeats the GET-only check on the running container |
| The seed entries become the correlation library once their W1 records exist | Pass | `test_e2e.py::test_a_later_factor_is_measured_against_the_seed_library` (a later factor's owner evidence shows a non-vacuous library correlation over the seed members); the end-to-end test checks one library member per evaluated seed |
| A stack with no seeds records the library gate as vacuous | Pass | `test_e2e.py::test_a_stack_with_no_seeds_records_the_library_gate_as_vacuous` |

## Delivered scope

| Task | Delivered | Main tests |
|---|---|---|
| P3.1 | eval_db migration 0002: configuration versions, epochs, data snapshots, intake, queue, runs, metrics, series files, official records, trial ledger, burn meters, quota usage, release queue, released reports, library, pool and intake cursors, events; insert-only REVOKEs and triggers; five `feedback` views for `feedback_ro` | `tests/eval/test_eval_database.py` |
| P3.2 | eval-scheduler: since_seq pulls, library sync from pool events, schema and kind checks, exact and behavioral dedup, rolling quotas with deferral and expiry, strategies held, fair round-robin queue with `SKIP LOCKED` | `tests/eval/test_scheduler.py` |
| P3.3 | Screening in a limited child process: static limits, one pass over the full snapshot, coverage, the prefix probe, CPU and memory limits, degeneracy | `tests/eval/test_worker.py` |
| P3.4 | W1 runs through the factor plugin: runs, metrics, series files, official records, ledger rows and release-queue rows in one transaction, with results hashes | `test_worker.py`, `test_reproduce.py` |
| P3.5 | release-worker: whitelisted intake, screening, W1 and library reports, decimal rounding, 6-hour batches, reason codes and diagnostic flags | `tests/eval/test_release.py` |
| P3.6 | feedback-api: GET only, released reports, artifact status timeline, library, policy and protocol cards | `tests/eval/test_apis.py` |
| P3.7 | eval-admin-api (versions and activation, intake, runs, records, owner evidence, series, burn, quota usage, library, private config), `qfr eval reproduce`, MCP tools `qfr.evidence.get`, `qfr.report.list`, `qfr.ops.activate_protocol`, `qfr.ops.activate_policy`, `qfr.ops.activate_quotas`; `qfr.status`, `qfr.setup.status`, `qfr.pool.*` and `qfr.config.get` now read the evaluator | `test_apis.py`, `tests/eval/test_mcp_tools.py`, `tests/mcp` |
| P3.8 | `qfr data serve`: daily full-snapshot builds after 18:30 Asia/Shanghai from the latest investment_data release, a synthetic replay source for tests, an off switch, raw cleanup | `tests/ingest/test_serve.py`, `tests/ingest/test_cli.py` |

Compose runs the six evaluation-zone services from a new `eval` image target
(`qfr-v2-eval:phase3`) with heartbeat or `/healthz` health checks. The evaluation store
is a new volume written only by eval-worker. Release policies and quotas are mounted
only into the scheduler. `just up` records the git commit and the eval image id in
every official record. `just doctor` expects the Phase 3 services, checks BND-03 on the
live feedback-api and records `docker stats` memory per container.

Nothing is preloaded: no factors, strategies, pool entries or sample files.

## Checks executed

- `ruff check`, `ruff format --check`, `mypy`, all four import contracts, schema and
  public-card generation (no diff after regeneration) and the license check pass.
- `pytest -n 4` against PostgreSQL 16 with the Phase 0 roles and all migrations
  (`QFR_REQUIRE_DB_TESTS=1`): **985 passed, 0 skipped** in about three minutes; Phase
  3 adds 69 tests. registry_db and eval_db are empty after the run (control_db keeps
  the one audit row that the Phase 0 boundary test writes on purpose).

Not executed here: Docker image builds, `just up`, `just doctor` and anything on the
Mac Studio. Docker Desktop memory was not changed.

## On-machine test (owner)

Run the synthetic dry run first, on a throwaway Compose project, so the real stack's
evaluator never pins the synthetic epoch (one epoch can be active until Phase 8). Keep
Docker Desktop memory as it is; the point is to see real RAM use.

1. **Update and build.** `git fetch origin && git checkout claude/project-thread-e4uzhe`,
   then `uv sync --locked`, `just check`, `just build`.
2. **Throwaway stack.** `just down` (the real stack keeps its volumes), then in the
   same shell:
   `export COMPOSE_PROJECT_NAME=qfr-dry QFR_EPOCH=synthetic_001 QFR_INGEST_SOURCE=off`.
3. **Synthetic data, then start.** `just data-build --source synthetic`, then
   `just up`. Expect every service healthy within a few minutes; `just doctor` should
   pass with the Phase 3 services, the BND-03 check and a `container_memory` block.
4. **Seeds.** Put a pool_import/1 file under `imports/`: your own raw pool, or the 30
   test seeds with
   `uv run --locked python -c "import json; from tests.eval.test_e2e import entries; json.dump({'schema_version': 'pool_import/1', 'entries': entries()}, open('imports/dry-run-seeds.json', 'w'))"`.
   Ask the host agent to call `qfr.pool.import` with that file.
5. **Watch it run.** `just logs tail` (or `qfr.logs.tail`): the scheduler pulls the
   versions, the worker logs `job_completed` per job, and `qfr.status` shows the
   queue, burn meters and data freshness. While the worker is busy, run `docker stats --no-stream`
   a few times and note the peak for eval-worker and postgres.
6. **Release.** Reports appear at the next 00:00, 06:00, 12:00 or 18:00 UTC
   (08:00, 14:00, 20:00 or 02:00 in Shanghai). Then `qfr.report.list` shows rounded
   values, and `qfr.evidence.get` on one version shows full precision.
7. **Reproduce.** Take a `record_id` from the evidence and run
   `just eval-reproduce <record_id>`; it must print `"match": true`.
8. **Clean up.** `just down`, then `docker compose -p qfr-dry down -v` to remove only
   the dry run's volumes, and `unset COMPOSE_PROJECT_NAME QFR_EPOCH QFR_INGEST_SOURCE`.
9. **CN run, after the epoch decision.** Start the real stack with `just up`, then
   `just data-build --source cn --release-tag <tag>` while the worker is idle (the CN
   build is the largest memory user), and `just doctor`. The scheduler pins epoch_001
   only once its windows satisfy the embargo.

Send back `just doctor`'s output, the `docker stats` peaks and anything unhealthy.
