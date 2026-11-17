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


## Quant Factor Harness decisions — 12 November 2026

1. The owner-approved harness plan in `docs/harness/PLAN.md` supersedes pending
   feature development. Retain the repository, license, original plans, branches
   and deployment evidence. Close previous PRs 14–19 without merging them.
2. Use DSH SDK/plugin extension points for sessions, actual inference and the
   frontend. Do not fork its agent loop or wrap the entire QFR orchestration stack.
   Keep official evaluation independent and preserve the existing research boundary.
3. Keep the cumulative 200 CNY DeepSeek-only budget and 56.256735 CNY carry-forward.
   Admit each provider request atomically at the wire, including retries; retain
   unknown reservations. Use the owner's Beijing windows and start sequentially.
4. Compare mechanisms on equal combined evidence and requested aggregate output
   allowance; disclose unequal call counts and actual compute. The first one-case
   pilot does not demonstrate collaboration benefit or satisfy the core gate.
5. Build iFind and RQData together, with credentials entered through DSH. After the
   owner's free-source request, select anonymous BaoStock for daily testing. Pin a
   single source per session, keep per-provider quotas and never fallback silently.
6. Preserve both failed guarded BaoStock attempts. Fix the observed SDK newline
   parsing edge in a scoped bounded transport; prove it offline and then retest
   once. Each manual free-source allowance revision leaves the paid caps unchanged.
7. Setup UI and research chat are distinct delivery states: the former is tested;
   live interactive chat through the shared budget guard is not delivered yet.
   RQData report/news seams are implemented but entitlement/live checks and full
   PDF extraction remain pending. Do not label tool schemas as completed research.
8. Archive actual old deployment measurements and scientific failures separately
   from new prototype results. Process RSS on this Mac is not production VM sizing.


## MIT license transition — 12 November 2026

The owner directed: "Since DSH is using MIT license, and I don't want to violate
anything or take any risk, let's change the license to MIT as well."
This supersedes the earlier PolyForm/custom-permission choice for project-owned
code from this revision. Use the standard MIT text with copyright 2026 Ziwei
Huang across the workspace, all five Python packages, harness and DSH plugin.
Remove the obsolete additional permission and commercial-use restrictions.
Retain DeepSeek's own copyright and full MIT permission notice, other dependency
licenses, and vendor-data terms. MIT does not require matching downstream
licenses; this transition is the owner's affirmative licensing choice. Earlier
commit/review records remain historical. See LICENSING_REVIEW.md for the exact
source, scope and distribution verification.

## Interactive research and billing clarification — 12 November 2026

The owner directed: "Please proceed with the integration and make DSH ready for
me to test." The concrete live scope is: "Run one real trial with a supervisor
and two workers using DeepSeek and BaoStock, keep the original 200 CNY budget and
time windows, and record everything."

Use native DSH subagent sessions and Agent Teams tasks behind a small bounded
research-worker tool. Keep the original ledger, one-provider data policy and
independent evaluator boundary. Allow at most three small interactive sessions
(one validation plus two owner trials), 20 model requests per trial and one new
12-calendar-day BaoStock query. Exact repeats reuse the same evidence. Preserve
all previous failed data attempts and old model traces. Do not infer acceptance
of the full Hybrid v1 system from this trial.

The owner clarified: "Let me clarify the actual deepseek cost, the data is from
the official api usage record, CNY 20.35." Record this as an owner-reported
official cumulative billing baseline at the then-current 908 recorded calls.
Preserve raw call counts and conservative historical estimates; reserve/estimate
new requests separately. Do not reset or enlarge the original 200 CNY budget.

The owner identified the experimental "Agent teams" interface and requested
different model/provider choices for different roles, plus limited market data
and news for researchers. Review the pinned native Team/subagent implementation
and stage these modules in `docs/harness/ROLE_MODELS_AND_CONTEXT.md`. Additional
provider designs do not authorize additional live providers in this trial.

## 2026-11-12: per-agent evidence for the scheduled real trial

Owner: "Proceed with the real DeepSeek/BaoStock trial at 18:00 Beijing. Report each
agent’s actual work, cost, TPM/RPM, cache hit rate and machine usage, and tell me
whether DSH is ready for my own trials."

Keep the existing one-time continuation and all budget/data/time limits. Extend
the export with measured per-role request/token totals, weighted cache hits,
rolling rates, observed operations and contribution decisions. Because native DSH
agents share a process, report shared CPU/RAM during activity windows and the
sampling coverage; do not label these isolated per-agent allocations. Record wire
and native-session file sizes separately.

Price measured tokens using a dated official tariff for reporting while preserving
the conservative ledger debit. Two read-only account-balance observations may
compare the account-level change before/after the trial; keep absolute balances
private, count those requests separately, and never use them as an automatic
billing reconciliation. Readiness remains pending the actual three-role desktop
trial, settled accounting and retained evidence. Synthetic tests do not establish it.

## 2026-11-12: Flash-only trial clarification

Owner: "One thing I forget to emphasize: we use deepseek-flash only."

The supervisor, researcher and reviewer must all use the exact `deepseek-flash`
model ID. The current role policy and running guard already enforce this; preserve
their existing ledger and reject any other model ID before provider dispatch.
Make this restriction explicit in the scheduled continuation and trial docs.
The 18:00 Beijing start, BaoStock scope and original 200 CNY total cap are unchanged.

