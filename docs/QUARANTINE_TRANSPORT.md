# Data-only upload and mapped import

The Stage 4 intake edge accepts explicitly authorized source transport without
running supplied code or starting ingestion/evaluation. Its implementation is in
`qfr_eval.ingest.intake_app` and `quarantine`; it is a separate data-plane service,
not the Research API. Deployment wiring and Mac acceptance remain pending.

The service requires its own `intake`-audience, program-scoped bearer bindings.
It needs only a private quarantine volume and explicitly mapped read-only source
roots. It has no PostgreSQL/evaluation credential, signing key, provider credential,
Docker socket or evaluator administration route. Research/MCP receive typed
metadata references and cannot read its filesystem or download original bytes.

1. `POST /v1/programs/{program}/uploads` declares an operation key, size, SHA256,
   media type, source identity, intended use, provenance and licence. Declaration
   retries are idempotent; a key cannot name changed content.
2. Send fixed bounded binary chunks to `uploads/{id}/chunks`, with
   `X-Chunk-Offset` and `X-Chunk-SHA256`. Do this through the upload HTTP endpoint,
   never by placing a large base64 package in an MCP tool/model context. Repeating
   an identical chunk is safe; conflicting bytes at the same offset are refused.
3. `uploads/{id}/finalize` verifies completeness and the original declared hash,
   validates bounded format/archive structure, then atomically links immutable
   bytes into private quarantine. Invalid material remains explicitly rejected;
   it cannot become a usable source reference.
4. An alternative `POST /v1/programs/{program}/imports` names a configured mount
   ID and relative regular-file path plus the same declaration. Directory
   descriptors and no-follow opens prohibit symlink races, path escapes and
   special files. The service copies and hashes the exact bytes privately,
   protecting the reference from later source-mount edits. No arbitrary host
   path or URL fetch is accepted.
5. `GET .../uploads/{id}` and `GET .../assets` return metadata; `POST .../assets/verify`
   checks the exact finalized reference and bytes. `validation=transport_only`
   and `execution_authorized=false` are explicit. Semantic table/model admission
   and licensed-data usage remain subsequent authorized operations.

SQLite transactions persist declarations, immutable chunk history, terminal
validation state and append-only principal/request/UTC audit events on the private
volume. Failed/abandoned declarations retain their reservation and history. Limits
in `configs/research/intake_transport_v1.json` bound per-source bytes, program
reservations, chunks, metadata and archive expansion; no automatic deletion or
silent quota reset exists. Operators must budget storage for immutable chunks
plus finalized files (up to twice reserved source bytes), with additional temporary
space for one active finalization. Quota pauses never imply research completion.

ZIP validation rejects links, special files, traversal, duplicate names, oversized
directories/members/expansion, encryption and unsupported compression. Compressed
archive signatures cannot evade validation through a generic media declaration;
unsupported archive formats fail explicitly. Original Chinese UTF-8 text remains
unchanged. The service never extracts or imports an uploaded Python module.

The existing `qfr ingest once` exact-plan authorization remains mandatory for
building snapshots. Transport validation neither authorizes that CLI nor grants
research access to full raw data. Real original-pilot transport and deployment
boundary evidence belong to Mac acceptance, not the small synthetic unit tests.
