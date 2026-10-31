# Phase 0 decisions

The authoritative document is the owner's complete HTML, retained byte for byte as
`docs/PLAN.md` as explicitly required by Section 0 and as `.html` for browser reading.
SHA-256: `ed2f01c8697e75bf3b48c31fe128df883cf4de33e4e8e1a0067a309090609e56`.
The root `AGENTS.md` is extracted verbatim from Section 21.1.

1. The new plan supersedes the previous implementation and discussion, including the
   proposed immediate research-feedback default. Phase 0 stores the plan's batched
   defaults; it implements no release engine. No prior application code is reused.
2. The plan requires one valid and one invalid example per schema (P0.5) and also
   forbids default factors and samples. Contract validation fixtures live only under
   `tests/contracts`, never in runtime configuration, a deployed image, or a pool.
3. Operational commands named in P0.1 whose complete behavior is assigned to later
   phases return explicit `not_implemented_in_phase_0` results, never false success.
   Phase 0 does not run the provider probe, ingest data, or import factors.
4. Placeholder services log startup and shutdown and exit successfully, as P0.3
   requests. Doctor distinguishes expected completed placeholders from running
   services; it never describes them as implemented business APIs.
5. Private evidence schemas are built by qfr_eval into JSON Schema artifacts. Public
   deliverable and history contracts carry opaque JSON at owner-evidence joins;
   qfr_mcp validates those joins against the build artifact, without importing eval.
6. Provider model ids and null prices are copied from the plan's configuration
   examples, explicitly unverified. No provider can run in Phase 0.

7. Section 17.2 gives the shared research network egress while Sections 5.4 and 17.1
   allow it only for research-worker. The stricter rule wins: shared networks are
   internal; an additional research_egress_net serves only research-worker. The
   research API therefore has no internet egress. postgres joins control_net because
   qfr-mcp must connect to control_db; database CONNECT grants enforce the boundary.
8. The whole logs volume is read-only in qfr-mcp, with only its own service directory
   overlaid read-write for the mandated file sink. A networkless, non-root one-shot
   init-volumes container creates service subdirectories before subpath mounts.
9. Four per-database migration roles supplement the five required application roles,
   as Section 5.4 prescribes. They own DDL; application roles cannot create objects.
   Phase 0 creates only the MCP call table. Domain tables and feedback view grants
   arrive in their assigned phases rather than being pre-created speculatively.
10. The unspecified fixed fingerprint seed is 20261030 in the protocol config. W3's
    ending date remains unresolved until an epoch activation pins it; Phase 0 never
    infers a measurement window from the clock.
11. The container's MCP listener binds 0.0.0.0 internally so Docker can route to it;
    its sole published host address is 127.0.0.1:8765. Direct non-container launches
    reject a non-loopback bind. The original default remains loopback in mcp.yaml.
12. The MCP catalog is deliberately restricted to the five Phase 0 tools. Status
    reports missing domain backends as unavailable; owner-only configuration remains
    an evaluator API read and is unavailable until that API exists. Public cards
    are whitelist-built, labelled previews and not represented as activated config.
13. PostgreSQL initialization files are baked read-only into a PostgreSQL 16 image.
    The first Mac bind-mounted attempt failed before bootstrap SQL because the
    external volume's execution permissions blocked the shell script. Only this
    task's failed, unused database volume was recreated; no old data was touched.
14. Docker's automatic address pools are exhausted by existing project networks.
    The new stack uses configurable, explicit 10.233.40.0/24 through 10.233.45.0/24
    subnets; its isolated test database uses 10.233.46.0/24. These did not overlap
    any existing Docker subnet or specific host route when checked. Existing
    networks and Docker daemon settings were preserved.
15. P0.3 requires downstream domain services to exit cleanly; MCP-01 also asks for
    their live request-id logs. Scripted-backend tests verify actual header and log
    propagation, while live calls record their real unavailable backend attempts.
    The owner resolved this on 2026-10-30: "Keep clean-exit placeholders; defer live
    downstream acceptance". That portion is deferred, not marked passed. No stub
    business API is presented as done.
