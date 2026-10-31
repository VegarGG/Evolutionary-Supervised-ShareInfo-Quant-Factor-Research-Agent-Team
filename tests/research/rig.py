"""The research zone in process: research-api and research-worker over real research_db,
with scripted models, on the small synthetic world.

research_db runs inside an outer transaction rolled back after the test, like the other
rigs. research_rig alone gives research with registry-api (for publications and the
trace tests); research_stack adds the whole Phase 3 stack and the MCP front door, which
reaches research-api over an ASGI transport with the control token, as in Compose.
"""

import asyncio
import io
import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from qfr_core.config import logging_config
from qfr_core.eval_api import Card, ReportPage
from qfr_core.logging import JsonLogger
from qfr_registry.db import WRITE_LOCK
from qfr_research import api as research_api
from qfr_research.clients import FeedbackClient, RegistryClient, ServiceUnavailable
from qfr_research.db import RESEARCH_LOCK, Database, FixedClock
from qfr_research.env import ResearchEnv
from qfr_research.prompts import PromptLibrary
from qfr_research.providers import ProviderUnavailable
from qfr_research.settings import ResearchConfig
from qfr_research.worker import Worker
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection
from starlette.testclient import TestClient

from tests.eval.eval_rig import START, EvalRig, eval_rig
from tests.eval.stack_rig import LateApp, eval_apps
from tests.mcp.setup_rig import EVAL_TOKENS, SetupRig, setup_rig
from tests.registry_rig import TOKENS, RegistryRig, database_url, registry_rig
from tests.research.scripted import Script, ScriptedModels, priced
from tests.synthetic_fixtures import BuiltZones

RESEARCH_TOKEN = "test-research-control-token"


class TransactionalResearchDb(Database):
    """One research_db connection; every service transaction is a savepoint inside a
    rolled-back outer transaction. The rig holds the research advisory lock for the whole
    test, so parallel tests (pytest -n) never interleave research writes."""

    def __init__(self, url: str) -> None:
        engine = create_engine(url)
        super().__init__(engine=engine)
        self.conn = engine.connect()
        self.outer = self.conn.begin()
        self.mutex = threading.RLock()  # research-api handlers run in a thread pool

    @contextmanager
    def transaction(self, lock: bool = False) -> Iterator[Connection]:
        with self.mutex, self.conn.begin_nested():
            yield self.conn

    @contextmanager
    def read(self) -> Iterator[Connection]:
        with self.mutex:
            yield self.conn

    def scalar(self, sql: str, **params: Any) -> Any:
        with self.mutex:
            return self.conn.execute(text(sql), params).scalar()

    def rows(self, sql: str, **params: Any) -> list[Any]:
        with self.mutex:
            return list(self.conn.execute(text(sql), params).all())

    def close(self) -> None:
        self.outer.rollback()
        self.conn.close()
        self.engine.dispose()


class NoModels:
    """research-api's model source: it holds no provider keys (BND-07)."""

    def model(self, role: str, ref: Any) -> Any:
        raise ProviderUnavailable("research-api holds no provider keys")

    async def list_models(self, provider: str) -> list[str]:
        raise ProviderUnavailable("research-api holds no provider keys")

    async def balance(self, provider: str) -> dict[str, Any]:
        raise ProviderUnavailable("research-api holds no provider keys")


class NoReports(FeedbackClient):
    """feedback-api for research tests without the evaluator: nothing released yet, and no
    active card (research reads the bundled preview cards)."""

    def __init__(self, logger: JsonLogger) -> None:
        super().__init__("http://feedback-api:8000", EVAL_TOKENS["feedback-api"], logger)

    def reports(self, **params: Any) -> ReportPage:
        return ReportPage(items=[], next_after_id=None)

    def card(self, kind: str) -> Card:
        raise ServiceUnavailable("feedback-api: no evaluator in this rig")


async def no_sleep(seconds: float) -> None:
    return None


def research_logger(tmp_path: Path, service: str) -> JsonLogger:
    return JsonLogger(
        service,
        "research",
        tmp_path,
        logging_config(Path("configs")),
        stdout=io.StringIO(),
        secrets=[RESEARCH_TOKEN, *TOKENS.values(), *EVAL_TOKENS.values()],
    )


@dataclass
class ResearchRig:
    db: TransactionalResearchDb
    clock: Any
    config: ResearchConfig
    script: Script
    api_env: ResearchEnv
    env: ResearchEnv
    worker: Worker
    app: Any
    client: TestClient
    tmp_path: Path

    def tick(self) -> dict[str, Any]:
        """One research-worker tick: probe, monitor, then queued generations."""
        return asyncio.run(self.worker.tick())

    def logs(self, service: str) -> list[dict[str, Any]]:
        lines = []
        for path in sorted((self.tmp_path / service).glob("*.jsonl")):
            lines += [json.loads(line) for line in path.read_text().splitlines() if line]
        return lines

    def steps(self, **where: Any) -> list[Any]:
        clauses = " AND ".join(f"{k} = :{k}" for k in where) or "true"
        return self.db.rows(f"SELECT * FROM trace_steps WHERE {clauses} ORDER BY at", **where)


