# Phase 0 implementation and acceptance record

Status: **implemented; local and hosted CI checks pass under the owner's clarified
requirements; ready for owner audit**. Owner acceptance and merge are not asserted.
No later phase has begun. The implementation has an independent local Git root;
its canonical remote is
[VegarGG/Evolutionary-Supervised-ShareInfo-Quant-Factor-Research-Agent-Team](https://github.com/VegarGG/Evolutionary-Supervised-ShareInfo-Quant-Factor-Research-Agent-Team).
The owner instructed that the previous developments and files, including the
README, are stale. The replacement PR uses the new Phase 0 file tree and preserves
the old Git history without using it as implementation guidance.

## Authority and provenance

The complete owner-supplied v2.1 English HTML plan is preserved byte for byte as
`PLAN.md` and `QFR-Implementation-Plan-v2.1-EN.html`. Its SHA-256 is
`ed2f01c8697e75bf3b48c31fe128df883cf4de33e4e8e1a0067a309090609e56`.
Source Library identifier: `libfile_d170ba334e5081919344b1880010666e`.
All 24 chapters were read before implementation. Root `AGENTS.md` is the text
from Section 21.1. Ambiguities and environment adaptations are in `decisions.md`.

No old application code was copied. Existing Python/uv tooling and identical,
hash-verified public dependency wheels were reused. Old branch histories and data
are preserved. The canonical PR replaces the stale working-tree files. The parent
task reports that PRs #1–8 are labelled outdated; that remote work is separate.

The visible Codex host default is **gpt-6-astra, reasoning effort xhigh**. The
current turn's actual configuration cannot be inspected or changed through the
available tools. The requested maximum-effort configuration is therefore **not
verified**, and no stronger configuration is claimed.

## Implemented scope

| Task | Delivered | Verification |
|---|---|---|
| P0.1 | Python 3.12 uv workspace; five packages; ruff, mypy, pytest, hypothesis; required just targets | `just check`; PostgreSQL suite |
| P0.2 | Four import-linter contracts, including MCP importing only core | Four contracts kept; zero broken |
| P0.3 | PostgreSQL 16; four databases, five app roles, four migration roles; native images, hardened Compose, scoped mounts and networks; clean-exit placeholders | ARM64 builds, real database tests, deployed doctor and host ingress pass |
| P0.4 | Nine YAML configuration categories, pydantic-settings, typed validation, canonical hashes; Section 20 defaults | Config and public-preview privacy tests |
| P0.5 | Eleven public model contracts, two public enums, two private contracts; generated JSON Schema; one valid and invalid fixture per contract | Pydantic/JSON Schema tests and property-based release-boundary checks |
| P0.6 | structlog JSON, context/HTTP/queue correlation, stdout and daily files, size rotation, mandatory redaction, search/tail/correlate CLI | LOG-01/02 across thirteen service names; pagination, rotation, range, secret and symlink tests |
| P0.7 | Official FastMCP streamable HTTP, bearer auth, limits, fail-closed audit; exactly five read tools; client snippets | Scripted HTTP tests plus real host HTTP/DB/file checks pass; live downstream trace acceptance is deferred by owner |
| P0.8 | GitHub Actions checks with PostgreSQL and ARM64/AMD64 image matrices recording digests | Canonical CI passes: check target, 56 tests with zero skips, all eight image builds; digests retained |
| P0.9 | Exact plan, AGENTS, decisions, this report and evidence | Source hash verified; reviewed locally |

The five MCP tools are `qfr.status`, `qfr.config.get`, `qfr.logs.search`,
`qfr.logs.tail` and `qfr.logs.correlate`. Status explicitly reports Phase 0 and
unavailable domain backends. Public config is labelled an unactivated preview.
Owner-only config still requires the later evaluator API. No fabricated pool,
budget, data-freshness or research-state counts stand in for unimplemented APIs.

Contract examples exist only under tests. A new deployment contains no default
factors, strategies, research jobs, official measurements or pool entries.
Pool import/setup, provider probing, research workflows, evaluator execution,
retention jobs, backups and benchmarks remain in their assigned later phases.
The corresponding required command placeholders return nonzero, explicit deferred
status rather than reporting success.

## Checks actually executed

- `just check`: PASS. Ruff, formatting, mypy (strict core/MCP), all four import
  contracts, schema generation and public-card generation.
- `just test-db`: **56 passed, zero skipped** against PostgreSQL 16. A Starlette
  TestClient deprecation warning remains; it does not affect test results.
- BND-01: real database authentication succeeds for each tested role and fails
  across prohibited databases. Application and migration roles cannot update,
  delete or truncate `mcp_calls`. The feedback role lacks private-schema access.
- BND-04: all four package boundaries pass. BND-07: only research-worker receives
  provider environment names. BND-08: scoped log mounts and MCP read permissions
  pass both configuration checks and deployed inspection.
- LOG-01/02: required fields and entity IDs are retained; fake keys, environment
  secrets and secret-shaped dictionary keys are absent from stdout and file sinks.
- Four final native ARM64 images are built; metadata/digests are retained. No local
  AMD64 emulation was run: the plan assigns AMD64 to CI.
- Canonical [CI run 41066156741](https://github.com/VegarGG/Evolutionary-Supervised-ShareInfo-Quant-Factor-Research-Agent-Team/actions/runs/41066156741)
  passes all nine jobs for PR head `aa1841d8ca1ed67fc7b0de44f7d8184001fe8618`.
  The checkout tested GitHub's PR merge commit
  `ad00b0875f3dcda5f8cf8bba72cc4a39bb2c8ca7`. The Linux AMD64 check job passes
  lint, formatting, types, all four import contracts, generated-file consistency
  and **56 tests with zero skips**, including the required real PostgreSQL tests.
  The four image targets (postgres, runtime, mcp and migrate) build successfully
  for each of `linux/arm64` and `linux/amd64`. All eight metadata ZIPs were
  downloaded and SHA-256 checked against GitHub's recorded artifact hashes;
  reviewed metadata records and image digests are retained under
  `docs/evidence/ci-images/`, with hashes and links to the complete source artifacts.
  These image checks verify construction for both architectures, not full-stack
  runtime behavior or performance on both. Native ARM64 runtime checks are local.
- `just up` starts healthy PostgreSQL and MCP. Migration and domain placeholders
  complete with exit 0. Four databases and five application roles are present.
- Host MCP smoke: a scripted client on the Mac calls all five tools at
  `127.0.0.1:8765/mcp` over real streamable HTTP. Each call has exactly one matching
  `mcp_calls` row and one file audit line, verified inside the container without
  exposing PostgreSQL on the host. No interactive agent client was registered.
- `just doctor`: **PASS — 112 of 112 checks pass**, including host reachability,
  exclusive MCP ingress, internal shared networks and every current container's
  OOMKilled flag. Memory allocation is recorded separately as an observation.

## Setup results, owner decisions and review status

The Mac is native arm64, with 18 CPUs and 36 GiB host RAM. Docker exposes 18 CPUs
and 8,317,267,968 bytes (about 7.75 GiB) of RAM. The owner clarified that 24 GiB is
an expectation and actual allocation will depend on performance. No current
container reports OOMKilled. This does not establish capacity for later research
or evaluation workloads; Phase 0 domain services are placeholders. Docker's disk
capacity and free space meet the configured minimum. Sleep
is disabled. Secrets are generated locally into a mode-0600 `.env`, excluded from
Git and from image build contexts. Docker settings were not changed.

| Remaining item | Exact blocker | State / next action |
|---|---|---|
| DEP-01 memory | Resolved by owner clarification | Allocation unchanged; expectation retained; current OOM flags checked and no OOM observed |
| Host MCP transport | Resolved and verified | Owner-approved qfr-mcp-only ingress network; host calls and audit checks pass; research/evaluation shared networks remain internal |
| Live MCP-01 downstream trace | Explicitly deferred by owner | Keep clean-exit placeholders. Scripted propagation and real MCP audits pass; live downstream completion is not claimed |
| CI / AMD64 | Resolved and verified | All nine canonical CI jobs pass; eight ARM64/AMD64 image digests and the test log excerpt are retained |
| Model requirement | Host default is visible; this turn's actual model/effort is not | Owner/task configuration must establish the requested maximum effort if mandatory |
| Owner audit / merge | Pending owner review | Technical evidence is ready in PR #10; no approval record or merge is asserted |

The three owner decisions are quoted and recorded in `decisions.md`. No action
above was denied by automatic approval review. An initial CI attempt in a separate,
noncanonical repository did not execute; it does not establish acceptance for this
project. The first canonical CI run exposed a PostgreSQL health-command quoting
error in the workflow; double quotes fixed runner argument parsing, and the next
run passed all nine jobs. Canonical PR checks provide the current remote result.
The failed setup
experiments were confined to this new project's disposable resources. No broad
Docker pruning, global restart or paid provider calls occurred. Code publication
is authorized in the canonical project; the misplaced PR is superseded.

## Reproduction and evidence

On this Mac, prefix commands with `PATH="$PWD/.tools:$PWD/.venv/bin:$PATH"` when
the tools are not in the shell's normal PATH. Then:

```sh
uv sync --locked
just check
just test-db
just up
just doctor
python scripts/smoke_mcp.py --host
just logs tail --service qfr-mcp --n 5
```

`just test` alone skips the three database tests unless their credentials are
configured. `just test-db` creates only the `qfr-v2-ci` database project, uses
loopback port 55433, runs migrations and supplies all database test credentials.
The main `qfr-v2` PostgreSQL instance exposes no host port. Do not delete volumes
to repeat normal tests; the audit table is intentionally append-only.

The normal build is `just build`. On this machine the initial public-wheel
downloads stalled. The successful local build used the Dockerfile's optional
`--build-context wheel-cache=.cache/linux-wheels` with wheels verified against
`uv.lock`; cache bytes are excluded from Git and runtime images. For example:

```sh
docker buildx build --platform linux/arm64 --target mcp \
  --build-arg QFR_PACKAGE=qfr-mcp \
  --build-context wheel-cache=.cache/linux-wheels \
  -f infra/Dockerfile -t qfr-v2-mcp:phase0 --load .
```

Reviewed, non-secret evidence is under `docs/evidence/`; raw working receipts and
logs are under ignored `exports/`. The evidence index records file hashes so an
independent reviewer can distinguish verified results from unresolved acceptance.
The earlier failed doctor report remains in Git history and the ignored raw
`exports/doctor` directory; current evidence records the approved resolution.
