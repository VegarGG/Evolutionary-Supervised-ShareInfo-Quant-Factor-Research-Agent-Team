# Stage 0 acceptance evidence

Scope: P0.1–P0.7 only. The owner explicitly authorized pushing `stage-0-foundation`
and substituted local CI for GitHub Actions because the monthly Actions allowance is
unavailable. Publication uses `[skip ci]`. No merge is authorized or performed.
The GitHub workflow remains available; a remote green run is not claimed.

The tested implementation revision is `0ee49391c64aed9537e5394b0138483cc22ba598`; it is recorded in
each image record. Later acceptance-document commits contain evidence only. Licensed raw inputs and
local generated credentials remain outside Git tracking and all image build contexts.

| Exit gate | Status | Test or command and evidence |
|---|---|---|
| Public valid/invalid examples | PASS | `test_public_schema_valid_and_invalid_examples`: all 86 public contracts accept their valid document and reject their invalid document using Pydantic and generated JSON Schema. Five artifact-kind examples also validate. |
| PostgreSQL startup | PASS | `just up` and `test_postgres16_databases_and_roles`: PostgreSQL 16, research_db/registry_db/eval_db and four nonsuperuser application roles. Published database port binds only 127.0.0.1. |
| BND-01 | PASS | `test_bnd_01_connect_isolation`: research_rw cannot CONNECT to eval_db; eval_rw cannot CONNECT to research_db. Allowed connections succeed and additional cross-zone denials pass. |
| BND-04 | PASS | `test_bnd_04_import_contracts`: five contracts kept, none broken. `test_bnd_04_detects_an_actual_forbidden_import` proves an injected forbidden research import fails. |
| Pilot fixture metadata and evidence | PASS | `test_pilot_input_hash_rows_columns_dates`: fourteen source comparisons across the six inputs plus label map in both original packages. `test_pilot_golden_evidence_exact_source_extraction` matches original ledgers and reference CSVs exactly. Without QFR_PILOT_ROOT, fifteen tests skip with an explicit licensed-data message. |
| Local CI substitute, including both architecture builds | PASS | `just local-ci`: Linux checks pass; 142 tests pass with 15 explicit licensed-data skips. Four images build for each platform; all eight manifest digests, platforms and source-revision labels verify. See [image digests](evidence/stage-0/image-digests.json). GitHub Actions remains unexecuted. |

Additional database evidence: `test_feedback_can_only_select_released_views` rejects private
table access and writes. `test_reg_01_insert_only_grants_and_owner_triggers` and
`test_all_insert_only_tables_have_mutation_and_truncate_triggers` verify grants and actual
UPDATE/DELETE/TRUNCATE rejection. Bootstrap owners cannot bypass the triggers with ordinary
DML; application roles cannot disable the triggers. Administrators can deliberately change
DDL, so this is a privilege boundary, not protection against a malicious database administrator.

Completed host commands: `just check` passed Ruff lint/formatting, mypy on
41 package source files, all five import contracts and generation checks for 86 public schemas.
`just test` passed all 157 tests with real PostgreSQL and QFR_PILOT_ROOT set to the parent of
the owner's original P0/P1 delivery directories. The missing-data branch separately passed
one metadata test and explicitly skipped fifteen licensed-data tests.

The GitHub service-container bootstrap was also run against a fresh local PostgreSQL 16
container: generated credentials were installed and host authentication switched to SCRAM.
All fourteen database tests passed against that independent service; the temporary service
was then removed. See [verification metadata](evidence/stage-0/verification.json) and its
linked logs. The four final ARM images passed package-isolation and non-root clean-exit
smoke checks with networking disabled and a read-only filesystem. These checks exercised
only the Stage 0 stubs.

Builds do not establish native production runtime, numerical parity or sandbox acceptance.
The local Docker server is Linux/ARM64; AMD64 builds use emulation. Native acceptance on the
eventual Mac Studio/VM and on AMD64 remains separate. No factor, model replay, evaluation,
LLM request, API operation or continuous scheduler was implemented or exercised.

Decisions recorded in `docs/decisions.md`:

- S0-01: authoritative checkout, document section reconciliation and Stage 0 scope.
- S0-02: fifteen reconciled AGENTS rules.
- S0-03: original versus proposed windows, prior exposure and private epochs.
- S0-04: retain distinct cost and quarterly-bootstrap conventions from their sources.
- S0-05: verify missing hashes/full headers from originals; preserve null/not-applicable quality.
- S0-06: preserve exact source CSV strings, hashes, row references and replay oracles.
- S0-07: illustrative provider routing; unknown identity/capability/pricing fields remain null.
- S0-08: protected SQL table reservations; domain repositories and migrations remain later work.
- S0-09: loopback PostgreSQL bridge and internal application zones with clean-exit stubs.
- S0-10: generated CI credentials and SCRAM; rotate early exposed local test credentials.
- S0-11: 86 public contracts, private record exclusion and explicit authenticity limits.
- S0-12: isolated task-owned Colima environment; build/runtime acceptance remain distinct.
- S0-13: unresolved quotas, seeds, budgets and final job gates are not invented.
- S0-14: owner-authorized push with CI skipped and a local CI substitute.
- S0-15: build the locked test environment once, then run checks offline without re-syncing it.

Open owner choices, before the stages that depend on them:

- Which ARM host/VM and executable sandbox backend will be accepted for deployment?
- Which protocol/epoch defaults, missing pilot caps and stock fingerprint seed will be frozen?
- Which exact provider models, endpoints, verified capabilities, limits and spending authority
  should Stage 5 use? No such access is needed or authorized by this Stage 0 result.
- What concrete delivery gate and budgets should the first executing research job freeze?

Deferred to Stage 1: canonical data representation, logical hashing, availability/as-of slicing,
quality/lineage propagation and parity with the baseline source features. Other later stages
retain independent evaluation, registry/API behavior, signed delivery checking, executable
sandboxing, MCP tools, LLM orchestration and evolutionary research. No later stage began.

To reuse the task-owned environment on this workstation, from the repository root:

```sh
export PATH="$PWD/.venv/bin:$HOME/.local/bin:/opt/homebrew/bin:$PATH"
export DOCKER_HOST="unix://$HOME/.colima/qfr-stage0/docker.sock"
export DOCKER_CONFIG="$PWD/.local/docker"
export QFR_TEST_POSTGRES_DSN=postgresql://127.0.0.1:55432/postgres
export QFR_PILOT_ROOT='/Volumes/Work/Evolutionary Supervised ShareInfo Quant Factor Research Agent Team'
just up
just check
just test
just local-ci
```

The Docker host/config exports select this task's VM and locally verified CLI plugins;
they do not change the user's default Docker context. Other hosts should use their own
Docker engine and Compose/Buildx installation. `just down` stops only the Compose project
and preserves its data volume. Secrets remain in ignored `.secrets/`; do not copy them into
source, images or acceptance artifacts.
