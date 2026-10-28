# Stage 4 Mac acceptance handoff

This is the remaining test procedure, not a pass record. Use a reviewed exact
commit from `stage-4-blackboard-delivery` in the existing Mac test checkout.
Record commit/tree/lock and host/container platforms before starting, and do not
change source beneath active tests. Preserve the Stage 3 base and all original
pilot inputs, oracle outputs, database volumes and evidence.

## Prerequisites and bounded work

Use the existing Docker Desktop engine and approved Docker-native controller.
There is no new backend, Docker grant, host setting or provider authorization.
The current lock is pinned by `sandbox_docker_native_v5.json`; earlier runtime
identities cannot be relabelled to this build. Build the four application images
and core-only sandbox image for each container architecture, serially. Record
immutable IDs and architecture, labelling AMD64 emulation on this Apple host.
The accepted host target is macOS ARM64, not Linux ARM64 by itself.

Ordinary cloud component checks use two numerical threads, a five-minute external
test timeout and about 360 MiB peak child RSS. These are observations, not a
resource estimate for all pilot/sandbox/image work. The Mac owns the latter work.
Use the already reviewed per-job sandbox limits; record memory, free disk and
inodes before each build/run, stop safely if headroom is insufficient, and clean
only explicitly task-owned recreatable caches. The API overlay has explicit
per-service limits documented in [STAGE_4_SERVICES.md](STAGE_4_SERVICES.md).

Required private inputs are the original P0/P1 inventory (339 unchanged files),
verified historical replay oracle, existing PostgreSQL role credentials and
short-lived test authentication/signing material. Keep the signing key exclusively
with the evaluator operator. Use reviewed per-service/program scopes, public
verification keys and actual image/runtime identities. Structural examples do
not supply these inputs. Do not print secrets, resolve Compose environment values
into public logs, or place licensed inputs in image layers or Git.

## Actual human-driven sequence

1. Run required-PostgreSQL native/static checks and the corresponding CI-container
   checks on the exact source, with real licensed inputs, original oracle and
   actual sandbox enabled. Record every skip reason independently. Use the
   original workflow steps, including database bootstrap regressions, boundaries
   and all ten image builds; a unit count does not establish deployment acceptance.
2. Apply reviewed migrations separately, then explicitly start the Stage 4
   services with the base, approved sandbox and Stage 4 overlays. Use the optional
   read-only import overlay only for the exact original-data mount. Verify
   health/authentication, actual volume access, database roles and denied private
   paths. Observe idle service/database counters: no job, ingest, evaluation,
   release or provider call may be started automatically.
3. Follow [PORTABLE_INTAKE_GUIDE.md](PORTABLE_INTAKE_GUIDE.md), preserving A.2/A.8
   business rules, source hashes and exposure labels. Exercise real authenticated
   upload and mapped import with original-byte hash checks. The separately
   authorized `qfr ingest once` operator build creates the research catalog;
   register it through MCP. Publish original P0/P1 artifacts only through Registry
   HTTP, then register their exact baseline references.
4. Freeze the already approved protocol with evaluator CLI `protocol-create` and
   `protocol-activate --expected-hash`. Activate the existing release policy and
   publish its public cards. Do not use confirmation, alter windows, change
   numerical settings or grant research access to evaluator administration.
5. Before admission, freeze an exit-gate version 2 and checker v3 with P0 assessed
   relative to the preserved P1 reference. Both remain registered baselines and
   require actual released reports plus replay. This distinction is fixed by the
   comparison objective, not chosen from favorable outcomes. Insufficient P0
   uncertainty or unresolved hurdles still fail delivery. Use API policy v2 and
   exact checker hashes. Preserve any earlier admitted job as a separate record.
6. Demonstrate actual Codex and the independent SDK CLI using the standard endpoint
   and discovered schemas; see [MCP_CLIENTS.md](MCP_CLIENTS.md). Each must connect,
   submit, disconnect, reconnect, poll and export. They may retry the same frozen
   admission/key to show that a second client recovers the same durable job.
   Record actual client versions, protocol negotiations and operation identities.
   No model turn/provider request is needed or authorized. Verify a differing
   payload conflicts and cancellation of a status request leaves the job intact.
7. Independently screen, measure and reproduce the actual registered weekly P0/P1
   artifacts under the frozen runtime. Preserve strict original parity and the
   private append-only replay evidence. These operations are evaluator-owner
   commands, never MCP tools or request-triggered evaluation.
8. Attempt release before eligibility and verify that future/unsigned reports are
   unavailable. Record the real database UTC eligibility boundary, then checkpoint
   and wait for elapsed time. Do not backdate records, advance clocks or modify the
   six-hour policy. A pending release remains pending. After eligibility, run the
   scoped `release-ready` operator command, independently verify signatures and
   read only the declared scalar/flags/public planning metadata. Confirmation
   fields and raw diagnostics must remain absent.
9. Publish a human-authored research note citing both exact reports and their
   limitations. Propose the permitted conclusion, invoke independent
   `delivery-check`, and accept only its matching signed receipt through Research
   API/MCP. A reference's self-comparison insufficiency remains visible; it is not
   a passing candidate. If assessed evidence cannot support the negative result,
   preserve the failed receipt and report the gate failure without changing scope.
10. Export/download through both actual clients and independently run
    `qfr_core.exports.verify_export`. Verify exact frozen intent, scope, artifacts,
    datasets, cards and signed reports; exclude private results/data/secrets.
    Restart the deployed containers and verify the admitted job, checkpoints,
    receipt and export remain identical. Recheck denied databases, source mounts
    and Docker/controller socket boundaries after restart.

## Gate evidence map

| Gate | Component evidence already implemented | Additional actual acceptance evidence |
|---|---|---|
| REL-01–06 | `test_release_projection.py`, `test_release_database.py`, `test_release_preparation.py`, `test_signed_publication.py` | Real P0/P1 release, actual elapsed batch, original attribution, no confirmation fields |
| BND-03 | `test_feedback.py`, live database and Compose boundary suites | Deployed GET-only Feedback, exact role grants and denied private connectivity |
| MCP-01–06 | `test_mcp_http.py`, service launch and upload/export tests | Actual Mac Codex and independent client lifecycles, lost ack/conflict, size/import escape, tampered/unsigned refusal |
| JOB-01–03 | `test_research_jobs.py`, checkpoint/persistence/service tests | Idle zero-work counters, actual container restart, request cancellation separate from durable job, no elapsed/generation completion limit |
| DLV-01–03 | `test_delivery_checker.py`, `test_delivery_assessment.py`, `test_delivery_worker.py`, `test_delivery_acceptance.py`, `test_exports.py` | Real independent negative-result receipt, strict replay, exact references and both client exports |
| Workflow/native target | `just check`, required-database ordinary suite; earlier Stage 3 evidence kept separate | Final-source native/container suites, Compose startup/restart/boundaries and ten images, exact-commit hosted CI after draft PR |

Retain commands, UTC timestamps, individual outcomes and hashes privately. Publish
only the non-sensitive technical acceptance summary. An unavailable prerequisite,
pending batch, failed check or skipped required test must be reported explicitly.
Stage 5 and production acceptance are outside this handoff.
