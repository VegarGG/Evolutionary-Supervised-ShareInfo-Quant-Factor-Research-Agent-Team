# QFR v2 — Phase 0

New, independent implementation of the owner's
[authoritative plan](docs/QFR-Implementation-Plan-v2.1-EN.html).
The canonical project is
[Evolutionary-Supervised-ShareInfo-Quant-Factor-Research-Agent-Team](https://github.com/VegarGG/Evolutionary-Supervised-ShareInfo-Quant-Factor-Research-Agent-Team).
Previous QFR code and PRs are outdated and are not dependencies of this repository.
This Phase 0 proposal replaces the stale implementation and README while preserving
their Git history for reference.

Scope: foundation, contracts, logging, database boundaries and five MCP read tools.
No factors, strategies, research jobs, evaluation runs, provider calls or promotion
workflows are implemented or preloaded.

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

Do not proceed to Phase 1 until every Phase 0 acceptance check has passed.

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