## 2026-11-12: real Flash/BaoStock result and boundary repair

The authorized scheduled round dispatched at 18:01:22 Beijing. Seven actual Flash
requests and one BaoStock query/login completed. A single JSON code fence caused
the researcher's report to fail validation; the supervisor stopped, so the reviewer
and draft never ran. Preserve that failed state and all usage. Do not use an offline
format recheck to retroactively accept it or start a second paid trial automatically.

Accept one entire JSON/unlabelled fence as presentation, with unchanged contents,
size/schema/citation checks and raw-result retention. Submit worker settlement only
once; failed/uncertain settlement is not grounds for a replacement write. Include
completed worker-operation counts in failure messages so the supervisor can report
actual work. Verify those changes in unit tests and native synthetic success/failure
flows. Independent arithmetic found additional incorrect model calculations and
an unsupported preregistration claim; JSON validity does not resolve those issues.

The round's tariff estimate is 0.04310952 CNY, conservative debit 0.115572 CNY,
remaining original budget 179.534428 CNY. Both account observations showed zero
displayed delta, which does not prove free usage or verify actual invoiced cost.
Keep the ledger unchanged by those observations. Readiness remains unaccepted
pending a real complete three-role run; the UI is available to inspect the trace.

## 2026-11-12: owner-authorized arithmetic repair and real rerun

Owner: "Please fix the remaining arithmetic and reporting issues, then rerun the
full supervisor plus two-worker trial using deepseek-flash only and BaoStock.
Keep the original 200 CNY budget and time windows, and record everything."

Implement deterministic development-sample return statistics and explicit
lookback/execution/label alignment. New workers cite measurement IDs and fact
keys observed through their own tool calls; the host supplies numerical values
and attaches both workers' facts to the draft. Keep prose qualitative and formula
parameters separate. Add host audit summaries and label all proposals as
post-observation exploration. Preserve the previous failed trial and all charges.

The rerun uses the same bounded real BaoStock evidence through exact-cache reuse,
the existing three-session allowance and 179.534428 CNY remaining before new calls.
No data quota, model route, time window or total spending cap is enlarged. The
current 18:00–24:00 Beijing window permits execution after offline verification.
See `MEASUREMENT_CONTRACT.md` for the contract and its scientific limits.

The first rerun attempt at 21:15 Beijing reached both actual workers. The researcher
passed; the reviewer's nine findings violated the unchanged eight-item limit.
All sixteen Flash calls settled; no draft was accepted. Preserve its 0.359878 CNY
conservative debit and frozen evidence. Before the next attempt, the accounted total
is 20.825450 CNY, leaving 179.174550 CNY of the original budget.

Use `submitted-reports-v3`: each active worker submits its own report through a
validated tool before ending. Return field-level rejection diagnostics; permit
correction only in that same active native turn and existing six-call role allowance.
Freeze accepted reports in append-only events and require normal native completion.
Do not silently truncate oversized lists or replay completed/failed workers. Block
further research tools after a final worker failure, apart from status and settlement.
Keep native final chat brief; only host-validated reports/facts constitute the record.
The third and final configured pilot slot is used for the fresh full rerun after
offline validation. No automatic extension or reset of the three-trial cap is allowed.

## 2026-11-12: full real rerun completed, with separate quality audit

The frozen `69053ae` source completed the full round at 21:29:22–21:31:49 Beijing.
Sixteen actual Flash calls settled: seven supervisor, four researcher and five
reviewer. The reviewer corrected the same nine-findings error through the new
submission tool inside its active turn. Both workers and native tasks completed;
one immutable draft contains twenty-eight host-resolved fact references. All three
data reads reused the real BaoStock cache; no new vendor query or quota expansion.

Keep workflow and scientific acceptance separate. Independent exact-rational
checks verified all forty-four calculator facts and alignment, with seventy-seven
frozen-file hashes verified. The draft still overstates label overlap and the
meaning of non-significance, and leaves an incomplete executable specification.
Those issues are append-only audit findings; do not rewrite the model draft or
claim an evaluator/backtest/alpha pass. See `LIVE_RERUN_2026-11-12.md`.

The final round's published-tariff estimate is 0.11078532 CNY; its conservative
debit is 0.427794 CNY. Accounted cumulative spending is 21.253244 CNY, leaving
178.746756 CNY under the original total. There are no unsettled reservations.
Account observations are not reconciled invoices. All three pilot sessions are
now used; no fourth run or automatic allowance increase was made. The tested
desktop remains available for history inspection. Further paid trials require a
deliberate allowance amendment preserving the existing ledger and original bounds.

## 2026-11-12: owner-authorized statistical repairs and pilot extension

Owner: "Please fix the remaining statistical and specification issues, extend the
pilot allowance, and rerun the full trial using DeepSeek-flash only and BaoStock.
Keep the original 200 CNY budget and time windows, and record everything."

Implement `executable-contrast-v4`: each worker executes one fully specified
development contrast against its own permitted evidence. The reviewer must
independently execute the selected definition; the host renders draft parameters,
timings and inference. Calculate positive label overlap separately from touching
endpoints. Report insufficient/inconclusive states without claiming independence,
confirmation or absence of effect. Fixed inference protocol, sample floors and
bootstrap semantics remain operator configuration. Ten live rows cannot satisfy
the floors. This is a bounded contrast, not a strategy or official evaluator.

