# Phase 2 implementation and acceptance record

Status: **implemented; every Phase 2 acceptance check passes in local tests against a
real PostgreSQL 16; ready for owner review**. Owner acceptance and merge are not
asserted. Phase 2 was built on the Phase 1 branch (PR #12) and rebased onto `main` after
#12 merged. No Phase 3 work has begun. Design choices are in
[decisions.md](decisions.md#phase-2-decisions).

## Acceptance checks

| Check (plan) | Result | Evidence |
|---|---|---|
| REG-01: UPDATE and DELETE on artifact_versions, pool_entries and pool_events raise at the database level, even as registry_app | Pass | `tests/registry/test_pools.py::test_reg_01_updates_and_deletes_raise_even_as_registry_app` (UPDATE, DELETE and TRUNCATE on all three tables: permission denied) and `::test_reg_01_triggers_block_mutation_for_the_table_owner` (the same nine statements as the table owner: the append-only triggers refuse). `::test_registry_role_has_no_ddl_and_the_view_is_read_only` |
| REG-02: republishing identical content returns the same version id | Pass | `tests/registry/test_publish.py::test_reg_02_republishing_identical_content_returns_the_same_version` (200, same id, one row) |
| REG-03: any manifest change produces a new version_no and content_hash | Pass | `test_publish.py::test_reg_03_any_manifest_change_creates_a_new_version` |
| REG-04: the server recomputes content_hash and ignores client hashes | Pass | `test_publish.py::test_reg_04_server_computes_hashes_and_ignores_client_values` (client values dropped and logged) |
| BND-09: the OpenAPI document has no mutation route but POST /v1/artifacts and the two pool POST routes; pool routes reject every token but control | Pass | `tests/registry/test_openapi.py::test_bnd_09_openapi_has_only_the_three_mutation_routes`, `::test_bnd_09_pool_routes_reject_every_token_but_control` (publisher, reader and evaluator get 403; missing or wrong tokens get 401), `::test_no_put_patch_or_delete_route_exists`. `just doctor` repeats the route check on the running container |
| AUD-01: every write produces an audit event with a principal and a request id | Pass | `test_publish.py::test_aud_01_every_write_has_an_audit_row_with_principal_and_request_id` (a publish: the audit row, the stored version and the log lines carry the principal and the caller's request id, which the response echoes); `test_pools.py` checks the POOL_ENTRY_ADDED and POOL_EVENT_APPENDED rows of every pool write |
| POOL-01: entries and status events need an approval whose scope covers the version (seed imports excepted), reject research and evaluator tokens, and produce events and audit rows | Pass | `test_pools.py::test_pool_01_seed_imports_need_a_setup_reference_and_only_control_writes`, `::test_pool_01_approved_entries_require_an_approval_covering_the_version`, `::test_pool_01_status_events_need_approval_and_annotations_do_not`, `::test_kind_must_match_the_pool` |
| SET-01: a fresh stack is empty and says so | Pass | `tests/mcp/test_setup.py::test_set_01_a_fresh_stack_is_empty_and_says_so`: through MCP, `qfr.status` and `qfr.setup.status` report zero versions, families and pool entries with the no-defaults notice; `qfr.pool.import` with `no_pool=true` records the `empty` state and the notice in control_db `setup_state`. `tests/mcp/test_setup_cli.py::test_setup_without_a_pool_records_the_empty_start` does the same through `qfr setup` |
| SET-02: a 5-row sample file imported through MCP yields 5 human_seed versions and 5 seed entries; an invalid row is rejected with a reason code and logged | Pass | `test_setup.py::test_set_02_a_five_row_file_yields_five_human_seed_versions_and_entries` (CSV under imports/, 5 versions with operator human_seed and no job, 5 seed entries carrying the setup reference, 5 DSL_VALIDATED and 5 SEEDS_PUBLISHED trace steps); `::test_set_02_invalid_rows_are_rejected_with_reason_codes_and_logged` (YAML with FORBIDDEN_CONSTRUCT and SCHEMA_INVALID rows, each logged as `pool_import_entry_rejected`, plus a seed strategy over two seed factors); `::test_set_02_reimport_is_idempotent_and_a_changed_row_is_a_new_version` |

SET-01 also asks, in the plan's test table, that a job submitted through MCP complete a
generation from exploration alone and that there be zero programs. Jobs and programs
arrive in Phase 4 and the evaluator in Phase 3, so that part is checked then
(decision 21). The Phase 2 acceptance wording is covered in full.

## Delivered scope

| Task | Delivered | Main tests |
|---|---|---|
| P2.1 | registry_db migration 0002: families, versions, parents with AST diffs, pool entries, pool events, the registry event log, the `pool_current_v` view; REVOKEs plus row and TRUNCATE triggers. control_db migration 0002: `setup_state` and `trace_steps`, both insert-only | `tests/registry/test_pools.py` |
| P2.2 | `POST /v1/artifacts`: schema validation, declared-versus-parsed checks, server hashes, families and version numbers, lineage with AST and strategy diffs, idempotency, human_seed rules, publish keys | `tests/registry/test_publish.py` |
| P2.3 | Version, family and lineage reads, `since_seq` listing, pool listing with cursors, pool events `since_seq`, entry detail, a counts summary | `test_publish.py`, `test_pools.py` |
| P2.4 | Add entry and append event; control token only; approval scope check; setup reference for seeds; kind-to-pool rule | `test_pools.py` |
| P2.5 | Four distinct role tokens with constant-time checks, request ids from `X-Request-Id` on every log line and response, body-size limit, audit rows for every write | `tests/registry/test_openapi.py`, `test_publish.py` |
| P2.6 | MCP tools `qfr.setup.status`, `qfr.pool.import`, `qfr.pool.list`, `qfr.pool.get`, `qfr.dsl.validate` (with a plain-language explanation) and `qfr.artifact.get`; `qfr.status` now reports setup and pool counts; pool_import/1 parsing (JSON, YAML, CSV) and validation; seed publication; the empty start; `qfr setup` | `tests/mcp`, `tests/test_pool_import.py`, `tests/dsl/test_explain.py` |

Compose now runs registry-api from its own `registry` image target (healthy only when
its database is reachable), and qfr-mcp reads raw pool files from `/imports`. CI builds
the new image target for both architectures. `just doctor` expects registry-api to be
running, checks BND-09 on the live OpenAPI document and reports the setup state.

Nothing is preloaded: no factors, strategies, pool entries or sample files.

## Checks executed

- `ruff check`, `ruff format --check`, `mypy` (strict for core and MCP), all four import
  contracts, schema and public-card generation, and the license check pass. The
  regenerated schemas are committed.
- `pytest` against PostgreSQL 16 with the Phase 0 roles and both new migrations
  (`QFR_REQUIRE_DB_TESTS=1`): **916 passed, 0 skipped** in about two minutes. Phase 2
  adds 91 tests. The databases are empty after the run.
- Without database credentials the new database tests skip, as before.

Not executed here: Docker image builds, `just up` and `just doctor`, which need
Docker. CI builds the images for arm64 and amd64.

## On the Mac

```sh
just build && just up
just doctor                      # registry-api healthy, BND-09, setup state
just setup                       # asks the pool question; Enter for none
# or, with a file placed in the repository's imports/ folder:
uv run --locked qfr setup --non-interactive --pool-file raw_pool.csv
```

A host agent can do the same with `qfr.setup.status` and `qfr.pool.import`.
