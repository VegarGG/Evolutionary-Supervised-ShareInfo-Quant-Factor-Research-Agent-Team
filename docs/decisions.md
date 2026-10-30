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

Open owner question: confirm the requested maximum-effort task configuration.
Full CI execution requires permission to publish this new repository; no remote is
configured yet. The visible host default is gpt-6-astra/xhigh, not verified per turn.

Implementation references: [official MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk),
[Compose services](https://docs.docker.com/reference/compose-file/services/),
[uv workspaces](https://docs.astral.sh/uv/concepts/projects/workspaces/).
