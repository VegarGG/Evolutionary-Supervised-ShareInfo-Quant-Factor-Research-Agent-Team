# Hybrid v1 — Development Plan for Vibe Coding

**System:** Supervisor–worker coordination + shared research blackboard + evolutionary factor development, supported by parallel specialists, iterative review and standardized artifact preparation, with a strictly independent evaluation service.

**Front door:** a vendor-neutral MCP server in a Docker Compose deployment. A host agent such as Codex normalizes a folder, file, standalone factor/model/strategy, or natural-language idea into a validated input bundle and submits it through MCP. Internal research agents use independently configured online providers.

**First job:** the P0 / P1 A-share industry-rotation packages (Appendix A).

**Status of this document:** planning only, revision 1.1 aligned October 23, 2026. No system implementation or live-provider acceptance is claimed. Read [PLAN_ALIGNMENT.md](PLAN_ALIGNMENT.md) first: it records the owner's requirements, reconciles this plan with the local QFR chapters, and governs conflicting defaults. [LOCAL_IMPLEMENTATION_REFERENCE.md](LOCAL_IMPLEMENTATION_REFERENCE.md) preserves those aligned technical chapters.

Companion files in this folder: `appendix-a-pilot-case-industry-rotation.md` (the pilot fixture, business rules, golden numbers) and `appendix-b-research-notes.md` (external research with sources that justify the technology and protocol choices).

---

## 0. How to use this document

This plan is written for the project owner and whichever coding agent implements it; no particular agent product is required. Sections 1–7 are the design. Section 8 is the technology shortlist. Section 9 is repository layout and the rules to put in `AGENTS.md`. Section 10 is the phased build, where every phase has an acceptance test and a kickoff prompt that can be given to the coding agent. Sections 11–13 are verification, risks and open decisions.

Working rule for vibe coding this system: **build and verify the deterministic parts (data layer, evaluator, registry) against the original machine-readable golden outputs before production LLM research.** Small offline experiments with supervisor/worker coordination, blackboard sharing and justified revisions may run alongside the early phases, as the brainstorming Page recommends; they do not establish financial or production acceptance.

---

## 1. What we are building

### 1.1 Goal

An on-demand system that accepts a research objective with an idea, factor, model, strategy or mixed package and runs an auditable **propose → publish → independently evaluate → read feedback → propose again** loop. It preserves the Hybrid v1 research architecture and produces the deliverables required by a frozen exit gate. Factor evolution remains central; imported models and strategies retain their own execution semantics. Jobs may run as long as needed within authorized resource/spend controls; success is an independently validated delivery, not merely stopping a loop.

### 1.2 Non-goals for v1

- Live or paper trading against a broker. Simulated tracking of published artifacts on newly arriving data is in scope as a module; brokers are not.
- Automated data acquisition from licensed providers. New data is a human-authorized step that creates a new dataset version.
- Autonomous parallel research lanes and discovery of new factor-composition strategies (Hybrid v2). Importing, evaluating and revising an existing model/strategy under a declared v1 contract is in scope.
- A mandatory web UI. MCP is the required interface; the local plan's dashboard remains an optional operator feature. Local LLM hosting and a compulsory 24/7 deployment are also out of scope.
- Proving alpha. The system is designed to produce defensible evidence either way; the pilot data (Appendix A) may well end with "no candidate clears the bar", and that is a successful run.

### 1.3 The governing principle, made operational

The brainstorm's Final Recommendation reduces to one rule: **separation of proposal and measurement**. In this plan that rule is enforced four ways, not by prompt instructions:

1. **By construction:** research agents have no tool that can start, configure, cancel or read unreleased evaluation work. The evaluator is not an LLM agent; it is deterministic code with its own process, credentials and schedule.
2. **By storage permissions:** three databases (`research_db`, `registry_db`, `eval_db`) with distinct least-privilege service roles. Research writes its blackboard, publishes through the Registry API, and reads only the Feedback API. The feedback service alone holds the restricted role for released evaluation views.
3. **By data access:** the research plane sees only the development window of the data. The validation and confirmation windows (and any optional diagnostic window) are mounted read-only into the evaluator's sandbox and nowhere else.
4. **By release policy:** what the evaluator publishes back is coarsened, budgeted and version-linked, so iterating against feedback cannot quietly become fitting the test set.

---

## 2. The job it must do first

The user's real task was "optimize the models in this folder". The folder (Appendix A) contains four generations of research code, Chinese and English documents, caches at several as-of dates, reference outputs, audit protocols, hashes, a Windows scheduled-task deployment, and about 10 MB of data for 31 industry indices. The honest finding in the folder's own audit is that the accepted model P1 beats the original P0 by about one percentage point of hit rate, inside intervals that all contain zero, on history that had already been inspected.

This shapes three requirements that a generic "quant agent" would miss:

- **Intake is a first-class component.** The local agent normalizes supplied material into the common InputBundle, brief and available manifests. Baselines are optional unless the objective needs them. Resolve material ambiguity with the owner; existing explicit authorization need not be requested again. An unresolved idea may be admitted for clarification, but execution waits for required data and contracts.
- **The evaluator must be at least as careful as the folder's own audit.** Paired comparisons, block bootstrap, family-wise adjustment, leave-one-year-out, placebo shifts and prefix tests already exist there as conventions; our evaluator must reproduce the folder's numbers before it is trusted on anything new.
- **The data have known timing weaknesses.** Fundamentals are half-year with approximate availability dates and backfilled membership. The system has to carry a `pit_grade` label on every input and every artifact so that hypotheses can be marked "blocked on data" instead of silently evaluated on leaky inputs.

---

## 3. System architecture

### 3.1 Component map

Three planes plus a boundary object. Names in brackets refer to the nodes of the brainstorm's hybrid architecture diagram.