16. Docker Desktop did not publish the MCP port when its only network was internal.
    A temporary, separate ingress-network experiment with outbound masquerading
    disabled still reached external addresses. The experiment was removed. The
    owner approved the resolution on 2026-10-30: "Allow the qfr-mcp-only network".
    The dedicated mcp_ingress_net uses 10.233.47.0/24 and permits outbound
    connectivity from qfr-mcp. Only qfr-mcp joins it; control, research, registry
    and evaluation shared networks remain internal. Only 127.0.0.1:8765 is published.
17. The disposable PostgreSQL test service alone uses a loopback debugging port,
    55433. Port 55432 belongs to an older project; a failed authentication attempt
    discovered that collision before any DDL or writes. The test service now uses
    its own network and volume. Production PostgreSQL publishes no host port.
18. The first normal Docker build stalled on public dependency downloads. Native
    wheels were fetched from the exact URLs in uv.lock and SHA-256 verified. The
    Dockerfile accepts an optional wheel-cache build context and installs it with
    `--require-hashes`; the regular build uses the frozen lockfile. Runtime images
    do not contain that cache. No private package source or paid provider was used.
19. The owner clarified Docker memory policy on 2026-10-30, verbatim:

    > Leave Docker setting unchanged. The plan's 24GiB is a expectation. The real RAM setting will based on the actual performance. Report if you meet OOM.

    Docker settings remain unchanged. The 24 GiB value is retained as a planning
    expectation in configs/deployment.yaml, not a failing acceptance threshold.
    Doctor records the actual allocation and checks each current container's
    OOMKilled state. An observed OOM fails the check and must be reported. This is
    an inspection during execution, not a promise of continuous monitoring or a
    full-load capacity benchmark. Domain placeholders do not establish capacity
    for later research/evaluation workloads.

These later owner instructions amend operational acceptance without changing the
preserved original HTML plan or its verbatim AGENTS.md extract.

20. The owner corrected the publication destination on 2026-10-30:

    > I must correct you that this system belongs to this project: https://github.com/VegarGG/Evolutionary-Supervised-ShareInfo-Quant-Factor-Research-Agent-Team. Here is where you suppose to upload.
    > You should ignore the previous developments and files, including the readme. Those are stale.

    The named repository is canonical. The separate qfr-v2 GitHub repository was
    created in error and is not the project's home. The new PR replaces the stale
    file tree with this Phase 0 implementation, including its new README and plan
    instructions. The base history and Phase 0 implementation history are preserved.
    No stale implementation files or instructions are carried into the new tree.
    The misplaced PR is superseded; no repository history is deleted.

21. The Phase 0 tree replacement removed the owner-approved license (LIC-01,
    2026-10-26). The owner asked on 2026-10-30 to put it back. LICENSE (unchanged
    PolyForm Noncommercial 1.0.0, SHA-256 c0ea4a89...fabbe5), NOTICE,
    ADDITIONAL-PERMISSION.md and THIRD-PARTY-NOTICES.md are restored at the root
    and byte-identical in each of the five packages, with SPDX metadata in every
    pyproject and `scripts/check_licenses.py` in `just check`. The license terms
    are unchanged. THIRD-PARTY-NOTICES.md is updated to the Phase 0 dependency
    set, which no longer includes Polars, NumPy, SciPy or Lark and adds the MCP
    SDK, FastAPI, structlog and certifi (MPL-2.0). Runtime images carry the four
    notice files in /app. See docs/LICENSING_REVIEW.md.

Publishing and opening a PR are authorized in the canonical project. PR #10 holds
the replacement, and the misplaced PR is closed. Canonical CI run 41066156741
passes all nine jobs: checks with PostgreSQL and all eight ARM64/AMD64 image
builds. The recorded evidence identifies its exact head and tested merge commits.

