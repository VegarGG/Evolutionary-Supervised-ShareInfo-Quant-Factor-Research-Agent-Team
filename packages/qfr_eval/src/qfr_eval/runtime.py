"""Evaluation-zone runtime: service configuration, environment, clock, database, logs."""

import importlib.metadata
import os
import sys
import threading
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol

import yaml
from pydantic import BaseModel, ConfigDict, Field
from qfr_core.config import RuntimeSettings, logging_config
from qfr_core.logging import JsonLogger
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine

EVAL_CONFIG_FILE = "eval.yaml"
# Every write to the evaluator's intake and queue state takes this transaction-level
# advisory lock first, so the scheduler's decisions are serialized (Section 8.3).
SCHEDULER_LOCK = 0x5146_5245_5641_4C  # "QFREVAL"


class SchedulerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    interval_seconds: float = Field(gt=0)
    intake_batch: int = Field(ge=1, le=2000)
    pool_event_batch: int = Field(ge=1, le=2000)
    bootstrap_configs: bool


class WorkerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    poll_seconds: float = Field(gt=0)
    max_attempts: int = Field(ge=1)
    retry_backoff_seconds: list[int]
    lease_seconds: int = Field(gt=0)


class RunnerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    mode: Literal["subprocess", "inline"]
    wall_clock_factor: float = Field(ge=1)
    load_cpu_seconds: float = Field(gt=0)


class ReleaseConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    interval_seconds: float = Field(gt=0)
    batch_limit: int = Field(ge=1)


class ApiConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    bind: str
    port: int = Field(gt=0, le=65535)
    list_default: int = Field(gt=0)
    list_max: int = Field(gt=0)


class IngestConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    check_seconds: float = Field(gt=0)
    recheck_seconds: float = Field(gt=0)
    keep_raw_releases: int = Field(ge=1)


class SimulationConfig(BaseModel):
    """sim-engine's operating parameters; the simulation rules are in the protocol."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    interval_seconds: float = Field(gt=0)
    mode: Literal["forward", "replay"]
    replay_days_per_tick: int = Field(ge=1)


class EvalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: str
    scheduler: SchedulerConfig
    worker: WorkerConfig
    runner: RunnerConfig
    release: ReleaseConfig
    apis: dict[Literal["feedback", "admin"], ApiConfig]
    ingest: IngestConfig
    simulation: SimulationConfig


def eval_config(root: Path) -> EvalConfig:
    return EvalConfig.model_validate(
        yaml.safe_load((root / EVAL_CONFIG_FILE).read_text(encoding="utf-8"))
    )


@dataclass(frozen=True)
class EvalEnvironment:
    """Paths and identities from the environment (Compose sets them; tests pass them)."""

    config_dir: Path
    store_dir: Path
    full_snapshot_dir: Path
    epoch_config: Path | None
    code_version: str
    image_digest: str
    worker_id: str = field(default_factory=lambda: f"{os.uname().nodename}-{os.getpid()}")

    @classmethod
    def from_env(cls, environ: Mapping[str, str], settings: RuntimeSettings) -> "EvalEnvironment":
        epoch = environ.get("QFR_EPOCH_CONFIG")
        return cls(
            config_dir=settings.config_dir,
            store_dir=Path(environ.get("QFR_EVAL_STORE_DIR") or "data/eval-store"),
            full_snapshot_dir=Path(environ.get("QFR_FULL_SNAPSHOT_DIR") or "data/snapshots/full"),
            epoch_config=Path(epoch) if epoch else None,
            code_version=environ.get("QFR_GIT_SHA")
            or f"qfr-eval-{importlib.metadata.version('qfr-eval')}",
            image_digest=environ.get("QFR_IMAGE_DIGEST") or "unpinned",
        )


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FixedClock:
    """A settable clock for tests; scheduling and release times come only from a Clock."""

    def __init__(self, at: datetime) -> None:
        self.at = at

    def now(self) -> datetime:
        return self.at

    def advance(self, **delta: float) -> datetime:
        from datetime import timedelta

        self.at = self.at + timedelta(**delta)
        return self.at


class Database:
    """eval_db access as eval_rw (or feedback_ro for feedback-api)."""

    def __init__(self, url: str | None = None, engine: Engine | None = None) -> None:
        if engine is None:
            if not url:
                raise ValueError("a database URL is required")
            engine = create_engine(url, pool_pre_ping=True)
        self.engine = engine

    @contextmanager
    def transaction(self, lock: bool = True) -> Iterator[Connection]:
        with self.engine.begin() as conn:
            if lock:
                conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": SCHEDULER_LOCK})
            yield conn

    @contextmanager
    def read(self) -> Iterator[Connection]:
        with self.engine.connect() as conn:
            yield conn

    def healthy(self, probe: str = "SELECT to_regclass('eval.intake')") -> bool:
        try:
            with self.read() as conn:
                return conn.execute(text(probe)).scalar() is not None
        except Exception:
            return False


def service_logger(
    service: str, settings: RuntimeSettings, secrets: list[str] | None = None
) -> JsonLogger:
    config = logging_config(settings.config_dir)
    if settings.log_level:
        config = config.model_copy(update={"level": settings.log_level})
    return JsonLogger(
        service, "eval", settings.log_dir, config, stdout=sys.stderr, secrets=secrets or []
    )


def start_heartbeat(path: Path | None, seconds: float = 30.0) -> None:
    """Touch the healthcheck file from a daemon thread, for services whose single job can
    outlast the healthcheck window (a W1 run, a daily CN build). It proves the process is
    alive; the job's own logs show progress."""
    if path is None:
        return

    def beat() -> None:
        while True:
            heartbeat(path, datetime.now(UTC))
            time.sleep(seconds)

    threading.Thread(target=beat, name="heartbeat", daemon=True).start()


def heartbeat(path: Path | None, now: datetime) -> None:
    """Touch the healthcheck file; Compose marks a stale heartbeat unhealthy."""
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(now.isoformat() + "\n", encoding="utf-8")
    os.replace(tmp, path)
