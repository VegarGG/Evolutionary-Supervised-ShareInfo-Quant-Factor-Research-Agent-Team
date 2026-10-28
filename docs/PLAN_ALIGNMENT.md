# Hybrid v1 plan alignment — requirements and acceptance contract

Revision 1.2 · October 27, 2026 · Planning specification, not a production acceptance

This amendment aligns the repository development plan and the nine-chapter local QFR plan with the owner's requirements. It preserves supervisor–worker coordination, the shared research blackboard, evolutionary candidate development, immutable publication, and an independent deterministic evaluator. It does not introduce Hybrid v2 research lanes, autonomous portfolio construction, broker trading, or local LLM hosting.

## A. Authority and preserved scope

Precedence is: the owner's current instructions → the Hybrid v1 architecture in [Quant Research System Brainstorming](https://chatgpt.com/space/page_01cc4d43aa90819196816d335c0e6f1c) → this alignment contract → the two plans' applicable details. The repository main plan remains the ordered build plan. The local chapters retain their detailed DSL, database, evaluation, evolution and test specifications; their daily-stock assumptions belong to the named `stock_daily_v1` profile. The repository pilot belongs to `pilot_industry_v1`. Neither profile silently becomes the universal product contract.

Sources reviewed: repository commit `89f39f66b0314549cfe4d12c4054106aaab97b6e`; all nine original local chapters; the Page's sequence 8 (Hybrid v1, with its separate v2 section excluded); both October 22 P0/P1 packages' README, model descriptions, replay entry and integrity manifests; repository Appendices A and B. Original repository text is recoverable from that commit. The original local chapters are preserved outside the plan renderer in `alignment-review/original-local-plan/`. No sample code, data, outputs or accepted baseline is changed by this planning revision.

| Requirement | Aligned commitment | Acceptance evidence |
|---|---|---|
| R1: Hybrid v1 multi-agent research and evolution | Preserve the research/evaluation boundary, roles, blackboard, population, lineage and released-feedback loop | Boundary tests; one trace from hypothesis through publication, independent report and a justified revision |
| R2: Apple ARM64 and Linux AMD64 deployment, Apple first, same-computer agent access | First target: macOS on Apple Silicon, using the Mac Studio's existing Docker Desktop; second target: Linux AMD64. One Compose bundle with `linux/arm64` and `linux/amd64` container images, standard MCP front door | Native host acceptance per target, with host OS/CPU distinct from container OS/CPU; Apple release first, Linux AMD64 readiness claimed only after its separate native validation; Codex MCP import-to-export demonstration |
| R3: Work on call until deliverables pass an exit gate | Explicit durable jobs, no compulsory continuous service schedule, no default total elapsed-time or generation ceiling | Disconnect/restart/resume and exit-gate tests; failed/budget-paused jobs cannot appear completed |
| R4: Packages and standalone ideas, factors, models or strategies | One typed input envelope with type-specific adapters; missing information remains explicit | Separate idea, factor-only, model-only, strategy-only and P0/P1 package fixtures |
| R5: Online, heterogeneous, tunable LLMs | OpenAI-compatible provider boundary; Kimi, GLM and DeepSeek required in first production-ready release | Individual provider conformance records and a mixed-provider job, including role-specific settings |
| R6: Optimization rather than a goal rewrite | Keep both plans' useful detail; record conflict resolutions and scope limits below | Reviewable diff, unchanged source backups and sample manifests, synchronized alignment text |

## B. Explicit reconciliation decisions

