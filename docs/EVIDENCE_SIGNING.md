# Signed evidence and atomic release

Stage 4 adds evaluator-only signing and public verification. This is an
implementation checkpoint; actual Mac delivery/MCP acceptance remains pending.

The evaluator signs Ed25519 messages with the domain `qfr-signed-json-v1`.
The message binds the purpose, algorithm, content-addressed public-key ID and
typed payload. Canonical JSON is UTF-8, sorted by key, compact, and forbids
nonfinite numbers. The top-level signature is excluded. Report, private
measurement-receipt and delivery-receipt purposes are separate. Verifiers accept
only explicitly configured public keys and purposes; evidence cannot supply its
own trust authority. Input size is bounded and duplicate JSON members are refused.

Private keys are raw 32-byte files owned by the evaluator's effective UID, with
no group/other permission bits. Symlinks, non-regular files, missing files and
wrong sizes fail closed. The implementation creates no persistent keys or grants.
Examples contain public test-vector material only and are not deployment trust
configuration. Tests use ephemeral synthetic keys. Research, MCP and Feedback
receive public verification configuration only; no private-key mount is permitted.

`qfr-eval-admin sign-receipt` reads an original private receipt, verifies all
referenced files and exact record/request/protocol/snapshot/runtime identities,
then stores a separate immutable signed wrapper. The original receipt retains
its `internal_unsigned` label and original hash. Neither the wrapper nor its
private file references are public Feedback or export content.

`qfr-eval-admin release-ready` requires explicit `--program-id`,
`--policy-sha256`, `--limit`, `--principal`, `--request-id`, `--signing-key`,
`--verification-policy` and `--evidence-root`. Intake sources additionally need
their frozen `--intake-runtime`. There is no caller clock or automatic campaign.
The database clock must have reached the immutable source's batch time. Pilot
publication uses `release_pilot_v2.json`; v1 preparations and earlier cards are
retained as history, not silently upgraded.

Within one transaction, publication takes the Ladder and queue locks, reprojects
the immutable source, verifies/signs the private receipt where applicable, signs
and verifies the report, writes the report and Ladder, records disclosure counts,
and marks the source published. All audit writes roll back on failure. Retries
return the same immutable report, including its original timestamp and signature.
No saved unsigned preparation can advance the Ladder or become public evidence.

The Feedback API validates every report signature in addition to role, program,
batch and schema checks. MCP must independently verify evidence before attaching
an official label. The delivery checker, Research API completion and actual export
integration are subsequent Stage 4 work; signing a structural object alone does
not establish that its research-delivery requirements passed.

The cryptography dependency and its transitive dependencies are pinned in the
lock; upstream notices remain in installed distributions. New sandbox profiles
pin that lock with all isolation/resource controls unchanged. Earlier profiles,
runtime identities, official records and golden evidence are not rewritten.
