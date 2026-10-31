# QFR v2

New, independent implementation of the owner's
[authoritative plan](docs/QFR-Implementation-Plan-v2.2-EN.html).
The canonical project is
[Evolutionary-Supervised-ShareInfo-Quant-Factor-Research-Agent-Team](https://github.com/VegarGG/Evolutionary-Supervised-ShareInfo-Quant-Factor-Research-Agent-Team).
Previous QFR code and PRs are outdated and are not dependencies of this repository.
This Phase 0 proposal replaces the stale implementation and README while preserving
their Git history for reference.

Phase 0 delivered the foundation, contracts, logging, database boundaries and five
MCP read tools. Phase 1 adds the data layer, the factor DSL and the measurement core:
dense panels and content-addressed snapshots in a full and a date-truncated research
zone, synthetic planted, null and decay worlds, CN ingest from investment_data, the
operator library, metrics, PSR, DSR and PBO, the reference backtester, the strategy
composite and the W0 research workbench. No factors, strategies, research jobs,
evaluation runs, provider calls or promotion workflows are implemented or preloaded.

Use Python 3.12, uv, just and Docker Compose v2. Start with `uv sync --locked`,
`just check`, and `just test`. Run `just init-secrets` once, `just build`, then
`just up`. Use `just test-db` for the full suite against the isolated PostgreSQL
instance, `just doctor` for deployed checks and `just logs tail` for container logs.
The local `.tools` directory can be added to PATH on this Mac; it contains verified
uv and just binaries and is intentionally ignored by Git.

Read [the acceptance report](docs/phase0-acceptance.md) before use. Phase 0 is
implemented and ready for owner audit: local checks and canonical-repository CI
pass, including all eight ARM64/AMD64 image builds. Owner acceptance and merge
remain pending; [PR #10](https://github.com/VegarGG/Evolutionary-Supervised-ShareInfo-Quant-Factor-Research-Agent-Team/pull/10)
contains the replacement.
The owner's network and memory decisions are applied. `just doctor` checks current
OOM flags; 24 GiB is a planning expectation, not a required allocation. Test the
host endpoint with `python scripts/smoke_mcp.py --host`. Domain placeholders still
exit cleanly; live downstream tracing is deferred by the owner.
`just backup` runs a backup now (Phase 7); the backup service runs one every night.
`just mcp-config` prints bearer-bearing client snippets; keep its output private.

Phase 1: build snapshots with `uv run --locked qfr data build --source synthetic`
(written under `data/snapshots/`) or, in Compose, `just data-build --source synthetic`
or `--source cn --release-tag <tag>`. Check one with `qfr data verify <path> --zone
research`. Read [the Phase 1 record](docs/phase1-acceptance.md) and the
[Phase 1 decisions](docs/decisions.md#phase-1-decisions).

Phase 2 adds the artifact registry and the pools. registry-api stores immutable factor
and strategy versions with lineage, and append-only pool entries and events; the
database refuses updates and deletes. The MCP front door gains `qfr.setup.status`,
`qfr.pool.import`, `qfr.pool.list`, `qfr.pool.get`, `qfr.dsl.validate` and
`qfr.artifact.get`. Run `just setup` to import a raw factor pool (pool_import/1 as
JSON, YAML or CSV, placed under `imports/`) or to start empty, which records the
no-defaults notice. Read [the Phase 2 record](docs/phase2-acceptance.md) and the
[Phase 2 decisions](docs/decisions.md#phase-2-decisions). Phase 2 was built on the
unmerged Phase 1 branch at the owner's request.

Phase 3 adds the independent evaluator. eval-scheduler pulls published versions and
pool events, deduplicates them, applies quotas and queues work; eval-worker screens each
factor in a limited child process and runs W1; release-worker releases rounded,
whitelisted reports as soon as they are recorded; feedback-api (GET only) serves them to research,
and eval-admin-api serves the owner. data-ingest builds a new full snapshot each day
after 18:30 Shanghai time. The MCP front door gains `qfr.evidence.get`,
`qfr.report.list` and `qfr.ops.activate_protocol`, `_policy` and `_quotas`. Re-run an
official record with `just eval-reproduce <record_id>`. Read
[the Phase 3 record](docs/phase3-acceptance.md), which ends with the on-machine test
steps, and the [Phase 3 decisions](docs/decisions.md#phase-3-decisions).

Phase 5 adds the evolutionary engine. Before each generation, research refreshes its
population of published factors from the released reports (official members with W1
fitness, provisional members waiting for evaluation), rebuilds the 64-cell MAP-Elites
archive and updates each island's Thompson-sampling arm. It then proposes the
generation: publication slots per island, the operator mix with the diversity
guardrail, parents by tournament or archive elite, crossover partners and ready-made
syntactic mutants. The engineer drafts from a context of parents, elites, archive
members and what the lineage already tried, and the pre-screen and provisional fitness
choose at most 12 publications. `qfr.trace.export` writes a version's trace and
iteration history to `exports/traces/`. `just bench` runs BM-PLANTED and BM-NULL, which
CI also runs nightly. Read [the Phase 5 record](docs/phase5-acceptance.md) and the
[Phase 5 decisions](docs/decisions.md#phase-5-decisions).

Phase 7 makes QFR operable through the host agent. `qfr.deliverable.export` writes a
deliverable bundle (deliverable, iteration history, each item's manifest, trace and
owner-grade records, the evaluator's series as Parquet and CSV, and a SHA-256 manifest)
to `exports/<job>/<deliverable>/`; `just export-verify <path>` re-checks it.
`qfr.evidence.get` shows every window, labelled gate values and every simulation
account; every owner-grade response is labelled owner_only with the hygiene warning.
`qfr.status` adds queues, quotas, burn meters, data freshness, disk, open alerts per
zone and today's costs; `qfr.ops.alerts` merges evaluation, research and operations
alerts and `qfr.ops.acknowledge_alert` acknowledges one; `qfr.ops.pause_research` and
`resume_research` stop and restart all research. Log search reads compressed days, and
`qfr.logs.export` writes a slice to `exports/logs/`. The ops-nightly service compresses
and prunes logs, guards the disk and checks backups; the backup service dumps the four
databases every night into `backups/<date>/` and mirrors the snapshots. Run
`just restore-drill` quarterly and `just rotate-mcp-token` to replace the owner token.
Host agents read [the host-agent guide](docs/HOST_AGENT_GUIDE.md) (also the MCP
resource `qfr://docs/host-agent-guide`) and the `qfr.approval` and `qfr.investigate`
prompts. Read [the Phase 7 record](docs/phase7-acceptance.md), which ends with the
on-machine rehearsal, and the [Phase 7 decisions](docs/decisions.md#phase-7-decisions).

## License and use

Copyright 2026 Ziwei Huang. This is source-available software under the unchanged
[PolyForm Noncommercial License 1.0.0](LICENSE), with a separate
[additional permission](ADDITIONAL-PERMISSION.md) for individuals researching and
trading their own funds in personal accounts, including for personal financial
gain. It is not offered as OSI-approved open-source software. The additional
permission does not cover running a business, work for employers or clients,
managing others' money, or paid products, signals, advice, or services; it does
not withdraw broader rights already granted by the PolyForm license.

For uses outside the public license and additional permission:
Commercial use requires a separate written license from Ziwei Huang.
Separately authorized companies may use the software within their written
license's scope. These grants cover only rights Ziwei Huang owns or is authorized
to license; [third-party materials retain their own licenses](THIRD-PARTY-NOTICES.md).

This system was originally developed for research purposes only; it provides no guarantee of investment performance, and, to the extent permitted by law, Ziwei Huang accepts no liability for gains, losses, or other consequences arising from its use.