| Topic | Repository plan | Local plan | Resolution and reason |
|---|---|---|---|
| Architecture | Hybrid v1 with MCP and pilot | Same core with detailed services | Retain both; MCP is a required product entry point |
| LLM runtime | Anthropic tool runner, Claude models and workspace assumptions | PydanticAI and configurable strong/fast tiers | Typed closed-tool loops through an OpenAI-compatible adapter; PydanticAI retained as the implementation default, with a thin OpenAI SDK adapter where needed |
| Agent client | Claude Code intake and configuration | API/CLI, later dashboard | Codex and other conforming MCP clients; no required Claude installation, SDK, subscription or configuration |
| Durability | DBOS step checkpoints | Deterministic state machine and Postgres queues | Retain deterministic state transitions and durable Postgres records; DBOS is an optional research-only checkpoint backend after a capability spike, not an evaluator dependency |
| Deployment isolation | Host OS users and peer auth | Compose services and three databases | Compose service identities, networks, mounts and three databases/least-privilege roles; no assumption that host peer auth works across containers |
| Input scope | Pilot folders, factors and fixed composites | DSL factors first; strategy/Python later | Generic intake plus executable factor/model/strategy adapters are required for production v1; advanced autonomous composition remains v2 |
| Data/universe | 31 industries and uploaded caches | CSI 300 daily community data | Case-specific protocol profiles; uploaded P0/P1 is the first acceptance fixture, stock research remains an optional supported profile |
| Lifecycle | Finite pilot, optional forward tracking | Recurring generations, ingest and mandatory forward promotion | On-demand research delivery by default; forward promotion is a separately selected acceptance objective, never silently removed |
| Feedback/fitness | One Ladder scalar plus flags | Multiple coarse metrics used by fitness | Release policy and fitness profile are bound together at job freeze; selectors cannot use metrics the selected policy withholds |
| UI | MCP only | Dashboard in local Phase 7 | MCP required; dashboard remains an optional operator feature with its existing role boundaries |
| Model/SDK versions | Exact Claude assumptions and third-party version notes | Generic model IDs | Model identifiers, capabilities, price snapshots and SDK versions are deployment configuration verified by conformance tests |
| Pilot confirmation | Sealed historical period, with inconsistent unseen claims | Private W3 and future W4 | Access isolation does not erase prior exposure. Pilot history is previously seen; it cannot establish unseen confirmation |

The first production milestone therefore includes both Linux image variants, native acceptance on the Apple host, MCP, generic intake, model/strategy execution, online provider conformance, durable recovery and delivery validation. Native Linux AMD64 validation follows as a separate target acceptance and does not gate the first Apple release. These are promoted from missing/later items only where the owner's requirements require them. Existing statistical gates and optional extensions are preserved under named profiles; they are not silently relaxed or all made prerequisites for every input kind.

## C. Two independent compatibility boundaries

**MCP is the external agent-to-system protocol.** It is vendor-neutral JSON-RPC with typed tools/resources. It is not an OpenAI chat endpoint, and its origin does not require an Anthropic runtime. Codex performs local interpretation and invokes the system; the internal research agents use their own configured online providers. External-client model choice never selects all internal worker models implicitly.

**OpenAI compatibility is the internal LLM access contract.** Support both `openai_chat_completions` and `openai_responses` adapters behind one normalized request/result interface. Chat Completions is the portable baseline for the three required providers; Responses is enabled for endpoints/models with tested support, including models whose tool calling requires it. Do not assume the two wire formats or all provider features are interchangeable. Do not implement a new public LLM proxy merely to satisfy this requirement.

Provider adapters normalize text, tool-call identifiers/arguments, tool results, structured-output validation, usage, finish reasons, errors and streaming completion. Preserve provider-required continuation items in the provider's session record; do not pass provider-specific reasoning state to a different provider. Reject or explicitly map unsupported settings before a paid call. A successful HTTP response is insufficient evidence that a parameter took effect.

Caching, batch submission, hosted tools, server-side conversation state and native schema enforcement are optional capabilities, not required foundations. Tool execution and authorization remain in our deterministic tool layer. Schema validation is always local, including after provider-native structured output; bounded repair attempts consume budget. An unsupported feature cannot silently reduce the requested validation or tool-permission guarantees.

## D. Provider, model and role configuration

The first production release MUST support online APIs from Moonshot/Kimi, Z.ai/GLM and DeepSeek, and MUST demonstrate all three participating in one job. An OpenAI provider profile is also supported by the adapter design but an OpenAI account is not required to run the mandatory three-provider configuration. GPT-6 Astra, Kimi K3, DeepSeek v4.1 Flash and GLM 5.3 Flash are capability examples supplied by the owner, not fixed role assignments or invented API model IDs.

