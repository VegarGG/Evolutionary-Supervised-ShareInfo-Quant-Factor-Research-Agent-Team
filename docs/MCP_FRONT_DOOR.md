# MCP front door

Stage 4 uses the pinned official Python MCP SDK 2.3.0 over Streamable HTTP at
`/mcp`. The adapter imports only `qfr_core` and calls explicitly configured
Research, Registry, Feedback and quarantine HTTP endpoints. It holds no database,
evaluator-admin, signing or provider credential. Serving the adapter admits no
work and runs no source payload.

## Authentication and transport

Each request requires an MCP-audience bearer credential. Its configured principal,
program and exact roles must have a matching backend binding at startup; handlers
check scope again. Backend tokens are separate references, scoped to the same
principal/program and required public-service role. Administrators must configure
these consistently; tool annotations grant no authority. Research writes require
`research_lead`; checkpoint decisions require `human_reviewer`. Registry and
Feedback backend access is read-only. Do not supply evaluator or publisher tokens
as those read credentials.

The versioned `configs/research/mcp_v1.json` limits requests, inline results,
resource pages, binary chunks and body-reading time. Host/Origin checks protect
MCP transport against DNS rebinding. Publish only on the host loopback. There is
no OAuth discovery, anonymous research, vendor-specific session store or arbitrary
URL/path tool. Credentials belong in private operator configuration, never source
files, examples, request logs or tool arguments.

The SDK transport is stateless; the Research API owns jobs. Initialization,
disconnection, HTTP request cancellation and MCP-process restart cannot terminate
or complete durable work. A caller-supplied admission key recovers the same job
and its current revision after a lost response; changed intent under that key is
a conflict. Explicit job controls use a separate operation key and expected
revision. Polling returns immediately with state and next action; no tool waits
for research or for an evaluation batch.

## Tools and resources

Tools use the `qfr_` namespace and declared input/output schemas:

- Program creation/read, input validation, dataset/baseline registration and
  non-authoritative protocol proposals.
- Research submit/status/list/control, manual blackboard reads/writes and human
  checkpoint creation/read/answer.
- Registry manifest reads/listing and released report reads/listing.
- Delivery proposal, independently signed receipt acceptance and export/shortlist.
- Quarantine declaration/status/finalization, metadata listing and mapped import.

There is no protocol activation, evaluation scheduling, evaluation cancellation,
private-holdout read, official-record write or promotion tool. A research pause
or cancel cannot control the independently scheduled evaluator.

Responses contain structured data, a short text summary and, where needed, a
resource reference. Large JSON is read in bounded pages through `artifact://`,
`artifacts://`, `report://`, `reports://`, `program://`, `job://`, `jobs://`,
`blackboard://` and `sources://`. Every page records the whole-document SHA256.
Clients must check that all pages share that hash; mutable lists/status may change
between reads, so restart pagination if their identity changes. No raw package,
model code or source dataset is embedded in tool/resource results.

The adapter independently checks configured Ed25519 signatures, report program
and release time, Registry canonical hashes, job/receipt bindings and complete
export membership/checksums. Only actual verified official evidence carries
`official_signature_verified: true`; a successful HTTP response is insufficient.
Export download verifies the archive again before returning bytes.

## Separate file transport

`qfr_upload_prepare` returns an upload ID and chunk size. Send each binary chunk
to `POST /v1/programs/{program}/uploads/{upload}/chunks` with the MCP bearer token,
`Content-Type: application/octet-stream`, `X-Chunk-Offset` and `X-Chunk-SHA256`.
Retrying a committed identical chunk is idempotent. Reconnect, read upload status,
and continue from the recorded offset; finalize using the complete original hash.
Source bytes go only to the private quarantine service. This API has no raw-source
GET route and never executes or builds the uploaded source.

Mapped import accepts a declared mount ID plus confined relative regular-file
path. Absolute paths, parent traversal and symbolic links are refused. The mount
mapping belongs to the private intake service, not the MCP container. See
[QUARANTINE_TRANSPORT.md](QUARANTINE_TRANSPORT.md) for quotas and validation.
Transport validation is not ingest authorization, dataset registration or sandbox
acceptance. `qfr ingest once` remains a separate exact-plan operator action.

The export tool returns a relative authenticated download path and SHA256/length.
Use ordinary HTTP to save the verified ZIP; do not ask a model to carry archive
bytes in context. [RESEARCH_API.md](RESEARCH_API.md) describes completion and
[DELIVERY_CHECKER.md](DELIVERY_CHECKER.md) describes independent acceptance.

## Component evidence and remaining acceptance

The focused tests use actual loopback HTTP, the official SDK, a separate raw
JSON-RPC client, real PostgreSQL and explicitly synthetic financial evidence with
ephemeral Ed25519 keys. They cover three earlier protocol generations
(2025-03-26, 2025-06-18 and 2025-11-25), SDK negotiation, reconnect/lost-response
recovery, conflicts, cancellation, app recreation, scopes, pagination, malicious
imports, checksummed upload, signatures and export integrity.

These fixtures are not the actual Codex client, original pilot acceptance,
container restart or full Stage 4 gate. [Explicit service wiring](STAGE_4_SERVICES.md),
[client examples](MCP_CLIENTS.md) and the [intake guide](PORTABLE_INTAKE_GUIDE.md)
are available; real Mac end-to-end evidence remains required. No provider calls,
confirmation query or persistent authentication grant were made by these tests.
