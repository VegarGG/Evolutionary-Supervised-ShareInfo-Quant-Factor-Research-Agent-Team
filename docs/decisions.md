# Plan amendments

1. **v2.2, 2026-10-31: immediate release.** The owner replaced the batched release of
   reports to research (6-hour W1 batches, weekly W2 and advancement batches,
   advancement delayed at least 7 days) with immediate release: every report is
   released as soon as the evaluator records it, and research starts its next
   generation when the previous generation's feedback is complete (or after at most
   6 hours). Coarsening, quotas, the Ladder, the private W3 holdout, the trial ledger
   with DSR and the burn meters are unchanged. Sections changed: 1.2, 1.3, SC5, the
   architecture and workflow figures, 4.4, D11, 7.9, 9.1 to 9.3, 11.1, 11.8, 12.1
   (published provisional members no longer expire), 13.3, 15.3, 16.3, 17.1, 17.4,
   REL-02, P3.5, P6.2, the Phase 3 acceptance check, M1 and the Release and Research
   defaults. The plan is now `docs/QFR-Implementation-Plan-v2.2-EN.html` and
   `docs/PLAN.md`; the SHA-256 under Phase 0 below is that of v2.1. Phase 3 decision
   16 records the implementation.

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
and nothing from Phase 3 onward is started. It is built on the Phase 1 branch (PR #12),
which was not yet merged, as the owner asked.

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

# Phase 3 decisions

Phase 3 implements P3.1 to P3.8 only: eval_db, the scheduler and queue, the eval
worker with screening and W1, the release engine, feedback-api, eval-admin-api,
`qfr eval reproduce` and the daily data-ingest service, plus the MCP tools that reach
them. Strategies are held at intake (their plugin is Phase 6); W2, simulation,
acceptance, approvals, research jobs and providers are not started. It was built on
the Phase 2 branch and rebased onto main once Phases 1 and 2 merged (PRs #12 and #13).
The Phase 3 on-machine test on the Mac Studio is left to the owner, and Docker Desktop
memory is not changed.

1. **eval_db is insert-only where the plan says so.** Official records, the trial
   ledger, metrics, series files, released reports, events, burn history and quota
   usage are protected by REVOKE plus row and TRUNCATE triggers, as in Phase 2.
   Configuration versions may only move draft → active → retired; a guard trigger
   refuses any content change to an active or retired version, and a partial unique
   index keeps one active version per kind. One epoch may be active.
2. **Configuration bootstrap.** On first start, when no protocol, policy or quota
   version is active, the scheduler activates the shipped files (principal
   `eval-scheduler`, no approval id; `bootstrap_configs: true` in `configs/eval.yaml`).
   Later versions are created and activated by the owner through
   `qfr.ops.activate_protocol`, `qfr.ops.activate_policy` and `qfr.ops.activate_quotas`.
   The approval id is optional and stored when given, because the approval workflow is
   Phase 6; every activation is logged and audited.
3. **Which epoch.** The scheduler pins `configs/epochs/${QFR_EPOCH:-epoch_001}.yaml`.
   The protocol's `epoch_ref` is recorded next to the epoch in the activation check
   (`protocol_epoch_ref_matches`), so a synthetic dry run with
   `QFR_EPOCH=synthetic_001` is visible as such rather than silently passing. Switching
   epochs later needs a fresh evaluator database; rollover is Phase 8.
4. **The embargo is enforced, and epoch_001's W1 and W2 start later than the plan's
   defaults.** Activation resolves the windows on the snapshot's own trading calendar
   and refuses with `EMBARGO_TOO_SHORT` (logged as `epoch_activation_refused`) when any
   gap is below `embargo_trading_days` (20). On the SSE calendar the plan's dates
   (W1 from 2020-02-04, W2 from 2023-02-01) leave 17 and 16 trading days because of
   the Spring Festival closures. The owner chose on 2026-10-31 to move the starts to
   2020-02-07 and 2023-02-07, which gives 20, 20 and 23 (checked against the
   exchange_calendars XSHG calendar; `tests/eval/test_epochs.py` keeps the check). The
   window ends, W0 and W3 are unchanged. The file keeps version 1 because no epoch was
   ever activated with the old dates: no evaluator before Phase 3 existed, and Phase 3
   refuses them.
5. **Two job kinds.** A `fingerprint` job computes the 40-date W0 fingerprint that
   behavioral dedup needs; an `evaluate` job screens and, on a pass, runs W1.
   Fingerprint jobs are claimed first. The queue is fair round-robin across families
   (priority = jobs still waiting in the family, then enqueue order), claimed with
   `FOR UPDATE SKIP LOCKED`.
6. **Dedup.** Exact dedup compares the canonical hash with every version already
   admitted in the epoch. Behavioral dedup compares fingerprints with the admitted set
   at similarity ≥ 0.95 and is serialized under the scheduler's advisory lock, so two
   near-duplicates published together cannot both pass. The reason is
   `NEAR_DUPLICATE_OF` with the earlier version id.
7. **Quotas.** A W1 slot is consumed at admission (when the evaluate job is queued),
   in rolling windows: family `w1_count` per `w1_hours`, program `w1_daily` and global
   `w1_daily` per 24 hours, by the evaluator's clock. A version without room is
   `Deferred` (`QUOTA_DEFERRED`, released) and re-tried every tick; after
   `deferral_expiry_days` (7) it is rejected with `QUOTA_EXPIRED`.
8. **Strategies are Held.** A strategy version gets an intake row in state `Held` with
   the hold reason "the strategy plugin arrives in Phase 6", and no job.
9. **Runner limits.** Production computes each factor in a child process. The CPU
   budget is an RLIMIT_CPU soft limit (snapshot load gets `load_cpu_seconds`, then the
   protocol's `cpu_seconds`), with a wall-clock backstop of 3× the budget; a watchdog
   ends the child when its peak RSS passes `memory_gb`. Either way the result is
   `RUNTIME_LIMIT` with the limit named in owner evidence only.
10. **Prefix probe tolerance.** The probe compares values at each seeded cut date with
    a relative tolerance (`prefix_tolerance` 1e-9, scaled by the value's magnitude), so
    rolling-sum rounding cannot be mistaken for lookahead while a one-day peek always
    is (EVL-03).
11. **Degeneracy and coverage.** `DEGENERATE` when more than
    `degenerate_date_fraction_max` (10%) of W1-window dates have fewer than two finite
    values among eligible stocks, or no spread at all; `LOW_COVERAGE` when mean coverage is
    below `coverage_min`. Screening uses only data up to the end of W1.
12. **Screening records.** A screening record carries `window: W1`, its metrics (no
    W1 performance) and its reasons. Screening failures are not trials: the ledger and
    the burn meter count W1 runs only (EVL-06).
13. **Internal errors.** An evaluator exception (not the artifact's fault) is retried
    with backoff up to `max_attempts` (3). After that the version is `ScreenFailed`
    with `INTERNAL_ERROR`, no official W1 record and no trial.
14. **Library values.** Each evaluated version's W1 factor values are stored once as a
    `factor_values` series in the eval store, so the library-correlation check reads
    them back instead of recomputing. The series route of eval-admin-api refuses
    `factor_values` (it is evaluator-internal, and large).
15. **Library membership.** The scheduler follows pool events from the registry. A
    library entry is effective from the version's W1 record time in the epoch, so a
    factor evaluated before a pool admission is not compared with it after the fact.
    Library changes are released immediately (Section 9.2). A pool admission never
    triggers an evaluation.
16. **Release timing.** By the owner's plan change of 2026-10-31 (plan v2.2,
    Section 9.2), every report is released as soon as the evaluator records it; no
    report waits for a batch time. The deciding service queues the report in the same
    transaction as its decision with `due_at` = the decision time, and release-worker
    releases it on its next tick (`release.interval_seconds`, 1 second), writing
    `released_at` = the release time. The release policy says `release_timing:
    immediate` in place of the old `batching` block, so the public policy card tells
    research when it hears back. Release-worker stays the only writer of
    `released_reports`, which keeps rounding and whitelisting in one place and lets a
    library change for a version not yet pulled wait for its intake row. The feedback
    views keep their `released_at <= now()` filter as a guard. Reports due together are
    released in the order they were queued (the UUIDv7 queue id breaks ties), so a
    version's intake precedes its screening and W1 (REL-02). Policy `default/1` is
    edited in place rather than published as `default/2` because Phase 3 is not merged;
    a stack that activated the earlier `default/1` keeps serving the old policy card
    until its evaluation database is recreated.
17. **Rounding.** Released values are rounded half away from zero to the policy step
    in decimal arithmetic (`Decimal(repr(x))`), so 0.0125 at step 0.005 is 0.015, not
    the binary-float 0.01. Negative zero is released as 0.0.
18. **Diagnostic flags.** The thresholds live in the release policy (`flags:`): the
    plan's fixed rules (DECAYS_FAST below 40% of h=1, COST_DOMINATED below 50% of
    gross) and, where the plan gives no number, the W1 gate values (turnover 0.60,
    library correlation 0.70, RankIC 0.02 with NW-t 2.5) and 0.50 for monotonicity.
    The policy refuses to load unless every rule has a threshold.
19. **Policy card.** The public policy card includes the active quota card, and its
    ref is `default/1+quotas:default/1`, so research sees the quotas it is held to.
    Cards never name windows, dates, holdout or acceptance details.
20. **Contract fixes.** `W1Content.decay_profile` keys are the strings "1", "5", "10",
    "20" (`HorizonKey`), because JSON object keys are strings and the released report
    must round-trip through the schema. A released W1 report carries the Section 9.2
    values and no pass or fail; the artifact status route shows `EVALUATED` for it,
    and the W1 gate verdict is owner evidence. `OwnerEvidence` gains `evaluation` (the
    intake state) and `library_correlation`. The schemas are regenerated.
21. **One feedback token.** feedback-api has one reader token for the research zone;
    requests may narrow by program, and per-program tokens wait for Phase 4. It
    connects as `feedback_ro`, which reads five views in the `feedback` schema only.
22. **Owner reads.** eval-admin-api serves summary, intake, runs, records, owner
    evidence, series, burn meters, quota usage (by the evaluator's clock), the library
    and the private configuration. It has no report routes; `qfr.report.list` goes to
    feedback-api like research would.
23. **Data ingest service.** `qfr data serve` runs once per local day after
    `schedule.ingest_local` (18:30 Asia/Shanghai). The CN source reads the latest
    investment_data tag from the `/releases/latest` redirect (no API token) and builds
    only when the tag is new; otherwise it re-checks hourly. Daily builds write the
    full zone only: the research snapshot never changes within an epoch (Section 6.4),
    and evaluation stays pinned to the epoch's snapshot. Full snapshots are retained
    for reproducibility; extracted raw copies are removed and two raw archives kept.
    `--source replay` reveals a synthetic world one day per build (tests), and
    `--source off` (`QFR_INGEST_SOURCE=off`) keeps the service healthy without
    downloading, for a synthetic dry run.
24. **Health and provenance.** Scheduler, worker, release engine and ingest write a
    heartbeat file from a background thread; Compose marks them unhealthy when it is
    older than 180 seconds. `just up` passes the git commit and the eval image id,
    which every official record stores as `code_version` and `image_digest`.
25. **Disk.** Retaining every daily full snapshot grows the data volume by roughly one
    snapshot per trading day. The Phase 7 disk guard owns the limit; until then the
    owner can see the size with `just doctor`.
26. **Tests and locks.** Evaluation tests run in a rolled-back outer transaction like
    Phase 2. Each rig takes the registry write lock before touching eval_db, so
    parallel test workers cannot deadlock across the two databases. Catalog checks
    replace TRUNCATE probes, which would wait on other workers' open transactions.

# Phase 4 decisions

Phase 4 implements P4.1 to P4.12: research_db, the provider layer and probe, the tool
layer, feedback sync, the six agents with versioned prompts, the DSL card, the packager,
the generation state machine, the budget ledger, research jobs with the job monitor and
research-api, the MCP job, deliverable and trace tools with resources and prompts, and
scripted offline scenarios. The evolution engine (Phase 5), approvals and
`qfr.job.close` (Phase 6) and the host-agent guide (P7.5) are not started. It is built
on the Phase 3 branch (PR #14), which was not yet merged. Nothing here has reached a
real provider: the one real generation per provider is the owner's on-machine step.

1. **Phase 4 generations explore only.** Without the evolution engine the proposal is
   the empty-start rule of Section 12.1 every generation: explore slots spread evenly
   over the brief's islands, plus at most the charter's `compose_strategy` tasks in the
   strategy modes. An invalid supervisor plan gets one repair attempt, then the
   proposal's default. A mutation, crossover or repair task is skipped with
   `PHASE_5_OPERATOR`. Selection ranks pre-screen survivors by W0 sign-adjusted RankIC
   IR, then originality, round-robin across islands, until Phase 5's provisional
   fitness.
2. **Research reads the tier; the front door confirms it.** The monitor reads each
   version's tier from its released reports with the public gates of the active
   protocol card, because released W1 reports carry values and no pass or fail
   (Phase 3 decision 20). Released values are rounded, so near a gate this reading can
   differ from the evaluator's decision. `qfr.deliverable.get` therefore adds
   `tier_confirmation` per item from eval-admin-api (`research_tier`,
   `official_evidence_tier`, `confirmed`), and the `qfr.report_deliverable` prompt
   tells the host agent to report a mismatch.
3. **No new LLM work after the criteria are met.** When the monitor finds the
   deliverable criteria met during a generation's SYNCING, the generation stops
   (`criteria_met`) and goes straight to selection and publishing: candidates already
   approved are still published, but no new plan, hypothesis or draft is paid for.
4. **Stops and closing.** A generation cap or job cost cap stops research
   (`research_stopped`, `next_generation_at` cleared) and moves a RUNNING job to
   WAITING_FOR_EVALUATION; evaluation of what was published continues. When nothing is
   pending and nothing reached the tier, the job closes as `budget_exhausted`; at the
   wall-clock deadline it closes as `expired`. Either close assembles a `best_effort`
   deliverable from the best readings so far when anything was published. A
   `best_effort` item may have no tier yet, so `DeliverableItem.tier_reached` is
   nullable (schema regenerated).
5. **Delivery and closing are separate.** `qfr.deliverable.get` marks the deliverable
   fetched and the job DELIVERED. The `qfr://deliverables/{id}` resource reads the same
   composition without marking it. Closing a delivered job as approved or rejected is
   `qfr.job.close` with an approval record, which the plan puts in Phase 6 (P6.7); until
   then a delivered job stays DELIVERED and spends nothing.
6. **The owner-only scan (MCP-03, submit and steer).** The front door compares every
   decimal number with at least two decimals in a brief or steering note with every
   non-integral owner value of the referenced versions (seed versions, seed pool
   entries' versions, and for a steer every version of the job): at full precision
   written to the text's own decimals, and at the release step of the metric's class.
   Keys that hold public or non-measurement numbers (`threshold`, `version`,
   `protocol_version`, `seed`, `step`) are skipped, zero never matches, and signs are
   ignored. A match rejects the text with `OWNER_ONLY_VALUE`, names the versions and
   never the value, and logs `owner_only_scan_rejected` without the number. Only the
   verdict reaches research, which refuses a brief whose scan does not cover every seed
   version (`SCAN_INCOMPLETE`). The rule can reject an unrelated number that happens to
   equal an owner value at two decimals; the owner then rephrases. The approval half of
   MCP-03 is Phase 6.
7. **Active cards first.** research-worker, the monitor and the MCP resources read the
   active protocol and policy cards from feedback-api, and fall back to the bundled
   preview cards only when feedback-api does not answer or has no active card. The
   resources label which one they serve (`active` or `preview_not_activated`).
8. **Cadence (plan v2.2).** Reports are released as soon as the evaluator records them,
   so the next generation starts as soon as the previous generation's feedback is
   complete (`cadence.after_feedback_complete`), and at the latest `max_wait_hours` (6)
   after it closed. A version counts as answered once its intake is refused or deferred
   (a quota deferral is an answer), its screening fails, or its W1 report is released.
   The seeds are generation 0: with seeds the first generation waits for their
   feedback in the same way; without seeds, or after a generation that published
   nothing, the next one starts at once. After a FAILED generation the next one waits
   the full `max_wait_hours`, so a provider outage cannot use up the generation cap in
   minutes. The monitor reads each waiting version's reports from feedback-api by
   version id without moving the program's sync cursor, so the next generation's sync
   still interprets them. This replaces the earlier rule (six hours, then just after
   the next W1 release batch, or ten new reports).
9. **One generation at a time.** One research-worker runs one generation at a time and
   a program never has two open generations. Tasks inside a generation run with the
   charter's concurrency (4). A queue job that fails is retried after 60, then 300
   seconds; the third failure marks the generation FAILED (it counts toward the cap) and
   the job schedules the next one. A worker that dies leaves its lease; after
   `lease_seconds` (3600) the generation returns to the queue and resumes from its last
   persisted state.
10. **Budgets.** Every agent run is admitted against the smallest remaining cap (job,
    daily, program daily, generation) before it is sent, using the whole prompt at the
    miss rate plus the full output budget, and a token limit that leaves room for one
    more request at the dearest rate. A refused call stops the generation with
    `budget_<scope>`; nothing is ever sent over a cap. The daily cap defers the job to
    the next UTC day instead of stopping it. Probe calls are recorded in the ledger
    under the role `probe`; the probe at job start counts toward that job's cost, the
    setup and daily probes toward no job.
11. **Provider layer.** Models are PydanticAI's `OpenAIChatModel` with
    `DeepSeekProvider` and `MoonshotAIProvider`, and `ZaiModel` with `ZaiProvider`
    (pydantic-ai 2.63). The library supplies each provider's thinking control and
    reasoning pass-back; QFR passes `max_tokens`, the timeout and `thinking` (the
    model's effort on strong models, off or the lowest effort on fast ones) and a
    temperature only when the model does not think. `supports_forced_tool_choice` is
    off for all three in providers.yaml, so output tools use `tool_choice: auto`.
    Structured output tries the output tool, then after two validation failures a
    prompted `json_object` run. The OpenAI SDK's own retries are off; QFR retries with
    its backoff, then falls back along the role's chain. The critic's chain excludes the
    provider that drafted the candidate. `tests/research/test_providers.py` records the
    request body each configured model receives over a mock transport.
12. **Model ids and prices are the owner's to set.** The shipped providers.yaml names
    the plan's model ids and has no prices, so no model may run until the owner fills
    them in from each provider's console. `qfr llm probe` (`just llm-probe`) then checks
    that each model is listed, priced, accepts the tool and `json_object` requests with
    its thinking setting, and on Moonshot that the configured account concurrency covers
    `request.concurrency` (4) and the balance is positive. The probe runs at setup,
    daily at 00:30 UTC and before a job's first generation.
13. **Prompts in the image.** The research image target copies `prompts/` and sets
    `QFR_PROMPTS_DIR`; prompt ids and hashes go into every agent run and trace step.
    The DSL card is generated from the operator registry and the protocol's DSL limits,
    and its hash is recorded in each engineer step.
14. **Network and credentials.** research-api is on research_net and control_net (as in
    the Phase 0 Compose file) so qfr-mcp can reach it; it checks
    `RESEARCH_CONTROL_TOKEN` on every route but `/healthz`, holds the registry
    publisher token (seed publication) and the feedback reader token, and no evaluation,
    registry control or owner token. control_net also carries eval-admin-api, which
    research-api could open a connection to but holds no token for (BND-05 checks the
    configuration and the code). research-worker is on research_net and
    research_egress_net, holds the provider keys (BND-07) and no control token.
15. **Health.** research-api's Compose healthcheck reads `/healthz`; research-worker
    touches `/tmp/heartbeat` from a background thread, like the Phase 3 services, and is
    unhealthy when the file is older than 180 seconds.
16. **Logging.** `sensitive_field_pattern` now matches `token` only as a whole word part
    (`api_key`, `_token`, `token_`), so token counts such as `tokens_in` stay readable
    while credential fields stay redacted. Services take credential values from the
    environment by name (`env_secrets`), skipping purely numeric values, which are
    settings such as a token-count limit and would otherwise be redacted inside
    timestamps. Every Phase 3 service now binds the job id where it knows one, so one
    job id joins qfr-mcp, research, registry and evaluation log lines (LOG-03).
17. **Scripted scenarios.** Tests answer every role with PydanticAI `FunctionModel`s
    built from the prompt text (`tests/research/scripted.py`), and the test session sets
    `ALLOW_MODEL_REQUESTS = False`. The provider request-shape test lifts that switch
    only around a mock HTTP transport. The expressions the scripted engineer drafts are
    chosen by each test; the product ships none.
18. **Deferred.** The `qfr://docs/host-agent-guide` resource arrives with the guide in P7.5.
    Per-program feedback tokens (Phase 3 decision 21) are not added: both research
    services are one trust zone, and requests narrow by program.

# Phase 5 decisions

Phase 5 implements P5.1 to P5.8: the population and its refresh, official and
provisional fitness, the MAP-Elites archive, parent selection, the variation operators,
the context assembler, the publication pre-screen and selection, the Thompson-sampling
allocator with stagnation, migration and the diversity guardrail, and the BM-PLANTED and
BM-NULL benchmarks. Approvals, `qfr.job.close` and the promotion workflow (Phase 6) are
not started. It is built on the Phase 4 branch (PR #15), which is stacked on the Phase 3
branch (PR #14); neither was merged. Nothing here has reached a real provider.

1. **Provisional members are published versions without a released W1 report.**
   Section 12.1 (v2.2) defines a provisional member as "an approved but unpublished
   candidate with W0 statistics" and lets an unpublished one live 3 generations, but
   task parents, lineage edges and the iteration history all name versions, so an
   unpublished candidate cannot be a parent without publishing it. The population
   therefore holds published versions: a version joins its island as provisional with
   its W0 metrics and provisional fitness, does not expire while it waits for
   evaluation (a quota deferral included), becomes official when its first W1 report is
   released, and leaves the population (archived) when it is rejected at intake or its
   screening fails. A failed screening sets fitness 0 and makes it a repair target; a
   quota expiry is not a judgement, so it counts as neither a failure nor a repair
   target. Approved candidates that selection did not publish are not members (the
   owner has been asked to confirm this). A provisional member parents at most 1 child
   per generation (engine and plan validator). The population holds factors only:
   strategies compose factors and are not members.
2. **Population start.** The population is initialized once per program: pool entries
   named in the brief (all entries in the improve modes) and a parent job's members as
   official members in the island matching their tags (else I6), the brief's
   human_seed versions as provisional members. Their reports are fetched by version id,
   like seed reports, because they were published outside the program. With no pool and
   no seeds the population is empty and generation 1 is all explore (SET-01). A program
   started before migration 0003 adopts its publications at its next refresh.
3. **Fitness details.** pct is the mid-rank percentile in (0, 1), so ties share the
   middle of their ranks and a lone official member scores 0.5 on every term. RankIC_IR
   is multiplied by the declared sign. Ties are broken by originality, then lower
   complexity, then version id, so every ordering is deterministic. Provisional fitness
   ranks this generation's pre-screen survivors among themselves (per island once an
   island has 5), and its library term uses the maximum behavioral similarity to the
   factor pool, research's view of the library, which is neutral (0.5) with an empty
   pool. The W2 multipliers apply when a W2 status is released.
4. **Fitness is relative, so improvement is measured on a record.** Official fitness is
   recomputed from percentiles each generation, so a member's fitness falls when better
   members join. Each island keeps its best fitness so far and the generation it last
   improved (migration 0003). Stagnation counts generations since that record improved.
   BM-PLANTED's "best island fitness improves" compares the best record across islands
   in the first and the last generation; the current best is recorded beside it.
5. **Archive.** The 64 cells are rebuilt each generation from the current official
   members, because fitness is relative. A cell's elite must have a positive fitness, so
   a failed or sign-mismatched factor never holds a cell. The horizon descriptor is the
   best decay horizon for the declared sign. The field group is volume_only for
   volume-type fields alone (volume, amount, adv20), price_volume when price and volume
   fields mix, range_volatility for a price-only expression with a dispersion operator
   or both range fields, and price_only otherwise. These lists are charter settings.
   When an island exceeds 60 live members, its lowest-ranked official members are
   archived (CAPACITY).
6. **Bandit.** A published child counts once in its island's arm, at the first refresh
   that sees its W1 report (or a failed screening, which is a failure): it succeeds when
   its official fitness is at or above the island's 75th percentile, interpolated
   linearly, at that refresh. `bandit_outcomes` is insert-only with one row per child, so
   a child is never counted twice and every update names its report. Both counts decay
   towards the prior by 0.95 once per generation. Slots are split in proportion to the
   sampled values with a floor of 1 per active island and a cap of 40%. The cap is never
   below the even share, so it cannot leave slots unused. When the quota is smaller
   than the number of islands, the islands with the highest samples get the floor.
   Each publication slot gives 3 candidate slots (36 for 12, the charter's
   candidate_slots_max).
7. **Selection.** A tournament draws 3 of the island's top 10 without replacement, and
   the best entrant wins. The archive side takes a uniformly random occupied cell. When
   one side is empty the other is used, and a slot without any parent becomes an
   explore slot. A crossover partner comes from another island's members or an archive
   cell with behavioral similarity at most 0.5 to the first parent. Without one, the
   slot becomes an llm_mutation of the first parent (`NO_PARTNER`). A syntactic mutation
   that cannot be made, or a repair slot without a target, also becomes explore. Every
   draw has a seed derived from the program, the generation, the purpose and the island
   (`derive_seed`), and the seed and the choice are in PROPOSAL_EMITTED.
8. **Operators.** llm_mutation gives the engineer the targeted instruction for each
   released flag of the parent (Section 12.4; the texts are charter settings) or a
   generic instruction when there is none. Syntactic mutants arrive as ready-made
   variants in `syntactic_batch` tasks of at most 3. They get an automatic change
   summary and inherit the parent's rationale, and the critic does not review them:
   Section 14.5 lists no LLM steps for them. When the remaining budget cannot pay for the
   generation's LLM tasks, a crossover becomes a deterministic subtree exchange
   (`LOW_LLM_BUDGET`). Repair targets are program versions whose screening failed for
   LOW_COVERAGE or DEGENERATE, whose hypothesis is open or supported ("promising"), and
   that no repair task has taken; the repair instructions are a new prompt,
   `prompts/repair.md`. Every application is a MUTATION_APPLIED, CROSSOVER_APPLIED or
   SYNTACTIC_MUTATION_APPLIED step with each parent's expression and the AST diff from
   each. A child of a version this program published joins that version's family (the
   first parent's for a crossover), so its trials count in that family. A child of a
   version published elsewhere starts a new family.
9. **Stagnation and pauses.** For a stagnant island, the plan must either give it at
   least 2 explore tasks or pause it, and the validator refuses a plan that does
   neither. The engine's default plan reseeds when the island has enough slots for 2
   explore tasks, and pauses it otherwise. A paused island stays paused for the rest of
   the program.
10. **Context assembler.** The engineer's context holds the parents' manifests and
    released report digests, the island's top 3 elites, 2 archive elites from cells
    unlike those elites, knowledge items, seed entries and the last 12 things the
    lineage tried, each oldest first so the prompt budget trims the oldest first. Only
    research-visible material enters: manifests and released, rounded reports. The
    engineer prompt is engineer/2.
11. **Status changes record their reason.** An archived member whose archive reason
    changes is a status change in the trace, like a move between statuses. Migration adds the migrants to the members already in
    memory. Reloading them, as the first version did, dropped the status changes made
    earlier in the same refresh.
12. **W0 numbers are cached per process.** `workbench.evaluate` and the engine's W0
    refresh share a cache of factor reports by canonical expression and sign, bounded at
    2048 entries. The research snapshot is immutable for a process, so cached numbers
    are the numbers the workbench would compute again.
13. **Iteration history before and after.** A hop's `expression_before` is the published
    expression of each parent, as the registry has it, so it matches the parent's own
    hop. The AST diff comes from the operator's APPLIED step. `qfr.trace.export` (Section
    13 lists it for Phases 4 and 7) writes trace.json and iteration_history.md under
    `QFR_EXPORTS_DIR` and joins owner-grade records from eval-admin-api into its copy
    only, labelled owner_only; the trace_hash is computed without them.
14. **TRC-03 scripts only the parent choice.** The unscripted engine reaches lineages of
    3 to 4 generations within the BM-PLANTED run, so a five-generation lineage with a
    crossover is not guaranteed there. `tests/research/test_lineage.py` scripts the
    engine's parent choice (one subclass method) so the lineage is known in advance and
    runs everything else on the production path. BM-PLANTED checks the same properties
    (parents, AST diffs, every hop of every published version's DAG) on the lineages
    the engine produces.
15. **Benchmarks.** BM-PLANTED and BM-NULL run the whole offline stack (MCP front door,
    research, evaluator) with a scripted LLM: the supervisor returns the proposal's
    tasks, and the engineer drafts from a fixed 300-expression test pool (planted A1 and
    A2 forms with their windows, and noise forms). Like an engineer with tools, it checks
    its options with `workbench.evaluate` and `similarity.search` and drafts the
    strongest in-sample options that are not near duplicates. The pool is test data,
    not a product default. The scripted answers come from the benchmark's seed, and
    `fix_engine_seeds` puts the same seed in place of the fresh program id in the
    engine's seeds, so both run with fixed seeds as Section 18.3 asks. A discovery is a
    published version that passes W1 with mean W0 rank correlation of at least 0.7 to A1
    or A2. Results are JSON files, kept as an artifact by the nightly workflow
    (`.github/workflows/benchmarks.yml`). BM-NULL's W1 pass rate is recorded but not
    gated: zero acceptances on the null world is a Phase 6 check.
16. **Benchmarks are not in the default run.** `pytest` deselects the `benchmark` marker,
    so `just test` and CI stay fast. `just bench` runs both against the disposable test
    database (or CI's), and `scripts/test_database.py` now passes extra arguments to
    pytest.
17. **Immediate release and the benchmark clock (plan v2.2).** Research gets each
    report as soon as the evaluator records it. Nothing in the engine depends on release
    times: stagnation, migration and forgetting count generations, and reports are read
    from report_cache by release time and id. The benchmark harness runs the job on the
    v2.2 cadence: a generation starts when the previous one's feedback is complete (or
    after the max wait), and the reports are released at once. Because the test clock
    only moves when the harness moves it, the harness advances it 1 hour per generation
    to stand for the time a generation and its evaluation take; the 24-hour quotas then
    see a realistic pace. After the generation cap it steps 6 hours at a time, so
    versions deferred by their family quota are evaluated and the job closes. Both
    steps are recorded with the results (`clock_hours`).
