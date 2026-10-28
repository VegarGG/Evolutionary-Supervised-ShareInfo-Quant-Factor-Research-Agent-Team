# Human-driven research API (Stage 4 checkpoint)

`qfr_research.api.app.create_app` implements the typed Research API. Deployment
wiring, MCP and actual client acceptance are still in progress; this document is
not a Stage 4 gate pass. It uses only `research_rw` in `research_db`, authorized
research snapshots and HTTP reads of Registry/released Feedback. It holds no
evaluation credentials, private protocol, signing key or evaluation control.

## Admission and lifecycle

All non-health routes require a configured `research`-audience bearer token with
explicit programs. `research_lead` controls research; `reader` reads; a separate
`human_reviewer` answers human checkpoints. No default token or persistent grant
is generated. Requests log authenticated principal, UTC time, server request ID,
route template, method and status, excluding credentials, bodies and raw errors.

Create/read programs at `/v1/programs`; register a trusted ingest catalog ID at
`/v1/programs/{program}/datasets` and immutable Registry baselines at the matching
`baselines` route. Dataset metadata exposes the authorized research slice and an
opaque full-snapshot identity, never the full manifest. Protocol proposals are
non-authoritative research notes; freezing still belongs to the evaluator-owner
CLI and cannot be invoked through this API.

`POST /v1/programs/{program}/input-validation` verifies a `JobAdmission` before
submission to the corresponding `jobs` route. Admission freezes the complete
input bundle, brief, gate and configuration hashes. It checks source references
with the separately authenticated intake service, research registrations,
baselines and public protocol cards. It never invents missing inputs. An admitted
`ready` job starts only after an explicit control; it has no LLM worker in Stage 4.

Same key/same intent recovers the existing job, including after a lost response
or service restart. A conflicting valid intent returns 409. Immutable intent
cannot be edited: materially revised inputs require a new admission. A missing
registration can be supplied without changing an otherwise frozen ready bundle.
Data waits, unresolved inputs and budget pauses remain distinct from completion.

`GET /v1/jobs/{job}` returns state, revision, next action and polling guidance.
`POST /v1/jobs/{job}/control` accepts only start, await-evaluation, pause, resume
or cancel, with an operation key and expected revision. It affects research
tasks only. Request/connection cancellation does not cancel an admitted job.
No default deadline or generation count ends it. Checkpoint open/read/answer
routes persist questions and immutable, separately authorized answers; a delivery
approval binds the exact active proposal and gate.

## Completion and export

A proposal names immutable artifacts, released report hashes, requested outputs
and a supported conclusion. The independent evaluator pulls
`GET /v1/jobs/{job}/delivery-proposals/{proposal}` on its own authorized operation.
Research can subsequently submit a receipt **ID**, never a caller-authored receipt
body, to `delivery-receipts`. The API reads it through Feedback, verifies its
signature and exact job/input/brief/configuration/proposal/checker bindings and
re-resolves released evidence. A failed receipt stays failed. Only a passing
receipt matching every frozen requirement moves the job to `completed`.

Checker profile `pilot_research_delivery_v2.json` adds the complete input-bundle
and admission hashes to its signed configuration references. Version 1 profiles,
receipts and their serialization remain unchanged. Version 2 changes no business
rule, approved measurement protocol, seed, tolerance or release policy.

`POST /v1/jobs/{job}/exports` creates an immutable, audited archive and returns its
download path, byte count, archive hash and manifest hash. Downloads are scoped to
the same program. Lost-request retries return the same stored bytes. A shortlist
view adds its selection index and retains all receipt-required evidence.

The archive contains the signed receipt, frozen public intent/configuration,
Registry manifests and payloads, released reports, public protocol cards, source
references and authorized research dataset metadata. Dependency/provenance
references remain in the immutable artifact manifests. Original source packages,
licensed table bytes, private protocols, evaluator files, secrets and unreleased
results are not source paths available to this exporter. Arbitrary directory
archiving and original-source download are absent. User-authored public artifacts
remain untrusted material; signing does not authorize executing them.

`qfr_core.exports.verify_export` verifies the trusted checker hash and signatures,
all member hashes and exact signed relationships, and refuses extra unbound
members, path traversal, links, duplicate references and excessive expansion.
The verification keys and checker allowlist must come from the operator, not
from the downloaded archive. This is evidence-integrity verification: it does not
claim to re-run private financial measurement from research-only metadata.

## Limits and verification scope

`configs/research/api_v1.json` versions body/read-time/page/export limits; invalid
JSON, duplicate keys, nonfinite values, oversized bodies and missing credentials
fail before admission. PostgreSQL statement/lock timeouts bound each connection.
Export construction and offline verification share the same explicit limits.

The component suite uses real PostgreSQL and ephemeral signatures with explicitly
synthetic measurement/replay fixtures. Real P0/P1, elapsed release batches,
Compose restart, Codex/independent clients and complete Mac CI remain separate
Stage 4 acceptance requirements. No provider call, confirmation query, investment
promotion or Stage 5 loop is enabled by this checkpoint.