**Intake plane (runs on the user's device)**

- **Host MCP client + portable intake instructions.** Codex or another agent inventories supplied assets, drafts the typed input bundle, preserves originals, resolves missing information and submits through MCP. It also reads job status, released reports and delivery exports. No Claude harness or local model is required.

**Research plane (the system; agent-writable)**

- **Supervisor [S].** Plans and re-plans research tasks, allocates research token/task budgets within operator authorization, respects evaluator-published quotas, reads released reports and proposes a completion or pause. It cannot allocate the evaluator's own run budget or pass its own exit gate. Implemented as a planning step that produces a structured plan, not as a free-running loop.
- **Specialist workers [W].** Research-data engineer, factor researcher, performance-report analyst (read-only), skeptical reviewer, factor-code and packaging agent. Each is an LLM loop over a closed, role-specific tool set.
- **Evolutionary worker [E].** Maintains the candidate population and lineage, selects parents from released scores and diversity, proposes mutations and recombinations as new artifact versions.
- **Review and packaging [P].** Freezes a proposal into an immutable artifact: canonicalizes the definition, computes the content hash, runs static causality checks and the research-side prefix test on the development window, attaches hypothesis text and data requirements, publishes to the registry.
- **Shared research blackboard [B].** Hypotheses, tasks, notes, population and lineage, links to released report identifiers, archive of rejected ideas. Agent-writable.

**Boundary object**

- **Immutable artifact registry [A].** Append-only. An artifact version is content-addressed (hash of canonical definition + config + data requirements + protocol compatibility tag). Nothing is ever overwritten; revision creates a new version with a parent pointer.

**Evaluation plane (independent; evaluator-writable only)**

- **Intake and scheduler [C].** Polls the registry for eligible, unevaluated versions; owns the queue, budget and order. Research cannot enqueue, reorder or cancel.
- **Backtesting engine [T].** Deterministic replay under a frozen protocol: publication → execution → exit per decision cycle, paired against the designated baseline.
- **Simulated tracking engine [M].** Forward tracker: when a new dataset version is registered by a human, records each published artifact's new signals and settles earlier ones. Opt-in and inactive in the frozen pilot (no new data); the schema exists from day one. A missed historical signal is replay, not prospective evidence.
- **Output quality checks [Q].** Static analysis of artifact code, causality checks, prefix-consistency test across historical cutoffs, reproducibility (two runs, identical hashes), resource usage.
- **Official records [O].** Per-version, per-protocol run records, period ledgers, metrics, diagnostics, receipts with hashes.
- **Release policy [L] and read-only feedback interface [F].** Decides what the research plane may see and when; publishes released views.
- **Final acceptance [G].** Sealed confirmation window; human-triggered, budgeted queries; promotion decision recorded outside agent authority.

### 3.2 Boundary rules as enforceable checks

| Rule from the brainstorm | How v1 enforces it |
|---|---|
| Agents cannot invoke, configure or cancel evaluation | The research service has no network route or credential to the evaluator process. Evaluator is driven only by its own poller and by the human CLI. Compose separates service identities, credentials, networks and read-only mounts. The trusted sandbox launcher accepts only validated run contracts; neither research/MCP nor untrusted artifacts receive a Docker socket. Host peer authentication is not assumed across containers. |
| Official reports cannot be forged | Every report and receipt is signed by the evaluator with a key only its OS user can read; the MCP server verifies the signature before serving anything labelled official. |
| Agents cannot change evaluation data, windows, costs or assumptions | Protocol is a frozen file whose hash is embedded in every report. The protocol directory is owned by the evaluator OS user. Data beyond the development window live only in the evaluator's mount. |
| Agents cannot edit official results | `eval_db` is evaluator-owned; only feedback_ro can select released views. Research has no direct CONNECT privilege on eval_db. |
| A report about an older version must never become the score of a newer one | Reports reference the immutable `artifact_version_id`, its separate content hash, `protocol_id`, dataset version and evaluator version. The blackboard stores report ids, never copies of metrics as facts about lineages. |
| Final holdout stays outside iterative feedback | Confirmation evidence stays evaluator-only. An owner-authorized query produces only the policy-allowed decision; private measurements never enter research MCP. Prior exposure is recorded even if a window is sealed. |
| Pending or failed evaluations are recorded explicitly | Every version has an evaluation status row: `queued`, `running`, `failed:<reason>`, `complete`, `withheld`. Research reads statuses, never infers from absence. |
| Non-trading outputs get type-appropriate checks | Data-engineering artifacts are checked for reproducibility, schema and temporal quality; research notes get deterministic completeness, citation and released-value checks, not a trading backtest. |

### 3.3 One full cycle, end to end

1. The user gives Codex or another host agent an idea or source assets. Portable intake instructions produce an InputBundle and proposed brief, identifying unresolved fields and preservation constraints.
2. The host agent uses MCP to create the project and validate the InputBundle, register datasets and baselines when required by the objective, and propose a protocol. Files use finalized upload IDs or declared read-only import mappings. The evaluator owner freezes the protocol separately; `submit_research_brief` returns a durable job id. Missing required inputs leave the job awaiting clarification rather than inventing a runnable contract.
3. Trusted data ingest builds the permitted development-window slice, and the research service writes the brief to the blackboard, and the supervisor produces a first plan: for example, "data engineer: verify canonical tables and parity with baseline features; factor researcher: propose six hypotheses in the price/volume family; packaging: publish P0 and P1 as version 0 artifacts".
4. Workers execute tasks, writing notes and proposals to the blackboard. Packaging freezes approved proposals into artifact versions and inserts them into the registry.
5. The evaluator's poller finds new versions, runs quality checks, then the backtest under the frozen protocol, writes official records, and applies the release policy. Released views now show the Ladder-gated scalar and the flags for the new versions.
6. The report analyst reads released results and writes interpretations to the blackboard. The skeptical reviewer challenges them. The evolutionary worker updates the population, selects parents and proposes the next generation. The supervisor re-plans and spends budget or stops.
7. At configured checkpoints the user gets a summary through MCP (`get_job_status`, `get_report`) and can pause or redirect research. Evaluation keeps running on whatever is already published.
8. The supervisor proposes delivery. An independent checker validates the frozen exit-gate specification and issues a version-linked receipt before the job becomes completed. A supported negative result may pass a research-delivery gate; budget exhaustion or missing evidence cannot. Investment promotion, if requested, follows its separate evaluator/human gates. See PLAN_ALIGNMENT sections G and I.

---

## 4. Core contracts

Contracts are written as field tables. They are the first thing to build (Phase 0) and the thing least allowed to drift later. Use one schema library for all of them and generate JSON Schema from it so the MCP tools, the database and the agents share one definition.

### 4.1 Research brief

| Field | Type | Notes |
|---|---|---|
| `project_id` | id | created by `create_project` |
| `objective` | text | one paragraph, human-approved |
| `universe` | list of codes + label map | industry codes for the pilot |
| `benchmarks` | list of codes | with one `primary` |
| `decision_cycles` | list | each with name, signal-date rule, publication rule, execution rule, review rule |
| `selection_rule` | object | top fraction, rounding, tie-break, equal weight |
| `eligibility_rule` | object | warm-up, coverage threshold, minimum eligible count, neutral fill |
| `primary_metric`, `secondary_metrics` | names | from the evaluator's metric catalogue |
| `cost_levels_bps` | list | e.g. 0, 10, 30 |
| `protocol_proposal_ref`, `exposure` | objects | proposed public evaluation objectives plus prior data exposure. Exact private windows belong to the evaluator-owned protocol, not to ordinary research prompts. Pilot proposals in 7.10 are already historically exposed |
| `baseline_artifact_ids` | list | the versions used for paired comparison |
| `constraints` | list of text + machine flags | no data fetch; allowed feature families; PIT constraints |
| `success_criteria` | object | the hurdle definition the supervisor should aim at (see 7.6) |
| `budgets`, `exit_gate`, `role_profiles` | objects | authorized spend and token/concurrency limits; optional generation/wall-clock limits (unset by default); evaluator-owned quota references; frozen deliverables/checks and allowed conclusions; role and task profile references |
| `human_checkpoints` | list | after intake, after protocol freeze, every N generations, before confirmation query |

### 4.2 Dataset manifest and canonical data layer

A dataset version is a set of canonical Parquet tables with pinned schemas plus a manifest. Its id is a Merkle-style hash of table hashes and the manifest. Each table carries two hashes: a physical SHA-256 of the file (for transfer and integrity) and a logical hash over canonically sorted rows and the schema (for identity), because Parquet bytes are not reproducible across writer versions and the evaluator must recognise the same data regardless of how it was written. The manifest also records the point-in-time cutoff used to build the tables.

| Canonical table | Key | Columns (minimum) | Pilot source |
|---|---|---|---|
| `calendar` | date | is_open | trading_calendar.csv |
| `universe` | code | name_zh, name_en, kind (industry / benchmark) | industry_labels.csv + config |
| `prices_daily` | date, code | close | index_prices.csv + evaluation_prices.csv (overlap verified) |
| `panel_weekly` | date, code | ret1, ret4, breadth, amount, turnover, stock_count, plus every engineered baseline feature with a documented formula | industry_signal_panel + features |
| `fundamentals` | code, report_period, metric | value, available_date, pit_grade | stock_finance.csv.gz + available_date logic (grade B) |
| `membership` | stock_code, industry_code | effective_from, effective_to, pit_grade | constituents snapshot (grade D, backfilled from a current snapshot) |

Manifest fields per table: path, physical and logical hashes, rows, columns, date range, grain, `pit_grade`, `pit_notes`, licence note, source description. Manifest-level fields: dataset_version_id, as_of date, creator, parent dataset version, change log.

`pit_grade` has four values, borrowed from the honest-labelling proposals in the 2026 literature (Appendix B.3): **A** exact availability timestamps; **B** availability set by a documented deadline rule; **C** approximate dates, to be used only with an extra-lag sensitivity run; **D** restated, backfilled or unknown. Observation dates and calendar dates are explicit; that alone does not certify historical data vintages or point-in-time revisions. The pilot's half-year fundamentals carry an `available_date` based on the package's interim-deadline-plus-one-day convention (B for that availability rule); value vintages and membership quality remain separately recorded and may be D/unknown. The constituent snapshot mapped backward is grade D. Historical index reconstruction is a concern marked unverified in Appendix B; preserve `vintage_status=unknown` until source evidence establishes it. Reports say "lookahead tested, not certified": the checks in 7.3 detect leaks they can reach and prove nothing by their silence.

**As-of slicing** is a core service, not a utility: `slice(dataset_version, upto)` returns views where every row satisfies `date ≤ upto` and `available_date ≤ upto`. The research plane is only ever given `slice(…, development_end)`. The evaluator builds one slice per decision date when running prefix tests and uses the full dataset with per-decision cutoffs otherwise.

### 4.3 Factor artifact

Immutable. Content-addressed. The common manifest supports semantic kinds factor, model, strategy, research_note and data_product; the factor-specific tiers below remain the preferred representation for evolutionary factor proposals. See PLAN_ALIGNMENT section E for standalone model/strategy/package contracts.

| Field | Type | Notes |
|---|---|---|
| `artifact_version_id`, `content_hash` | opaque id, SHA-256 | registry-assigned immutable version id; separate hash of canonical immutable manifest and payload digests, excluding server-assigned IDs/timestamps. Implementation fingerprints are separate from full publication identity |
| `artifact_id` | id | stable lineage name chosen by the author |
| `parent_version_ids` | list | zero (seed), one (mutation) or two (recombination) |
| `kind`, `implementation` | enum, tagged object | semantic kind factor/model/strategy/research_note/data_product; representation DSL, constrained Python, fixed composite or declared package runner. Existing factor tier labels map to representation, not separate product kinds |
| `definition` | text or AST | Tier 1: expression AST over canonical columns and a fixed operator set. Tier 2: Python source implementing one function with a fixed signature against a constrained context API. Composite: list of (version_id, weight) with no fitting. |
| `parameters` | object | numeric parameters named explicitly so the evolutionary worker can mutate them |
| `data_requirements` | object | tables, columns, lookback length, minimum `pit_grade` |
| `cycles` | list | which decision cycles it is intended for |
| `hypothesis` | text | economic rationale, what would falsify it |
| `mechanism_card` | object | five short fields borrowed from published schema-plan work: event (what happens), context (when it matters), qualities (which industries it touches), direction (sign and horizon), output (what the score means); used for hypothesis-level crossover and for the diversity requirement in 6.4 |
| `formulation` | text | the formula in plain mathematical notation, independent of the code |
| `variables` | list | canonical columns and derived series the definition reads, each with its `pit_grade` |
| `complexity` | integer | AST node count (Tier 1) or statement count (Tier 2); a niche dimension and a cap |
| `provenance` | object | source hashes, author/role/task, blackboard references, provider + endpoint + exact model ID, effective settings and prompt/config hashes, fallback events, prior exposure and dependency locks |
| `research_side_checks` | object | DSL validation, static analysis result, development-window prefix test result, correlation to existing population on development window |
| `created_at`, `created_by` | | |

**Tier 1 — expression DSL.** A small typed language: time-series operators that look only backward (`delay`, `delta`, `ts_return`, `ts_mean`, `ts_std`, `ts_min`, `ts_max`, `ts_rank`, `ts_zscore`, `ewm`), cross-sectional operators (`cs_rank`, `cs_percentile`, `cs_zscore`, `cs_demean`), arithmetic, `clip`, `where`, `fill_neutral`. Operands are canonical columns. The interpreter enforces causality by construction and produces a canonical string for hashing. This is the representation the evolutionary worker mutates. The six v4 price features in Appendix A are all expressible in it.

**Tier 2 — constrained Python.** For things the DSL cannot express (rolling regressions, breadth from stock-level data). The function receives a context object exposing as-of views only (`ctx.prices(upto)`, `ctx.panel(upto)`, `ctx.fundamentals(upto)`) and returns a score per code for one decision date. Static checks reject imports outside an allowlist, file and network access, randomness without a seed, and wall-clock calls. Only the evaluator's sandbox executes Tier 2 against non-development data.

**Composite.** Fixed-weight combination of existing versions, preserving supplied P0/P1 definitions. Existing trained models and strategies may be imported with frozen weights and declared inference/training interfaces. New fitting/evolution is allowed only within an explicitly frozen case contract and training slice; autonomous v2 composition is not introduced by intake support.

### 4.4 Evaluation protocol and report

**Protocol** (frozen file, hashed, human-approved):

| Field | Notes |
|---|---|
| `protocol_id`, `protocol_hash` | hash of the canonical file |
| `dataset_version_id` | the exact data it binds to |
| `brief_id` | the brief it implements |
| cycles, publication / execution / exit rules, selection, eligibility, review rule | copied from the brief, then frozen |
| `windows` | development, validation, confirmation (sealed), optional diagnostic |
| `baseline_version_ids` | for paired comparison |
| `metrics` | catalogue subset; `primary_metric` |
| `costs_bps` | list |
| `bootstrap` | method, draws, seed, block lengths per cycle, confidence |
| `multiple_testing` | family definition, method, how the trial count is maintained |
| `release_policy` | Ladder step rule, fields released per window, per-lineage query budgets, confirmation query count, withholding rules |
| `diagnostics` | leave-one-year-out, placebo shift settings, prefix-test cutoffs, neighbourhood rule if any |
| `pit_grade_requirements` | minimum quality per table for an artifact to be eligible |

**Report** (one per artifact version per protocol):

| Section | Content |
|---|---|
| identity | artifact_version_id, protocol_hash, dataset_version_id, evaluator code hash, run id, timestamps |
| quality checks | static analysis, reproducibility (two independent runs, identical ledger hash), prefix test results per cutoff, resource usage |
| coverage ledger | expected / published / evaluated / immature / excluded decisions per cycle and window |
| per-window metrics | means and paired deltas vs each baseline, with bootstrap intervals, for the validation window and any optional diagnostic window; confirmation withheld; minimum detectable effect for the window and cycle |
| multiple-testing context | trial count in the family at time of report, adjusted interval or hurdle, rank among evaluated versions |
| diagnostics | leave-one-year-out, placebo percentiles, turnover and cost sensitivity |
| flags | `small_sample_warning`, `pit_grade_downgrade`, `fallback_rows_fraction`, `duplicate_of` (if scores are identical or correlation ≥ threshold with an earlier version) |
| release | which fields were released, rounding applied, release timestamp |
| card | a one-row summary in the style of open-source asset-pricing signal documentation (identifier, mechanism, sample, sign, primary metric, t-statistic, costs, data grade), plus model-card sections (intended use, out-of-scope use, limitations, evaluation data) and a seven-point backtesting-protocol checklist (motivation, multiple testing, data and sample, cross-validation, dynamics, complexity, culture); templates in Appendix B.3 |

Research agents see only the released projection of this report (7.7).

### 4.5 Blackboard records

| Record | Key fields | Who writes |
|---|---|---|
| `hypothesis` | id, text, family, status (`open`, `in_progress`, `published`, `rejected`, `blocked_on_data`), supporting note ids | factor researcher, reviewer |
| `task` | id, role, input refs, status, budget, result refs | supervisor (create), workers (update) |
| `note` | id, author role, task id, text, structured claims, refs to report ids | any worker |
| `population_member` | artifact_version_id, generation, niche key, released primary metric (coarse), status (`alive`, `parent`, `retired`) | evolutionary worker |
| `lineage_edge` | child_version_id, parent_version_id, operator (`mutate_param`, `mutate_op`, `crossover`, `rewrite`) | packaging |
| `rejected_idea` | text, reason, refs | reviewer, supervisor |
| `plan` | generation, tasks, budgets, stop criteria, rationale | supervisor |

Append-only event log beside the tables: every write is also an event (`who`, `what`, `when`, `refs`). Agents are activated by events ("new released report for version X", "task assigned"), which is the blackboard-as-dispatcher pattern from the brainstorm.

### 4.6 Event log and job model

Both planes persist durable state in Postgres. Research uses the local plan's deterministic generation state machine with checkpointed steps and a leased queue. An optional DBOS backend may implement research checkpoints after a compatibility spike; it is not required in the evaluator. Evaluation uses its own queue, leases, fencing and idempotency keys, claimed with skip-locked semantics.

Persist each completed LLM/tool result before advancing. A provider timeout can leave a paid call with unknown outcome, so audit ambiguous attempts and bound retries instead of promising exactly-once billing. Client disconnects and container restarts do not discard admitted jobs.

The job lifecycle, required state records, independent delivery receipt and uncapped default elapsed time are defined in PLAN_ALIGNMENT section G. Generation CLOSED is distinct from job completed. Spend/input/data pauses preserve work and never count as successful delivery.

### 4.7 Generic intake and delivery contracts

Implement the InputBundle and type-specific execution contracts in PLAN_ALIGNMENT section E. Ideas, factors, models, strategies and mixed packages are first-class intake fixtures. Missing dependencies produce needs_input or waiting_for_data with a blocked_on_data reason rather than fabricated executable inputs.

The frozen job record references its input bundle, authorized provider/role configuration, public protocol card, allowed spending and exit-gate specification. The final delivery bundle contains artifacts, released evidence and a signed/version-linked delivery receipt; private evaluator protocols/data and credentials are excluded.

---

## 5. The MCP front door

### 5.1 Tool surface

Few, coarse tools, each with a short description written for an agent that has never seen the system. Portable conventions are based on the MCP specification and tested client behavior; PLAN_ALIGNMENT section F governs client compatibility:

- Use stable names within the pinned MCP specification limits. The table gives logical operation names; a consistent namespace may be applied in the exported tool schema and client guide. Released-report reads never imply evaluator-admin access.
- Honest annotations describe actual read/write, idempotency and cancellation behavior; they do not grant permissions. Enforce role/project access in handlers. Submit/retry uses a caller-supplied idempotency key; a conflicting payload is rejected.
- An `outputSchema` on every tool, with the structured result mirrored into a text block, since some clients drop structured content.
- Concise descriptions lead with purpose, required input and effects; test discovery and schema handling in Codex and a second MCP client. Do not build correctness around one vendor's truncation limits.
- Return bounded summaries and resource links with pagination. Payload limits are server configuration tested against supported clients; model packages use the upload/import path, not large inline tool bodies.

| Tool | Purpose | Notes |
|---|---|---|
| `create_project` | new project with name and description | returns project_id |
| `register_dataset` | register canonical tables or raw files + manifest | accepts only a declared read-only import-mount reference with an explicit host-to-container mapping; otherwise the client first uploads a tarball to a plain HTTPS upload endpoint served beside the MCP app and passes the upload id, under configured upload limits rather than inlining binary packages into model/tool context; returns dataset_version_id and a validation report |
| `register_baseline_artifacts` | publish frozen baseline artifacts with expected golden evidence | optional unless the objective needs a baseline; publication through Registry API |
| `propose_protocol` | submit the protocol derived from the brief | returns protocol draft id; freezing happens only in the evaluator CLI by a human |
| `submit_research_brief` | admit an InputBundle and brief as a durable research job | returns job_id promptly; validates dependencies, role profiles, spend authorization, exit gate and frozen protocol compatibility |
| `get_job_status` | progress, generation, budget spent, open checkpoints | cheap; polled |
| `pause_research`, `resume_research`, `cancel_research` | control research only | never touches evaluation queue |
| `list_artifacts`, `get_artifact` | registry reads | includes evaluation status |
| `list_reports`, `get_report` | released reports only | returns a resource link for large bodies |
| `read_blackboard` | summaries, hypotheses, plans, notes | read-only, paginated |
| `answer_checkpoint` | human answers a supervisor question | the human-in-the-loop channel |
| `export_shortlist` | artifacts + released reports + public protocol card + dataset/source manifests + delivery receipt | supports an empty shortlist with an allowed evidence-backed conclusion; never exports private protocols or data |

Not exposed through MCP on purpose: anything that freezes a protocol, releases confirmation results, or edits evaluation records. Those live in the evaluator's own CLI, run as the evaluator OS user.

### 5.2 Long-running work

The job is durable application state, independent of a client session or request lifetime. Submission validates and returns a job ID promptly; status polling carries research progress, budget, checkpoints and released evaluator status only. Jobs may run for days or longer without a default total-time/generation limit.

Disconnecting or cancelling an MCP request does not cancel an admitted research job. Explicit pause/resume/cancel tools affect research only. Repeating a lost submit with the same key recovers the same job. Optional MCP task features are capability-negotiated; submit-and-poll is always available. No unverified Claude-specific timeout or extension behavior is a product dependency.

### 5.3 Resources

- `report://{artifact_version_id}` — the released report as JSON plus a Markdown rendering.
- `artifact://{artifact_version_id}` — the frozen definition and metadata.
- `blackboard://{project_id}/summary` — the supervisor's latest plan and the population table.

Tool results reference these resources instead of inlining large bodies. Use the supported MCP resource interface or a paginated read-tool fallback, with authorization rechecked on every access. Cache immutable reports by report ID and invalidate listings as new released reports arrive; no client-specific mention syntax is required.

### 5.4 Transport and auth

Deploy the MCP server in the Docker bundle over Streamable HTTP, publishing the host port on loopback by default; use bearer authentication and project/role checks. Configure private remote access with TLS and appropriate authorization separately. An optional stdio bridge only transports requests and does not own job lifetime. Pin and test the SDK against actual supported protocol generations, including legacy negotiation where needed. OAuth is an extension for clients/deployments that require it; never pass provider LLM keys through as MCP credentials.

Same-host files require an explicit read-only import mount/path mapping, or authenticated uploads with finalized IDs, checksums and size/path/archive controls. Generic host paths are not assumed visible inside a container. See PLAN_ALIGNMENT section F.

### 5.5 Portable host intake instructions

Provide an agent-neutral intake guide usable by Codex and other MCP clients: classify sources, extract business rules, identify prior evidence and exposure, preserve original assets, prepare InputBundle/brief/manifests, resolve required missing fields and submit. A skill wrapper may be added for a client, but cannot become a required Claude SDK or harness dependency. The server validates contracts and never executes uploaded instructions as service policy.

---

## 6. The research plane

### 6.1 Agent runtime choice

Retain closed-tool loops with typed outputs and a deterministic orchestrator. Use the local plan's PydanticAI abstraction with OpenAI-compatible Chat Completions and Responses adapters; a thin OpenAI SDK adapter is the fallback if a provider capability is not represented correctly by the framework. Neither the Anthropic SDK nor Claude Agent SDK is a foundation of this system.

Supervisor planning remains structured and validated, with bounded planning/tool steps and durable external context. Framework/library choices must pass the provider and recovery contracts in PLAN_ALIGNMENT; they do not own the evaluator's permissions.

### 6.2 Roles, tools and models

| Role | Tools | Configurable capability profile |
|---|---|---|
| Supervisor | blackboard/released reports/budgets read; plan/tasks write; human checkpoint | strong planning, reliable tools, long context and durable task reasoning |
| Research-data engineer | manifest/schema read; research-slice queries; propose data products | structured data reasoning and efficient tool use |
| Factor/quant researcher | research evidence/statistics read; propose hypotheses and typed definitions | financial reasoning and report interpretation |
| Performance-report analyst | released reports/population read; interpretation notes write | evidence-grounded synthesis, never private metrics |
| Skeptical reviewer | proposals/research checks read; critique/verdict write | independent scrutiny; no evaluation or promotion authority |
| Factor-code helper and deterministic packager | validate/repair DSL or declared implementation on development data; publish only after deterministic checks | configurable helper model; hashing, freezing and permissions remain code |
| Evolution worker | population/released scores; mutations/recombinations through role tools | deterministic population/selection; configurable LLM variation profiles |
| Literature researcher | authorized search/fetch and notes | optional, with separate external-data authorization |

Models are selected by provider endpoint, exact model ID, capability profile, role profile and task override. Temperature, reasoning/thinking effort, context budget, max output, tools, retries, concurrency and fallback are per profile; unsupported values fail preflight. Preserve requested and effective settings with every call. The same model may serve different roles with different settings or through different infrastructure.

First production acceptance requires online Kimi, GLM and DeepSeek support and a job using all three. The owner's model examples are capability illustrations, not final assignments. OpenAI/Responses can be selected for a compatible supervisor without forcing that provider onto other roles. No local LLM deployment is planned.

Atomic cost reservations, local schema validation, persisted call results and explicit unknown-outcome accounting are mandatory. Cache and batch APIs are optional provider capabilities, not Anthropic dependencies. See PLAN_ALIGNMENT sections C–D and the illustrative `examples/llm-profiles.example.json`.

### 6.3 The research-side sandbox

Research agents are allowed to compute on the development window. They get a research slice (as-of the development end date) and a set of deterministic tools: evaluate a DSL factor on the slice and return Rank IC series, hit rates, turnover and correlation to existing population members; run the prefix test on the slice; profile a table. This is ordinary research hygiene, not official evaluation. It keeps the evaluator's queue short, because obviously broken or duplicate ideas die before publication, and it gives the evolutionary worker a cheap novelty signal. Nothing computed here is ever written to `evaluation` or quoted as performance in a report.

### 6.4 Evolutionary worker design

**What the evidence says first.** The 2025–2026 literature on LLM-driven alpha mining (Appendix B.2) is consistent on four points: in-sample gains mostly vanish out of sample and after costs; "replace the best on any small improvement" loops overfit; LLM mutation chains without real selection collapse to templates while classical subtree mutation does not; and the quality of what comes out depends on the loop and the evaluator far more than on which model writes the code. The design below therefore mixes classical operators with LLM rewrites, forces mechanism diversity, and rewards marginal contribution to the pool rather than standalone scores.

- **Population and archive.** Every published version with a released primary metric, plus seeds (baselines). A quality-diversity archive organized by niche: decision cycle × mechanism family (from the `mechanism_card`) × complexity bucket, so weekly reversal and quarterly breadth ideas do not compete for the same slots and simple factors are not crowded out by complex ones. Archive size around 40–100 members; two or three islands with rare migration (every tenth generation, a small fraction), which published systems found necessary to avoid premature convergence. The `rejected_idea` table doubles as veto memory: before proposing, the worker checks it so dead ideas are not re-proposed.
- **Parent selection.** Use the published weighted rule rather than greedy best: a parent's weight is a sigmoid of its released score's robust distance from the population median, divided by one plus the number of children it already has, so good parents are preferred but over-sampled parents fade. Inspirations shown to the LLM rewrite operator: one elite and one diverse member, ordered from worst to best. Always include at least one baseline and one random alive member per generation.
- **Operators.** Parameter mutation (lookbacks, weights, clip bounds, with step sizes per parameter), operator mutation (swap a time-series operator for a neighbour in the same family), subtree crossover between two DSL parents, and LLM rewrite given two parents' mechanism cards and released outcomes. Target mix roughly 60% small edits, 30% larger rewrites, 10% crossover, adjusted by what produces published children. Each child records its operator in `lineage_edge`.
- **Diversity requirement per generation.** The supervisor requires children to span at least three distinct mechanism themes; published ablations show that dropping this requirement reduces the number of useful mechanisms found and raises pairwise correlation among survivors.
- **Novelty gates before publication.** Structural: AST similarity (largest common subtree against the population and against the baseline feature zoo) and a near-duplicate check on the canonical form. Statistical: correlation of the child's development-slice scores with every alive member above a threshold (0.7 is the published convention) fails the child unless its released outcome later proves incremental. Failing children are recorded as rejected with the reason.
- **Children per generation.** Small, 8–16, because the evaluator's family-wise accounting makes every evaluated version more expensive in evidence terms. Research-side filters (duplicate, correlation, prefix test, fallback fraction too high, complexity cap) remove most candidates before publication.
- **Budgets.** Counted in tokens and in evaluations, not in rounds. Published runs of comparable loops cost between a few and a few tens of dollars and several hours per five-to-ten-generation run; plan the pilot at that scale and run at least three seeds, since seed variance in these loops is large.
- **Stopping.** Configured lineage stagnation may trigger reseeding or review. A job completes only after its frozen delivery gate passes. Budget exhaustion pauses; explicit cancellation ends as cancelled. Total elapsed-time and generation limits are optional, unset by default. A supported negative result may satisfy the delivery gate; no loop is required to manufacture profitable alpha.
- **What the worker never sees.** Per-period details, confirmation results, unrounded metrics, or anything from an optional diagnostic window beyond its labelled flags. It also never sees evaluator configuration.

Appendix B.2 records the external systems whose design choices informed these settings and the failure modes they reported.

### 6.5 Human checkpoints

Human decisions are required for unresolved material intake choices, evaluator protocol freeze, new data/spending outside authorization, private confirmation queries and investment promotion. Existing authorization persists. Periodic one-page summaries need not pause the run; optional review checkpoints and final delivery sign-off are set in the frozen brief. Checkpoints are blackboard tasks of type `human` with the question text, surfaced through `get_job_status` and answered through `answer_checkpoint`.

---

## 7. The evaluation plane

### 7.1 Principles

Deterministic, reproducible, boring. No LLM in the measurement path. Everything the evaluator does is a function of (artifact version, protocol, dataset version, evaluator code hash), and the report carries all four.

### 7.2 Scheduler

A single poller: find registry versions with no `evaluation_status` row for the active protocol, create `queued` rows, process in a fixed order (oldest first, baselines first), under a run budget per day. Research cannot see the queue beyond each version's status. Failures are recorded with reasons and retried a fixed number of times; persistent failures are released as `failed` so research does not wait forever.

### 7.3 Sandbox for artifact execution

Tier 1 definitions run in the evaluator's interpreter. Tier 2 Python and declared package runners execute only in an isolation backend proven on the target Linux/VM and CPU architecture (gVisor is the candidate backend), with all these controls from their first executable release: no network, a read-only root filesystem, all capabilities dropped, no new privileges, a non-root user, memory, CPU and process-count limits, a small writable scratch directory in memory, an external wall-clock timeout, a single size-capped result file, and a fixed interpreter image with pinned libraries. In-process "restricted Python" and browser-style WebAssembly sandboxes are rejected: both had published escapes in 2025–2026 and their authors say they are not security boundaries (Appendix B.4).

**Lookahead prevention by construction, not by inspection.** For each cutoff the evaluator materializes a data slice containing only rows observable at that cutoff into the read-only mount, so generated code cannot see future rows whatever it does. The runner executes the artifact once per decision date with the as-of slice, or, when the artifact declares vectorized support, once with the full history and then verifies prefix consistency on sampled cutoffs. Two further checks run on every Tier 2 version: a perturbation test (alter rows after the cutoff and assert that values at and before the cutoff are unchanged) and a determinism re-run (identical outputs across two executions). Any attempt to read outside the mount, reach the network or exceed limits fails the version with a quality-check flag.

**Knowledge lookahead is a separate problem the sandbox cannot solve.** The language model proposing a factor has read about 2020–2025 markets; a hypothesis such as "coal momentum" may encode hindsight rather than insight. Published work in 2026 shows LLM-generated strategies' backtest performance decaying out of sample relative to point-in-time models. The system therefore records the proposing model's identifier and knowledge cutoff in artifact provenance, labels windows before that cutoff as `knowledge_exposed` in reports, and requires genuinely prospective tracking for claims of unseen performance, while still checking data quality and protocol integrity. For the pilot the source documentation says all history was inspected; model knowledge cutoffs are separately recorded as known or unknown, which is one more reason the pilot's deliverable is evidence and a tracking setup, not a promotion.

**Evaluator assets are never inside any sandbox-writable or research-writable path.** Documented escapes in 2025–2026 came from exposed container sockets, writable host mounts, privileged containers and outbound channels such as an LLM proxy's fetch feature. The evaluator's code, protocol files, scoring data and signing key live under the evaluator OS user with no mount into any container except the read-only slices.

### 7.4 Backtest engine

Port the conventions in Appendix A.4 exactly: publication schedule, first-close execution, exits at the next decision's execution, immature intervals kept as NaN slots, eligibility hash per decision, top and bottom groups with tie-break by name, portfolio drift between events, costs on traded notional at each level, quarterly review rule, paired comparison with explicit `pair_status`, split purging at window boundaries. Acceptance is reproduction of the golden numbers in Appendix A.6.

### 7.5 Uncertainty and multiple testing

- **Trial ledger first.** Every evaluated version, including failures and withheld ones, is a trial. The ledger is the input to every multiple-testing statistic below; omitting failed trials biases all of them toward optimism. A published 2026 experiment also showed that a planted lookahead oracle passes deflated-Sharpe and backtest-overfitting tests, which is why leakage safety in this plan is structural (7.3) and statistics are only the second line.
- **Per-period uncertainty.** Paired circular or stationary block bootstrap on per-period deltas per cycle and window, with the block length chosen automatically by the standard rule and recorded, at least ten thousand draws for official reports, seeds from the protocol, and small-sample warnings as in the pilot's own code. Child-versus-parent differences use a paired studentized bootstrap. For the pilot's golden-number tests the package's exact settings (2,000 or 4,000 draws, fixed blocks) are reproduced as written.
- **Family-wise accounting.** A family is "all artifact versions evaluated under this protocol for this cycle". For each version the evaluator reports: the trial count at report time; a deflated test statistic that uses an effective trial count (clustering correlated trials rather than counting them all); the per-generation probability of backtest overfitting from the generation's period-by-trial matrix; step-down adjusted intervals against the baseline (Holm or Romano-Wolf style, implemented through the stepwise tests in a maintained statistics library); and the version's rank in the family. The selection-aware hurdle is a protocol field; the published convention for new factors is a t-statistic above three or a false-discovery-rate calibrated equivalent, and the hurdle rises as the ledger grows.
- **Placebos.** Calendar-shift placebo as in the pilot's audit, with the resolution of its percentile stated (one over the number of eligible shifts; never report zero), plus a within-date cross-sectional permutation test that asks whether the ranking carries any information at all.
- **Diagnostics as flags.** Leave-one-year-out and placebo results are computed for every version on the validation window and released as flags (all-years-positive yes or no; placebo percentile bucket), not as raw tables.
- **Marginal contribution, not standalone score.** For every version the evaluator also reports the incremental Rank IC after controlling for the baseline pool (the residual of the candidate's cross-sectional scores regressed on the baselines' and current elites' scores, then correlated with returns), the maximum return-correlation to the pool, and the fold-majority flag (improvement over the baseline in a strict majority of yearly folds). Published benchmarks show standalone in-sample IC gains disappearing after neutralization and out of sample; the released gate record therefore leads with these incremental measures.
- **Neighbourhood robustness** for hurdle-passing candidates only: the evaluator re-runs a fixed set of one-step parameter neighbours (the pilot's audit used six) and releases the range as a diagnostic. Neighbours are not selectable but every diagnostic evaluation is logged. Their treatment in multiple-testing statistics is frozen in the protocol; diagnostic labels cannot erase evaluation or feedback exposure.

### 7.6 Success criteria and hurdle

The brief's `success_criteria` becomes the protocol's hurdle. For the pilot: paired primary-metric improvement over the designated baseline on the validation window whose family-adjusted interval excludes zero at the primary cost level; positive incremental Rank IC after controlling for the baseline pool; improvement in a strict majority of yearly folds, with leave-one-year-out point estimates all positive; placebo percentile above a threshold; maximum correlation to the pool below the novelty threshold; turnover below a cap. The evaluator reports hurdle status as a flag with each component's status; it never promotes. The evaluation runs as a cascade: quality checks, then development-window sanity, then validation, with the sealed confirmation window computed last and stored locked.

### 7.7 Release policy

The policy follows two published results (Appendix B.3): the amount of feedback leaked per query matters more than its precision (releasing one score per submission cost about 1.4 points of held-out performance in a 2026 study, releasing eighteen cost over four; coarser feedback delays the harm but does not remove it), and detailed feedback to research agents roughly doubles evaluator-gaming attempts in a 2026 agent study. So the research plane gets one gated scalar and flags, nothing else.

- **Development window:** not evaluated officially (research computes its own).
- **Validation window, one scalar through a Ladder.** For each lineage the evaluator keeps the best released primary-metric value. A new version's primary metric is released only if it exceeds the lineage best by at least one step; otherwise the lineage best is re-released unchanged. The step equals one block-bootstrap standard error of the metric on the window, and released values are rounded to that step. This is a Ladder-inspired policy whose concrete step rule and flags need validation; no theorem about a different setting is assumed to guarantee this implementation. Re-released lineage bests carry the originating artifact ID, never the current child's score.
- **Flags, not metrics.** Alongside the scalar: hurdle component flags (incremental contribution positive, fold majority, placebo bucket, cost-aware net result positive, turnover cap met, novelty threshold met), quality-check flags, and the version's rank bucket in the family. Secondary metrics are released in full only for versions whose hurdle flag is set, and in aggregate (family-level distributions) at the end of each generation.
- **Budgets.** A per-lineage query budget limits how many versions of one lineage can be released per generation; excess versions are evaluated but released later or marked `withheld:budget`. The budget is public to the supervisor so it can plan.
- **Confirmation window:** computed and locked. A human may spend one of a small fixed number of queries per protocol version; the evaluator stores the complete answer privately and releases only the approved decision/category to research, logged with the version id. A human-only report may include its paired interval; it cannot enter research MCP. After a query the confirmation window is treated as burned for that protocol version: further confirmation evidence comes from the forward tracker (7.9) as new data accrue, which is the only way to grow a holdout that nobody has looked at.
- **Optional diagnostic window:** if a protocol defines one, it is released with the same gating, labelled `not_for_selection`, and excluded from parent selection by the evolutionary worker's tool, not by instruction. The pilot defines none (7.10).

The mechanisms borrowed, the constants and their caveats are in Appendix B.3.

### 7.8 Reports and receipts

Each run writes: a JSON report (4.4), a Markdown rendering, a period ledger file, and a receipt with hashes of protocol, dataset manifest, artifact definition, evaluator code and the ledger. Reproducibility check: a second run of the same inputs must produce the same ledger hash; the report records both run ids.

### 7.9 Forward tracking (simulated trading engine)

In an explicitly authorized forward campaign, newly available data produce timestamped signals from frozen definitions; later observations settle those previously recorded signals. Uploading a later historical snapshot cannot retroactively create prospective predictions: missed decisions are labelled replay. The schema exists from day one; the frozen pilot starts no forward campaign. A job requiring forward acceptance may wait for data without a fixed deadline.

### 7.10 Detectability and the pilot's windows

With 31 industries the per-period noise is large and fixed by arithmetic: under no skill, the standard deviation of a single period's Rank IC is about 0.18 and of a single period's top-7 hit rate about 14 percentage points. The number of periods therefore decides what any window can detect. Using the pilot's history (January 2020 to October 2026), the smallest mean effects detectable at a t-statistic of two or three, assuming independent periods, are roughly:

| Cycle | Periods in full history | Mean Rank IC at t=2 / t=3 | Hit rate at t=2 / t=3 (random 22.6%) |
|---|---|---|---|
| Weekly | about 354 | 0.019 / 0.029 | 24.1% / 24.8% |
| Monthly | about 82 | 0.040 / 0.060 | 25.7% / 27.3% |
| Quarterly | about 27 | 0.070 / 0.105 | 28.0% / 30.7% |

The pilot's accepted model P1 improves on P0 by about one percentage point of hit rate and 0.03 of Rank IC in the 2024–2026 window (Appendix A.6). On the full history that is detectable for weekly decisions only; monthly and quarterly improvements of that size cannot be established with this data at any conventional hurdle. A one-year validation window makes it worse by a factor of two to three.

Consequences for the pilot protocol, proposed here and confirmed at the protocol freeze:

- **Windows (candidate pilot configuration, not a clean holdout).** Development 2020-01-01 to 2022-12-31 (research-visible; effectively 2021 onward after warm-up), validation 2023-01-01 to 2024-12-31 (official, Ladder-released), confirmation 2025-01-01 to the data end (sealed, one human query per protocol version, then extended by the forward tracker). No diagnostic window. The pilot's own audit used different windows for the human-era comparison of P0 and P1; the golden-number tests in Appendix A.6 reproduce those windows exactly, while a separately approved research protocol may use these. All periods remain previously seen; sealing changes access, not evidential independence.
- **Minimum detectable effect in every report.** Each released report states, for its window and cycle, the smallest mean effect the window can detect, and the supervisor's planning prompt carries the same numbers, so research effort is not spent chasing monthly or quarterly improvements that no window here can confirm.
- **Weekly is the primary cycle for the pilot.** Monthly and quarterly candidates are evaluated and released under the same rules, but the brief's success criterion applies to weekly; for the slower cycles the deliverable is directional consistency flags plus forward tracking.
- **Overlap and dependence.** Weekly counts are inflated if holding horizons overlap or regimes persist; the bootstrap block length and the effective-trial clustering in 7.5 are the mitigation, and the report states both.

Appendix B.3 gives the derivation and sources for the noise levels and detectability figures.

---

## 8. Technology choices for v1

Shortlist with the reasoning the plan depends on. Versions and current-status notes are maintained in Appendix B, which is the place to update when a choice changes.

| Component | v1 choice | Why | Rejected for now |
|---|---|---|---|
| Language and runtime | Python 3.12, `uv` for environments, pinned lockfile | matches the data stack and the pilot's own pins | mixed-language services |
| Data tables | Parquet files + a Polars or pandas access layer behind the as-of slicing API | small data, columnar, hashable, no server | a database for market data |
| Blackboard, registry index, evaluation records | PostgreSQL 16, three databases and distinct service roles as in the local reference | least-privilege grants, durable state, released feedback through its own API | a shared all-powerful service account |
| Job durability (research service) | deterministic state machine, Postgres leased queue and persisted step results; optional DBOS research-only backend after a spike | combines both plans without binding correctness to a harness or exactly-once paid calls | adding a mandatory workflow server before evidence of need |
| Job durability (evaluator) | plain queue table with leases, idempotency keys and skip-locked claiming | deterministic, cheap to recompute, minimal dependencies for auditability | a workflow framework inside the component that must stay boring |
| Artifact storage | content-addressed files under a registry directory (sha256-named, OCI-compatible digests) + insert-only Postgres index | simple, auditable, matches the pilot's hash culture, a later move to an OCI registry is a rename | DVC (git-coupled dataset tool, now part of lakeFS), lakeFS (server + object store), MLflow registry (model-centric, tracking server) |
| Boundary enforcement | Compose service identities, private networks, role-specific credentials and mounts; no LLM keys in evaluation | portable across Linux AMD64/ARM64 and Docker host VMs; independent evaluator | host peer-authentication assumptions or Anthropic workspace controls |
| Report authenticity | evaluator signs each report and receipt with an Ed25519 key readable only by its OS user (minisign-style); the MCP server verifies before labelling anything official | research-side code cannot forge an official result | unsigned files in a shared directory |
| MCP server | pinned maintained Python MCP SDK, optionally FastMCP, over Streamable HTTP; tested current/legacy clients | standard schemas, authenticated submit/poll/resources and explicit upload mapping | hand-rolled protocol or Claude-only client assumptions |
| LLM access | OpenAI-compatible Chat Completions and Responses adapters; typed PydanticAI loops or a thin OpenAI SDK adapter | online Kimi, GLM and DeepSeek; per-role/task capabilities and settings | Anthropic SDK/harness dependency or local LLM hosting |
| Sandbox | validated target-host backend (gVisor candidate), offline, non-root, read-only, resource-limited and externally timed | same security contract for factors, models and strategies on both target architectures | silently falling back when isolation is unsupported |
| Observability | structured logs; OpenTelemetry traces for LLM calls into a single-container trace viewer (Arize Phoenix, SQLite-backed); per-task token and cost ledger in Postgres; hash-chained event table; Postgres audit extension on the official schema | enough to debug, bill and audit, with nothing heavy to run | multi-service tracing stacks (Langfuse self-hosted needs ClickHouse, Redis and object storage) until a team exists |
| Statistics | `arch` for block bootstraps, automatic block length and stepwise reality-check tests; `statsmodels` for multiple-testing corrections and HAC standard errors; deflated test statistics and probability-of-backtest-overfitting implemented in-repo from the papers with their own tests (they are short) | maintained, permissively licensed, and the in-repo pieces stay auditable | single-maintainer or stale packages for the overfitting statistics (audit before trusting), copyleft forks, and factor-analytics libraries in maintenance mode as dependencies of the evaluator |
| Testing | pytest with the pilot package as a fixture and golden numbers as assertions; property tests for the DSL interpreter's causality | the evaluator cannot be trusted without them | end-to-end LLM tests as the primary test layer |

---

## 9. Repository layout and `AGENTS.md`

### 9.1 Layout

```
repo/
  docs/                      this plan and appendices; architecture decisions
  contracts/                 schema definitions and generated JSON Schema
  data_layer/                canonical tables, manifests, as-of slicing, loaders for the pilot
  dsl/                       expression language, interpreter, canonicalizer, mutation operators
  registry/                  content-addressed artifact store and index
  evaluator/                 protocol, scheduler, sandbox runner, backtest engine, statistics, release policy, CLI
  research/                  blackboard, supervisor planner, worker loops, evolutionary worker, packaging
  mcp_server/                tools, resources, auth, job status
  skills/intake/             optional portable intake wrapper; no vendor SDK dependency
  llm/                       provider adapters, capability profiles and role routing
  configs/                   provider/model/role profiles, jobs, protocols and release policies
  fixtures/pilot/            manifests and licensed local-fixture references; raw data gitignored
  tests/
  deploy/                    multi-platform Compose/images, service roles and sandbox configuration
```

Logical deployment components (Compose isolates credentials and mounts): `research-service` (supervisor loop, workers, packaging) and `evaluator-service` (scheduler, sandbox runner, release). They share a Postgres instance with separate databases/roles; registry and read-only feedback APIs enforce cross-zone access. LLM keys exist only in the research worker.

### 9.2 Rules for `AGENTS.md`

Short, enforceable, and read by the coding agent on every session:

1. The evaluator never imports from `research/`, and `research/` never imports from `evaluator/`. Shared code lives in `contracts/`, `data_layer/` and `dsl/`. Add an import-linter rule.
2. Nothing in `research/` or `mcp_server/` may hold evaluator credentials, connect to eval_db or write official records. Tests assert the role grants.
3. Every evaluator change must preserve independently verified golden evidence. Never update expected values merely to make a test pass; an evidence-backed protocol/oracle change requires a recorded decision.
4. Contracts are schema-first. Change the schema, regenerate JSON Schema, then change code.
5. Every artifact write goes through the registry API. No direct file writes under the registry directory.
6. No LLM call without a budget argument. No LLM output consumed without structured-output validation.
7. The DSL interpreter may only add backward-looking operators; every new operator ships with a causality property test.
8. Do not add features to a phase that is not yet accepted. Finish the acceptance test first.
9. Model identifiers are exact strings from the configuration file; never invent variants.
10. Chinese text in fixtures is data; do not translate or normalize it in code.
11. Read PLAN_ALIGNMENT.md first. Preserve v1 scope; notify the owner before a material goal/scope change.
12. Do not replace a missing provider, elapsed-time wait or failed exit gate with a silent fallback/success state.

---

## 10. Phased build plan

Each phase lists goal, scope, deliverables, acceptance, a kickoff prompt for the local MCP client, and what not to build yet. Effort assumes one developer assisted by a coding agent; treat the numbers as ordering, not commitments.

### Phase 0 — Contracts, fixture and scaffolding (1–2 days)

**Goal.** A repository where every later phase has a place, with the pilot data in place and the contracts defined.

**Scope.** Generic intake, role/provider configuration, durable-job and independent exit-gate schemas from PLAN_ALIGNMENT; multi-platform Docker build strategy; source integrity manifests; Repo layout from 9.1; `AGENTS.md` with the rules in 9.2; contracts for brief, manifest, artifact, protocol, report, blackboard records as schema definitions with generated JSON Schema; references/hashes for the six licensed pilot inputs and label map (local fixtures only; no raw data committed); exact golden values extracted from the original machine-readable ledgers/reference CSVs identified in Appendix A.6; a Postgres Compose file with three databases and distinct roles; `uv` project with pinned dependencies; pytest wired.

**Acceptance.** Schemas validate example documents (one brief, one manifest, one artifact of each kind, one protocol, one report). A test loads each fixture file and checks hash, row count, column names and date range against Appendix A.3. Role grants are created by a migration and a test confirms the research role cannot connect to `eval_db` or mutate official records.

**Kickoff prompt.**
> Read `docs/HYBRID_V1_DEVELOPMENT_PLAN.md` sections 4 and 9 and `docs/appendix-a-pilot-case-industry-rotation.md` sections A.3 and A.6. Create the repository layout in section 9.1, write `AGENTS.md` with the rules in 9.2, and implement the contracts in section 4 as schema classes with generated JSON Schema and example documents. Reference the six pilot inputs as gitignored local fixtures and write a test that checks their hashes, row counts, columns and date ranges against Appendix A.3. Add a Postgres compose file with the three databases and roles and a test proving the research role cannot connect to eval_db. Do not implement any business logic yet.

**Not yet.** No backtest logic, no DSL, no agents.

### Phase 1 — Canonical data layer and parity with the baseline features (3–5 days)

**Goal.** Raw pilot files become canonical tables with an as-of slicing API, and the baseline features are recomputed from raw inputs with exact parity.

**Scope.** Loaders for the six pilot files into the canonical tables in 4.2 with manifest generation and `pit_grade` labels; the as-of slicing service; re-implementation of the six v4 price features (Appendix A.5) and of the P0 weekly, monthly and quarterly feature pipeline, each with a documented formula; a parity test comparing recomputed columns to the corresponding columns in `features.csv.gz`.

**Acceptance.** Recomputed `v4_raw_*` and `v4_p_*` columns match the fixture to 1e-12 on every weekly date. Recomputed P0 cycle scores and ranks match the fixture's `score_*` columns and the `reference_outputs/p60/*_ranking.csv` latest ranks exactly. `slice(upto)` never returns a row with `date` or `available_date` after `upto` (property test). Manifest round-trips: load → write → hash equals recorded hash.

**Kickoff prompt.**
> Implement `data_layer/` as described in section 4.2 of the plan using the fixture in `fixtures/pilot/`. Build loaders that produce the canonical Parquet tables and a manifest with SHA-256, row counts, date ranges and `pit_grade` labels. Implement `slice(dataset_version, upto)` with a property test that no returned row has `date` or `available_date` later than `upto`. Then re-implement the six price features from Appendix A.5 and the P0 weekly, monthly and quarterly scoring pipelines following the business rules in Appendix A.4, and write parity tests against `features.csv.gz` and the p60 ranking reference CSVs. Where you cannot reach exact parity, stop and report the first differing cell rather than loosening the tolerance.

**Not yet.** No evaluation of returns, no DSL.

### Phase 2 — Independent evaluator core (5–8 days)

**Goal.** A deterministic evaluator that reproduces the golden numbers for P0 and P1 under a frozen protocol file.

**Scope.** Protocol file format and freezing CLI (hash, human approval record); publication schedule and execution logic; period evaluation with portfolio drift and costs; quarterly review rule; eligibility hash; paired comparison with `pair_status`; block bootstrap with automatic block length plus the pilot's fixed settings; splits with boundary purging; coverage ledger; the trial ledger and family-wise statistics from 7.5 (deflated statistic with effective trial count, per-generation probability of backtest overfitting, step-down adjusted intervals); minimum-detectable-effect computation per window and cycle (7.10); leave-one-year-out; calendar-shift placebo and within-date permutation test; incremental-contribution metrics; prefix-consistency test harness; report and receipt writer including the report card; reproducibility check (two runs, equal ledger hash). P0 and P1 implemented at this stage as built-in scorers over the canonical tables, not yet as registry artifacts.

**Acceptance.** All Appendix A.6 golden numbers reproduce: primary-window means and Rank IC for the three cycles, 2026 hit rates and coverage, bootstrap intervals with the stated seeds, the six-neighbour ranges, the leave-2026-out monthly difference, and the placebo percentiles. Prefix test passes at the six historical cutoffs. Running the evaluator twice gives identical ledger hashes.

**Kickoff prompt.**
> Implement `evaluator/` per section 7 of the plan and the business rules in Appendix A.4, as deterministic code with no LLM calls. Start with the protocol file and its freeze command, then the publication schedule, period evaluation with drift and costs, quarterly review, pairing, block bootstrap, splits, coverage ledger, the trial ledger with the family-wise statistics and minimum detectable effect from sections 7.5 and 7.10, leave-one-year-out, placebo and permutation tests, and the prefix test. Implement P0 and P1 as built-in scorers for now. Write acceptance tests that reproduce the exact source ledgers/reference CSVs behind Appendix A.6 and fail loudly on the first mismatch. Keep every protocol parameter in the protocol file, never in code.

**Not yet.** No registry polling, no sandbox, no release policy beyond writing full reports to disk.

### Phase 3 — Registry, DSL and sandbox; baselines as artifacts (4–6 days)

**Goal.** Factors become immutable artifacts; the evaluator pulls them from the registry and evaluates them, Tier 1 in-process and Tier 2 in a container.

**Scope.** Content-addressed registry with an index table and an append-only API; the Tier 1 DSL (parser, canonicalizer, interpreter, causality property tests, a first mutation operator set); the Tier 2 constrained context API and static checker; composite artifacts; P0 and P1 as frozen registry fixtures plus generic factor-only, model-only and strategy-only fixtures; dormant P2–P4 definitions remain optional historical provenance; evaluator scheduler polling the registry; sandbox image and runner for Tier 2 with the controls in 7.3 (validated isolation backend, with gVisor as candidate; no network, read-only mounts, dropped capabilities, resource limits, capped output); quality checks (static, prefix, perturbation, determinism, resources).

**Acceptance.** Evaluating the registry versions of P0 and P1 reproduces the Phase 2 numbers exactly. The six v4 features expressed in the DSL match the Phase 1 features to 1e-12. A deliberately leaky Tier 2 artifact (reads a future price) fails the prefix and perturbation tests and is reported `failed:lookahead`. A Tier 2 artifact that tries to open the network or write outside its output directory fails with a resource flag. Two identical definitions yield one `artifact_version_id`.

**Kickoff prompt.**
> Implement `registry/` and `dsl/` per sections 4.3 and 7.3 of the plan. The registry is append-only and content-addressed. The DSL has only backward-looking time-series operators and cross-sectional operators over canonical columns; every operator needs a causality property test. Add the Tier 2 constrained Python context and static checker, and a container sandbox runner using a target-host-validated isolation backend with every control listed in section 7.3, plus the perturbation and determinism checks. Register P0/P1 and the generic executable fixtures as artifacts without fitting dormant historical candidates and make the evaluator poll the registry and evaluate them, reproducing the Phase 2 numbers. Add negative tests: a lookahead artifact must fail the prefix test and a network-using artifact must fail with a resource flag.

**Not yet.** No release policy, no blackboard, no agents.

### Phase 4 — Blackboard, release policy, MCP front door and intake skill (3–5 days)

**Goal.** The system can be driven end to end by a human through the local MCP client, with no research agents yet.

**Scope.** Blackboard tables and event log (4.5, 4.6); released views and the release policy (7.7): Ladder gating with a bootstrap-standard-error step, flags, per-lineage budgets, the locked confirmation table and the human-only confirmation query command in the evaluator CLI; report signing by the evaluator and signature verification in the MCP server; MCP server with the tools and resources in section 5; documented Codex and generic MCP client connection examples with placeholder credentials; the intake skill with the folder taxonomy, brief and manifest drafting, and the tool call sequence.

**Acceptance.** From a fresh Codex session with the pilot folder, the intake skill produces a brief and manifest matching Appendix A.8, registers the dataset and baselines, proposes the protocol; the human freezes it in the CLI; `list_reports` then shows released reports for P0 and P1 containing only the gated scalar and flags, with confirmation fields absent and valid signatures. A test confirms the research role cannot select from unreleased tables. A simulated adaptive noise submitter verifies release-step/budget invariants and reports false positives under a predeclared statistical test; zero improvements is not a universal requirement. Submitting the same brief twice with the same idempotency key creates one job.

**Kickoff prompt.**
> Implement the blackboard and event log from sections 4.5 and 4.6, the release policy from section 7.7 (Ladder gating, flags, per-lineage budgets, locked confirmation table, signed reports), and the MCP server from section 5 using a pinned maintained Python MCP SDK (FastMCP optional) over streamable HTTP on localhost with a bearer token. Then write `skills/intake/SKILL.md` for the local MCP client following section 5.5 and Appendix A.2, A.8. Prove the end-to-end path manually with the pilot folder and add tests for role separation, Ladder gating against a noise submitter, signature verification and idempotent job submission. Research agents are not part of this phase.

**Not yet.** No LLM research loops.

### Phase 5 — Supervisor and specialist workers (5–8 days)

**Goal.** A brief produces published artifact versions from LLM workers under budgets, with human checkpoints, using the released feedback.

**Scope.** The deterministic generation workflow with durable step checkpointing (4.6); closed-tool worker loops for the roles in 6.2; supervisor planning call with structured plan output; task lifecycle on the blackboard; research-side sandbox tools on the development slice (6.3); packaging agent that freezes, checks and publishes; token budgets and accounting per task; prompt-caching layout; structured outputs everywhere; capability-checked, operator-allowed provider fallbacks; checkpoint tasks surfaced through MCP.

**Acceptance.** Given the pilot brief, one generation runs end to end: the supervisor plans, the factor researcher proposes at least six Tier 1 hypotheses in the price/volume family, the reviewer blocks at least one with a written reason, packaging publishes the rest, the evaluator releases reports, the analyst writes interpretation notes citing report ids. Every LLM call is logged with tokens and cost; the generation stays under its budget; a deliberately leaky proposal is caught by the packaging prefix test before publication. No official record in `eval_db` was written by the research role (assert by audit log).

**Kickoff prompt.**
> Implement research roles through the typed OpenAI-compatible adapter described in section 6 and PLAN_ALIGNMENT sections C–D. Use configurable endpoint/model/role/task profiles; implement Kimi, GLM and DeepSeek conformance and a mixed-provider fixture. Validate tools and structured outputs locally, enforce atomic budget reservations, preserve effective settings and checkpoint completed results. Run offline scenarios first; execute paid provider smoke only with operator-authorized credentials and spend. Show released reports, notes, routing evidence and the cost ledger.

**Not yet.** No evolutionary operators beyond what packaging needs; no multi-generation loop.

### Phase 6 — Evolutionary worker and the closed loop (5–8 days)

**Goal.** Multi-generation research under the release policy, with population management, diversity and stopping rules.

**Scope.** Population and lineage records; niche archive with islands (6.4); parent selection with the weighted rule from released Ladder scores plus development-slice diversity; mechanism cards and the per-generation mechanism-diversity requirement; novelty gates and veto memory; mutation and crossover operators over the DSL; LLM rewrite operator with two parents; per-lineage query budgets honoured; stopping rules; optional batch generation through a capability-tested provider adapter; supervisor re-planning across generations; periodic progress summaries and only the human checkpoints selected in the brief.

**Acceptance.** A ten-generation run on the pilot completes within budget without human intervention except the configured checkpoints; the population table shows lineage edges with operators; no lineage exceeds its release budget; duplicates and highly correlated children are filtered before publication; a kill switch (pause through MCP) halts research within one task boundary while evaluation of already-published versions continues. The run's final summary states hurdle status for every alive member.

**Kickoff prompt.**
> Implement the evolutionary worker from section 6.4 and connect it to the supervisor loop so the system runs for multiple generations under the release policy of section 7.7. Add population, niche and lineage records, the weighted parent-selection rule combining released Ladder scores with development-slice diversity, mechanism cards with the diversity requirement, novelty gates and veto memory, DSL mutation and crossover operators, an LLM rewrite operator, per-lineage release budgets and stopping rules. Use a provider batch API only when the selected profile supports it; ordinary requests remain a complete path. Run ten generations on the pilot and produce the final summary with hurdle status per candidate.

### Phase 7 — Pilot run and honest report (1–2 weeks of runs and analysis)

**Goal.** Use the system on the real task and produce evidence a skeptical reader would accept.

**Scope.** Full run with the pilot brief; constraints: price, volume and breadth families only, fundamentals marked blocked on data; supervisor budget sized to the number of trials the family-wise accounting can absorb; at least three seeds; one confirmation query at most, spent by the human; final shortlist export; a written report comparing the best candidates with P1 and P0 on validation, with diagnostics, and a clear statement of what remains unknown.

**Control arm.** Run a matched-token-budget control in which children are proposed independently from the brief without parent feedback (no evolution), evaluated under the same protocol and counted in the same family. The brainstorm asks for A/B comparisons of collaboration mechanisms; this is the first one, and the published evidence (Appendix B.2) suggests the evolutionary advantage at matched budget may be small. The report states which arm produced the shortlist.

**Acceptance.** All PLAN_ALIGNMENT AC-01–AC-14 requirements pass with recorded evidence, including native AMD64/ARM64 and mandatory-provider checks. The report is generated from the registry and released records only; every number is traceable to a report id; the confirmation query, if spent, is logged; the leave-one-year-out and placebo flags are shown for every shortlisted candidate; the report states explicitly whether any candidate cleared the hurdle.

### Phase 8 — Extensions and continuing operations

Core isolation, signed releases, provider budgets, backup/restore, restart recovery and both-architecture readiness are required before the production acceptance in Phase 7, not deferred here. This phase extends the proven system: optional dashboard, additional data/runner adapters, explicitly enabled forward tracking and monitoring, stronger multi-user auth, and a separate v2 design review for parallel lanes/composition. New remote infrastructure or hosted sandboxes requires a documented need and approved access policy.

---

## 11. Verification strategy

- **Golden-number tests** (Appendix A.6) are the evaluator's definition of correctness. They run on every change under `evaluator/`.
- **Parity tests** between recomputed features and fixture columns guard the data layer.
- **Causality property tests** for every DSL operator and for the slicing API: perturbing any future row must not change any past output.
- **Prefix tests** at historical cutoffs for every artifact, both research-side (development window) and evaluator-side (all windows).
- **Boundary tests**: role grants, import-linter rules, an attempted write from the research role, an attempted evaluator call from a research tool.
- **Negative artifacts** in the fixture: lookahead, network, filesystem escape, non-deterministic, oversize output; each must fail with the right flag.
- **Idempotency and crash tests**: kill a worker mid-task and confirm the lease expires and the task resumes without duplicate artifacts.
- **Cost tests**: a generation must stop at its token budget; tests use a mocked model client.
- **Statistical self-tests**: the in-repo deflated statistic and probability-of-backtest-overfitting implementations are checked against published worked examples; the Ladder is checked for step/budget/version-attribution invariants and calibrated error behavior under an adaptive noise submitter; the minimum-detectable-effect calculation is checked against the closed-form null variances in 7.10.
- **Agent tests** are the smallest layer: a recorded transcript per role to catch prompt regressions, not a correctness oracle.

---

## 12. Risks and mitigations

| Risk | Mitigation |
|---|---|
| The pilot data are too weak to show anything; the loop converges to noise | Coarsened releases, per-lineage budgets, family-wise accounting, stopping rules; the report says "no candidate clears the hurdle" without embarrassment |
| Lookahead through code paths the DSL does not control | Tier 2 runs only in the evaluator sandbox on as-of views; prefix tests mandatory; negative fixtures |
| Research agents probe the Ladder step or the flags with near-duplicate versions | One scalar only, Ladder re-releases the lineage best unless beaten by a full step, budgets per lineage, duplicate and correlation gates, the confirmation window never released automatically |
| Scope creep into v2 (lanes, composition) before v1 is trusted | Phase gates with acceptance tests; `AGENTS.md` rule 8 |
| Cost blowups from long agent loops | Budgets enforced in code, batch generation, prompt caching, cheaper models for mechanical roles, kill switch |
| Protocol drift: parameters creep into code | Rule in `AGENTS.md`; protocol hash in every report; freeze command refuses unapproved hashes |
| Sandbox escapes on a shared workstation | Target-host-validated isolation backend (gVisor candidate), non-root, no network, read-only mounts, dropped capabilities and resource limits from the first version; never expose the container socket, never mount a writable host path, never run privileged; evaluator assets outside every sandbox path |
| Knowledge lookahead: the model has read about the historical period it is asked to predict | Record model id and knowledge cutoff in provenance; label exposed windows in reports; treat forward-tracked evidence as the only clean evidence; keep the pilot's deliverable framed as evidence plus a tracking setup |
| Agents tamper with or game the evaluator (documented in 2025–2026 agent evaluations) | Evaluator locked away from research-writable paths; prefix, perturbation and determinism checks; hidden confirmation window; signed reports; budgets that make probing expensive |
| The evolutionary loop adds little over independent proposals or parameter tuning, or collapses to templates | Classical operators mixed with LLM rewrites; mechanism-diversity requirement; veto memory; matched-budget control arm in the pilot; incremental-contribution metrics instead of standalone scores |
| Chinese and English artifacts confuse the intake agent | Key on codes, keep names as labels, taxonomy in the intake skill, human confirmation of brief and manifest |
| The user's MCP client times out on long tool calls | Submit-and-poll design, progress notifications, resource links for large bodies |

---

## 13. Deployment and job choices still to record

The architecture, on-demand Docker deployment, generic intake and online Kimi/GLM/DeepSeek support are settled requirements. These remaining choices are configurable and do not reopen them.

1. **Target host/VM and sandbox backend:** support Linux AMD64 and ARM64, and prove native runtime/isolation on each. Docker Compose remains the deployment bundle.
2. **Windows, Ladder step and query budgets for the pilot protocol** (7.7, 7.10). Proposed: development 2020–2022, validation 2023–2024, confirmation 2025 to data end; step equal to one bootstrap standard error; one confirmation query per protocol version. Confirm or change before the protocol freeze.
3. **Whether fundamentals are in scope for the pilot at all.** The plan says blocked on data. If a grade-A or grade-B fundamentals table can be produced by a human-authorized data step, it enters as a new dataset version.
4. **Endpoint/model/role profiles and spending authorization:** select exact model IDs and tested capability settings per role/task; OpenAI-compatible access is fixed, not a Claude runtime choice.
5. **Confirmation query count** per pilot run (proposed: one).
6. **Whether to include the literature researcher in v1** or defer it.

---

## 14. Glossary

- **Artifact version:** immutable version ID plus content hash for a factor, model, strategy, research note or data product, with a declared implementation.
- **As-of slice:** a view of the dataset containing only rows observable at a given date.
- **Development / validation / confirmation windows:** date ranges with different access rules; only development is visible to research agents in raw form; validation feeds the Ladder; confirmation is sealed. A protocol may add an optional diagnostic window that is never used for selection.
- **Minimum detectable effect:** the smallest mean improvement a window can establish at a stated t-statistic given its number of periods; reported with every release.
- **Ladder:** release rule under which a lineage's score only updates when a new version beats the lineage's best by at least one step.
- **Family:** the set of artifact versions evaluated under one protocol for one cycle; the unit of multiple-testing accounting.
- **Prefix test:** recompute signals from data truncated at a cutoff and assert equality with the full-history run at the same date.
- **Release:** the projection of an official report that research agents may read.
- **Hurdle:** the protocol's definition of a success, reported as a flag, never as a promotion.
- **PIT grade:** a label (A to D) on inputs and artifacts describing how trustworthy their timing is; see 4.2.
