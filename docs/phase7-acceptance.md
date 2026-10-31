# Phase 7 implementation and acceptance record

Status: **implemented; every check that can run without Docker passes. SC8 (a real host
agent), DEP-01 and the restore drill run on the Mac Studio and are the owner's next
step**. Owner acceptance and merge are not asserted. Phase 7 is stacked on the Phase 6
branch (PR #17), which is stacked on PR #16, #15 and #14, and follows plan v2.2
(immediate release). It depends on none of the open owner decisions. Design choices are
in [decisions.md](decisions.md#phase-7-decisions).

No test reaches a provider: every model answer is scripted, and the test session sets
`ALLOW_MODEL_REQUESTS = False`.

## Acceptance checks

| Check (plan) | Result | Evidence |
|---|---|---|
| SC8: the rehearsal completes all five steps with a real host agent; every MCP call appears in mcp_calls and the logs; exports validate against their schemas | Scripted twin passes; the real host agent is the owner's step | `tests/research/test_operator_rehearsal.py`: status, a brief, its deliverable, the evidence view, `qfr.deliverable.export` and `just export-verify` (every hash and schema; a changed byte, a rewritten manifest line and an unlisted file are each caught), the approval with short codes, the pool entry, the evaluator's library sync, pause and resume, alerts, costs, correlation and a log export. Every call has an audit row and a front-door log line with its request id |
| SC9: the trace export of the delivered version reconstructs every hop | Pass | `tests/research/test_lineage.py` (TRC-03, a five-generation DAG with a crossover); the rehearsal checks the bundle's `trace.json` hash against the deliverable's |
| SC10: `qfr.logs.correlate` on the job id returns the whole story across services | Pass | The rehearsal: the job id finds lines from qfr-mcp, research-api, research-worker, registry-api, eval-scheduler, eval-worker and release-worker, including the export; `tests/research/test_research_e2e.py` (LOG-03, MCP-01) |
| DEP-01 passes on the Mac Studio | Owner's step | `just doctor` now also checks ops-nightly and backup, and that each service can write its own log folder |
| The restore drill passes | Owner's step; its database steps verified here | A backup made by `infra/backup/backup.sh` from the test databases was restored into a freshly bootstrapped PostgreSQL 16 by the drill's code: all four restores, the 11 BND-01 probes and the 18 REG-01 probes passed, both with empty registry tables (trigger check) and with a seeded row (the owner is stopped by "append-only table"). The Docker steps and EVL-04 are tested with a recorded runner (`tests/mcp/test_restore_drill.py`) |
| LOG-04: daily rotation, compression after 7 days and deletion after 180 behave as configured | Pass | `tests/test_log_maintenance.py`: compression and deletion by age, rotated parts, recovery of an interrupted run, the disk guard, search over compressed days, tail, correlate and export |
| MCP-02: the catalog snapshot | Pass | `tests/mcp/test_server.py`: 44 tools (5 new), 5 resources plus 4 templates, 4 prompts; the guide resource is the file verbatim |

## Delivered scope

| Task | Delivered | Main tests |
|---|---|---|
| P7.1 | `qfr.deliverable.export`: per-item manifest, trace.json, owner records and the evaluator's NAV, daily RankIC and long-short series plus each simulation's NAV as Parquet and CSV, deliverable.json, iteration_history.md, bundle.json (export_bundle/1) and MANIFEST.sha256 under `exports/<job>/<deliverable>/`, written atomically and recorded in control_db `deliveries`; `just export-verify` | `test_operator_rehearsal.py`, `tests/test_contracts.py` |
| P7.2 | `qfr.evidence.get` with every window, gate values labelled by stage and window (acceptance gates included), every simulation account and the acceptance cases; `qfr.config.get` owner_only; the owner_only label and hygiene warning on every owner-grade response | `tests/eval/test_approval_tools.py`, `test_operator_rehearsal.py` |
| P7.3 | `qfr.status` with queues, quotas, burn meters, data freshness, disk, the last nightly run, open alerts per zone and today's costs by provider; `qfr.ops.pause_research` and `resume_research`; `qfr.ops.acknowledge_alert` for evaluation, research and operations alerts; provider alerts for repeated fallbacks and failed probes; `qfr.ops.costs` (Phase 4) groups by job and provider | `test_approval_tools.py`, `tests/research/test_roles.py`, `tests/research/test_operations.py`, `test_operator_rehearsal.py` |
| P7.4 | Date-ranged search, tail, correlate and export over `.jsonl` and `.jsonl.gz` days; `qfr.logs.export` and `qfr logs export`; ops-nightly with compression and retention (LOG-04), the disk guard and the backup check; `qfr logs maintain` | `tests/test_log_maintenance.py`, `tests/mcp/test_nightly.py` |
| P7.5 | `docs/HOST_AGENT_GUIDE.md` as `qfr://docs/host-agent-guide`; the `qfr.approval` and `qfr.investigate` prompts; the backup service (`just backup`); `just restore-drill`; `just doctor` additions; `just rotate-mcp-token` | `tests/mcp/test_server.py`, `tests/test_backup_script.py`, `tests/mcp/test_restore_drill.py`, `tests/boundary/test_compose.py`, `test_nightly.py` |
| P7.6 | The scripted rehearsal and the owner's runbook below | `test_operator_rehearsal.py` |

Migrations: control_db 0004 (`deliveries`, `ops_alerts`, `alert_acks`, `ops_runs`, all
insert-only) and research_db 0004 (`provider_alerts`, insert-only apart from
acknowledgement). New Compose services: `ops-nightly` (the mcp image) and `backup` (built
from the postgres image). New settings: logging.yaml `correlate_default_days` and
`export_max_lines`, deployment.yaml `backup`, research service.yaml `alerts`. Nothing is
preloaded: no factors, strategies, seeds, sample briefs or prices.

## Checks executed

- `ruff check`, `ruff format --check`, `mypy`, all four import contracts, schema and
  public-card generation (no diff after regeneration) and the license check pass.
- `pytest -n 4` against PostgreSQL 16 with the Phase 0 roles and all migrations
  (`QFR_REQUIRE_DB_TESTS=1`): **1154 passed, 0 skipped** in about four minutes. Phase 7
  adds 25 tests. The benchmarks are not part of this run, and Phase 7 changes nothing
  they measure.
- The backup script against the test databases (pg_dump 16) and the restore drill's
  restore, BND-01 and REG-01 steps against a scratch PostgreSQL 16 cluster bootstrapped
  with `infra/postgres/init`.

Not executed here: Docker image builds, `just up`, `just doctor`, `just backup` and
`just restore-drill` in Docker, and any provider call.

## On-machine steps (owner)

Use the throwaway stack, as in Phase 6: the real stack that ran the Phase 3 CN test has
evaluator settings from before Phase 6 (Phase 6 decision 1).

1. **Update and build.** `git fetch origin`, then
   `git checkout -B claude/project-thread-uwdpk6 origin/claude/project-thread-uwdpk6`,
   `uv sync --locked`, `just check`, `just build` (it now also builds the backup image).
   Make sure `backups/` exists next to `imports/` and `exports/` (`mkdir -p backups`).
   The migrate service applies control_db and research_db migrations 0004 at the next
   `just up`.
2. **Start and check (DEP-01).** `export COMPOSE_PROJECT_NAME=qfr-dry
   QFR_EPOCH=synthetic_001 QFR_INGEST_SOURCE=off`, `just data-build --source
   synthetic`, `just up`, then `just doctor`. Expect PASS with ops-nightly and backup
   healthy and a `log_writable` check per service; the report is in `exports/doctor/`.
3. **The rehearsal with a real host agent (SC8).** Connect the host agent
   (`just mcp-config`) and ask it to read `qfr://docs/host-agent-guide` first. Then, in
   your own words:
   - "What is the state of QFR?" (`qfr.status`).
   - A small factor brief (`budget.max_generations: 2`, a small `budget.max_cost`);
     this calls the providers. Let it wait and report the deliverable
     (`qfr.deliverable.get`).
   - "Export the deliverable." Then run `just export-verify <path it gives>`; expect
     `"ok": true`.
   - Approve with the short codes ("APPROVE J-0001 F-1"); ask it to add the factor to
     the pool, close the job and list the pool (E- code, tier w1_pass).
   - "Did anything go wrong?" (`qfr.ops.alerts`; the monitored entry raises a staleness
     alert about a minute after approval because the synthetic snapshot ends in 2019).
     Acknowledge it in your words.
   - "Tell me the story of job J-0001 from the logs" (`qfr.logs.correlate`) and "export
     those log lines" (`qfr.logs.export`).
   - "Pause all research", then "resume it".
   Save the transcript to `exports/rehearsal/transcript.md` and the audit rows with
   `docker compose exec -T postgres psql -U postgres -d control_db -c "SELECT at, tool,
   outcome, request_id FROM mcp_calls ORDER BY at" > exports/rehearsal/mcp_calls.txt`.
4. **Backup and restore drill.** `just backup` (prints the new folder's SHA256SUMS; in
   `backups/<date>/`, `shasum -a 256 -c SHA256SUMS` agrees), then `just
   restore-drill`. Expect PASS with every BND-01, REG-01 and EVL-04 check; the report
   is in `exports/restore-drill/`. EVL-04 needs an official record, so run it after
   step 3.
5. **Clean up.** `just down`, `docker compose -p qfr-dry down -v`, and
   `unset COMPOSE_PROJECT_NAME QFR_EPOCH QFR_INGEST_SOURCE`. The drill removes its own
   project.

Send back: the doctor and restore-drill reports, the export-verify output, the
transcript and the audit rows (or anything unhealthy or unexpected).
