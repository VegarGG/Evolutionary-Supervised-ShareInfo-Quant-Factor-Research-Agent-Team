# Phase 0 implementation and acceptance record

Status: **implementation ready for review; Phase 0 acceptance remains blocked**.
No later phase has begun. This is a new independent repository with no remote.

## Authority and provenance

The complete owner-supplied v2.1 English HTML plan is preserved byte for byte as
`PLAN.md` and `QFR-Implementation-Plan-v2.1-EN.html`. Its SHA-256 is
`ed2f01c8697e75bf3b48c31fe128df883cf4de33e4e8e1a0067a309090609e56`.
Source Library identifier: `libfile_d170ba334e5081919344b1880010666e`.
All 24 chapters were read before implementation. Root `AGENTS.md` is the text
from Section 21.1. Ambiguities and environment adaptations are in `decisions.md`.

No old application code was copied. Existing Python/uv tooling and identical,
hash-verified public dependency wheels were reused. Old repositories, branches,
remote histories and data were not changed by this implementation task. The parent
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
| P0.3 | PostgreSQL 16; four databases, five app roles, four migration roles; native images, hardened Compose, scoped mounts and networks; clean-exit placeholders | ARM64 builds, real database tests, deployed doctor; host ingress remains blocked |
| P0.4 | Nine YAML configuration categories, pydantic-settings, typed validation, canonical hashes; Section 20 defaults | Config and public-preview privacy tests |
| P0.5 | Eleven public model contracts, two public enums, two private contracts; generated JSON Schema; one valid and invalid fixture per contract | Pydantic/JSON Schema tests and property-based release-boundary checks |
| P0.6 | structlog JSON, context/HTTP/queue correlation, stdout and daily files, size rotation, mandatory redaction, search/tail/correlate CLI | LOG-01/02 across thirteen service names; pagination, rotation, range, secret and symlink tests |
| P0.7 | Official FastMCP streamable HTTP, bearer auth, limits, fail-closed audit; exactly five read tools; client snippets | Scripted HTTP tests plus real container HTTP/DB/file checks; host connectivity remains blocked |
| P0.8 | GitHub Actions checks with PostgreSQL and ARM64/AMD64 image matrices recording digests | Workflow authored; ARM64 built locally; hosted CI and AMD64 not executed |
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
- `just test-db`: **55 passed, zero skipped** against PostgreSQL 16. A Starlette
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
- `just up` starts healthy PostgreSQL and MCP. Migration and domain placeholders
  complete with exit 0. Four databases and five application roles are present.
- Container MCP smoke: all five tools return over real streamable HTTP. Each call
  has exactly one matching `mcp_calls` row and one file audit line. This is a
  scripted client inside the container, **not a successful Mac host connection**.
- `just doctor`: **FAIL — 91 of 93 checks pass**. The two failures are Docker
  memory and host MCP loopback reachability. See the complete JSON evidence.

## Setup results and unresolved acceptance

The Mac is native arm64, with 18 CPUs and 36 GiB host RAM. Docker exposes 18 CPUs
but only 8,317,267,968 bytes (about 7.75 GiB) of RAM. The plan requires at least
24 GiB. Docker's disk capacity and free space meet the configured minimum. Sleep
is disabled. Secrets are generated locally into a mode-0600 `.env`, excluded from
Git and from image build contexts. Docker settings were not changed.

| Remaining item | Exact blocker | State / next action |
|---|---|---|
| DEP-01 memory | Docker allocation is below 24 GiB | Owner decision pending; changing it restarts Docker and affects old containers |
| Host MCP transport | Docker Desktop does not publish a port from the fully internal control network | Owner decision pending on a separate qfr-mcp-only ingress network; that network permits control-container outbound connectivity |
| Live MCP-01 downstream trace | P0.3 requires domain placeholders to exit; MCP-01 expects live downstream log lines. Log tools also read files directly per Section 15.5 | Owner interpretation pending. Scripted propagation and real MCP audits pass, but live downstream completion is not claimed |
| CI / AMD64 | New repository has no remote and publishing was not authorized | Workflow ready; hosted checks and two-architecture CI acceptance have not run |
| Model requirement | Host default is visible; this turn's actual model/effort is not | Owner/task configuration must establish the requested maximum effort if mandatory |

No action above was denied by automatic approval review. Configuration decisions
remain pending; hosted CI was not attempted. The failed setup experiments were
confined to this new project's disposable resources. No broad Docker pruning,
global restart, paid provider calls or code publication occurred.

## Reproduction and evidence

On this Mac, prefix commands with `PATH="$PWD/.tools:$PWD/.venv/bin:$PATH"` when
the tools are not in the shell's normal PATH. Then:

```sh
uv sync --locked
just check
just test-db
just up
just doctor
python scripts/smoke_mcp.py
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
