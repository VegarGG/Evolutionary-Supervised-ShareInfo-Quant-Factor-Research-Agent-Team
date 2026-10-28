# Stage 4 service launch

The API launch commands require explicit operator configuration. They perform no
migration, credential creation, grant change, ingest build, evaluation, release,
model call or job admission. Base Compose remains idle. This is deployment code;
actual Mac container evidence is still required before Stage 4 acceptance.

| Service | Explicit command | Database identity |
|---|---|---|
| MCP | `python -m qfr_mcp.serve /etc/qfr/service.json` | None |
| Research | `python -m qfr_research.serve /etc/qfr/service.json` | `research_rw` / `research_db` |
| Registry | `python -m qfr_registry.serve /etc/qfr/service.json` | `registry_app` / `registry_db` |
| Feedback | `python -m qfr_eval.feedback.serve /etc/qfr/service.json` | `feedback_ro` / `eval_db`, reads only |
| Quarantine | `python -m qfr_eval.ingest.serve /etc/qfr/service.json` | No PostgreSQL; private transport journal |

Launch files validate against the corresponding `*ServiceConfiguration` contract
in `contracts/jsonschema`. The examples are structural examples, **not working
credentials, approved inputs or deployment defaults**. Before use, set exact
programs, principals, role bindings, verification keys, upstream URLs, policy
hashes and existing credential references. Backend token scopes must agree with
the caller mappings. The MCP and Research services receive public verification
keys only. Private signing keys remain with the separately invoked evaluator.
For new explicit P0/P1 candidate/reference jobs, use `configs/research/api_v2.json`
in Research and MCP export verification, checker
`configs/delivery/pilot_research_delivery_v3.json`, and exit-gate schema version 2.
Legacy gate/checker identities remain valid only with their original semantics;
never relabel an existing admitted job or signed receipt.

`configs/research/http_server_v1.json` records bounded concurrency and connection/
shutdown settings. Native service examples bind `127.0.0.1`; container launch
configurations must explicitly use `0.0.0.0:8000` inside their private networks.
The Compose host publication remains `127.0.0.1`. Proxy-header trust and access
logs containing raw URLs are disabled. Application audit logs record scoped
principal and server-generated request identity, not request bodies or credentials.
The bootstrap parser refuses duplicate keys, nonfinite numbers and JSON larger
than the version-1 4 MiB bootstrap bound.

## Credential delivery and startup

Each service's private environment file contains only the references it resolves.
Compose reads these host files; they are **not bind-mounted**. Keep their host mode
0600 and their containing directory private. No host chmod, Docker configuration
change, root application startup or new role is needed. Missing/empty credentials
and wrong audiences fail before serving. Database roles/names are fixed by service
code; a supplied environment cannot turn Research into an evaluator identity.
Connections have bounded startup time, and startup checks required migrated
relations without altering them. Apply reviewed migrations separately using the
existing operator procedures.

JSON configuration contains references and public verification material only;
mount the individual file read-only and make that non-secret file readable by the
container's existing UID 65532. Do not solve an unreadable **secret** file by
broadening its mode. Environment-file permissions and container environment are
separate concerns. A Docker administrator can inspect container environments;
this deployment adds no Docker API access to any API or research container.

The service overlay is opt-in:

```sh
# QFR_STAGE4_CONFIG_ROOT is the reviewed private directory containing
# mcp/research/registry/feedback/intake .json and .env files.
docker compose --env-file configs/deployment.env \
  -f infra/docker-compose.yml -f infra/docker-compose.stage4.yml \
  config --no-env-resolution --quiet

docker compose --env-file configs/deployment.env \
  -f infra/docker-compose.yml -f infra/docker-compose.stage4.yml \
  up -d --wait mcp-api research-api registry-api feedback-api quarantine-api
```

Start and verify the existing PostgreSQL service and apply migrations before this
sequence. Never publish `docker compose config` output with resolved environment
values. A health response proves that a service is alive, not that every upstream
or financial gate passed. Only the MCP host port is published by this overlay.
The frozen ingest and evaluator-owner CLI operations remain separate; there is
no background worker invoked by starting these APIs.

The optional `infra/docker-compose.stage4-import.yml` mounts the explicitly
supplied `QFR_STAGE4_IMPORT_ROOT` read-only at `/imports/originals`, **only** in
quarantine. Its intake configuration must declare the corresponding mount ID.
No undeclared host path is created. Otherwise use the authenticated binary upload
path. Research sees only its existing read-only research snapshot volume; neither
Research nor MCP gets quarantine, full data, evaluator secrets or runtime sockets.

New named volumes inherit UID/GID 65532 and mode 0700 for Registry and quarantine
from the image. Existing volumes are not silently chowned or replaced. A mismatch
fails and must be diagnosed while preserving original data. Existing sandbox
profiles, controller grant and PostgreSQL SCRAM/bootstrap behavior are unchanged.

Resource caps are explicit: one CPU, 64 PIDs, no swap beyond each service's memory
cap, 1 GiB per MCP/Research/Registry/quarantine and 512 MiB for Feedback. API request
concurrency defaults to four. Quarantine's reservation policy can consume more
disk than its declared source bytes because both chunk history and finalized
originals are retained. Monitor disk/memory/inodes on the Mac; run image builds
serially and preserve databases, inputs, logs and evidence. These operational caps
are not financial screening or measurement settings.

## Required deployment evidence

Verify actual non-root file access, service readiness, correct PostgreSQL roles,
authentication, idle zero-work behavior, process/container restart and durable
jobs/checkpoints. Test both the permitted HTTP paths and denied evaluator/database/
socket/source paths. Then run the actual Codex and independent-client flow, the
original P0/P1 measurement/replay, real elapsed release batch and signed negative
result export. Static Compose rendering, component fixtures and image builds do
not establish those gates. Heavy tests and the final image matrix run on the Mac,
with macOS host and Linux container architectures recorded separately.