def brief(**overrides: Any) -> dict[str, Any]:
    """A brief for tests. Every field is the test's choice; nothing is a product default."""
    body: dict[str, Any] = {
        "schema_version": "brief/1",
        "title": "Short-horizon reversal",
        "objective": "Find a short-horizon reversal factor on the synthetic universe.",
        "mode": "new_factors",
        "seeds": {"pool_entry_ids": [], "version_ids": [], "expressions": [], "notes": ""},
        "islands": ["I2"],
        "constraints": {
            "fields_allowed": [],
            "operators_allowed": [],
            "max_nodes": 30,
            "max_lookback_days": 120,
        },
        "strategy_spec": None,
        "deliverable": {"tier": "w1_pass", "min_count": 1, "max_candidates": 2},
        "budget": {"max_cost": 40.0, "max_generations": 3, "max_wall_clock_days": 14},
        "parent_job_id": None,
        "priority": "normal",
    }
    return body | overrides


@contextmanager
def research_rig(
    tmp_path: Path,
    zones: BuiltZones,
    registry: RegistryRig,
    script: Script,
    *,
    clock: Any = None,
    feedback: TestClient | None = None,
) -> Iterator[ResearchRig]:
    db = TransactionalResearchDb(database_url("RESEARCH"))
    try:
        # Lock order across rigs: registry first, then research (as the eval rig does).
        registry.db.conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": WRITE_LOCK})
        db.conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": RESEARCH_LOCK})
        clock = clock or FixedClock(START)
        config = priced(ResearchConfig.load(Path("configs")))

        def env(service: str, models: Any) -> ResearchEnv:
            logger = research_logger(tmp_path, service)
            return ResearchEnv(
                config=config,
                db=db,
                clock=clock,
                logger=logger,
                registry=RegistryClient(
                    "http://registry-api:8000", TOKENS["publisher"], logger, client=registry.client
                ),
                feedback=NoReports(logger)
                if feedback is None
                else FeedbackClient(
                    "http://feedback-api:8000",
                    EVAL_TOKENS["feedback-api"],
                    logger,
                    client=feedback,
                ),
                models=models,
                prompts=PromptLibrary(Path("prompts")),
                research_snapshot_dir=zones.research.path,
                sleep=no_sleep,
            )

        api_env = env("research-api", NoModels())
        worker_env = env("research-worker", ScriptedModels(config, script))
        app = research_api.create_app(api_env, RESEARCH_TOKEN)
        with TestClient(app, base_url="http://research-api:8000") as client:
            client.headers["Authorization"] = f"Bearer {RESEARCH_TOKEN}"
            yield ResearchRig(
                db,
                clock,
                config,
                script,
                api_env,
                worker_env,
                Worker(worker_env, "test-research-worker"),
                app,
                client,
                tmp_path,
            )
    finally:
        db.close()


@contextmanager
def research_only(
    tmp_path: Path, zones: BuiltZones, script: Script
) -> Iterator[tuple[RegistryRig, ResearchRig]]:
    with (
        registry_rig(tmp_path) as registry,
        research_rig(tmp_path, zones, registry, script) as research,
    ):
        yield registry, research


@dataclass
class ResearchStack:
    mcp: SetupRig
    eval: EvalRig
    admin: TestClient
    feedback: TestClient
    research: ResearchRig

    def settle(self, rounds: int = 4) -> None:
        self.eval.cycle(rounds)


@contextmanager
def research_stack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, zones: BuiltZones, script: Script
) -> Iterator[ResearchStack]:
    admin_late, feedback_late, research_late = LateApp(), LateApp(), LateApp()
    transports: dict[str, httpx.AsyncBaseTransport] = {
        "eval-admin-api": httpx.ASGITransport(app=admin_late),
        "feedback-api": httpx.ASGITransport(app=feedback_late),
        "research-api": httpx.ASGITransport(app=research_late),
    }
    monkeypatch.setenv("RESEARCH_CONTROL_TOKEN", RESEARCH_TOKEN)
    with (
        setup_rig(tmp_path, monkeypatch, transports) as mcp,
        eval_rig(tmp_path, zones, registry=mcp.registry) as rig,
    ):
        admin_late.app, feedback_late.app = eval_apps(rig)
        with (
            TestClient(admin_late.app, base_url="http://eval-admin-api:8000") as admin,
            TestClient(feedback_late.app, base_url="http://feedback-api:8000") as feedback,
        ):
            admin.headers["Authorization"] = f"Bearer {EVAL_TOKENS['eval-admin-api']}"
            feedback.headers["Authorization"] = f"Bearer {EVAL_TOKENS['feedback-api']}"
            with research_rig(
                tmp_path, zones, mcp.registry, script, clock=rig.clock, feedback=feedback
            ) as research:
                research_late.app = research.app
                yield ResearchStack(mcp, rig, admin, feedback, research)