Configuration has four levels: **provider endpoint → model capability profile → role profile → task override**. Effective settings are frozen and hashed when a task is admitted. A changed profile creates a new task/config revision; it never retrospectively relabels an existing result.

| Configuration group | Required configurable fields |
|---|---|
| Provider connection | Provider/vendor ID, endpoint ID, base URL, API dialect, secret reference, region/account label, connect/read/idle timeouts, retry/backoff and concurrency/rate limits |
| Model capabilities | Exact model ID, documented context limit and output limit, supported input modalities, tool calling, structured-output mode, streaming, reasoning/thinking settings, compatible sampling parameters, optional batch/cache support |
| Role/task policy | Provider + model profile, prompt template/version, tool allowlist, temperature, top-p, reasoning effort/thinking budget, output-token limit, tool-turn cap, context allocation/compaction policy, pricing snapshot, budget reservations, fallback allowlist |
| Audit | Requested and effective settings, source of overrides, capability-test revision, provider/model/endpoint actually used, prompt/config hash, usage/cost with unknowns explicit, retry/fallback events |

Settings may be unset where the provider controls them; unset is distinct from zero. Different roles may use the same model with different supported settings or route the same model through different endpoints. Invalid combinations fail preflight with a field-specific explanation. No global environment override may accidentally collapse all role assignments to one model.

Suggested role capabilities, without prescribing vendors: supervisor needs reliable planning, tool use, long context and durable-task reasoning; quant researcher needs financial reasoning and report interpretation; critic needs independent scrutiny; data/packaging helpers favor speed and structured output. Deterministic validation, hashing, scheduling and official measurement use no LLM.

Long tasks use external durable memory: versioned brief, current plan, evidence references, accepted decisions, unresolved questions and checkpoint summaries. Context limits and compaction thresholds are per role; preserve cited source references and the ability to retrieve originals. A large model context window does not replace durable state.

Fallback is allowed only within an operator-configured provider/model allowlist that satisfies the role's capability and data-sharing policy. Log its cause and effective settings. Otherwise enter `needs_input` or a retryable failure. Never silently switch to Claude, a local model, an unapproved endpoint, or an endpoint lacking required tools.

Use secret references/environment injection, never credentials in briefs, manifests, prompts, logs or exported bundles. Only research workers receive LLM keys. Cost reservations are atomic across concurrent calls and reconcile actual usage; unknown prices/usage remain unknown and require a conservative configured reservation. Provider account limits are supplementary. Budget exhaustion checkpoints work and requests continuation; it is not a successful exit and must not silently renew a daily allowance forever.

## E. Generic intake contract

The host agent inventories and interprets user-supplied material, preserves originals, and prepares an `InputBundle`. The server validates that bundle; neither filenames nor the host agent's prose count as authority to execute code or change evaluation policy.

| Field | Contract |
|---|---|
| `schema_version`, `input_kind` | Versioned envelope; kind is `idea`, `factor`, `model`, `strategy` or `bundle` |
| `objective`, `requested_deliverables` | Requested research/change, frozen-baseline preservation rules, required files and evidence |
| `source_assets` | Immutable upload/mounted-import references, hashes, media type, provenance and intended use; source text/code is data, not service instructions |
| `definition` | Type-specific formula, model specification/weights/entrypoint, strategy rules, or natural-language hypothesis; no fake empty executable for an idea |
| `data_refs`, `data_requirements` | Existing authorized dataset IDs or required fields/universe/frequency/availability; can be unresolved at intake |
| `baseline_refs` | Optional exact versions; required only when the chosen comparison objective needs them |
| `execution_contract` | For executable inputs: runner/image digest, dependency lock, command/function interface, input/output schemas, seeds and resource limits |
| `exposure_and_quality` | Previously inspected periods, training/tuning history, PIT limitations, licence/use constraints, unknowns |
| `job_config` | Role-profile references, permitted data/provider access, cost authorization, stop/pause policy, proposed exit gate and human checkpoint policy |
| `protocol_proposal_ref` | Non-authoritative draft; an evaluator owner separately freezes the official protocol |

