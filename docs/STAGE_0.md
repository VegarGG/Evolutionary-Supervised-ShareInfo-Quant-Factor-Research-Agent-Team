# Stage 0 foundation

Stage 0 defines contracts, configuration, packaging and storage boundaries. It contains no
factor computation, evaluation engine, LLM calls, API handlers or background scheduling.
The ordered source of authority is the owner's request, PLAN_ALIGNMENT.md, the development
plan and applicable local-reference details. Licensed packages remain outside this repository.

The five uv packages are independent deployment units. `qfr_core` contains public contracts
and deterministic shared foundations; official records and trial ledgers belong in `qfr_eval`.
`qfr_mcp` will call authorized APIs over HTTP. Each later component has a package namespace;
empty namespaces are reservations, not implemented capabilities.

Install Python 3.12 and uv, then run `uv sync --locked --all-packages`. The development group
includes the `just` binary (`rust-just`); add `.venv/bin` to PATH if just is not installed globally.
Run `just check` and `just test`. Dependency versions and distribution hashes are frozen in
`uv.lock`; use `--locked` for reproducible installation.

Tooling reference: [uv workspace documentation](https://docs.astral.sh/uv/concepts/projects/workspaces/).

Start the local database with `just up`; it creates ignored `.secrets/` files if absent and
keeps state in named Docker volumes. `just down` preserves those volumes. For live checks:

```sh
export QFR_TEST_POSTGRES_DSN=postgresql://127.0.0.1:55432/postgres
export QFR_PILOT_ROOT='/path/to/parent/of/original/P0-and-P1-folders'
just check
just test
```

Only test/bootstrap code receives the administrator credential. Application services receive
one role-specific secret file each; MCP has none. PostgreSQL initialization reserves table
names and enforces storage permissions. Full domain repositories, signed-report verification,
API authorization, state machines and measurement are not implemented. The feedback views
contain released rows only; per-program authorization remains an API responsibility in Stage 4.

Build with `just build-images`. Both platforms and four deployment package images produce
OCI archives under ignored `build/` and digest JSON under `build/digests/`. CI runs database
checks against a PostgreSQL service, verifies Compose startup separately, and uploads
AMD64/ARM64 digest artifacts. Builds do not constitute native runtime or sandbox acceptance.

`just local-ci` runs the same checks and tests in a Linux container against the Compose
PostgreSQL instance, then builds all four images for both architectures. It saves logs in
`build/local-ci/` and verifies each OCI manifest digest, platform and source revision before
writing `build/digests/*.digest.json`. Run from a clean commit for acceptance evidence.
The trusted test container mounts generated database credentials read-only; no secret or
licensed raw input enters its build context. The host pilot tests use `QFR_PILOT_ROOT` as above;
the Linux container explicitly skips those licensed-input tests. A local AMD64 build on an
ARM Docker host uses emulation and does not establish native AMD64 runtime acceptance.

The owner authorized a local CI substitute because GitHub Actions usage is exhausted this
month. Publication commits contain `[skip ci]` so the retained workflow does not run on this
push. GitHub Actions is unexecuted, not verified green; local results are recorded separately.

The local test environment used a task-owned `qfr-stage0` Colima profile. Its default context
was not activated. Deployment is portable Docker Compose; Colima itself is not a project dependency.
The actual deployment host/VM (including the proposed Mac Studio), executable sandbox backend,
provider IDs/capabilities, operator spending and evaluator protocol freeze remain owner choices
before the stages that require them. Stage 1 will build canonical data, logical hashing, as-of
slicing and source-feature parity; original replay, evaluator logic, APIs and LLM calls remain
in their ordered later stages.