Model provenance limitation: the visible host default is gpt-6-astra/xhigh;
the actual per-turn configuration and requested maximum effort remain unverified.
No stronger configuration or owner acceptance is claimed.

Implementation references: [official MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk),
[Compose services](https://docs.docker.com/reference/compose-file/services/),
[uv workspaces](https://docs.astral.sh/uv/concepts/projects/workspaces/).

# Phase 1 decisions

Phase 1 implements P1.1 to P1.11 only. No factor, strategy, pool entry, research job
or evaluator run exists, and nothing from Phase 2 onward is started.

1. **One implementation of every measurement.** Metrics, fingerprints, PSR, DSR, PBO,
   the reference backtester and the composite live in `qfr_core`. P1.11 asks the
   workbench to use exactly the evaluator's definitions, and Section 5.3 lets both
   zones import core, so a single implementation is the only way to guarantee it.
   The import contracts are unchanged. Tests compare the research workbench with the
   evaluator's path on the full snapshot restricted to W0: the numbers agree to a
   relative 1e-12, the only difference being summation order across a different
   number of instrument columns.
2. **Panel conventions.** Rows are dense from each instrument's first to its last
   observation. A day is suspended when it has no row, no close or zero volume;
   market fields are null on suspended rows and the adjustment factor is carried
   forward. `ret_1d` is measured against the last traded adjusted close.
   `listed_days` counts the instrument's earlier panel rows. `adv20` is the 20-row
   mean of amount with the DSL validity rule (16 valid values).
3. **Limit flags.** The reference price is the last traded adjusted close divided by
   today's factor, which is the exchange's ex-rights reference. Limit prices are
   rounded half-up to the 0.01 tick and compared with half a tick of tolerance.
   STAR (SH688, SH689) is 20%; ChiNext (SZ300, SZ301) is 20% from 2020-08-24 and 10%
   before; other names are 10%. The release has no ST flag, so the 5% ST limit cannot
   be applied and ST names are treated as main board. Every manifest records this.
4. **CN panel scope.** The panel holds every name that was in a configured universe
   (csi300, csi500) at any date, over its whole listed history, with point-in-time
   membership flags. The benchmark is the SH000300 close when the release has it,
   otherwise the equal-weight csi300 return.
5. **Release checksum.** This sandbox cannot reach GitHub release downloads, so the
   investment_data manifest format was not inspected. The reader accepts the common
   shapes (a top-level hash, a name-to-hash map, a list of name and hash entries,
   nested assets) and fails closed otherwise, in which case the owner passes
   `--sha256`. Verification always precedes extraction. Extraction refuses path
   traversal, links, special files and archives over the configured size caps.
6. **Snapshot identity.** The snapshot id is the SHA-256 of the canonical manifest,
   which lists the SHA-256 of every file. Beyond Section 6.3's fields the manifest
   records `files`, `checks`, `research_window` and `parent_snapshot_id`. Parquet
   bytes depend on the Polars writer, so ids are reproducible under one `uv.lock`
   (tested by rebuilding) but not across Polars upgrades. Readers verify every file
   hash and the id before use.
7. **Snapshot locations.** The plan's `QFR_FULL_SNAPSHOT_DIR` and
   `QFR_RESEARCH_SNAPSHOT_DIR` name each zone's directory. Each holds one directory
   per snapshot id and a `current.json` pointer that is replaced atomically. Outside
   Compose they default to `data/snapshots/full` and `data/snapshots/research`, the
   plan's repository layout. The plan gives data-ingest read-write raw storage but
   lists no volume for it, so a `data_raw` named volume, mounted only into
   data-ingest and located by the new `QFR_RAW_DIR`, holds downloads and extractions.
8. **Research zone.** The research snapshot is the full data truncated at the W0 end:
   panel and calendar rows on or before the cutoff, membership intervals clipped at
   the cutoff, and no extra files. Its manifest names the generator only, never the
   synthetic world, seed or ground truth, so research cannot tell planted data from
   null data. BND-06 is checked on the data itself (the latest panel, calendar and
   membership dates) by the writer, by `qfr data verify --zone research` and on
   every workbench open; a test forges a manifest to prove it. Compose tests and
   doctor check that only data-ingest writes snapshots and that research services
   mount only the research snapshot, read-only.
9. **Synthetic timing.** The planted signal of decision day t moves the return from
   close t+1 to close t+2, which is the one-day label under Section 6.5. Section 6.6's
   "z-score at t" is therefore aligned with the label rather than the same-day return.
   Prices follow a latent fair value; traded closes are rounded to the tick and held
   within the limit of the ex-rights reference, so limit-locked names catch up later.
   Corporate actions move the factor, not the adjusted path. Suspensions are
   zero-volume rows. All random numbers are drawn once, and each alpha is calibrated
   by coordinate bisection on a separate calibration seed against the evaluator's own
   RankIC. Tests check the generator's signals against the DSL evaluation of the
   ground-truth expressions to 1e-12.
10. **A3.** The plan gives A3 no target RankIC. It uses 0.03, recorded in
    `configs/data/synthetic_v1.yaml`. "Halfway through W2" is W2's middle trading day.
11. **Synthetic epoch.** epoch_001's dates fall outside the 2,600-weekday synthetic
    calendar (2010-01-04 to 2019-12-20). `configs/epochs/synthetic_001.yaml` defines
    W0 to W3 on that calendar with 20-day embargoes, for tests and benchmarks only.
12. **Details the plan leaves open.** Turnover compares with the previous evaluated
    date, so the first date has none and long-short net returns start on the second.
    Quintiles are equal-count with ties broken by ascending instrument id. The
    Newey–West lag is max(h, floor(4(T/100)^(2/9))). Library correlation is absent,
    not zero, when the library is empty. In the backtester, holdings without a score
    rank lowest, blocked sells are retried the next day on top of the dropout sells,
    blocked buys pass to the next candidate, and the average holding period follows
    Little's law. In the composite a missing component contributes 0; the composite
    is missing only when every component is.
13. **Fingerprint seed in the public card.** Section 8.2 puts the fingerprint seed in
    the protocol, and Section 7.5 says both zones compute fingerprints with the same
    code on W0. The public card therefore carries the fingerprint block (40 dates,
    seed, W0). It reveals nothing after W0. Window dates, holdout rules and acceptance
    thresholds stay out of the card.
14. **Defaults stay in configuration.** PBO takes the protocol's `pbo_blocks`; ingest
    URLs, field lists and size caps live in `configs/data`. The ingest batch size
    (200 names per panel batch) bounds memory and does not affect any result.
15. **data-ingest resources.** Measured in this sandbox (4 vCPU) on a CN-sized fake
    release of 1,800 names over 4,800 days (6.9 million panel rows): a one-pass panel
    build peaked at 3.4 GB. Building per 200-name batch gives identical data (tested)
    and peaks at 1.7 GB, or 2.3 GB including both snapshot writes, in 24 seconds. The
    plan's 1 GB limit for other services cannot hold a CN build, so data-ingest gets
    4 GB, keeping 1 CPU, in Compose and `configs/deployment.yaml`. Limits are caps,
    not reservations. Docker Desktop stays at 7.75 GiB as the owner instructed; real
    use is to be measured on the Mac in Phase 3. The default synthetic build peaks at
    about 0.7 GB in 42 seconds.
16. **Findings left for Phase 3.** None of these change the owner's configuration.
    - epoch_001 embargoes: there are 17 SSE trading days between W0's end
      (2019-12-31) and W1's start (2020-02-04), and 16 between W1's end (2022-12-30)
      and W2's start (2023-02-01), both because of Spring Festival closures. Both
      are below `embargo_trading_days: 20`; W2 to W3 has 23. Epoch activation should
      check embargoes against the real calendar, and the owner decides whether to
      move the W1 and W2 starts.
    - A 250-day window operator takes about 13 seconds on a 6 million row panel in
      this sandbox. With the 120 CPU-second screening limit, expressions that stack
      several long windows may time out; the Phase 3 benchmark on the Mac settles it.
    - The eval_db `data_snapshots` table (Section 16.3) arrives with the eval_db
      domain tables in Phase 3. Phase 1 records snapshots in manifests and pointers.
    - The first real CN ingest confirms the manifest shape and the raw-price check
      (at least 99% of raw closes between 0.5 and 5,000 CNY).
17. **Ignore rule.** Phase 0's `.gitignore` line `data/` also matched
    `packages/qfr_core/src/qfr_core/data`, `configs/data` and `tests/data`. It is now
    anchored to the repository root (`/data/`), as the plan's layout intends.

# Phase 2 decisions

Phase 2 implements P2.1 to P2.6 only: the registry, the pools, raw pool import and the
empty start. No research job, evaluator run, provider call or approval workflow exists,
and nothing from Phase 3 onward is started. It was built on the Phase 1 branch (PR #12),
as the owner asked, and rebased onto `main` after #12 merged.

1. **Ordered sequences.** Every registry write runs in one transaction that first takes
   a transaction-level advisory lock. `published_seq` and `event_seq` are bigserials,
   and without the lock a later number could commit before an earlier one, so a reader
   paging with `since_seq` could skip a row for good. One writer at a time is ample at
   this volume.
2. **Hashes and idempotency.** `content_hash` is the SHA-256 of the manifest's canonical
   JSON (sorted keys, compact) after server fields are removed. `canonical_hash` is the
   DSL canonical hash for factors and the strategy canonical hash (normalized weights)
   for strategies. Publishing content that already exists returns the existing version
   with 200. Each publisher's `publish_key` is single-use: reusing it for different
   content is `PUBLISH_KEY_REUSED` (409).
3. **Server fields (REG-04).** Client copies of server fields are dropped before
   validation and logged as `client_server_fields_ignored`. They are never stored.
4. **Families.** A new name opens a family. A later version of the same name must
   carry the family id; without it, the registry answers `NAME_CONFLICT` (409) and
   returns the family id. Kind, name and program must match the family.
5. **Lineage.** Parent edges store the AST diff (factors) or a strategy diff (component
   added, removed or changed with weights rounded to 0.01, plus portfolio and
   combination changes). A strategy's components are stored as `component` edges.
6. **What publication enforces.** The registry refuses schema, parse and type errors
   and declared-versus-parsed mismatches (400). Complexity and window-set violations
   are recorded in `analysis.static_limit_errors` and not refused, because screening
   (Section 8.4) owns that verdict and a publication is a record. The setup importer
   and `qfr.dsl.validate` reject them like any agent draft.
7. **Approvals without control_db.** registry_db has no access to control_db, where
   approvals live. The pool routes therefore take an approval reference (id, decision
   and scope: pool, version or entry, tier) from the front door. The registry checks
   that the scope covers the version and the requested tier (`APPROVAL_SCOPE_MISMATCH`,
   403) and stores the id; the approval record itself is written by the front door in
   Phase 6.
8. **Seed entries.** A seed entry carries the setup reference instead of an approval.
   Only human_seed versions with no job enter a pool as seeds (`NOT_A_SETUP_IMPORT`).
   Adding the same seed version again returns the existing entry with 200.
9. **Current pool state.** `pool_current_v` takes the status and tier from the latest
   status-bearing event and the tags from the union of all events. Annotations append
   tags; tags are never removed.
10. **Setup imports have no research snapshot.** `provenance.research_snapshot_id` is
    nullable, and only for setup imports (human_seed with no job). An owner's raw-pool
    factor was not developed on a QFR snapshot, and the front door may not read the
    research zone.
11. **Seed manifests.** They are built deterministically from the row: a seed
    hypothesis whose mechanism is the owner's notes (or a fixed sentence when there
    are none), fixed summary and falsification texts, `review.verdict_id` set to the
    DSL_VALIDATED step and `review.rounds` 0, and `trace_ref` set to the seed's
    candidate id.
12. **Re-import is idempotent.** Manifests carry fresh ids, so a rebuilt manifest would
    hash differently. The front door stores each manifest in its DSL_VALIDATED step,
    keyed by the entry digest (the definition without tags), and reuses it on
    re-import. The publish key is `seed:<digest>`. A changed definition under the same
    name becomes the next version of that family, with the earlier seed version as
    parent. The earlier seed entry stays: retiring it needs an approval
    (`qfr.pool.set_status`, Phase 6). New tags on an unchanged row are appended with
    an ANNOTATED event.
13. **Where setup traces live.** The front door cannot write research_db, so the
    human_seed trace steps of Section 14.5 (DSL_VALIDATED and SEEDS_PUBLISHED) are
    stored in a new insert-only control_db table `trace_steps`. The trace export joins
    them by candidate and version id.
14. **Setup state.** The pool step records `importing` (its row id is the setup
    reference on every entry of that import), then `imported` or `failed` with counts,
    or `empty` when the owner has no pool, with the no-defaults notice. `kept` is
    recorded when the owner declines an import but the pools already have entries.
    Phase 2 has no writer for the other steps: `qfr.setup.status` reports providers as
    deferred to Phase 4, data as deferred to Phase 3, and the token as working because
    the call authenticated. `setup_complete` stays false until all four are done.
15. **Refusals.** A whole-request problem (a path outside imports/, a missing,
    oversized, unreadable or empty file, too many entries, or conflicting arguments)
    is an MCP tool error. It is audited as failed, logged as `pool_import_rejected`
    and writes nothing. Invalid rows are reported in a partial result with reason
    codes and logged as `pool_import_entry_rejected`. Symlinks are resolved before
    the imports-folder check.
16. **Summary route.** `GET /v1/summary` (any registry token) gives version, family and
    pool counts for `qfr.status` and `qfr.setup.status`. It is read-only, so BND-09
    still has exactly three mutation routes.
17. **Evaluator fields.** `qfr.pool.list` and `qfr.pool.get` return the evidence tier
    and released state as null until eval-admin-api exists (Phase 3).
18. **`qfr setup`.** It is a small JSON-RPC client of the MCP front door, so the CLI
    and a host agent leave identical records. It reads the owner token from
    `QFR_MCP_TOKEN` or `.env`, accepts `--pool-file` or `--no-pool` for unattended
    runs, and prints the data and token commands rather than running them (data
    builds run a Compose service). It lives in qfr_mcp as a `qfr.commands` plugin; the
    Phase 0 placeholder in qfr_core is removed.
19. **Deployment.** registry-api gets its own image target and listens on 0.0.0.0 only
    inside its container (`QFR_REGISTRY_BIND`), with no host port. Its health check
    passes only when the database is reachable. qfr-mcp waits for registry-api to
    start but not to be healthy, so the front door can still report an unhealthy
    registry. `qfr-registry` now declares uvicorn and `qfr-mcp` declares typer.
20. **Tests keep the databases empty.** Registry and setup tests run inside an outer
    transaction that is rolled back, with a savepoint per write, so the fresh-stack
    check (SET-01) holds in the shared CI database. The REG-01 owner tests use
    `TRUNCATE ... CASCADE` so that the trigger, not the foreign-key check, refuses.
21. **SET-01 scope.** Phase 2 checks that a fresh stack is empty and says so. The rest
    of SET-01 (a job submitted through MCP completes a generation from exploration
    alone, with the library-correlation gate recorded as vacuous, and zero programs)
    needs research jobs (Phase 4) and the evaluator (Phase 3).
