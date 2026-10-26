# Stage 3 — Registry, execution contracts and sandbox

Work starts from the verified Stage 2 commit
`57fae27c956a0954f2347e203435a30883a42d09` on `stage-3-registry-sandbox`.
The predecessor remains unmerged. Stage 3 does not implement feedback release,
blackboard services, agents, provider calls or confirmation-query execution.

## Target-host preflight

The existing cloud Linux x86_64 host has gVisor `runsc release-20260413.0`
registered with Docker 28.4.0. Runtime binary SHA256:
`c97966a7bce00a6ce6de2f931b2b4cf0cbe979d5f47d9feda75f5bbbce0d93ad`.
A bounded trusted Python probe used the existing pinned Python image, explicit
`--runtime runsc`, no network, a read-only root, UID 1000, all capabilities
dropped, no new privileges, 128 MiB memory, half a CPU, a 3-second CPU rlimit,
64 tasks, 1 MiB tmpfs, capped files/logs and an external 20-second timeout.
It verified `PR_GET_NO_NEW_PRIVS=1`, zero capabilities, `EROFS` outside tmpfs,
no external network route and no visible host/evaluator/secret/socket paths.
Temporary probe containers were removed after each attempt.

The initial 16-task ceiling prevented runtime bootstrap; the same trusted probe
passed with 64 tasks. A local log-driver compression setting was corrected before
the runtime test. Neither change relaxed isolation or changed host configuration.
No runtime installation, daemon registration/restart, sysctl, security or network
policy change was made. These smoke results do not replace the complete SBX gate.

## Registry storage

The registry has its own online Alembic environment. Migrations require a separate
owner connection to `registry_db`; application connections have no DDL authority.
The Stage 0 bootstrap SQL and historical payloads remain unchanged. Typed metadata
constraints apply to new rows; historical reservation rows remain nonpublic.

Families, versions, parents, payload references and idempotency receipts are
append-only. Database triggers atomically record each insertion with its principal,
request ID and timestamp. Sequence assignment holds a transaction-scoped advisory
lock before allocating a value, so polling cannot advance past a publication that
has not committed. Lineage references must point backward within one program.

## Publication contract

`ArtifactDefinition` is the client-owned part of the existing manifest. A publication
request supplies a profile, a retry key, the definition and explicitly declared
base64 payloads. The server assigns UUIDv7 identities, family revision, sequence,
publisher and timestamp. An optional client content hash is ignored. The published
manifest remains the complete artifact identity; submission requires no fake IDs.

The `qfr-publication/1` content hash covers canonical sorted JSON containing the
definition without its assigned family ID, the explicit profile and the pinned DSL
configuration hash. The definition includes payload digests and lineage. Retry keys,
claims about the hash and server metadata are outside content identity. Implementation
and canonical DSL fingerprints remain separate. A metadata revision still creates a
version; downstream exact/behavioral dedup decides whether it warrants evaluation.

`configs/registry/publication_v1.json` bounds request, file and archive sizes. These
are ingestion resource controls, not pilot financial or screening thresholds.
Declared package metadata is checked without executing source, extracting archives
or unpickling weights. Paths, symlinks, special members, expansion and undeclared
payloads are rejected. Source inspection/execution requires the sandbox. Publication
alone never establishes executable readiness or schedules evaluation.

The HTTP app denies access unless an explicit authorizer is configured.
Its only artifact mutation is `POST /v1/artifacts`. No persistent token was created.

## Registry reads

Manifest, family, sequence-listing and bidirectional lineage reads enforce program
scope. Global sequence listing requires a reader or evaluator role. A publisher
can retrieve authorized individual artifacts, families, lineage and payloads.
An inaccessible identifier returns the same 404 response as an absent identifier.

`configs/registry/read_v1.json` pins page-size, byte, lineage-depth, node and edge
bounds. Sequence pages are strictly ordered; the next cursor is the final returned
publication, and an empty poll preserves its input cursor. Byte-limited pages do
not skip remaining entries. Family reads default to the first page at the configured
size and expose the same continuation cursor. Lineage results explicitly mark a
depth-truncated graph; resource-limit overflow fails instead of returning an
apparently complete graph.

Reads verify canonical manifest bytes against content-addressed storage. The
additional GET-only payload route resolves only an asset declared in an authorized
manifest, verifies its digest, and serves it as an attachment with a digest ETag
and `nosniff`. Client input never becomes a filesystem path. Missing read policy
is an explicit readiness failure. Reads do not notify or control the evaluator.

## Authentication and attribution

`RegistryAuthenticationConfiguration` declares versioned bindings from named
principals to explicit program IDs, registry roles and `env:` secret references.
`StaticTokenAuthorizer` resolves only those references from a supplied environment
mapping. Missing, malformed or reused token values prevent initialization. Bearer
authentication requires exactly one Authorization header; query-string tokens do
not authenticate. Comparisons use constant-time digest comparison over every binding.
The authorizer retains digests instead of credential values.

The committed `configs/registry/authentication_v1.json` is disabled with no bindings.
It creates no credential or grant. Production credentials and their deployment need
the separately required operator approval. Tests generate ephemeral synthetic values
in memory, including a real loopback HTTP publication/read/retry against PostgreSQL.

Every HTTP request records a UTC timestamp, request ID, authenticated principal
(or `anonymous`), route template, method and status. Logs omit Authorization headers,
query strings, raw paths, payloads and exception text. Invalid or duplicate request
IDs are rejected. Publication passes the same validated request ID and server-resolved
principal into the existing atomic append-only audit mechanism. Client claims cannot
replace publisher attribution. Denials, retries and server failures remain explicit.
The default structured stderr sink emits without relying on an embedding
application to lower Python's default logging level.

Full Stage 3 gate verification is pending implementation of the remaining packages.