135 offline tests and native synthetic DSH workflow checks pass. Record one
operator-only immutable amendment from three to six cumulative pilot sessions:
one repair verification and two small owner trials. Before/after logical hashes
prove unchanged budget/data tables and preserved original research policy/history;
exactly one event was appended. No model call or data quota is enlarged. Accounted
spending before the fresh trial remains 21.253244 CNY, leaving 178.746756 CNY.
Use Flash only and the existing real BaoStock cache in the current permitted
window. The new live result must be recorded separately; earlier drafts, failures
and charges remain unchanged. See `STATISTICAL_SPECIFICATION.md`.

## 2026-11-12: full specification-repair trial passed

Frozen clean source `ef71f3f` completed at 22:49:31–22:51:15 Beijing. Each real
Flash role made five calls; all fifteen settled. Both workers independently fetched
the same cached BaoStock evidence, computed metrics, executed the exact concrete
contrast and submitted accepted reports. Both Team tasks and the immutable draft
completed, with no report rejection, retry or new vendor query. Independent checks
verified seventy-three frozen files, forty-four facts per calculation, seventeen
draft references, seven aligned cases, five signal/two control cases and zero
positive label overlap. The outcome is insufficient_data with no bootstrap run.

The three prior blockers are resolved in this run. Retain a new qualitative audit
caveat: the researcher speculates about a larger-sample interval based on observed
dispersion, which the available evidence cannot justify, and the reviewer does not
challenge it. Exclude that speculation from verified conclusions; do not rewrite
the immutable report or claim all prose is scientifically validated.

Tariff estimate: 0.08414564 CNY; conservative debit: 0.354946 CNY. Accounted total:
21.608190 CNY; remaining original allowance: 178.391810 CNY. All seventy-eight
harness calls are settled. Two balance observations show 0.02 CNY account decline,
not a reconciled invoice; no billing baseline change. Four of six pilot sessions
are now used, leaving two bounded owner trials. Desktop completion/reload/Team
checks pass; mobile clipping remains. See `LIVE_SPECIFICATION_TRIAL_2026-11-12.md`
for per-agent work, costs, rates, cache and shared-machine observations. Keep the
server available for owner trials under the existing time/model/data guards.

## 2026-11-13: owner-authorized gradual sample expansion

Owner: "Please gradually expand the BaoStock sample and rerun the supervisor plus
two-worker trial with enough data for statistical inference. Keep DeepSeek-flash
only, the original 200 CNY budget and time windows, and record everything."

Keep the same stock/cutoff and freeze the previous concrete candidate before new
downloads. Add adjacent older chunks one at a time, each at most sixty-one calendar
days. Stop solely at the predeclared quality/support target: at least one hundred
aligned cases, forty per group and twenty complete blocks. Do not inspect effects
or intervals to decide whether to enlarge the sample. The maximum prepared scope
is March through October; smaller planned stages precede it. Only BaoStock quotas
increase for those explicit queries; paid sources and all model/budget/time limits
remain unchanged. Reuse the original ledger and remaining two pilot slots.

Compose immutable evidence with source lineage, preserve full calculations behind
bounded model views, and activate the new scope through an operator-only append-only
event. Old trials keep their original scopes. Expanded drafts say next observation
close rather than assuming verified trading-calendar completeness. The first
146 tests and a larger native synthetic team trial pass; no new paid inference has
run. The noon Beijing window is the next admission opportunity. See
`SAMPLE_EXPANSION_2026-11-13.md` for the fixed design and recording rubric.

## 2026-11-13 — GLM Coding Plan Pro replaces the noon trial

The owner authorized GLM, specified GLM 5.3 Flash before any evidence-backed
upgrade to GLM 5.3, confirmed DSH eligibility with Zhipu, and then directed:
"I propose to use GLM replace the scheduled work. Before Beijing Time today 18:00,
we use GLM to test and polish the QRH first." The owner identified the plan as Pro.
The noon DeepSeek run is therefore superseded. No new automation or model request
had been dispatched for that run. DeepSeek retains its prior time windows later.

Add an owner-only local DSH credential form and an operator-only append-only GLM
route activation. Freeze the selected route in each new trial; never rewrite old
DeepSeek trials or the original research policy. Use the existing DSH Messages
transport and native Team lifecycle through the local guard. No new model loop,
automatic provider fallback, credential environment fallback or live evaluator
access is introduced. The exact allowed model is `glm-5.3-flash`; expiry is
18:00 Beijing on 13 November. Preserve the original session allowance.

Retain the shared original cash reservations even for subscription calls; these
are conservative exposure debits, not claimed incremental subscription bills.
Separately cap this initial GLM package at 24 requests and 1,500 prepaid credits,
with one request at a time and retained reservations for unknown usage. Start
with two small transport probes, then one native team trial. Report missing cache
counters as unreported, not zero. The owner enters the key only in DSH.

The real BaoStock expansion stopped at its first qualifying stage: 121 rows,
118 aligned cases, 59 per bucket and 23 complete five-case blocks. Only afterward
did the independent bootstrap audit reproduce the primary result: inconclusive.
Longer-block sensitivities and all source/query limitations are retained; there
was no effect-based enlargement or candidate tuning.

