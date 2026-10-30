"""The evaluation zone in process: registry-api, eval-scheduler, eval-worker and the
release engine over real PostgreSQL, on the small synthetic world.

registry_db and eval_db each run inside an outer transaction that is rolled back after
the test, so every test starts from an empty stack. Each service write is a savepoint
inside it, under the same advisory lock as production. The clock is fixed and moved by
the test; the worker computes in process (the subprocess runner has its own tests).
"""

import io
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from qfr_core.config import RuntimeSettings, logging_config
from qfr_core.logging import JsonLogger
from qfr_eval.compute import InlineRunner, Runner
from qfr_eval.registry import RegistryReader
from qfr_eval.release import ReleaseEngine
from qfr_eval.runtime import SCHEDULER_LOCK, Database, EvalEnvironment, FixedClock, eval_config
from qfr_eval.scheduler import Scheduler
from qfr_eval.worker import Worker
from qfr_registry.db import WRITE_LOCK
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

from tests.registry_rig import TOKENS, RegistryRig, database_url, registry_rig
from tests.synthetic_fixtures import SMALL_EPOCH, BuiltZones

# In the past, so the feedback views (released_at <= now()) show what the rig releases.
START = datetime(2026, 1, 5, 1, 0, tzinfo=UTC)


class TransactionalEvalDatabase(Database):
    def __init__(self, url: str) -> None:
        engine = create_engine(url)
        super().__init__(engine=engine)
        self.conn = engine.connect()
        self.outer = self.conn.begin()

    @contextmanager
    def transaction(self, lock: bool = True) -> Iterator[Connection]:
        with self.conn.begin_nested():
            if lock:
                self.conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": SCHEDULER_LOCK})
            yield self.conn

    @contextmanager
    def read(self) -> Iterator[Connection]:
        yield self.conn

    def scalar(self, sql: str, **params: Any) -> Any:
        return self.conn.execute(text(sql), params).scalar()

    def rows(self, sql: str, **params: Any) -> list[Any]:
        return list(self.conn.execute(text(sql), params).all())

    def close(self) -> None:
        self.outer.rollback()
        self.conn.close()
        self.engine.dispose()


def eval_logger(tmp_path: Path, service: str) -> JsonLogger:
    return JsonLogger(
        service, "eval", tmp_path, logging_config(Path("configs")), stdout=io.StringIO()
    )


@dataclass
class EvalRig:
    registry: RegistryRig
    db: TransactionalEvalDatabase
    clock: FixedClock
    env: EvalEnvironment
    scheduler: Scheduler
    worker: Worker
    release: ReleaseEngine
    tmp_path: Path

    def drain(self, limit: int = 500) -> int:
        """Run the worker until the queue is empty (jobs due now)."""
        done = 0
        while done < limit and self.worker.run_once():
            done += 1
        return done

    def cycle(self, rounds: int = 3) -> None:
        """Scheduler tick and worker drain, repeated until intake settles."""
        for _ in range(rounds):
            self.scheduler.tick()
            self.drain()
        self.scheduler.tick()

    def state_counts(self) -> dict[str, int]:
        rows = self.db.rows("SELECT state, count(*) AS n FROM eval.intake GROUP BY state")
        return {r.state: int(r.n) for r in rows}


@contextmanager
def eval_rig(
    tmp_path: Path,
    zones: BuiltZones,
    *,
    runner: Runner | None = None,
    epoch: dict[str, Any] | None = None,
    registry: RegistryRig | None = None,
) -> Iterator[EvalRig]:
    db = TransactionalEvalDatabase(database_url("EVAL"))
    try:
        with _registry(tmp_path, registry) as reg:
            # Rolled-back rigs hold their rows and advisory locks until the test ends, and
            # every eval rig writes the same keys (the shipped protocol, the epoch). Taking
            # the registry lock first orders parallel tests (pytest -n) on one lock instead
            # of letting two of them wait on each other across the two databases.
            reg.db.conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": WRITE_LOCK})
            clock = FixedClock(START)
            settings = RuntimeSettings(config_dir=Path("configs"), log_dir=tmp_path)
            env = EvalEnvironment(
                config_dir=settings.config_dir,
                store_dir=tmp_path / "eval-store",
                full_snapshot_dir=zones.root / "full",
                epoch_config=None,
                code_version="test-sha",
                image_digest="sha256:test",
                worker_id="test-worker",
            )
            config = eval_config(Path("configs"))
            reader = RegistryReader(
                "http://registry-api:8000",
                TOKENS["evaluator"],
                eval_logger(tmp_path, "eval-scheduler"),
                reg.client,
            )
            scheduler = Scheduler(
                db, reader, env, config, eval_logger(tmp_path, "eval-scheduler"), clock,
                epoch_override=epoch or SMALL_EPOCH,
            )  # fmt: skip
            worker = Worker(
                db, env, config, eval_logger(tmp_path, "eval-worker"),
                runner or InlineRunner(), clock,
            )  # fmt: skip
            release = ReleaseEngine(db, config, eval_logger(tmp_path, "release-worker"), clock)
            yield EvalRig(reg, db, clock, env, scheduler, worker, release, tmp_path)
    finally:
        db.close()


@contextmanager
def _registry(tmp_path: Path, existing: RegistryRig | None) -> Iterator[RegistryRig]:
    if existing is not None:
        yield existing
        return
    with registry_rig(tmp_path) as rig:
        yield rig
