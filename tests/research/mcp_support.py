"""Actual loopback transports with explicitly synthetic financial evidence."""

import json
import secrets
import socket
import threading
import time
from contextlib import ExitStack, asynccontextmanager, contextmanager
from pathlib import Path
from types import SimpleNamespace

import httpx2
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from qfr_core.access import BearerAuthority
from qfr_core.contracts.access import PublicServiceClientConfiguration, ServiceAuthentication
from qfr_core.contracts.mcp import MCPPolicy
from qfr_core.contracts.publication import RegistryClientConfiguration
from qfr_core.contracts.transfers import IntakeTransportPolicy
from qfr_core.registry_client import RegistryClient
from qfr_core.service_client import PublicServiceClient
from qfr_eval.ingest.intake_app import create_app as intake_app
from qfr_eval.ingest.quarantine import Quarantine
from qfr_mcp.gateway import Backend, Gateway
from qfr_mcp.server import create_app
from qfr_research.api.app import create_app as research_app
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

ROOT = Path(__file__).resolve().parents[2]


def authority(program, audience, roles, name="synthetic-client"):
    token = secrets.token_urlsafe(32)
    policy = ServiceAuthentication(
        revision=1,
        audience=audience,
        minimum_token_bytes=32,
        maximum_token_bytes=256,
        bindings=[
            dict(principal=name, token_ref="env:TOKEN", roles=roles, programs=[str(program)])
        ],
    )
    return BearerAuthority(policy, {"TOKEN": token}), token


@contextmanager
def serving(app):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(32)
        server = uvicorn.Server(
            uvicorn.Config(
                app,
                log_config=None,
                access_log=False,
                lifespan="on",
                timeout_graceful_shutdown=3,
            )
        )
        worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        worker.start()
        try:
            deadline = time.monotonic() + 5
            while not server.started and worker.is_alive() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert server.started, "bounded fixture server did not start"
            yield f"http://127.0.0.1:{listener.getsockname()[1]}"
        finally:
            server.should_exit = True
            worker.join(5)
            assert not worker.is_alive(), "fixture server did not stop"


@contextmanager
def frontdoor(case, tmp_path, *, roles=None, policy_changes=None):
    roles = roles or ["research_lead"]
    caller_auth, token = authority(case.program, "mcp", roles)
    r_auth, r_token = authority(case.program, "research", roles)
    i_auth, i_token = authority(case.program, "intake", roles)
    evidence_token = secrets.token_urlsafe(32)
    mount = tmp_path / "import"
    mount.mkdir(parents=True)
    transport = json.loads((ROOT / "configs/research/intake_transport_v1.json").read_bytes())
    transport.update(chunk_bytes=256, max_upload_bytes=65536)
    store = Quarantine(
        tmp_path / "private", IntakeTransportPolicy.model_validate(transport), {"originals": mount}
    )
    evidence_calls, logs = [], []
    replacement = {}

    async def evidence(request):
        assert request.headers.get("authorization") == "Bearer " + evidence_token
        evidence_calls.append(request.url.path)
        if request.url.path.startswith("/v1/reports/"):
            result = case.evidence.signed_report
        elif request.url.path == "/v1/reports":
            report = case.evidence.signed_report
            return JSONResponse(
                dict(
                    schema_version="1",
                    items=[report.model_dump(mode="json")],
                    next_after_id=report.report_id,
                    has_more=False,
                )
            )
        elif request.url.path.startswith("/v1/delivery-receipts/"):
            result = case.evidence.receipt_value
        elif request.url.path.startswith("/v1/artifacts/"):
            identity = request.path_params["identity"]
            result = next(
                v
                for v in [case.evidence.factor, case.evidence.note]
                if v.manifest.artifact_version_id == identity
            )
        else:
            return JSONResponse({}, status_code=404)
        return JSONResponse(replacement.get(request.url.path, result.model_dump(mode="json")))

    public = Starlette(
        routes=[
            Route("/v1/reports", evidence),
            Route("/v1/reports/{identity}", evidence),
            Route("/v1/artifacts/{identity}", evidence),
            Route("/v1/delivery-receipts/{identity}", evidence),
        ]
    )
    with ExitStack() as stack:
        r_url = stack.enter_context(serving(research_app(case.service, authority=r_auth)))
        i_url = stack.enter_context(serving(intake_app(store, authority=i_auth)))
        e_url = stack.enter_context(serving(public))
        common = dict(
            revision=1,
            token_ref="env:TOKEN",
            timeout_seconds=3,
            max_request_bytes=4194304,
            max_response_bytes=8388608,
        )
        policy = json.loads((ROOT / "configs/research/mcp_v1.json").read_bytes())
        policy.update(policy_changes or {})
        gateway = Gateway(
            {
                ("synthetic-client", case.program): Backend(
                    frozenset(roles),
                    PublicServiceClient(
                        PublicServiceClientConfiguration(base_url=r_url, **common), r_token
                    ),
                    RegistryClient(
                        RegistryClientConfiguration(base_url=e_url, **common), evidence_token
                    ),
                    PublicServiceClient(
                        PublicServiceClientConfiguration(base_url=e_url, **common), evidence_token
                    ),
                    PublicServiceClient(
                        PublicServiceClientConfiguration(base_url=i_url, **common), i_token
                    ),
                )
            },
            MCPPolicy.model_validate(policy),
            case.service.policy,
            case.evidence.verifier,
        )
        app = create_app(gateway, authority=caller_auth, request_log=logs.append)
        url = stack.enter_context(serving(app))
        yield SimpleNamespace(
            url=url,
            token=token,
            gateway=gateway,
            app=app,
            logs=logs,
            evidence_calls=evidence_calls,
            replacement=replacement,
            store=store,
            mount=mount,
        )


@asynccontextmanager
async def connection(front):
    async with httpx2.AsyncClient(
        headers={"Authorization": "Bearer " + front.token}, timeout=5, trust_env=False
    ) as http:
        async with streamable_http_client(front.url + "/mcp", http_client=http) as (read, write):
            async with ClientSession(read, write, read_timeout_seconds=5) as session:
                info = await session.initialize()
                yield session, info
