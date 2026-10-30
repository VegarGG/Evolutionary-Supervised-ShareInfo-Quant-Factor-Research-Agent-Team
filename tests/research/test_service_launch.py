"""Explicit service launch with real roles; no startup jobs or synthetic success gates."""

import importlib
import json
import os
import secrets
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from qfr_core.contracts import services
from qfr_core.service_runtime import (
    MAX_LAUNCH_JSON_BYTES,
    database_arguments,
    load_contract,
)
from qfr_eval.signing import EvaluatorSigner

ROOT = Path(__file__).resolve().parents[2]
MODULES = [
    ("qfr_research.serve", "ResearchServiceConfiguration"),
    ("qfr_registry.serve", "RegistryServiceConfiguration"),
    ("qfr_eval.feedback.serve", "FeedbackServiceConfiguration"),
    ("qfr_eval.ingest.serve", "IntakeServiceConfiguration"),
    ("qfr_mcp.serve", "MCPServiceConfiguration"),
]


def sample(name):
    return json.loads((ROOT / f"contracts/examples/{name}.valid.json").read_bytes())


def launch_settings(name, tmp_path, program):
    value = sample(name)
    env = {}

    # Resolve only explicit credential references; the fixture has no provider keys.
    def references(node):
        if isinstance(node, dict):
            for key, item in node.items():
                if key == "token_ref":
                    env.setdefault(item.removeprefix("env:"), secrets.token_urlsafe(32))
                else:
                    references(item)
        elif isinstance(node, list):
            for item in node:
                references(item)

    references(value)
    for binding in value["authentication"]["bindings"]:
        binding["programs"] = [str(program)]
        binding["roles"] = ["reader"]
        binding["principal"] = "schema-example"
    for binding in value.get("backends", []):
        binding["program_id"] = str(program)
    if "verification" in value:
        value["verification"] = (
            EvaluatorSigner(
                secrets.token_bytes(32), purposes=["released_report", "delivery_receipt"]
            )
            .verifier(maximum_document_bytes=1048576)
            .policy.model_dump(mode="json")
        )
    if name == "RegistryServiceConfiguration":
        value.update(
            publication_policy_file=str(ROOT / "configs/registry/publication_v1.json"),
            read_policy_file=str(ROOT / "configs/registry/read_v1.json"),
            dsl_policy_files={
                "pilot_industry_v1": str(ROOT / "configs/dsl/pilot_industry_v1.json")
            },
            payload_root=str(tmp_path / "payloads"),
        )
    elif name == "ResearchServiceConfiguration":
        root = tmp_path / "research"
        root.mkdir()
        value["research_root"] = str(root)
    elif name == "IntakeServiceConfiguration":
        value["quarantine_root"] = str(tmp_path / "quarantine")
    return value, env


@pytest.mark.parametrize("module,name", MODULES)
def test_launch_requires_configuration_and_secret_without_disclosing_it(
    module, name, tmp_path, monkeypatch, capsys
):
    value, env = launch_settings(name, tmp_path, uuid4())
    file = tmp_path / "service.json"
    file.write_text(json.dumps(value))
    for key in env:
        monkeypatch.delenv(key, raising=False)
    target = importlib.import_module(module)
    with pytest.raises(SystemExit) as failed:
        target.main([str(file)])
    assert failed.value.code == 1
    output = capsys.readouterr()
    assert "startup refused" in output.err
    assert not any(secret in output.err + output.out for secret in env.values())
    assert not (tmp_path / "quarantine").exists()  # Authenticate before creating any storage.


def test_bootstrap_duplicate_keys_nonfinite_and_bounds(tmp_path):
    path = tmp_path / "config.json"
    for raw in [b'{"port":1,"port":2}', b'{"port":NaN}', b"x" * (MAX_LAUNCH_JSON_BYTES + 1)]:
        path.write_bytes(raw)
        with pytest.raises(ValueError):
            load_contract(path, services.HTTPServerConfiguration)
    config = services.ServiceDatabaseConfiguration.model_validate(
        sample("ServiceDatabaseConfiguration")
    )
    for env in [{}, {"EXAMPLE_DB_PASSWORD": ""}, {"EXAMPLE_DB_PASSWORD": "bad\x00secret"}]:
        with pytest.raises(ValueError):
            database_arguments(config, env, "research")
    options = database_arguments(config, {"EXAMPLE_DB_PASSWORD": "synthetic-only"}, "research")
    assert options["user"] == "research_rw" and options["dbname"] == "research_db"
    assert "synthetic-only" not in config.model_dump_json()
    assert "password" not in config.model_dump()
    assert config.password_ref == "env:EXAMPLE_DB_PASSWORD"


@pytest.mark.database
@pytest.mark.parametrize("module,name", MODULES)
def test_actual_launch_health_auth_and_idle_state(
    module, name, tmp_path, research_connect, registry_connect, eval_connect
):
    program = uuid4()
    value, env = launch_settings(name, tmp_path, program)
    identities = {
        "ResearchServiceConfiguration": (research_connect, "research_rw"),
        "RegistryServiceConfiguration": (registry_connect, "registry_app"),
        "FeedbackServiceConfiguration": (eval_connect, "feedback_ro"),
    }
    if name in identities:
        factory, role = identities[name]
        with factory(role) as conn:
            value["database"].update(host=conn.info.host, port=conn.info.port)
        directory = Path(os.environ.get("QFR_TEST_SECRET_DIR", ROOT / ".secrets"))
        ref = value["database"]["password_ref"].removeprefix("env:")
        env[ref] = (directory / f"{role}_password").read_text().strip()
    with research_connect() as conn:
        before = conn.execute(
            "SELECT (SELECT count(*) FROM research.jobs), "
            "(SELECT count(*) FROM research.research_jobs)"
        ).fetchone()
    app = importlib.import_module(module).application(
        getattr(services, name).model_validate(value), env
    )
    with TestClient(app) as http:
        response = http.get("/healthz")
        assert response.status_code == 200
        path = {
            "MCPServiceConfiguration": "/mcp",
            "ResearchServiceConfiguration": "/v1/programs",
            "IntakeServiceConfiguration": f"/v1/programs/{program}/assets",
            "FeedbackServiceConfiguration": "/v1/reports",
            "RegistryServiceConfiguration": "/v1/artifacts?since_seq=0&limit=1",
        }[name]
        assert http.get(path).status_code == 401
    with research_connect() as conn:
        assert (
            conn.execute(
                "SELECT (SELECT count(*) FROM research.jobs), "
                "(SELECT count(*) FROM research.research_jobs)"
            ).fetchone()
            == before
        )
    if name == "IntakeServiceConfiguration":
        import sqlite3

        with sqlite3.connect(tmp_path / "quarantine/transfers.sqlite3") as conn:
            assert conn.execute("SELECT count(*) FROM uploads").fetchone() == (0,)