An idea can be normalized and accepted for clarification before a dataset exists. It becomes runnable only when its data and evaluation requirements are resolved. A factor does not need a pre-existing model; a model does not need factor decomposition; a strategy does not need to be reduced to a factor expression. Missing execution prices, labels, weights, calendars or business rules yield `needs_input` or `waiting_for_data` (with a `blocked_on_data` reason), never invented values or silent substitutions.

Keep semantic kind separate from representation: `factor`, `model`, `strategy`, `research_note`, `data_product`; implementations include DSL, constrained Python, fixed composite, or a declared package runner. Preserve model weights, preprocessing, fallback logic, fit/inference distinction and serialization requirements. Strategy execution preserves position/state rules, costs and rebalance timing. Existing strategies/fixed composites are supported in v1; autonomous discovery of new multi-lane composition is still v2.

Use one common immutable manifest plus type-specific payload schema and evaluator plugin. Each kind declares eligible protocols, deterministic checks, output schema and released-report mapping. Reject unsupported executable formats explicitly; no format is accepted merely because it is Python or a ZIP. Unsafe deserialization and source code are inspected/executed only in the approved sandbox.

P0 and P1 are preservation/reproduction fixtures. Retain each original package, its six inputs, 24 reference business CSVs, raw labels and archived data. P1's cached P0 comparison CSV is a dependency, not authorization to run P0 or fit P3/P4. Historical P2–P4 definitions are optional provenance, not mandatory pilot models. Published challengers receive new versions; the accepted P1 is never overwritten or automatically replaced.

## F. MCP and file transfer

Use Streamable HTTP for the Docker endpoint, published on the host's loopback address by default. The service may listen on its container interface while Docker maps only `127.0.0.1:<port>` on the host. Private remote access is a separate deployment setting with TLS/authentication. Optional stdio is a small client bridge; loss of that bridge does not kill durable jobs. Test actual supported protocol versions with the pinned SDK and clients; do not equate one Claude client's behavior with the MCP specification.

Required tool families: project/setup and input validation; dataset/baseline registration; protocol **proposal**; research submit/status/pause/resume/cancel; registry reads; released-report reads; blackboard reads; human checkpoint answers; delivery/shortlist export. A factor-only job may omit baseline registration. Stable job IDs and caller-supplied idempotency keys are required. Same key plus different payload is a conflict.

Submission returns promptly after admission with job ID, status, next action and polling guidance. It never holds one tool call open until research finishes. Application job state is independent of MCP connection/session state; optional protocol task features may be added only after capability negotiation. Disconnecting or cancelling a status request does not cancel a committed job. If a submit acknowledgement is lost, repeating the same key recovers the same job.

Tools declare JSON schemas, concise structured results and small human-readable summaries, with paginated resources for large reports. Annotations describe actual semantics and are not authorization. Handler checks enforce project/role access on every call. MCP exposes no protocol activation, evaluation scheduling/cancellation, private holdout read, official-record write, or promotion command.

Same computer does not imply the same filesystem namespace. Files reach the container through either an explicit read-only import mount with a path mapping or an authenticated upload endpoint whose finalized upload ID is passed to MCP. Use declared size/hash limits, chunking when needed, checksum verification, staging then atomic finalization, and path/symlink/archive-expansion validation. Never accept an arbitrary host path, `../` escape, or undeclared URL fetch. Do not base64 entire model packages into an LLM/tool context.

Imported packages remain quarantined until inventory and schema checks pass. The trusted data-ingest component builds permitted research slices; research workers never mount the original full dataset or private evaluator assets. Record any historical data already exposed to the host agent: later access restrictions cannot make it unseen.

Exports contain frozen artifact payloads, checksums, dependency/config references, source/data manifests, public protocol cards, **released** reports, provenance and the delivery receipt. Full private protocols, unreleased records, holdout data and secrets remain evaluator-only. The evaluator may provide a separate authenticated operator export outside the research MCP surface.

## G. On-demand lifecycle and exit gates

A deployment is available when the operator starts it; no new research job, licensed-data fetch or forward simulation starts merely because containers are alive. Keep durable state in named volumes. An active job may run for minutes, days or longer. Default `max_wall_clock` and `max_generations` are unset; per-call timeouts, sandbox resource limits, authorized spend and evaluator query limits remain necessary controls.