155 offline tests and the final native synthetic GLM team run pass. Browser
dummy-key save/reload/remove checks pass; known native mobile clipping remains.
Real GLM access is pending owner credential entry. See
`docs/harness/GLM_CODING_PLAN_2026-11-13.md` for authority, controls and the rubric.


## 2026-11-13 — Use native Models and zai-coding-cn with guard extensions

The owner identified the working native Coding Plan provider and requested guard
extensions in DSH's Models page. Replace the temporary custom model form and
Messages route with native pi-ai `zai-coding-cn`; retain native Agent Teams and
subagents. Use the documented Models footer and host configuration/request-header
extension points, with the existing relay as the atomic budget boundary.

The first HTTP 401 remains a reviewed authentication rejection with its full cash
and credit reservations. A separately bounded repair attempt is allowed only after
operator review; it does not zero charges, reset request counts or increase the
200 CNY cap. Subscription limits aggregate both protocol routes. New calls reserve
the full input capacity and their output bound at the final wire boundary. All
uncertain streams still block continuation. See NATIVE_MODELS_2026-11-13.md.


## 2026-11-13 — Record first native GLM failure and repair evidence-access guidance

Both native GLM Flash probes passed with the saved credential. The first full
team trial used fourteen calls: researcher completed; reviewer eventually
performed the full calculation and submitted its report but exhausted its
six-call allowance before normal completion. The shared evidence hash had been
mistaken for an access grant. Preserve all six rejected evidence/calculation
operations, native failure and conservative 0.556952 CNY debit; no draft accepted.

Make each worker's first required source call explicit and return precise recovery
instructions for denied reads. Do not grant access automatically or increase
per-role limits. Both independently executed full calculations matched the frozen
reference; no model intelligence upgrade or statistical-method change is justified.

Within the owner's test/polish and trial-readiness authorization, append a new
route with sixty aggregate GLM requests and extend the session allowance from six
to seven, covering one repair rerun and one owner trial. All historical requests,
failed sessions and the 401's full cash/credit reservations remain counted. Keep
200 CNY, 1,500 credits, the same expiry, data scope, concurrency and per-trial caps.
167 offline tests pass; the repair rerun will be recorded separately.


## 2026-11-13 — Preserve zero-dispatch package refusal and amend only GLM sublimit

The sixth native session was refused before any provider dispatch: the retained
401 reservation plus prior calls and the next full-input reservation exceeded
the old ten-CNY work-package sublimit. There was no new token use or debit.
Preserve this session; do not reset the ledger or classify its refusal as an LLM
failure. Add a frozen operator GLM route with a twenty-CNY package allowance;
keep the original two-hundred-CNY cumulative ceiling, all usage/reservations,
sixty-request aggregate cap, fifteen-hundred-credit cap and expiry unchanged.
The original policy row is untouched. Tests prove both historical accounting and
the original cumulative bound survive the amendment. Extend cumulative sessions
to eight to retain one owner slot after the actual repair run. 169 offline tests
pass; use a read-only capacity preflight before the next submission.


## 2026-11-13 — Final native GLM trial passes with qualitative caveats

At 12:12–12:20 Beijing, clean source 8150415 ran fifteen real GLM 5.3 Flash
Coding Plan requests through native zai-coding-cn and native Agent Teams. All
three roles made five requests, both workers completed, both tasks completed,
and the immutable draft was recorded with zero tool/report failures. Both full
specifications match the frozen independent bootstrap reference: inconclusive.
The independent raw-wire/data/accounting audit verified ninety-six frozen files
and all 377 descriptive facts per calculation. Retain a qualitative finding:
reviewer and supervisor overstate what an interval containing zero says about
the information in a point estimate. Record the correction without rewriting the
draft. Multi-symbol recommendations remain suggestions, not scope authority.

Usage: 180,678 tokens, 57.47% cache hit ratio, 54.60039-credit upper estimate and
0.498666 CNY conservative exposure debit, not an incremental subscription bill.
The original official baseline remains 20.35 CNY; current accounting 22.664994,
reservation 5.242880 and unreserved 172.092126 CNY. There are 110 harness requests,
109 settled and one reviewed auth rejection retaining its reservations. Seven
of eight sessions are used; one bounded owner trial remains before route expiry.

Native Models key editing, dark/light readability, desktop completion/reload and
Team board checks pass. 169 offline tests and both CI suites pass on the live
source. Keep the idle guarded server available; no further provider request is
scheduled. Mobile clipping, broader scientific validation, mixed role providers
and current-market context remain staged. See LIVE_GLM_NATIVE_2026-11-13.md for
complete per-agent work, token/rate/cost/cache/resource measurements and evidence.


## 2026-11-13: return to modular capability development

The owner completed the eighth fixed-scope pilot and rejected production readiness.
Cancel the planned DeepSeek run and continue GLM Coding Plan Pro / GLM 5.3 Flash
until quota exhaustion or an explicit owner switch. No queued Codex automation,
user crontab or separate test scheduler was found. Enforce GLM-only admission in
the shared ledger, atomically with reservations, so old launchers cannot dispatch
DeepSeek. Previously dispatched requests can still settle. Retain the original
200 CNY cap, official 20.35 baseline and unresolved 401 reservation.

