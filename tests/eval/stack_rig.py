"""The whole Phase 3 stack in process: the MCP front door, registry-api, control_db,
eval-scheduler, eval-worker, release-worker, eval-admin-api and feedback-api.

Every database runs inside a rolled-back outer transaction. The front door reaches
registry-api, eval-admin-api and feedback-api over ASGI transports, so each call crosses
the same HTTP boundary, tokens and request-id propagation as in Compose.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from qfr_eval import admin_api, feedback_api
from qfr_eval.compute import Runner
from qfr_eval.runtime import EvalConfig, eval_config
from qfr_eval.store import ArtifactStore
from starlette.testclient import TestClient

from tests.eval.eval_rig import EvalRig, eval_logger, eval_rig
from tests.mcp.setup_rig import EVAL_TOKENS, SetupRig, setup_rig
from tests.synthetic_fixtures import BuiltZones


class LateApp:
    """An ASGI app bound after the front door is built (the eval rig needs its registry)."""

    def __init__(self) -> None:
        self.app: Any = None

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        await self.app(scope, receive, send)


@dataclass
class Stack:
    mcp: SetupRig
    eval: EvalRig
    admin: TestClient
    feedback: TestClient

    def settle(self, rounds: int = 4) -> None:
        self.eval.cycle(rounds)


def eval_apps(rig: EvalRig) -> tuple[Any, Any]:
    config = eval_config(Path("configs"))
    admin = admin_api.create_app(
        rig.db,
        EVAL_TOKENS["eval-admin-api"],
        config.apis["admin"],
        ArtifactStore(rig.env.store_dir),
        eval_logger(rig.tmp_path, "eval-admin-api"),
        rig.clock,
    )
    feedback = feedback_api.create_app(
        rig.db,
        EVAL_TOKENS["feedback-api"],
        config.apis["feedback"],
        eval_logger(rig.tmp_path, "feedback-api"),
    )
    return admin, feedback


@contextmanager
def stack(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    zones: BuiltZones,
    runner: Runner | None = None,
    *,
    epoch: dict[str, Any] | None = None,
    config: EvalConfig | None = None,
) -> Iterator[Stack]:
    admin_late, feedback_late = LateApp(), LateApp()
    transports: dict[str, httpx.AsyncBaseTransport] = {
        "eval-admin-api": httpx.ASGITransport(app=admin_late),
        "feedback-api": httpx.ASGITransport(app=feedback_late),
    }
    with (
        setup_rig(tmp_path, monkeypatch, transports) as mcp,
        eval_rig(
            tmp_path, zones, registry=mcp.registry, runner=runner, epoch=epoch, config=config
        ) as rig,
    ):
        admin_late.app, feedback_late.app = eval_apps(rig)
        with (
            TestClient(admin_late.app, base_url="http://eval-admin-api:8000") as admin,
            TestClient(feedback_late.app, base_url="http://feedback-api:8000") as feedback,
        ):
            admin.headers["Authorization"] = f"Bearer {EVAL_TOKENS['eval-admin-api']}"
            feedback.headers["Authorization"] = f"Bearer {EVAL_TOKENS['feedback-api']}"
            yield Stack(mcp, rig, admin, feedback)