Job states: `received → validating → ready → running → awaiting_evaluation → validating_delivery → completed`. Explicit side states are `needs_input`, `paused`, `budget_paused`, `waiting_for_data`, `failed`, and `cancelled`. Research generation state and evaluator run state remain separate records. A stopped generation is not a completed job. Pending evaluator work is awaited through released status; research cannot drain, accelerate or cancel the evaluator queue.

The brief freezes an **exit-gate specification** before execution: required deliverables and schemas, applicable protocol/checks, reproducibility criteria, evidence-release requirements, allowed conclusion types, and any human sign-off. The independent deterministic delivery checker validates it and emits an immutable receipt linked to exact artifact, data, protocol, configuration and report versions. The supervisor can propose completion but cannot mark its own work accepted.

Default gate type is `research_delivery`, following the repository plan's evidence-first objective. It can pass with a supported positive or negative result, including an empty shortlist, only when that conclusion is allowed by the frozen brief and all required checks/artifacts are present. A data-blocked report can count only if the requested deliverable explicitly permits it. An exhausted budget, crash, unresolved required input or missing evaluator report cannot be relabelled successful.

`investment_promotion` is a different, explicitly selected gate. It retains applicable private holdout, prospective forward evidence and human approval. Historical replay cannot substitute for forward incubation. If the selected gate needs new observations, the job stays `waiting_for_data`; there is no hidden elapsed-time cutoff. New data can be imported on demand, and the tracker settles only legitimately recorded prospective signals. Historical catch-up for dates with no contemporaneously recorded signal is labelled replay, not forward evidence.

After a valid delivery receipt, stop creating research tasks and close task-owned work. Results remain retrievable, and the deployment may idle or be shut down by the operator without deleting volumes. A job does not stop other active jobs or an independently authorized evaluator/forward campaign. Periodic monitoring, daily ingest and live clocks remain opt-in operating profiles, not first-release prerequisites.

Crash recovery checkpoints completed tool results, LLM responses, artifacts and state before subsequent work. Use leases and fencing to prevent duplicate commits. Local side effects are idempotent; a provider timeout after accepting a request can still have incurred cost. Preserve an `outcome_unknown` attempt and bounded retry policy rather than claiming exactly-once billing. A client session is never the only copy of progress.

## H. Docker and architecture acceptance

The owner clarified the deployment goal on October 27, 2026: **macOS on Apple Silicon (ARM64), first on the Mac Studio with its existing Docker Desktop; Linux AMD64 remains the second supported deployment target.** These are host OS/CPU targets. Docker Desktop's Linux ARM64 engine and containers are implementation details, not a replacement deployment target or proof of Apple host acceptance. No separate VM, alternate backend or host/runtime/security reconfiguration is authorized by this correction.

Ship a Compose bundle with separately scoped MCP/research, registry, evaluation/feedback and database services; service packaging may combine modules only when credentials, mounts and permissions remain isolated. Docker deployment does not require placing mutually untrusted roles in one privileged container.

Build `linux/arm64` images for Docker Desktop on Apple and `linux/amd64` images for Linux AMD64 from the same source and dependency locks, and record platform-specific digests plus native/emulated build mode. Building both variants remains required; an emulated AMD64 build on the Mac is not native Linux AMD64 acceptance. No local LLM weights, Ollama server, GPU or CUDA dependency is required. Online inference egress belongs only to research workers. Persist databases, immutable artifacts, checkpoints and authorized datasets outside container writable layers. No credentials or licensed pilot data are baked into images or committed as fixtures.

Use the local plan's three databases and distinct least-privilege roles; research accesses official feedback through the read-only feedback service. Do not expose a shared superuser credential or assume import-linter alone enforces a runtime boundary. Evaluator signing keys and full datasets are never mounted into research, MCP or artifact sandboxes. MCP verifies signed released reports before labelling them official.