The next package follows the approved standalone-module stage: versioned shared
state and review, using native DSH SDK sessions without a custom inference loop.
Findings cite exact source excerpts and pin a candidate version. Revisions retain
parentage and explicit adopt/reject/defer decisions. Host principals, immutable
events, optimistic concurrency and bounded state are checked independently from
semantic truth. This is not an official pool, evaluator or production core.

The owner trial accounting and independent data audit pass after repairing an
exporter attribution error: a killed server without stopped.json was incorrectly
associated with a later trial despite contributing no resource samples. The
original export and failed audit are retained. See MODULAR_DEVELOPMENT_2026-11-13.md
for subsequent live module attempts and their capability limits.

The first module package made eleven real GLM Flash calls across two paired
diagnostic cases and retained two failed attempts. The output-token limit and
case-insensitive export-name collision were repaired; source ids are now enumerated
in schemas after a correct units finding cited an invented source. All wire
accounting audits and 180 offline tests pass. Both timing arms correct the known
defect; no collaboration accuracy benefit is demonstrated. Both units formulas
are correct but their explanatory scale relationships are wrong, so semantic
acceptance is explicitly withheld. Review of final synthesis is a gate before
native adaptive coordination and broader research, not an excuse to label schema
success as scientific correctness. No GLM 5.3 upgrade is justified by this package.

Budget after the module package: 23.566904 CNY accounted, 5.242880 reserved and
171.190216 unreserved under the original 200 CNY ceiling. GLM has 58 aggregate
requests, 209.79563 upper-estimated settled credits and 555.74528 reserved credits.
These are local accounting quantities, not subscription cash invoices or an account
quota reading. Detailed source snapshots, runtime/wire records, comparisons and
per-agent resources are indexed in MODULAR_DEVELOPMENT_2026-11-13.md.

## 2026-11-13: completed-output review and adaptive native follow-ups

The owner authorized final-output review, adaptive supervisor follow-ups and repair
of the unit explanations using GLM 5.3 Flash only. Keep native DSH Models, subagents
and Agent Teams; the host adds versioned output/review records and bounded grants,
not another model loop. Explanation-only amendments must not force a computational
definition change. Finalization pins a clean review of the current exact version,
after the native tasks complete. A clean review may finish without an author task.

Live testing found three output-cap failures and a false semantic pass. At low
reasoning effort, both model reviewers missed an incorrect raw/target equality; an
author appended the right relationship without removing the old contradiction.
The artifact and native finalization are retained, while the separate audit rejects
semantic acceptance. Add a restricted source-derived unit-expression checker and
explicit English unit-relationship checks throughout the current output. Recognized
contradictions block review, amendment and finalization; obsolete equations remain
in historical versions. This grammar does not prove arbitrary natural language.

After the cap failures, the output ceiling increased from 8192 to 16384. The native
route `glm-coding-review-low-2026-11-13` requests low effort, retains thinking and Flash,
and extends the operator request cap from 100 to 120 without resetting prior usage.
The original 200 CNY ceiling, 20 CNY package sublimit, 1500-credit cap and old 401
reservations remain unchanged. No automatic provider or model fallback is added.

The final two unit repairs and clean-output control pass, with 212 offline tests
and native runtime/UI verification. Across all attempts: 53 actual API calls,
565131 tokens, 45.97% input cache hits and 1.590600 CNY conservative exposure.
Current accounting: 25.157504 CNY accounted, 5.242880 reserved, 169.599616 unreserved.
These amounts are not incremental subscription invoices. See
FINAL_OUTPUT_REVIEW_2026-11-13.md for every attempt, actor, resource sample summary,
source freeze, false pass and remaining capability gate. No official evaluation,
publication, pool operation or production-readiness claim follows from this diagnostic.

Final offline hardening preserves the written decimal rather than a rounded float
and rejects extreme prose/formula exponents before allocating large fractions.
All saved accepted outputs still pass. Separate reviewer tasks can see prior issues;
they are not blinded replications. Model chat acknowledgments are not themselves
the exact reviewed artifact. These limitations remain explicit in the report.

## 2026-11-16: unseen BaoStock controls and owner-directed GLM 5.3 rerun

Freeze a correct five-observation raw-return candidate, a new three-symbol BaoStock
bundle (177 rows, 59 common observed dates), question and bounded fixed/adaptive
workflows before dispatch. The host calculates a restricted factor specification;
DSH owns inference and native Agent Teams. Source-linked findings, explicit
dispositions, exact-version reviews and changed executable scores distinguish a
factor revision from explanation or retention. Never force a change to pass a gate.

The Flash fixed arm changed 162 scores through volatility normalization but its
explanation failed final review. Retain five rejected submissions and the incomplete
outcome. Clarify exact literal citations, initial versus repair resolutions and
defects versus ordinary limits; validate finding batches before append and use the
server's frozen Python source for native workers.

The owner then explicitly requested GLM 5.3 on the exact same task. Freeze the
unchanged source/question/initial candidate with model-specific cash and credit
rates. Use native zai-coding-cn, low reasoning effort, thinking enabled and
concurrency one. Local route bounds become 240 aggregate historical GLM requests,
4000 conservative credits and 40 CNY, all within the original 200 CNY ceiling.
No account quota is inferred and no metered/provider fallback is authorized.
Model and contract guidance both changed, so comparisons with Flash cannot isolate
model quality. The three GLM 5.3 runs share all 120 frozen source files and inputs.

