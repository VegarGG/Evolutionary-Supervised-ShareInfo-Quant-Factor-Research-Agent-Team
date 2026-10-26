import json
import secrets
import socket
import threading
import time
from pathlib import Path
from uuid import uuid4

import pytest
import uvicorn
from qfr_core.contracts.publication import (
    PublicationRequest,
    RegistryAuthenticationConfiguration,
    RegistryClientConfiguration,
)
from qfr_core.dsl.language import DSLConfig, analyze, parse
from qfr_core.registry_client import RegistryClient
from qfr_registry.api.app import create_app
from qfr_registry.auth import StaticTokenAuthorizer
from qfr_registry.policy import RegistryPolicy, RegistryReadPolicy
from qfr_registry.publication import Principal, Registry
from qfr_registry.storage.objects import PayloadStore


@pytest.fixture
def registry_policy():
    return RegistryPolicy.model_validate_json(
        Path("configs/registry/publication_v1.json").read_bytes()
    )


@pytest.fixture
def registry_service(registry_connect, registry_policy, tmp_path):
    return Registry(
        registry_connect,
        PayloadStore(tmp_path / "registry-payloads"),
        registry_policy,
        {
            profile: DSLConfig.load(Path(f"configs/dsl/{profile}.json"))
            for profile in ("pilot_industry_v1", "stock_daily_v1")
        },
    )


@pytest.fixture
def program():
    return "test-program-" + uuid4().hex


@pytest.fixture
def publisher(program):
    return Principal(
        "fixture-publisher-" + str(uuid4()), frozenset({"publisher"}), frozenset({program})
    )


@pytest.fixture
def draft(program):
    def make(expression="Ref($close,1)"):
        manifest = json.loads(Path("contracts/examples/ArtifactDefinition.valid.json").read_text())
        manifest.update(
            {
                "name": "factor-" + uuid4().hex,
                "family_id": None,
                "parent_version_ids": [],
                "payload_files": [],
            }
        )
        manifest["provenance"]["program_id"] = program
        manifest["implementation"] = {
            "type": "dsl",
            "language": "qfr-dsl/1",
            "expression": expression,
        }
        config = DSLConfig.load(Path("configs/dsl/pilot_industry_v1.json"))
        analysis = analyze(parse(expression, config), config)
        manifest["complexity"] = analysis.complexity
        manifest["payload"].update(
            {"fields_used": sorted(analysis.fields), "max_lookback_days": analysis.lookback}
        )
        return PublicationRequest.model_validate(
            {
                "publish_key": str(uuid4()),
                "profile": "pilot_industry_v1",
                "manifest": manifest,
                "files": [],
                "content_hash": "f" * 64,
            }
        )

    return make


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def registry_http(registry_service, program):
    token = secrets.token_urlsafe(32)
    config = RegistryAuthenticationConfiguration(
        revision=1,
        enabled=True,
        minimum_token_bytes=32,
        maximum_token_bytes=512,
        bindings=[
            {
                "principal": "seed-fixture",
                "token_ref": "env:TEST_REGISTRY_TOKEN",
                "roles": ["publisher", "evaluator"],
                "programs": [program],
            }
        ],
    )
    app = create_app(
        registry_service,
        authorize=StaticTokenAuthorizer(config, {"TEST_REGISTRY_TOKEN": token}),
        read_policy=RegistryReadPolicy.model_validate_json(
            (ROOT / "configs/registry/read_v1.json").read_bytes()
        ),
    )
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        server = uvicorn.Server(
            uvicorn.Config(app, log_config=None, access_log=False, lifespan="off")
        )
        worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        worker.start()
        try:
            deadline = time.monotonic() + 5
            while not server.started and worker.is_alive() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert server.started
            client_config = RegistryClientConfiguration(
                revision=1,
                base_url=f"http://127.0.0.1:{listener.getsockname()[1]}",
                token_ref="env:TEST_REGISTRY_TOKEN",
                timeout_seconds=5,
                max_request_bytes=8 * 1024**2,
                max_response_bytes=16 * 1024**2,
            )
            yield RegistryClient.from_environment(client_config, {"TEST_REGISTRY_TOKEN": token})
        finally:
            server.should_exit = True
            worker.join(5)
            assert not worker.is_alive()