Untrusted Python/package execution requires the planned no-network, non-root, read-only, dropped-capability, resource-limited sandbox with external timeout and capped output. The owner-approved ordinary-Docker backend (S3-26) accepts residual shared-kernel risk and grants Docker API access only to a trusted evaluator controller. Retain historical gVisor profiles without making them an Apple deployment prerequisite. Prove the backend through the actual deployment on each host target: the existing Docker Desktop on the Mac first, native Linux AMD64 separately. An unavailable isolation backend fails readiness for that artifact kind; do not silently fall back to unsafe execution or call a DSL-only deployment fully production-ready for the requested model/strategy scope. Any alternate backend needs an explicit decision and equivalent boundary tests. Docker-native implementation and actual Mac compatibility remain subject to all SBX and Registry pilot gates. The controller grant does not authorize additional host/security changes.

Reproduction is byte/hash exact within a pinned runtime where promised by the source package. Across CPU architectures, define numerical comparison rules in advance: exact identifiers, ranks, membership, counts and schemas; declared tolerances for floating values; independent hashes of each runtime's outputs. Do not claim all BLAS/Parquet bytes are inherently architecture-independent, round away differences, or weaken a failing P0/P1 oracle. Record host OS/CPU, Docker engine/container OS/CPU, runtime and image identity, and native/emulated execution separately. A Linux CI runner or ARM64 container suite alone cannot establish macOS acceptance.

**Acceptance order.** Stage 7/M5 first accepts AC-01–AC-14 in the Apple deployment scope. AC-11 requires ARCH-01, sandbox readiness and all numerical/oracle checks on the actual Mac deployment, including host import/file permissions, loopback MCP access, restart/resume and export. Native Linux AMD64 availability is not a prerequisite to that first Apple release. Cross-target ARCH-02 remains explicitly UNRUN until the two native target records can be compared; it cannot be reported as passed by an emulated build. Before claiming Linux AMD64 production readiness, repeat the applicable deployment, boundary, recovery and end-to-end gates there and pass ARCH-01, ARCH-02 and SBX-03 for that target. This preserves Linux AMD64 support and all security and measurement criteria. See the derived [deployment acceptance matrix](DEPLOYMENT_TARGETS.md); historical evidence retains its original environment and scope.

## I. Protocol and evidence rules that reconcile both plans

- The evaluator owns activation, windows, data slices, costs, quotas, release policy and acceptance. The brief may propose public objectives/constraints; it cannot amend a frozen protocol. Official measurement has no LLM and no online inference dependency.
- `pilot_industry_v1` preserves P0/P1 timing, 31-industry rankings, weekly/monthly/quarterly review rules, paired baseline comparisons and original golden outputs. `stock_daily_v1` retains the local plan's daily panel, DSL limits, reference backtest and W0–W4 design. Generic factor/model/strategy cases declare their own compatible contract. Never apply 30-stock/Top-50/daily rules to the 31-industry pilot.
- Protocols explicitly declare **metric identity**, sampling unit, period count, cost basis and comparison baseline. The pilot's top-7 hit rate, extreme-group recall and the stock profile's share of positive RankIC dates are different metrics. Numerical thresholds and fitness weights are never copied between profiles by name alone.
- Existing pilot history is `previously_seen`, even in a sealed table. Record provider/model knowledge exposure as known/unknown; no model cutoff or historical data vintage is guessed. No clean-holdout claim follows from a confirmation query on these packages. Retain missing announcement vintages, backfilled constituents and unverified index-vintage limits; dates alone do not establish full PIT quality.
- The common artifact manifest has an opaque `artifact_version_id`, a canonical content hash, and separate implementation/canonical fingerprints. The content hash covers immutable payload digests and declared configuration/provenance, excluding server-assigned identifiers/timestamps. Publish-key idempotency and numerical dedup are distinct. Protocol/dataset/evaluator versions are pinned in each evaluation record.
- Release policies declare exactly which metrics/flags are available and their leakage/query budgets. A repeated lineage-best score is labelled with its originating version; it is never assigned as the current child's measured result. No selection rule reads private metrics. Stock-profile multi-metric fitness is available only under its matching release policy; the pilot uses the single-scalar/flags rule.
- Keep all attempted/evaluated versions, failures, withheld results and diagnostic evaluations in the ledger. Missing metrics are null with reasons, not zeros. Diagnostic neighbours are non-selectable but still logged; their multiple-testing treatment is predeclared. Duplicate reuse is valid only with matching artifact, data and protocol semantics. A new lineage/protocol name cannot reset exposure history.
- Ladder/coarsening/quota controls reduce information release; they do not guarantee that a noise candidate can never improve or that overfitting is impossible. Test mechanism invariants and statistical error behavior on declared synthetic seeds/protocols. Treat the inherited fixed-seed null benchmark as a regression test, not universal proof.
- Preserve the original pilot replay as an oracle independently of any new evaluator's research protocol. Published rounded tables are explanatory; machine-readable source ledgers/reference CSVs supply exact expected values. A numerical mismatch cannot be cured by updating golden values without evidence and a recorded decision.
- Insufficient data for DSR/PBO/inference yields `not_applicable`/`insufficient_data` with the frozen policy's consequence. It is not an automatic passed gate. Non-trading outputs receive deterministic quality checks appropriate to their type.