The GLM 5.3 fixed/adaptive first pair completed and retained the baseline. The
adaptive arm repaired two contract errors; the larger model did not eliminate them.
The reverse-order adaptive attempt completed analysis/design, then DSH timed out
after 300 seconds without stream progress. The guard ended with ConnectTimeout
before an HTTP receipt and retained the full 8.847360 CNY/762.83904-credit reservation.
It remains blocking unknown usage, not a reviewed 401 or a zero-cost call. Stop
under the frozen rule; do not run the final control or replay the failed turn.

Record 41 GLM 5.3 attempts, 40 settled, 613321 known tokens and 5.223628 CNY exposure.
Including Flash, this checkpoint adds 59 attempts, 898176 known tokens and 5.890904
CNY exposure. Current accounting: 31.048408 CNY baseline plus conservative debits,
14.090240 reserved and 154.861352 unreserved. The official 20.35 baseline and every
earlier debit/reservation remain. Credits and cash exposure are not subscription
invoices. No additional source was fetched after the model switch.

Independent Decimal arithmetic passes; semantic limits and the unfinished review
remain separate. The unseen research experiment and capability cards are recorded,
but substantive adaptive revision, minimal-core acceptance and Hybrid v1 remain open.
An exploratory hypothesis need not prove alpha; the coherent starting definition
and limited evidence may be a weak stimulus for evolution. Before further live work,
reconcile the unknown charge and diagnose connection/recovery behavior.

After live dispatch stopped, add explicit unresolved-usage export without releasing
reservations; the regression also verifies pending-export refusal and blocked replay.
232 offline tests, format/lint, JS parsing and MIT checks pass. See
UNSEEN_CASE_2026-11-16.md for full agent work, resources, native UI checks, failures,
protocol amendments and evidence. Keep PR 22 draft and unmerged.

## 2026-11-16: owner-directed maximum reasoning effort and bounded retry

Pin GLM 5.3/max on the native Models/Agent Teams route and enforce the frozen effort
on every wire request before admission. Keep the exact prior ConnectTimeout row,
request hash and full cash/credit reservation unchanged. The explicit retry direction
authorizes only named fresh groups through an operator continuation; it does not
reconcile old usage, permit old-turn replay or waive another unknown charge.

The initial max/16384 analyst response ended at the output ceiling without a finding.
Record its six calls and failure, then freeze a fresh adaptive/fixed pair at 32768
output tokens. Increase only the local historical cash sublimit from 40 to 60 CNY
inside the original 200 CNY ceiling. Keep 240 historical requests, 4000 conservative
credits, 32 requests/case, five requests/worker, six tasks/inspections and the original
177-row BaoStock case. Both 32k arms use identical 125-file source snapshots.

The adaptive arm completed with retention, 15 calls and 479799 tokens. Independent
review rejects its incorrect count/warm-up explanation despite the model review's
pass; no change is forced to satisfy the revision criterion. The fixed control
inspected normalization (162 changed calculation values) but deferred it and submitted
retention. Two rejected submissions consumed time/requests. A sixth worker request
was refused after the accepted fifth-response submission, leaving the native task
failed/in progress and preventing final review. Preserve that 13-call incomplete
outcome; an accepted tool artifact does not establish successful native completion.

Across all stages: 34 settled calls, 880655 tokens, 60.57% input cache hits,
9.363500 CNY exposure and 805.86318 conservative credits. Current accounting is
40.411908 CNY plus 14.090240 reserved, leaving 145.497852 unreserved. The official
20.35 CNY baseline and both old reservations remain. These are exposure/credit
estimates, not incremental subscription invoices. No new data or DeepSeek request.

Large board tool responses exceeded DSH's roughly 50 KB model-visible output bound,
so the first export missed completion receipts. Verify the append-only native
session log, freeze it and its hash, then update only the exporter. Read every
Zstandard frame, check identity/event/revision ordering and latest task ownership,
and corroborate wire fields while excluding two derived display fields. The fixed
native task correctly remains incomplete. All failed export/preparation attempts
remain in evidence; the fix has offline regressions and 249 full tests pass.

Do not conclude that optimization is impossible or that low effort alone caused
retention. Operator authority/cap metadata changed from the low-effort comparison;
one case cannot establish model or workflow superiority. Next address compact board
delivery, terminal acknowledgement accounting, closed-attempt status, count/prose
validation and exploratory hypothesis criteria. DSH's Git-diff cards attributed
concurrent Codex edits to these research sessions; isolate the research workspace
and use audited tool events for agent-work claims. MAX_EFFORT_2026-11-16.md contains
all stage/actor/resource measurements. Core, Hybrid v1 and production gates stay open.

## 2026-11-17: bounded completion and a new frozen research comparison

The owner directed progression to the next checkpoint. Keep GLM 5.3/max, native
DSH Models/Agent Teams, BaoStock only and the original 200 CNY ledger. Freeze a
new three-symbol question and sequential small-to-larger source requests before
dispatch: nine business queries and anonymous logins produce 186 rows/62 common
dates. Historical BaoStock bounds become 23/23/720 calendar-symbol cells. No paid
data or DeepSeek is used. A testable source-motivated hypothesis may be adopted for
exploration without proving alpha; adoption never establishes investment benefit.

