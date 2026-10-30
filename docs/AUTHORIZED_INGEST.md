# Authorized on-demand ingest (P3.8)

`qfr ingest once` is an evaluation-side operator command. It reads local inputs,
builds full and research snapshots, and publishes a research-only dataset catalog.
Importing modules or starting services does not invoke it. It has no scheduler,
supplier URL, model call, protocol activation or evaluation trigger. Historical
catch-up is labelled replay; it is never prospective evidence.

The private `SnapshotBuildPlan` freezes source identity, adapter parameters,
program, research cutoff, supplied-data as-of date and build version. The separate
`SnapshotBuildAuthorization` must be enabled and name the exact canonical plan
SHA256, operator and effective timestamp. Resource bounds are explicit. The
generated authorization example is **disabled**; its synthetic dimensions and
limits are examples, not permission to run or universal product defaults.

Supported sources are the original P0/P1 local package with its inventory and
adapter-manifest hashes, a physically and logically verified existing snapshot,
and an explicitly selected synthetic replay recipe. Paths must be relative to
the operator's source root. Symlinks, special files, excessive inventory/bytes,
metadata or table dimensions, and changed source hashes fail closed. Data files
are parsed by existing data-only adapters; original package code is not imported.
The original sources remain unchanged. No remote fetch is supported.

Example operator sequence, using reviewed private files and existing evaluator
credentials (never embed credentials in command-line arguments):

```sh
qfr ingest plan-hash /operator/plan.json
qfr ingest once --plan /operator/plan.json \
  --authorization /operator/authorization.json \
  --source-root /imports --fixture-root /app/fixtures/pilot \
  --output /data --principal operator-name --request-id REQUEST_UUID
```

The operator first reviews the plan and fills the exact authorization; the hash
command itself does not approve it. A missing or inactive authorization does not
build data. Runtime identity must be `eval_rw` in `eval_db`; the command uses a
dedicated idle autocommit connection and bounded connection/lock waits. No
research or MCP endpoint can create this authorization or run ingest.

The private append-only request fixes its plan and authorization hashes. Build
outcomes and audit entries retain source identities and full-manifest hashes.
Retrying the same plan is idempotent; reusing its ID for different intent is a
conflict. A build failure is recorded as failure. After the private build commit,
catalog publication is atomic and cannot overwrite different bytes. A crash at
that boundary resumes from the original verified snapshots, even if source files
are no longer mounted; corrupt built evidence is refused, not regenerated.
`catalog_available` is recorded only after catalog publication. This status is
not research-job completion or delivery acceptance.

Only `research/catalog/<registration_sha256>.json` crosses into the research
volume. It binds the program, public source reference, opaque full-snapshot ID,
research manifest and its hash. It excludes source paths, private source bytes
and the full manifest. The reader verifies catalog scope/hash and actual research
snapshot files before use. Research mounts this volume read-only, never the full
zone. Snapshot-replay sources retain typed quality/exposure but do not copy
arbitrary full-zone conventions into the catalog. Missing availability remains
excluded; previously-seen and vintage/membership limitations remain labelled.

The trusted build writes audit files inside the full volume. Its optional audit
location does not affect snapshot identity or change the older `qfr data build`
command. New image directories initialize new full/research named volumes with
UID/GID 65532 and mode 0750. No host permission, existing volume, runtime or
security setting is changed. Deployment verification must use actual volume
ownership and fail if the evaluator cannot write; it must not broaden host-file
readability as a workaround.

Focused tests use tiny synthetic inputs and real PostgreSQL for authorization,
concurrent retries, append-only records, crash recovery, CLI output, private-zone
exclusion and read-only-root behavior. The separately marked original-pilot test
requires licensed inputs and checks input hashes before/after, quality labels and
the frozen development cutoff. Its absence is an explicit skip, not acceptance.
Actual Mac images, volume initialization and the full human-driven Stage 4 flow
remain required. Daily forward-campaign scheduling remains an optional later
operating profile and is not enabled here.
