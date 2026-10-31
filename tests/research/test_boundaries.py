"""BND-02 and BND-05 for the research zone, and the research services' Compose wiring."""

import ast
import json
from pathlib import Path

from qfr_core.logging import PROVIDER_ENV
from qfr_research.settings import ROLES
from qfr_research.tools import llm_tools, snapshot

COMPOSE = json.loads(Path("infra/docker-compose.yml").read_text())
RESEARCH = ("research-api", "research-worker")
# Evaluation-admin and control credentials and addresses (BND-05).
FORBIDDEN_ENV = {
    "EVAL_OWNER_TOKEN",
    "EVAL_ADMIN_API_URL",
    "EVAL_DB_URL",
    "CONTROL_DB_URL",
    "REGISTRY_CONTROL_TOKEN",
    "REGISTRY_EVALUATOR_TOKEN",
    "QFR_MCP_TOKEN",
}


def test_bnd_02_research_tool_registry_snapshot():
    assert snapshot() == {
        "blackboard.read": sorted(
            ["analyst", "critic", "engineer", "evolution", "hypothesis", "packager", "supervisor"]
        ),
        "blackboard.write": sorted(
            ["analyst", "critic", "engineer", "evolution", "hypothesis", "packager", "supervisor"]
        ),
        "kb.search": ["analyst", "critic", "engineer", "hypothesis", "supervisor"],
        "dsl.validate": ["critic", "engineer", "evolution", "packager"],
        "dsl.explain": ["critic", "engineer", "evolution", "packager"],
        "workbench.evaluate": ["critic", "engineer", "evolution"],
        "similarity.search": ["critic", "engineer", "evolution", "hypothesis", "packager"],
        "feedback.read": ["analyst", "engineer", "evolution", "supervisor"],
        "registry.read": sorted(
            ["analyst", "critic", "engineer", "evolution", "hypothesis", "packager", "supervisor"]
        ),
        "registry.publish": ["packager"],
        "budget.read": ["evolution", "supervisor"],
    }
    # No tool can affect evaluation, pools or jobs, and no LLM can publish.
    namespaces = {name.split(".")[0] for name in snapshot()}
    assert namespaces == {
        "blackboard", "kb", "dsl", "workbench", "similarity", "feedback", "registry", "budget",
    }  # fmt: skip
    for role in ROLES:
        names = {tool.name for tool in llm_tools(role)}
        assert "registry_publish" not in names and "blackboard_write" not in names, role
        assert all(n.endswith(("_read", "_search", "_validate", "_explain", "_evaluate"))
                   for n in names), (role, names)  # fmt: skip


def test_bnd_05_research_configuration_holds_no_evaluation_or_control_access():
    for path in sorted(Path("configs/research").glob("*.yaml")):
        text = path.read_text().lower()
        for word in ("eval-admin", "eval_owner", "control_db", "qfr-mcp", ":8765", "control_token"):
            assert word not in text, (path.name, word)
    for name in RESEARCH:
        environment = set(COMPOSE["services"][name]["environment"])
        assert not environment & FORBIDDEN_ENV, (name, environment & FORBIDDEN_ENV)
    # research-api holds the control token it checks; research-worker holds none.
    assert "RESEARCH_CONTROL_TOKEN" in COMPOSE["services"]["research-api"]["environment"]
    assert "RESEARCH_CONTROL_TOKEN" not in COMPOSE["services"]["research-worker"]["environment"]


def test_bnd_05_research_code_reaches_only_the_registry_and_feedback_api():
    """The research package names no evaluation-admin or control address or token, and its
    only HTTP clients are registry-api's and feedback-api's (the providers aside)."""
    root = Path("packages/qfr_research/src/qfr_research")
    for path in sorted(root.glob("*.py")):
        source = path.read_text()
        for word in (
            "EVAL_ADMIN_API_URL",
            "EVAL_OWNER_TOKEN",
            "CONTROL_DB_URL",
            "REGISTRY_CONTROL_TOKEN",
            "http://eval-admin-api",
        ):
            assert word not in source, (path.name, word)
        tree = ast.parse(source)
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import | ast.ImportFrom)
            for alias in node.names
        } | {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        assert not {m for m in imported if m and m.startswith(("qfr_eval", "qfr_mcp"))}
    clients = (root / "clients.py").read_text()
    assert {"RegistryClient", "FeedbackClient"} <= set(
        n.name for n in ast.parse(clients).body if isinstance(n, ast.ClassDef)
    )


def test_research_services_run_the_research_image():
    commands = {
        "research-api": ["python", "-m", "qfr_research.api"],
        "research-worker": ["python", "-m", "qfr_research.worker"],
    }
    for name, command in commands.items():
        service = COMPOSE["services"][name]
        assert service["command"] == command
        assert service["build"]["target"] == "research"
        assert service["build"]["args"] == {"QFR_PACKAGE": "qfr-research"}
        assert service["environment"]["QFR_ZONE"] == "research"
    worker = COMPOSE["services"]["research-worker"]["environment"]
    assert PROVIDER_ENV <= set(worker)  # BND-07: only the worker gets provider keys
    assert not PROVIDER_ENV & set(COMPOSE["services"]["research-api"]["environment"])
    assert COMPOSE["services"]["research-api"]["environment"]["QFR_RESEARCH_BIND"] == "0.0.0.0"
    mcp = COMPOSE["services"]["qfr-mcp"]["environment"]
    assert mcp["RESEARCH_API_URL"] == "http://research-api:8000"
    assert "RESEARCH_CONTROL_TOKEN" in mcp
    dockerfile = Path("infra/Dockerfile").read_text()
    research = dockerfile.split("FROM runtime AS research")[1].split("FROM ")[0]
    assert "COPY prompts /app/prompts" in research
    assert "QFR_PROMPTS_DIR=/app/prompts" in research