Bound tool views to 24000 UTF-8 JSON bytes with immutable 2500-character pages and
compact native receipts. Give every actor one actual acknowledgement request after
accepted submission, separate from work but within the same atomic aggregate/cash
ledger. The bounded case has six worker work calls, twelve supervisor work calls,
36 aggregate calls, six tasks and six inspections. A failed native task remains a
failure. Exact count fields and limited prose checks supplement independent review.
Keep old native sessions in place while creating a separate Git boundary for their
workspace, preventing unrelated repository edits from appearing as agent work.

The first control failed after 19 settled calls: its reviewer spent its allowance
paging through inputs and could not read an inspection event by ID. Preserve that
attempt and withhold the unstarted adaptive arm. Record one repair amendment:
preload full ordinary-sized evidence into up to 65536 bytes of compact worker scope,
expose inspection receipts and show work/acknowledgement budgets. Freeze a fresh
fixed/adaptive pair, keeping data/question/model and per-arm bounds unchanged.
Historical caps become 295 GLM attempts, 6000 conservative credits and 80 CNY local
exposure within the original 200. The old fingerprinted timeout remains unknown and
fully reserved; its exception covers only the named fresh groups. No further
automatic retry is allowed. The updated scripted native fixture passes with
27 synthetic requests/five tasks, separately from real inference.

The repaired pair uses identical 135-file runtime snapshots and finishes in 18/20
calls. Both designers adopt the same inspected volatility-scaled specification,
changing 171 scores with unchanged coverage. Independent Decimal arithmetic passes.
The fixed descriptive artifact passes with caveats. The adaptive supervisor targets
assignments with observed finding IDs and corrects one rejected basis-ID assignment,
but its final reviewer repeats an unsupported claim that 56 next-price observations
are executable signals. Preserve native finalization and withhold independent clean
semantic acceptance. Both raw and normalized scores are dimensionless; unreviewed
root progress also used misleading unit wording. No adaptive superiority is shown.

After the pair, an offline counterexample replay blocks that recognized execution
overstatement in both candidate and review. Do not rewrite either immutable live
artifact or describe the post-run fix as a live pass. Fix a separate startup/export
compatibility defect: manifests must serialize old packages exactly, without adding
new defaults. A regression reproduces the mismatch before transport and passes after
the fix. Final formatting/lint, JS syntax, MIT checks and 271 offline tests pass.

All three real attempts total 57 settled requests, 1523122 tokens, 70.79% input cache
hits, 15.171276 CNY exposure and 1306.28283 conservative prepaid credits. Accounting
is now 55.583184 CNY plus 14.090240 reserved, leaving 130.326576 unreserved. These are
conservative exposure/credit estimates, not an incremental invoice or account quota.
The original official 20.35 CNY baseline and prior reservations remain unchanged.

The checkpoint completes the bounded-delivery/completion engineering and records a
real adaptive computational revision. The minimal core's clean final-artifact gate
remains open. Next render metrics/units from typed pinned fields, distinguish observed
execution prices from actual tradability, and separate intermediate chat from audited
artifacts. Only then attach parent-child evolution and released-report matching.
Desktop/reload pass; mobile clipping, root-only footer metrics, general semantics,
timeout recovery, broader cases and production operations remain gaps. All attempts,
per-role work, resource measurements, limits and evidence are in
CHECKPOINT_2026-11-17.md. Keep PR 22 draft and unmerged.

## 2026-11-17: host reports, exact task references and semantic limits

The owner requests structured final-output reporting, remaining semantic fixes and
a GLM 5.3/max fixed/adaptive rerun under the original 200 CNY. Add a versioned
`structured-v3` report: the host supplies spec/data/score hashes, counts, metrics,
units, timing limits and inspection provenance; the model supplies separately
identified qualitative hypotheses and finding dispositions. Review the exact
candidate and complete report hash. Render the host text through native DSH's tool
card, preserving Models, Agent Teams and its model loop. Independent arithmetic,
semantic and native-task checks remain distinct. Prompted ID/status-only chat is
not a validator of all intermediate or final model prose.

Freeze the original 186-row BaoStock case, without new data or control-output
injection. The first fixed run completes in 22 calls, adopts normalization and passes
descriptive review with limits. The adaptive analyst fails after nine calls on a
truncated candidate ID and two wrong hashes; it never submits accepted findings.
Preserve that failure, native states and every charge. The initial operator account
of line-break corruption was wrong; the first supplied value was a truncated hash.

Record a specific interface repair, not an unchanged retry: immutable `assigned`
task targets, actor-owned inspection handles and case-local finding/review/candidate
handles bind full hashes on the host. Record raw payload hashes and every expansion;
do not guess malformed references, retarget stale tasks or alter research content.
Enumerate fact references and explain review defects versus disclosed limitations.
Sort rendered metric keys so canonical JSON round trips cannot reorder the report.
The initial exact wire text remains alongside its canonically ordered projection.

