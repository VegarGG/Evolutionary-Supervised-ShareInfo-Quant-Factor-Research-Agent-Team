"""A registry-api over the real PostgreSQL registry_db, one rolled-back transaction per test.

Every test runs inside an outer transaction that is rolled back at the end, so the
insert-only tables stay empty between tests (the fresh-stack checks rely on it). Each
registry write uses a savepoint inside it, under the same advisory lock as production.
"""

import io
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from qfr_core.config import logging_config, public_protocol_section, registry_config
from qfr_core.dsl import DslLimits, validate
from qfr_core.ids import uuid7
from qfr_core.logging import JsonLogger
from qfr_registry.app import create_app
from qfr_registry.auth import TokenAuth
from qfr_registry.db import WRITE_LOCK, Database
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection
from starlette.testclient import TestClient

TOKENS = {
    "publisher": "test-publisher-token",
    "reader": "test-reader-token",
    "evaluator": "test-evaluator-token",
    "control": "test-control-token",
}
LIMITS = DslLimits.from_protocol(public_protocol_section(Path("configs"), "dsl"))
SNAPSHOT = "a" * 64


def database_url(name: str) -> str:
    url = os.environ.get(f"QFR_TEST_{name}_DB_URL")
    if not url:
        if os.environ.get("QFR_REQUIRE_DB_TESTS") == "1":
            pytest.fail("real PostgreSQL tests required but credentials are absent")
        pytest.skip("PostgreSQL integration credentials not configured")
    return url


class TransactionalDatabase(Database):
    def __init__(self, url: str) -> None:
        engine = create_engine(url)
        super().__init__(engine=engine)
        self.conn = engine.connect()
        self.outer = self.conn.begin()

    @contextmanager
    def transaction(self) -> Iterator[Connection]:
        with self.conn.begin_nested():
            self.conn.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": WRITE_LOCK})
            yield self.conn

    @contextmanager
    def read(self) -> Iterator[Connection]:
        yield self.conn

    def close(self) -> None:
        self.outer.rollback()
        self.conn.close()
        self.engine.dispose()


def headers(role: str, **extra: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKENS[role]}"} | extra


@dataclass
class RegistryRig:
    client: TestClient
    db: TransactionalDatabase
    log_dir: Path

    def publish(self, manifest: dict[str, Any], role: str = "publisher", key: str | None = None):
        body = {"publish_key": key or f"k-{uuid7()}", "manifest": manifest}
        return self.client.post("/v1/artifacts", json=body, headers=headers(role))

    def log_lines(self) -> str:
        return "".join(p.read_text() for p in (self.log_dir / "registry-api").glob("*.jsonl"))


@contextmanager
def registry_rig(tmp_path: Path) -> Iterator[RegistryRig]:
    db = TransactionalDatabase(database_url("REGISTRY"))
    logger = JsonLogger(
        "registry-api",
        "registry",
        tmp_path,
        logging_config(Path("configs")),
        stdout=io.StringIO(),
        secrets=list(TOKENS.values()),
    )
    app = create_app(db, TokenAuth(TOKENS), registry_config(Path("configs")), LIMITS, logger)
    try:
        with TestClient(app, base_url="http://registry-api:8000") as client:
            yield RegistryRig(client, db, tmp_path)
    finally:
        db.close()


def research_ids() -> dict[str, Any]:
    return {
        "job_id": str(uuid7()),
        "program_id": str(uuid7()),
        "generation_id": str(uuid7()),
        "island_id": "I1",
    }


def factor_manifest(
    name: str = "momentum_ratio",
    expression: str = "Mean($close, 20) / Mean($close, 60) - 1",
    *,
    sign: int = 1,
    horizon: int = 5,
    family_id: str | None = None,
    parents: list[str] | None = None,
    operator: str = "explore",
    ids: dict[str, Any] | None = None,
    title: str | None = None,
) -> dict[str, Any]:
    analysis = validate(expression, LIMITS).analysis
    assert analysis is not None, expression
    parents = parents or []
    provenance = (ids if ids is not None else research_ids()) | {
        "operator": operator,
        "parent_version_ids": parents,
        "agent_runs": [],
        "trace_ref": str(uuid7()),
        "research_snapshot_id": SNAPSHOT,
        "qfr_core_version": "0.1.0",
    }
    return {
        "schema_version": "1",
        "kind": "factor",
        "family_id": family_id,
        "name": name,
        "title": title or f"Factor {name}",
        "implementation": {"language": "qfr-dsl/1", "expression": expression},
        "declared": {
            "expected_sign": sign,
            "horizon_days": horizon,
            "fields_used": list(analysis.fields),
            "max_lookback_days": analysis.max_lookback_days,
        },
        "rationale": {
            "hypothesis_id": str(uuid7()),
            "summary": "Test hypothesis.",
            "mechanism": "Trend persistence.",
            "falsification": "No positive relation.",
            "change_summary": "Changed the window." if parents else None,
        },
        "provenance": provenance,
        "review": {"verdict_id": str(uuid7()), "rounds": 1},
    }


def strategy_manifest(
    components: list[tuple[str, int, float]],
    name: str = "blend",
    *,
    family_id: str | None = None,
    extra_parents: list[str] | None = None,
    ids: dict[str, Any] | None = None,
    top_k: int = 50,
) -> dict[str, Any]:
    parents = [c[0] for c in components] + (extra_parents or [])
    return {
        "schema_version": "1",
        "kind": "strategy",
        "family_id": family_id,
        "name": name,
        "title": f"Strategy {name}",
        "implementation": {
            "language": "qfr-strategy/1",
            "components": [{"version_id": v, "sign": s, "weight": w} for v, s, w in components],
            "combination": "zscore_weighted_sum",
            "portfolio": {
                "type": "topk_dropout",
                "top_k": top_k,
                "dropout": 5,
                "rebalance": "daily",
                "long_only": True,
            },
        },
        "declared": {"expected_sign": 1, "horizon_days": 5},
        "rationale": {
            "hypothesis_id": str(uuid7()),
            "summary": "Test strategy.",
            "mechanism": "Blend.",
            "falsification": "No excess return.",
            "change_summary": "Composed from components.",
            "composition_rationale": "Equal blend.",
        },
        "provenance": (ids if ids is not None else research_ids())
        | {
            "operator": "explore",
            "parent_version_ids": parents,
            "agent_runs": [],
            "trace_ref": str(uuid7()),
            "research_snapshot_id": SNAPSHOT,
            "qfr_core_version": "0.1.0",
        },
        "review": {"verdict_id": str(uuid7()), "rounds": 1},
    }


def seed_manifest(name: str = "seed_ratio", expression: str = "Mean($close, 5) - $close"):
    manifest = factor_manifest(
        name,
        expression,
        operator="human_seed",
        ids={
            "job_id": None,
            "program_id": None,
            "generation_id": None,
            "island_id": None,
        },
    )
    manifest["provenance"]["research_snapshot_id"] = None
    manifest["review"]["rounds"] = 0
    return manifest
