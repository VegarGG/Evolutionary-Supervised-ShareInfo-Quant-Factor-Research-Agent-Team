"""research-worker (P4.8 and P4.10): the job monitor tick and the generation queue.

Each tick runs the daily probe when due, returns stale queue jobs, lets the job monitor
apply deadlines, watch stopped jobs and start due generations, then runs queued
generations one at a time (tasks inside a generation run in parallel). A generation
that raises is retried with the configured backoff and resumes from its persisted
state; after the last attempt it is marked FAILED and the job schedules the next one.
Only this service holds provider keys (BND-07).
"""

import asyncio
import os
import threading
import time
from datetime import UTC, datetime
from datetime import time as dtime
from pathlib import Path
from typing import Any
from uuid import UUID

from qfr_core.config import RuntimeSettings
from qfr_core.correlation import bind
from sqlalchemy import text

from qfr_research import queue
from qfr_research.env import ResearchEnv
from qfr_research.jobs import JobService
from qfr_research.monitor import JobMonitor
from qfr_research.probe import run_probe
from qfr_research.store import Ctx
from qfr_research.workflow import GenerationRunner

SERVICE = "research-worker"


class Worker:
    def __init__(
        self,
        env: ResearchEnv,
        worker_id: str = SERVICE,
        monitor: JobMonitor | None = None,
        runner: GenerationRunner | None = None,
    ) -> None:
        self.env, self.worker_id = env, worker_id
        self.jobs = JobService(env)
        self.monitor = monitor or JobMonitor(env, self.jobs)
        self.runner = runner or GenerationRunner(env, self.monitor)

    async def tick(self) -> dict[str, Any]:
        env = self.env
        cfg = env.config.service.worker
        probed = await self.daily_probe()
        with env.db.transaction() as conn:
            stale = queue.requeue_stale(conn, env.clock, cfg.lease_seconds)
        ticked = self.monitor.tick()
        ran: list[dict[str, Any]] = []
        while True:
            with env.db.transaction() as conn:
                job = queue.claim(conn, env.clock, self.worker_id)
            if job is None:
                break
            ran.append(await self.run(job))
        return {
            "probe": probed,
            "stale_requeued": stale,
            "generations_started": [str(g) for g in ticked.started],
            "deliverables": [str(d) for d in ticked.deliverables],
            "jobs_closed": [str(j) for j in ticked.closed],
            "ran": ran,
        }

    async def run(self, job: queue.QueueJob) -> dict[str, Any]:
        env = self.env
        cfg = env.config.service.worker
        generation_id = UUID(job.payload["generation_id"])
        job_id = UUID(job.payload["job_id"])
        with bind(job_id=str(job_id), generation_id=str(generation_id)):
            env.logger.logger.info(
                "queue_job_claimed",
                outcome="ok",
                payload={"kind": job.kind, "attempt": job.attempts},
            )
            try:
                await self.job_start_probe(job_id, generation_id)
                state = await self.runner.run(generation_id)
            except Exception as error:  # noqa: BLE001 - every failure is retried or recorded
                code = f"{type(error).__name__}: {str(error)[:200]}"
                env.logger.logger.error(
                    "generation_attempt_failed",
                    outcome="failed",
                    error_code="GENERATION_ERROR",
                    payload={"attempt": job.attempts, "error": code},
                )
                if job.attempts >= cfg.max_attempts:
                    self.runner.fail(generation_id, code)
                    with env.db.transaction() as conn:
                        queue.finish(conn, env.clock, job, "failed", code)
                    return {"generation_id": str(generation_id), "state": "FAILED"}
                delays = cfg.retry_backoff_seconds
                with env.db.transaction() as conn:
                    queue.retry(
                        conn, env.clock, job, delays[min(job.attempts, len(delays)) - 1], code
                    )
                return {"generation_id": str(generation_id), "state": "RETRY"}
            with env.db.transaction() as conn:
                queue.finish(conn, env.clock, job, "done")
            env.logger.logger.info("queue_job_finished", outcome="ok", payload={"state": state})
            return {"generation_id": str(generation_id), "state": state}

    async def job_start_probe(self, job_id: UUID, generation_id: UUID) -> None:
        """Probe the providers before a job's first generation (Section 11.8)."""
        env = self.env
        if "job_start" not in env.config.providers.probe.get("run_at", []):
            return
        with env.db.read() as conn:
            row = conn.execute(
                text(
                    "SELECT g.seq, g.state, j.submitted_at, p.program_id FROM generations g "
                    "JOIN programs p ON p.program_id = g.program_id JOIN research_jobs j ON "
                    "j.job_id = p.job_id WHERE g.generation_id = :g"
                ),
                {"g": generation_id},
            ).one()
            if row.seq != 1 or row.state != "PENDING":
                return
            done = conn.execute(
                text("SELECT 1 FROM llm_probes WHERE trigger = 'job_start' AND at >= :s LIMIT 1"),
                {"s": row.submitted_at},
            ).first()
        if done is None:
            await run_probe(env, "job_start", Ctx(job_id=job_id, program_id=row.program_id))

    async def daily_probe(self) -> str | None:
        env = self.env
        if "daily" not in env.config.providers.probe.get("run_at", []):
            return None
        now = env.clock.now().astimezone(UTC)
        due = dtime.fromisoformat(env.config.service.worker.probe_daily_utc)
        if now.time() < due:
            return None
        day = datetime.combine(now.date(), dtime(0), tzinfo=UTC)
        with env.db.read() as conn:
            done = conn.execute(
                text("SELECT 1 FROM llm_probes WHERE trigger = 'daily' AND at >= :d LIMIT 1"),
                {"d": day},
            ).first()
        if done is not None:
            return None
        report = await run_probe(env, "daily")
        return str(report.probe_id)


