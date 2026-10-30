# QFR v2

New, independent implementation of the owner's
[authoritative plan](docs/QFR-Implementation-Plan-v2.1-EN.html).
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
`just setup`, `just backup` and `just bench` explicitly report their later phases.
`just mcp-config` prints bearer-bearing client snippets; keep its output private.

Phase 1: build snapshots with `uv run --locked qfr data build --source synthetic`
(written under `data/snapshots/`) or, in Compose, `just data-build --source synthetic`
or `--source cn --release-tag <tag>`. Check one with `qfr data verify <path> --zone
research`. Read [the Phase 1 record](docs/phase1-acceptance.md) and the
[Phase 1 decisions](docs/decisions.md#phase-1-decisions); Phase 2 starts only after
the owner accepts Phase 1.
