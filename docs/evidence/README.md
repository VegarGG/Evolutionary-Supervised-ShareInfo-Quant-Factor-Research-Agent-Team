# Phase 0 evidence

These are local, non-secret verification receipts. `index.json` records their SHA-256 hashes.

`check.log` passes; `tests-postgres.log` records 56 passing tests. `doctor-latest.json`
passes 112 checks under the owner's clarified requirements. `mcp-host-smoke.json`
verifies host-loopback HTTP plus matching database audit rows and file logs.
`mcp-container-smoke.json` preserves the earlier container-only check. Live downstream
domain tracing is explicitly deferred by the owner. Image metadata is ARM64 only.
The Linux dependency cache was checked against each uv.lock SHA-256.

The original failed doctor receipt remains in Git history. See ../phase0-acceptance.md
for owner decisions, limitations, and unexecuted hosted CI/AMD64 acceptance.