## J. Delivery sequence without renumbering either plan

Use repository Phase IDs as the primary delivery order; local IDs remain stable for traceability. Run a small offline supervisor/worker/blackboard capability experiment alongside contract work to prove evidence sharing and justified revisions. It is a fixture experiment, not permission to bypass deterministic evaluation before production research.

| Repository phase | Local detail reused | Required alignment additions |
|---|---|---|
| 0: contracts and scaffold | Local P0, database/import boundaries | InputBundle; semantic artifact kinds; role/provider profiles; job/exit schemas; three DB roles; ARM/AMD64 image strategy; source-preservation manifests |
| 1: data parity | Local P1 data/DSL/metric primitives as applicable | Import adapters and as-of slicing; distinguish pilot/stock profiles; preserve original offline replay |
| 2: independent evaluator | Local P1 metrics, P3 records, P6 applicable gates | Type-specific checks; trial/exposure ledger; no private-feedback export; honest historical evidence labels |
| 3: registry and sandbox | Local P2 and required subset of P8.1/P8.2 | Factor/model/strategy execution contracts and safe runners, immutable package payloads, target-host sandbox tests |
| 4: MCP and blackboard | Local P3 feedback, P4 API/state | Codex plus independent MCP test client; mount/upload import; submit/poll/reconnect; signed released reports; delivery export |
| 5: role loops | Local P4 agents, budgeting and generation machine | Kimi, GLM, DeepSeek adapters; per-role/task settings; durable context; checkpointed calls; provider conformance |
| 6: evolution | Local P5 islands/archive/bandit/lineage | Policy-compatible fitness; no preset run-time cutoff; stop/pause versus completed distinction |
| 7: pilot and acceptance | Local P6 applicable checks, offline benchmarks | Generic-input fixtures; mixed-provider job; Apple-first native host acceptance, then separate native Linux AMD64 validation under H; delivery exit receipt; failure/recovery demonstrations |
| 8: extensions | Local optional dashboard P7 and remaining P8 | Advanced Python breadth, extra data adapters, v2 lanes/composition, optional monitoring/forward campaigns; core production boundaries cannot wait until this phase |

Old time estimates and demonstration generation counts are planning examples. They are not runtime caps or guaranteed delivery dates. A phase number shared by the two source plans does not imply identical work.

## K. First production acceptance checklist

These are requirements for the future implementation, not tests claimed to have passed in this documentation task. Apply them first to the Apple deployment and later to Linux AMD64 as specified in H; do not label a partial or blocked target accepted.

