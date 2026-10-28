# PostgreSQL credential startup

Generated credentials stay host-private (0600); PostgreSQL runs as a different
UID. Native Linux bind mounts enforce host ownership and permissions. Docker
Desktop file sharing can present the same metadata while permitting a container
UID to read the mount; `stat` alone does not establish a denied read there.
The former initialization hook attempted to read those mounts after dropping
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
  uv run --locked --all-packages python -m pytest --require-postgres tests/boundary/test_database.py
just down
```

The real-container regression script uses generated temporary credentials and
isolated disposable containers. It exercises missing/empty administrator and role
credentials, a nonempty failed read, absent tmpfs, a Linux-enforced UID mismatch,
and the failed-hook restart marker. The UID negative fixture copies a synthetic
secret into Linux tmpfs, verifies root ownership and mode 0600, and proves that
the PostgreSQL UID cannot read it before invoking the hook. It still requires a
read error, no SQL execution and a retained pending marker. This tests the denied
read invariant without assuming Docker Desktop's host-sharing implementation;
the host source remains untouched at 0600. A failed fixture precondition is a
failure, never a skip or pass. Run just this case during diagnosis with:

```sh
uv run --locked --all-packages python scripts/verify_postgres_startup.py --case linux-uid-mismatch
```

The Python tests additionally cover an actual unreadable file under an
unprivileged test UID (explicitly unrun under root),
all four role read failures, cleanup and SQL errors. Authenticated database tests
retain every previous boundary assertion and require non-null SCRAM credentials.
No test prints credential values or stored hashes.

The local-CI and hosted workflow both run the real-container regressions. Container
checks do not receive a Docker socket. Full local verification also includes the
locked Linux CI image, all four application images for both architectures, original
pilot integrity/parity checks and normal Git checkout permissions. The exact commit,
commands, outcomes and digest evidence belong in the repair PR's local-CI report.
ARM builds on an AMD64 host use BuildKit emulation and do not establish native
Apple host acceptance. Likewise AMD64 emulation on the Mac does not validate a
native Linux AMD64 deployment. Record macOS/Apple Silicon host evidence separately
from Linux ARM64 container results, with Apple-first release and later Linux AMD64
acceptance as defined in [DEPLOYMENT_TARGETS.md](DEPLOYMENT_TARGETS.md). A passing
PostgreSQL regression proves its stated startup invariant, not the full host or
sandbox gate. Local success does not change hosted Actions conclusions.

Database-backed tests use the `database` pytest marker. Without
`QFR_TEST_POSTGRES_DSN`, their prerequisite is resolved on pytest's thread before
HTTP clients or server threads start; they are reported as skipped/unrun. CI uses
`--require-postgres`, which instead fails immediately if the DSN is unconfigured.
An explicitly configured but invalid database remains a failure, with the driver
error class reported without its credential-bearing exception chain. For a
single endpoint, connection attempts are bounded by the five-second timeout in
`configs/testing/postgres_v1.json`; a refused or unresponsive endpoint fails,
never skips. This is a test-harness timeout, not a production database setting.
For a required local database run, use `PYTEST_ADDOPTS=--require-postgres just test`
alongside the existing DSN and secret-directory configuration. These harness
changes do not diagnose a Docker startup delay or change PostgreSQL permissions.