The fresh task-bound pair freezes identical 142-file snapshots and equal evidence,
model/effort and request/inspection bounds. Both complete: fixed 25 calls/779886
tokens retains the baseline after two actual inspections; adaptive 18/499281 adopts
normalization and changes 171 scores. Arithmetic, typed report fields, task bindings,
native completion and byte-exact report delivery pass. Adaptive descriptive review
passes with limits. Fixed review needs a named comparison measure: SD max/min ratios
are similar, but absolute SD ranges differ greatly. A model clean verdict does not
resolve this ambiguity. Intermediate analyst errors are recorded independently.

After both live snapshots freeze, add four offline counterexamples for that width
claim and a supported analyst heading that wrongly describes units as heterogeneous
across the universe. Shared CNY/share and dimensionless-return units do not differ
between names. These bounded checks reject known wording without forcing a factor
change; they do not prove a named statistic or arbitrary prose. No historical
artifact is changed or retroactively passed. Final formatting/lint/JS/MIT checks
and 294 offline tests pass. Two additional regressions verify independent spec-hash
and changed-row checks even when a faulty report builder produces consistent hashes.
The saved real artifacts pass that stronger read-only audit. An initial supplementary
output reused the perturbation variable in its count field; its wrong-typed output
is retained separately, corrected and covered by an output assertion. Original live
reports and calculations are unchanged. Six transient test failures were sandbox loopback-bind
refusals; their logs remain and the permitted offline rerun passes.

All four real attempts total 74 settled calls, 2202398 tokens, 74.71% input cache,
21.355184 CNY exposure and 1839.082620 conservative credits. Accounting becomes
76.938368 CNY plus 14.090240 reserved, leaving 108.971392 unreserved. The original
20.35 CNY official baseline and both old reservations remain. Latest local historical
limits are 364 attempts, 7500 conservative credits and 100 CNY exposure inside the
original 200; 335 attempts and 6178.406360 settled/reserved credits are used. This
specific amendment completes the named pair, with no further automatic replay or
paid pair. Coding Plan exposure is not an incremental invoice or account quota.

The root footer is session-only; post-drain audit includes all worker/supervisor
acknowledgements. Immediate mobile resize screenshots were clipped, but a settled
closed-sidebar view fits 390px; correct the earlier inference of permanent clipping.
Full mobile navigation and a first-class report/team-usage view remain unaccepted.
The reporting/reference engineering is verified, but the complete clean-pair/core
gate stays provisional. Verify unambiguous comparison claims before attaching
parent-child evolution and released-report matching. All attempts, actor/resource
measurements, guards and limitations are in STRUCTURED_REPORT_2026-11-17.md. Keep
PR 22 draft and unmerged; no official acceptance or production claim.


## 2026-11-17: Updated semantic guards tested in a fresh GLM maximum-effort pair

The owner explicitly requests the next fixed/adaptive checkpoint under the updated
guards. Freeze the same root prompt, previously seen 186 BaoStock rows, baseline,
model and limits. The new route admits only `semantic-guards-fixed-01` and
`semantic-guards-adaptive-02`, with 407 historical requests (335 plus 72), 9000
conservative credits and the unchanged 100 CNY local exposure cap inside the
original 200 CNY total. Preserve the exact old timeout fingerprints/reservation and
401 reserve. No fallback, new data, old-turn replay or further automatic pair.

Both arms freeze identical 144-file runtime snapshots, including the latest semantic
guards and independent audit hardening. They complete 17/19 real GLM 5.3/max calls,
with 440875/561935 tokens. The fixed designer inspects baseline and ten-observation
volatility normalization, then retains the baseline; adaptive executes the
five-observation normalization and changes 171 non-null scores. Its designer corrects
the analyst's wrong expectation that matching windows add warmup. Both independent
arithmetic/report audits pass; adaptive final descriptive review passes with limits.
Fixed still does not name its dispersion comparison measure, although both the SD
range and ratio support its directional claim. An incorrect analyst subtraction is
adopted without an explicit correction; host final counts remain correct. No guard
rejection occurs, demonstrating the bounded scope of the known-counterexample checks.

Both final chat summaries repeat eight work requests from the last case_board
snapshot, before finalize_case consumes a ninth work request. Each supervisor actually
uses nine work requests plus one acknowledgement. Budget enforcement and exports
are correct; final model summaries are not a reliable settled-usage surface. Native
root footers also exclude worker tokens. Exact reports are verified byte for byte
in the UI, but remain compact tool cards and full mobile navigation is unaccepted.

All 36 new requests settle: 1002810 tokens, 69.99% input cache, 9.613800 CNY conservative
exposure and 827.996760 conservative credits. Current accounting becomes 86.552168
accounted, 14.090240 reserved and 99.357592 unreserved. Historical GLM use is 371
attempts and 7006.403120 used/reserved credits. The official 20.35 CNY baseline and
both old reservations remain. All 294 offline tests, lint/format, JS parsing and MIT
notice checks pass. Failures in formatting, an early manifest read and a read-only
UI selector are preserved; none caused a paid resubmission.

The clean-pair/core checkpoint remains provisional. Next bind comparison measures
and observation cohorts to typed inspection references, use host count facts in
findings and render final team usage after settlement. Then verify clean final
narratives before parent-child evolution/released-report matching. Do not keep
adding superficial phrase guards or force a factor change to obtain a pass. No
causal workflow advantage, official acceptance or production readiness is claimed.
See SEMANTIC_GUARDS_2026-11-17.md and its complete per-agent/evidence directory.
Keep PR 22 draft and unmerged.