| ID | Required demonstration |
|---|---|
| AC-01 | Codex can connect over MCP, submit an idea or files, receive a job ID, disconnect, reconnect and export a completed result; a second conforming test client works without Claude-specific configuration |
| AC-02 | Idea-only, factor-only, model-only, strategy-only and mixed package inputs each either run under a valid contract or identify specific missing inputs; runnable fixtures exist for every executable kind |
| AC-03 | Both original P0/P1 package manifests pass and each produces its 24 business CSVs against its exact oracle in an isolated authorized replay; no other model is fitted or selected |
| AC-04 | Research/MCP cannot invoke, configure, cancel or forge evaluation; cannot read private tables, full data mounts or signing keys; only evaluator-released reports cross the boundary |
| AC-05 | Kimi, GLM and DeepSeek each pass text, multi-turn tools, schema validation, supported streaming, effective-setting and error/usage tests against configured online endpoints; offline mocks are reported separately |
| AC-06 | One job uses all three mandatory providers, with at least two role profiles using different effective settings; same-model/different-endpoint configuration is tested where available, without assuming parameter parity |
| AC-07 | Unsupported settings fail preflight; allowed fallback is visible; unavailable provider, rate limit, malformed JSON and context overflow recover within policy without inventing evidence |
| AC-08 | Client loss, worker crash and container restart preserve committed work and resume at checkpoints; duplicate submissions/publications do not create duplicate logical jobs/artifacts; ambiguous paid calls remain audited |
| AC-09 | No default wall-clock or generation deadline ends a valid active job; budget/input/data waits remain explicit; only a passing independent delivery receipt sets `completed` |
| AC-10 | A supported negative result can pass the research-delivery gate when permitted by the brief; failed quality checks or missing reports cannot; promotion gate still requires its own evidence and sign-off |
| AC-11 | Actual macOS/Apple ARM64 deployment first, then native Linux AMD64: each proves startup, imports, migrations, numerical/oracle parity, sandbox restrictions, MCP path, stop/resume and artifact export. Native cross-target parity remains a separate later ARCH-02 gate under H; image or Linux-container evidence alone is insufficient for host acceptance |
| AC-12 | Exported bundles retain exact version/config/source references and checksums, reproduce their stated evidence, and contain no secrets, unreleased results or private holdout payloads |
| AC-13 | Idle deployment generates no autonomous research, data requests or provider spend; active jobs continue independently of client lifetime and remain controllable |
| AC-14 | Release schema, version attribution, profile-specific metric identity, exposure labels and ledger accounting pass deterministic tests and declared synthetic error-rate checks |

Paid smoke campaigns require configured credentials and an explicit operator spend authorization. This planning task neither calls paid LLMs nor establishes runtime readiness.

## L. Decisions intentionally left configurable

The owner has settled the architecture, Apple-first then Linux AMD64 deployment targets, the existing Mac Studio Docker Desktop environment, Docker/on-demand model, generic intake and required provider families. Implementation must still record host OS/hardware and Docker engine versions, SDK pins, sandbox backend readiness, endpoint/model IDs, role allocations, spending caps, data permissions, pilot protocol values and exit-gate instance before the relevant run. Those records do not authorize replacing the chosen Mac environment or changing security settings. These are deployment/job choices, not reasons to revert to Claude or redesign the product. A material scope change must be surfaced to the owner before it is incorporated.

## M. Compatibility sources checked for this revision

Official references checked October 23, 2026; implementation pins and account availability still need runtime verification. These sources substantiate compatibility boundaries, not provider benchmarks or fixed role assignments.

- [OpenAI: Responses migration and API differences](https://developers.openai.com/api/docs/guides/migrate-to-responses) — the adapters must preserve their distinct tool and conversation representations.
- [Kimi: OpenAI API compatibility](https://platform.kimi.ai/docs/guide/migrating-from-openai-to-kimi) — configurable OpenAI SDK endpoint and credentials, with provider differences.
- [Z.ai: OpenAI Python SDK](https://docs.z.ai/guides/develop/openai/python) — OpenAI-compatible access with documented differences.
- [DeepSeek: thinking mode](https://api-docs.deepseek.com/guides/thinking_mode/) — reasoning settings and sampling support are mode-dependent; [Responses support](https://api-docs.deepseek.com/guides/responses_api/) has its own capability limitations.
- [MCP: transports](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports) — stdio/Streamable HTTP and compatibility with earlier protocol generations.
- [Docker: multi-platform builds](https://docs.docker.com/build/building/multi-platform/) — separate platform variants and manifest lists; this does not prove native runtime or sandbox correctness.
- [PydanticAI: OpenAI models](https://pydantic.dev/docs/ai/models/openai/) — typed role loops can use the retained model abstraction without adopting an Anthropic harness.

Appendix B's older research literature remains source notes. Its Claude-specific recommendations, prices, SDK pins and client limits are historical context, not active requirements. Unverified historical claims are not promoted into acceptance facts by this amendment.