def start_heartbeat(path: Path, seconds: float) -> threading.Thread:
    """Touch the healthcheck file from a background thread, as the Phase 3 services do,
    so a long synchronous step inside a generation (workbench, prescreen) cannot make a
    working worker look stale. Compose marks a file older than 180 seconds unhealthy."""

    def beat() -> None:
        while True:
            path.touch()
            time.sleep(seconds)

    thread = threading.Thread(target=beat, name="heartbeat", daemon=True)
    thread.start()
    return thread


async def serve(worker: Worker, beat_file: Path) -> None:
    env = worker.env
    cfg = env.config.service.worker
    start_heartbeat(beat_file, cfg.heartbeat_seconds)
    logged = 0.0
    while True:
        with bind():
            if time.monotonic() - logged >= cfg.heartbeat_seconds:
                env.logger.logger.info("worker_heartbeat", outcome="ok")
                logged = time.monotonic()
            try:
                result = await worker.tick()
                if result["ran"] or result["generations_started"] or result["jobs_closed"]:
                    env.logger.logger.info("worker_tick", outcome="ok", payload=result)
            except Exception as error:  # noqa: BLE001 - the loop survives and logs
                env.logger.logger.error(
                    "worker_tick_failed",
                    outcome="failed",
                    error_code=type(error).__name__,
                    payload={"error": str(error)[:300]},
                )
        await asyncio.sleep(cfg.tick_seconds)


def main() -> None:
    from qfr_research.api import build_env

    settings = RuntimeSettings(service=SERVICE, zone="research")
    env = build_env(settings, dict(os.environ), "worker")
    env.logger.logger.info(
        "service_started", outcome="ok", payload={"configuration_digests": env.config.digests}
    )
    beat_file = Path(os.environ.get("QFR_HEARTBEAT_FILE") or "/tmp/heartbeat")
    asyncio.run(serve(Worker(env, f"{SERVICE}:{os.getpid()}"), beat_file))


if __name__ == "__main__":
    main()
