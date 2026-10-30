# QFR v2 — Phase 0

New, independent implementation of the owner's
[authoritative plan](docs/QFR-Implementation-Plan-v2.1-EN.html).
Previous QFR code and PRs are outdated and are not dependencies of this repository.

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
implemented but **not accepted**: setup and owner decisions remain outstanding.
`just setup`, `just backup` and `just bench` explicitly report their later phases.
`just mcp-config` prints bearer-bearing client snippets; keep its output private.

Do not proceed to Phase 1 until every Phase 0 acceptance check has passed.
