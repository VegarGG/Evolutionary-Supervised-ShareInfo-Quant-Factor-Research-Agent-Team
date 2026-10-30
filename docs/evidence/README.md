# Phase 0 evidence

These are local, non-secret verification receipts. `index.json` records their SHA-256 hashes.

`check.log` and `tests-postgres.log` passed. `doctor-latest.json` retains its two failures.
`mcp-container-smoke.json` verifies actual container HTTP, database audit and file logs,
not host ingress or live downstream domain APIs. Image metadata is native ARM64 only.
The Linux dependency cache was independently checked against each uv.lock SHA-256.

See ../phase0-acceptance.md for the exact scope and outstanding owner/CI decisions.
