# PostgreSQL credential startup

Compose file-backed secrets retain the host file's ownership and permissions.
Generated credentials stay host-private (0600); PostgreSQL runs as a different
UID. The former initialization hook attempted to read those mounts after dropping
privileges. `export NAME="$(cat file)"` masked read failures, so the baseline SQL
received empty passwords. PostgreSQL cleared those role passwords and became
healthy even though application authentication failed. A NULL password under
SCRAM prevents authentication; it does not permit passwordless access.

The trusted PostgreSQL root entrypoint now validates all five input credentials
before initdb. It stages only the four application credentials into an explicit
private tmpfs: directory 0700 and files 0400, owned by PostgreSQL. Missing tmpfs,
missing/unreadable files and empty values stop startup. The original host mounts
remain read-only, with no chmod or chown of host files. Public SQL/init assets are
copied inside the container so managed checkout modes do not block initialization.
The official pinned PostgreSQL entrypoint still performs initialization and drops
privileges. Application containers, networks and grants are unchanged.

The initialization hook validates every read before any role DDL, passes values
only in its SQL child's environment, and removes the staged copies on success or
failure. Values never enter command arguments or logs. A pending marker in PGDATA
survives a failed hook and prevents a later restart from silently accepting its
partial initialization. After successful initialization, restarts validate inputs,
remove unused staged copies, and leave database contents/passwords unchanged.
No schema change or baseline SQL edit is involved.

Existing volumes that were already initialized with missing application passwords
are not automatically repaired or reset. An operator must inspect and recover such
a volume using its original credentials and data-preservation procedure. A pending
marker also requires operator recovery; do not remove it to relabel failure as
success. Do not delete a volume containing user data to work around this gate.

Verification runs `just check`, `just test` against a fresh PostgreSQL CI service,
and the following Compose path on a fresh disposable volume:

```sh
uv run --locked --all-packages python scripts/verify_postgres_startup.py
just up
QFR_TEST_POSTGRES_DSN=postgresql://127.0.0.1:55432/postgres \
  uv run --locked --all-packages python -m pytest tests/boundary/test_database.py
just down
```

The real-container regression script uses generated temporary credentials and
isolated disposable containers. It exercises missing/empty administrator and role
credentials, a nonempty failed read, absent tmpfs, the original host/container UID
mismatch, and the failed-hook restart marker. The Python tests additionally cover
all four role read failures, cleanup and SQL errors. Authenticated database tests
retain every previous boundary assertion and require non-null SCRAM credentials.
No test prints credential values or stored hashes.

The local-CI and hosted workflow both run the real-container regressions. Container
checks do not receive a Docker socket. Full local verification also includes the
locked Linux CI image, all four application images for both architectures, original
pilot integrity/parity checks and normal Git checkout permissions. The exact commit,
commands, outcomes and digest evidence belong in the repair PR's local-CI report.
ARM builds on an AMD64 host use BuildKit emulation and do not establish native ARM
runtime acceptance. Local success does not change hosted Actions conclusions.
