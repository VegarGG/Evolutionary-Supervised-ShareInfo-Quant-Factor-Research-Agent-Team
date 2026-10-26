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

Full Stage 3 gate verification is pending implementation of the remaining packages.
