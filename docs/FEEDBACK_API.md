# Released Feedback API

The Stage 4 service factory is `qfr_eval.feedback.app.create_app`. It receives an
explicit `FeedbackReader` and optional audience-bound `BearerAuthority`. With no
authority configured, protected reads refuse authentication. Merely importing or
starting the component admits no evaluation or research work. Compose/MCP wiring
and cryptographic verification are separate Stage 4 integrations.

The reader requires an idle connection authenticated as `feedback_ro` to
`eval_db`. It uses a read-only transaction, a bounded statement timeout and a
transaction-local list of programs from the authenticated token. Wildcards,
commas and control characters are not valid program scopes. Research and MCP do
not receive this database credential. They use HTTP and independently scoped
tokens. `configs/feedback/auth.example.json` contains only a placeholder secret
reference and example program; it is not a deployed grant.

All OpenAPI operations are GET. Other HTTP methods return 405. Request logs carry
only principal, generated request ID, route template, method and status; tokens,
query strings and response payloads are excluded. Production hosting should
retain these metadata logs and disable raw access logs that copy query strings.

| Route | Result |
|---|---|
| `/v1/reports` | Bounded release-order page; `after_id`, aware `since`, `version_id`, `family_id`, `type`, `limit` filters |
| `/v1/reports/{report_id}` | One scoped released report; absent and unauthorized IDs both return 404 |
| `/v1/artifacts/{version_id}/status` | Latest released report and paged released timeline; no private queue status |
| `/v1/library` | Paged released library-membership reports; no promotion or library mutation |
| `/v1/cards/policy?ref=...` | Whitelisted public policy cards |
| `/v1/cards/protocol?ref=...` | Whitelisted public protocol cards |
| `/healthz` | Liveness only |

Cursor IDs are looked up in the caller's scoped released view. Reconnecting and
resuming with the last ID has no effect on any job. Oversized pages/rows, invalid
schemas, inconsistent identity headers and malformed cards fail without returning
private values. Clients must not treat a structurally valid signature as verified;
actual signature checking is the next Stage 4 integration.

Database views require an immutable publication link, matching published queue
state, and an arrived batch time. Legacy reservation rows and unsigned preparation
objects are invisible. Explicit view write guards and SELECT-only grants preserve
the read boundary independently of PostgreSQL's view-updatability planning.

An evaluator owner can inspect/create/activate a release policy with
`qfr eval-admin policy-hash FILE`, `policy-create FILE --principal PRINCIPAL
--request-id UUID`, and `policy-activate --expected-hash SHA --principal PRINCIPAL
--request-id UUID`. `public-cards --policy-sha256 SHA --principal PRINCIPAL
--request-id UUID` projects cards from the frozen policy/protocol. These commands
are not HTTP or MCP capabilities. They do not publish reports, execute a candidate,
spend a confirmation query or contact a provider.

Read policy defaults are versioned in `configs/feedback/read_policy_v1.json`.
Unit tests use ephemeral synthetic tokens, structural report fixtures and declared
fixture clocks. They do not establish cryptographic authenticity, an actual elapsed
release wait or the final P0/P1 acceptance gate.
