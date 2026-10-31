"""eval-scheduler (PLAN Section 8.3): pull, check, dedup, apply quotas and enqueue.

Every 60 seconds the scheduler
  1. activates the shipped configuration on first start, registers the current full
     snapshot and pins the epoch;
  2. pulls up to 100 versions after the intake cursor and writes an intake row for each;
  3. pulls pool events after the pool cursors and updates the library (Section 10.4);
  4. moves intake rows through schema and kind checks, exact dedup, fingerprinting,
     behavioral dedup, quotas (with deferral and expiry) and fair enqueueing.
Decisions are queued for release at the next W1 batch. Pool changes never trigger an
evaluation; a seed version is evaluated because it is a published version. The scheduler
decides alone what to pull and when: nothing outside the evaluation zone can call it.
"""

import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from pydantic import TypeAdapter, ValidationError
from qfr_core.config import QuotaConfig, RuntimeSettings, canonical_json
from qfr_core.contracts import Manifest, ReasonCode
from qfr_core.correlation import bind, current
from qfr_core.ids import uuid7
from qfr_core.logging import JsonLogger
from qfr_core.metrics.fingerprint import Fingerprint, behavioral_similarity
from sqlalchemy import bindparam, text
from sqlalchemy.engine import Connection

from qfr_eval import queue
from qfr_eval.configs import (
    ActiveState,
    EvalError,
    activate_epoch,
    active_epoch,
    active_state,
    active_version,
    bootstrap_configs,
    epoch_from_mapping,
    load_epoch_file,
    record_event,
    register_current_full,
    snapshot_calendar,
)
from qfr_eval.registry import RegistryReader, RegistryUnavailable
from qfr_eval.reports import queue_report
from qfr_eval.runtime import (
    Clock,
    Database,
    EvalConfig,
    EvalEnvironment,
    SystemClock,
    eval_config,
    heartbeat,
    service_logger,
)
from qfr_eval.store import ArtifactStore

SERVICE = "eval-scheduler"
PRINCIPAL = "eval-scheduler"
MANIFEST: TypeAdapter[Manifest] = TypeAdapter(Manifest)
POOL_STATUS = {"seed": "seed", "approved": "active", "retired": "retired"}
# Versions that passed dedup and still count for behavioral comparisons.
ADMITTED = ("Deferred", "Screening", "ScreenFailed", "W1Evaluated", "W1GateFailed")


@dataclass
class TickReport:
    ready: bool = False
    pulled: int = 0
    pool_events: int = 0
    decisions: dict[str, int] = field(default_factory=dict)
    activated: list[str] = field(default_factory=list)
    note: str | None = None

    def count(self, key: str) -> None:
        self.decisions[key] = self.decisions.get(key, 0) + 1


def _refs(state: ActiveState, code_version: str) -> dict[str, str]:
    return {
        "protocol_id": state.protocol.id,
        "protocol_version": state.protocol.version,
        "data_snapshot_id": state.epoch.snapshot_id,
        "evaluator_code_version": code_version,
    }


class Scheduler:
    def __init__(
        self,
        db: Database,
        registry: RegistryReader,
        env: EvalEnvironment,
        config: EvalConfig,
        logger: JsonLogger,
        clock: Clock | None = None,
        epoch_override: dict[str, Any] | None = None,
    ) -> None:
        self.db, self.registry, self.env, self.config = db, registry, env, config
        self.logger, self.log = logger, logger.logger
        self.clock = clock or SystemClock()
        self.store = ArtifactStore(env.store_dir)
        self.epoch_override = epoch_override
        self._fingerprints: dict[UUID, Fingerprint] = {}

    # Setup ---------------------------------------------------------------------------

    def ensure_ready(self, report: TickReport) -> ActiveState | None:
        now = self.clock.now()
        request_id = current()["request_id"]
        with self.db.transaction() as conn:
            if self.config.scheduler.bootstrap_configs:
                report.activated += bootstrap_configs(
                    conn, self.env.config_dir, PRINCIPAL, request_id, now
                )
            snapshot_id = register_current_full(
                conn, self.env.full_snapshot_dir, PRINCIPAL, request_id, now
            )
            if active_epoch(conn) is None:
                protocol = active_version(conn, "protocol")
                if snapshot_id is None or protocol is None:
                    report.note = "waiting for a full snapshot and an active protocol"
                    return None
                self._activate_epoch(conn, snapshot_id, protocol.config, now, report)
            state = active_state(conn)
        for item in report.activated:
            self.log.info("config_activated", outcome="ok", payload={"version": item})
        return state

    def _activate_epoch(
        self,
        conn: Connection,
        snapshot_id: str,
        protocol: dict[str, Any],
        now: datetime,
        report: TickReport,
    ) -> None:
        if self.epoch_override is not None:
            epoch, sha = epoch_from_mapping(self.epoch_override)
        else:
            path = self.env.epoch_config or (
                self.env.config_dir / "epochs" / f"{protocol['epoch_ref']}.yaml"
            )
            epoch, sha = load_epoch_file(path)
        calendar = snapshot_calendar(self.env.full_snapshot_dir, snapshot_id)
        try:
            pinned = activate_epoch(
                conn, epoch, sha, snapshot_id, calendar, str(protocol["epoch_ref"]),
                PRINCIPAL, None, current()["request_id"], now,
            )  # fmt: skip
        except EvalError as error:
            self.log.error(
                "epoch_activation_refused",
                outcome="failed",
                error_code=error.code,
                payload={"epoch_id": epoch.epoch_id, "details": error.details},
            )
            raise
        report.activated.append(f"epoch:{pinned.epoch_id}")
        self.log.info(
            "epoch_activated",
            outcome="ok",
            payload={
                "epoch_id": pinned.epoch_id,
                "snapshot_id": snapshot_id,
                "embargo_check": pinned.embargo_check,
            },
        )

    # Pulling -------------------------------------------------------------------------

    def pull_versions(self, report: TickReport) -> None:
        with self.db.read() as conn:
            cursor = conn.execute(
                text("SELECT last_published_seq FROM eval.intake_cursor WHERE id = 1")
            ).scalar()
        since = int(cursor or 0)
        items, next_seq = self.registry.versions(since, self.config.scheduler.intake_batch)
        now = self.clock.now()
        with self.db.transaction() as conn:
            for item in items:
                if self._insert_intake(conn, item, now):
                    report.pulled += 1
            conn.execute(
                text(
                    "INSERT INTO eval.intake_cursor (id, last_published_seq, updated_at) "
                    "VALUES (1, :s, :at) ON CONFLICT (id) DO UPDATE SET "
                    "last_published_seq = GREATEST(eval.intake_cursor.last_published_seq, :s), "
                    "updated_at = :at"
                ),
                {"s": max(next_seq, since), "at": now},
            )
        if items:
            self.log.info(
                "intake_pulled",
                outcome="ok",
                payload={"versions": len(items), "since_seq": since, "next_seq": next_seq},
            )

    def _insert_intake(self, conn: Connection, item: dict[str, Any], now: datetime) -> bool:
        try:
            version_id = UUID(str(item["version_id"]))
            published_seq = int(item["published_seq"])
            content_hash, canonical = str(item["content_hash"]), str(item["canonical_hash"])
            family_id = UUID(str(item["family_id"]))
        except (KeyError, ValueError, TypeError):
            self.log.error("intake_unreadable", outcome="failed", payload={"keys": sorted(item)})
            return False
        manifest = item.get("manifest") if isinstance(item.get("manifest"), dict) else {}
        provenance = manifest.get("provenance") if isinstance(manifest, dict) else None
        provenance = provenance if isinstance(provenance, dict) else {}

        def maybe_uuid(value: Any) -> UUID | None:
            try:
                return UUID(str(value)) if value else None
            except ValueError:
                return None

        inserted = conn.execute(
            text(
                "INSERT INTO eval.intake (version_id, published_seq, content_hash, "
                "canonical_hash, family_id, program_id, job_id, kind, manifest, discovered_at, "
                "state, updated_at, request_id) VALUES (:v, :seq, :ch, :canon, :f, :p, :j, :k, "
                "CAST(:m AS jsonb), :at, 'Discovered', :at, :r) "
                "ON CONFLICT (version_id) DO NOTHING RETURNING 1"
            ),
            {
                "v": version_id,
                "seq": published_seq,
                "ch": content_hash,
                "canon": canonical,
                "f": family_id,
                "p": maybe_uuid(provenance.get("program_id")),
                "j": maybe_uuid(provenance.get("job_id")),
                "k": str(item.get("kind", "")),
                "m": canonical_json(item),
                "at": now,
                "r": current()["request_id"],
            },
        ).first()
        return inserted is not None

    def sync_library(self, report: TickReport, state: ActiveState) -> None:
        for pool in ("factor", "strategy"):
            with self.db.read() as conn:
                since = conn.execute(
                    text("SELECT last_event_seq FROM eval.pool_sync_cursor WHERE pool = :p"),
                    {"p": pool},
                ).scalar()
            since = int(since or 0)
            events, next_seq = self.registry.pool_events(
                pool, since, self.config.scheduler.pool_event_batch
            )
            now = self.clock.now()
            with self.db.transaction() as conn:
                for event in events:
                    self._apply_pool_event(conn, pool, event, state, now)
                    report.pool_events += 1
                conn.execute(
                    text(
                        "INSERT INTO eval.pool_sync_cursor (pool, last_event_seq, updated_at) "
                        "VALUES (:p, :s, :at) ON CONFLICT (pool) DO UPDATE SET "
                        "last_event_seq = GREATEST(eval.pool_sync_cursor.last_event_seq, :s), "
                        "updated_at = :at"
                    ),
                    {"p": pool, "s": max(next_seq, since), "at": now},
                )
            if events:
                self.log.info(
                    "library_synced", outcome="ok", payload={"pool": pool, "events": len(events)}
                )

    def _apply_pool_event(
        self,
        conn: Connection,
        pool: str,
        event: dict[str, Any],
        state: ActiveState,
        now: datetime,
    ) -> None:
        to_status = event.get("to_status")
        if event.get("action") == "ANNOTATED" or to_status not in POOL_STATUS:
            return
        version_id = UUID(str(event["version_id"]))
        status = POOL_STATUS[str(to_status)]
        previous = conn.execute(
            text("SELECT status FROM eval.library WHERE version_id = :v"), {"v": version_id}
        ).scalar()
        effective = conn.execute(
            text(
                "SELECT created_at FROM eval.official_records WHERE version_id = :v "
                "AND stage = 'w1' AND epoch_id = :e"
            ),
            {"v": version_id, "e": state.epoch.epoch_id},
        ).scalar()
        conn.execute(
            text(
                "INSERT INTO eval.library (version_id, pool, entry_id, status, approved_tier, "
                "effective_from, last_event_seq, updated_at) VALUES (:v, :pool, :entry, :s, "
                ":tier, :eff, :seq, :at) ON CONFLICT (version_id) DO UPDATE SET status = :s, "
                "approved_tier = :tier, last_event_seq = :seq, updated_at = :at, "
                "effective_from = COALESCE(eval.library.effective_from, :eff)"
            ),
            {
                "v": version_id,
                "pool": pool,
                "entry": UUID(str(event["entry_id"])),
                "s": status,
                "tier": event.get("approved_tier"),
                "eff": effective,
                "seq": int(event["event_seq"]),
                "at": now,
            },
        )
        if previous != status:
            queue_report(
                conn,
                "library",
                version_id,
                {
                    "content": {"type": "library", "status": status},
                    "refs": _refs(state, self.env.code_version),
                },
                now,
                current()["request_id"],
            )
            record_event(
                conn, now, PRINCIPAL, "library_changed", "library", str(version_id),
                current()["request_id"], {"from": previous, "to": status, "pool": pool},
            )  # fmt: skip

    # Intake decisions ----------------------------------------------------------------

    def _decide(
        self,
        conn: Connection,
        row: Any,
        new_state: str,
        reason: ReasonCode | None,
        now: datetime,
        state: ActiveState,
        report: TickReport,
        *,
        status: str | None = None,
        duplicate_of: UUID | None = None,
        similarity: float | None = None,
        extra: str = "",
    ) -> None:
        conn.execute(
            text(
                "UPDATE eval.intake SET state = :s, reason_code = :rc, duplicate_of = :dup, "
                "similarity = :sim, decided_at = CASE WHEN :final THEN :at ELSE decided_at END, "
                f"updated_at = :at {extra} WHERE version_id = :v"
            ),
            {
                "s": new_state,
                "rc": reason.value if reason else None,
                "dup": duplicate_of,
                "sim": similarity,
                "final": new_state in ("IntakeRejected", "Duplicate"),
                "at": now,
                "v": row.version_id,
            },
        )
        if status is not None:
            content: dict[str, Any] = {
                "type": "intake",
                "status": status,
                "reasons": [reason.value] if reason else [],
                "duplicate_of": str(duplicate_of) if duplicate_of else None,
            }
            queue_report(
                conn,
                "intake",
                row.version_id,
                {"content": content, "refs": _refs(state, self.env.code_version)},
                now,
                current()["request_id"],
            )
        record_event(
            conn, now, PRINCIPAL, "intake_decided", "intake", str(row.version_id),
            current()["request_id"],
            {"state": new_state, "reason": reason.value if reason else None,
             "duplicate_of": str(duplicate_of) if duplicate_of else None},
        )  # fmt: skip
        report.count(new_state)
        self.log.info(
            "intake_decided",
            outcome="ok",
            payload={
                "version_id": str(row.version_id),
                "state": new_state,
                "reason": reason.value if reason else None,
            },
        )

    def process_discovered(self, report: TickReport, state: ActiveState) -> None:
        now = self.clock.now()
        supported = set(state.protocol.config["supported_kinds"])
        with self.db.transaction() as conn:
            rows = conn.execute(
                text(
                    "SELECT version_id, published_seq, family_id, program_id, canonical_hash, "
                    "kind, manifest FROM eval.intake WHERE state = 'Discovered' "
                    "ORDER BY published_seq"
                )
            ).all()
            for row in rows:
                try:
                    manifest = MANIFEST.validate_python(row.manifest.get("manifest"))
                except ValidationError:
                    self._decide(
                        conn, row, "IntakeRejected", ReasonCode.SCHEMA_INVALID, now, state,
                        report, status="FAIL",
                    )  # fmt: skip
                    continue
                if manifest.kind not in supported or manifest.kind != row.kind:
                    self._decide(
                        conn, row, "IntakeRejected", ReasonCode.KIND_UNSUPPORTED, now, state,
                        report, status="FAIL",
                    )  # fmt: skip
                    continue
                original = conn.execute(
                    text(
                        "SELECT version_id FROM eval.intake WHERE canonical_hash = :c "
                        "AND published_seq < :seq AND state NOT IN ('IntakeRejected', "
                        "'Duplicate', 'Discovered') ORDER BY published_seq LIMIT 1"
                    ),
                    {"c": row.canonical_hash, "seq": row.published_seq},
                ).scalar()
                if original is not None:
                    self._decide(
                        conn, row, "Duplicate", ReasonCode.DUPLICATE_OF, now, state, report,
                        status="DUPLICATE", duplicate_of=original,
                    )  # fmt: skip
                    continue
                if manifest.kind == "strategy":
                    conn.execute(
                        text(
                            "UPDATE eval.intake SET state = 'Held', hold_reason = :h, "
                            "updated_at = :at WHERE version_id = :v"
                        ),
                        {
                            "h": "the strategy plugin arrives in Phase 6",
                            "at": now,
                            "v": row.version_id,
                        },
                    )
                    report.count("Held")
                    continue
                queue.enqueue(
                    conn,
                    "fingerprint",
                    row.version_id,
                    row.family_id,
                    {
                        "version_id": str(row.version_id),
                        "epoch_id": state.epoch.epoch_id,
                        "snapshot_id": state.epoch.snapshot_id,
                        "correlation": current(),
                    },
                    now,
                )
                conn.execute(
                    text(
                        "UPDATE eval.intake SET state = 'Fingerprinting', updated_at = :at "
                        "WHERE version_id = :v"
                    ),
                    {"at": now, "v": row.version_id},
                )
                report.count("Fingerprinting")

    def _fingerprint(self, conn: Connection, version_id: UUID, epoch_id: str) -> Fingerprint | None:
        if version_id in self._fingerprints:
            return self._fingerprints[version_id]
        row = conn.execute(
            text(
                "SELECT uri, sha256 FROM eval.fingerprints WHERE version_id = :v AND epoch_id = :e"
            ),
            {"v": version_id, "e": epoch_id},
        ).first()
        if row is None:
            return None
        value = self.store.read_fingerprint(row.uri, row.sha256)
        self._fingerprints[version_id] = value
        return value

    def process_fingerprinted(self, report: TickReport, state: ActiveState) -> None:
        """Behavioral dedup, strictly in published order (serialized by the lock)."""
        now = self.clock.now()
        threshold = float(state.protocol.config["dedup"]["behavioral_similarity_min"])
        epoch_id = state.epoch.epoch_id
        with self.db.transaction() as conn:
            rows = conn.execute(
                text(
                    "SELECT i.version_id, i.published_seq, i.family_id, i.program_id, "
                    "q.state AS job_state FROM eval.intake i LEFT JOIN eval.queue_jobs q "
                    "ON q.version_id = i.version_id AND q.kind = 'fingerprint' "
                    "WHERE i.state = 'Fingerprinting' ORDER BY i.published_seq"
                )
            ).all()
            admitted = [
                r.version_id
                for r in conn.execute(
                    text(
                        "SELECT version_id FROM eval.intake WHERE state IN :states "
                        "ORDER BY published_seq"
                    ).bindparams(_states()),
                    {"states": ADMITTED},
                ).all()
            ]
            for row in rows:
                if row.job_state not in ("done", "failed"):
                    break  # Later versions wait so they are compared with this one.
                mine = self._fingerprint(conn, row.version_id, epoch_id)
                best: tuple[float, UUID] | None = None
                if mine is not None:
                    for other_id in admitted:
                        other = self._fingerprint(conn, other_id, epoch_id)
                        if other is None:
                            continue
                        value = behavioral_similarity(mine, other)
                        if value is not None and (best is None or value > best[0]):
                            best = (value, other_id)
                if best is not None and best[0] >= threshold:
                    self._decide(
                        conn, row, "Duplicate", ReasonCode.NEAR_DUPLICATE_OF, now, state,
                        report, status="DUPLICATE", duplicate_of=best[1], similarity=best[0],
                    )  # fmt: skip
                    continue
                if mine is None:
                    conn.execute(
                        text(
                            "UPDATE eval.intake SET fingerprint_error = 'no fingerprint' "
                            "WHERE version_id = :v"
                        ),
                        {"v": row.version_id},
                    )
                self._admit(conn, row, state, now, report, first=True)
                admitted.append(row.version_id)

    def process_deferred(self, report: TickReport, state: ActiveState) -> None:
        now = self.clock.now()
        quotas = QuotaConfig.model_validate(state.quotas.config)
        expiry = timedelta(days=quotas.deferral_expiry_days)
        with self.db.transaction() as conn:
            rows = conn.execute(
                text(
                    "SELECT version_id, published_seq, family_id, program_id, deferred_at "
                    "FROM eval.intake WHERE state = 'Deferred' ORDER BY published_seq"
                )
            ).all()
            for row in rows:
                if now - row.deferred_at >= expiry:
                    self._decide(
                        conn, row, "IntakeRejected", ReasonCode.QUOTA_EXPIRED, now, state,
                        report, status="FAIL",
                    )  # fmt: skip
                    continue
                self._admit(conn, row, state, now, report, first=False)

    def _quota_room(
        self, conn: Connection, row: Any, quotas: QuotaConfig, now: datetime
    ) -> list[tuple[str, str]] | None:
        """The usage rows to write when there is room in every scope, else None."""
        scopes = [
            ("family", str(row.family_id), quotas.family["w1_count"], quotas.family["w1_hours"]),
            ("global", "all", quotas.global_limits["w1_daily"], 24),
        ]
        if row.program_id is not None:
            scopes.append(("program", str(row.program_id), quotas.program["w1_daily"], 24))
        for scope, key, limit, hours in scopes:
            used: int = conn.execute(
                text(
                    "SELECT count(*) FROM eval.quota_usage WHERE scope = :s AND key = :k "
                    "AND window_name = 'W1' AND used_at > :since"
                ),
                {"s": scope, "k": key, "since": now - timedelta(hours=hours)},
            ).scalar_one()
            if int(used) >= int(limit):
                return None
        return [(scope, key) for scope, key, _, _ in scopes]

    def _admit(
        self,
        conn: Connection,
        row: Any,
        state: ActiveState,
        now: datetime,
        report: TickReport,
        *,
        first: bool,
    ) -> None:
        quotas = QuotaConfig.model_validate(state.quotas.config)
        room = self._quota_room(conn, row, quotas, now)
        if room is None:
            if first:
                self._decide(
                    conn, row, "Deferred", ReasonCode.QUOTA_DEFERRED, now, state, report,
                    status="DEFERRED", extra=", deferred_at = :at",
                )  # fmt: skip
            return
        for scope, key in room:
            conn.execute(
                text(
                    "INSERT INTO eval.quota_usage (usage_id, scope, key, window_name, "
                    "version_id, used_at, quota_ref) VALUES (:id, :s, :k, 'W1', :v, :at, :q)"
                ),
                {
                    "id": uuid7(),
                    "s": scope,
                    "k": key,
                    "v": row.version_id,
                    "at": now,
                    "q": state.quotas.ref,
                },
            )
        queue.enqueue(
            conn,
            "evaluate",
            row.version_id,
            row.family_id,
            {
                "version_id": str(row.version_id),
                "epoch_id": state.epoch.epoch_id,
                "snapshot_id": state.epoch.snapshot_id,
                "correlation": current(),
            },
            now,
        )
        self._decide(
            conn, row, "Screening", None, now, state, report, status="PASS",
            extra=", enqueued_at = :at",
        )  # fmt: skip

    # The loop ------------------------------------------------------------------------

    def tick(self) -> TickReport:
        report = TickReport()
        with bind():
            try:
                state = self.ensure_ready(report)
                if state is None:
                    self.log.info("scheduler_waiting", payload={"note": report.note})
                    return report
                report.ready = True
                with self.db.transaction() as conn:
                    queue.requeue_stale(conn, self.clock.now(), self.config.worker.lease_seconds)
                self.pull_versions(report)
                self.sync_library(report, state)
                self.process_discovered(report, state)
                self.process_fingerprinted(report, state)
                self.process_deferred(report, state)
            except RegistryUnavailable:
                report.note = "registry unavailable; retrying next tick"
            self.log.info(
                "scheduler_tick",
                outcome="ok",
                payload={
                    "ready": report.ready,
                    "pulled": report.pulled,
                    "pool_events": report.pool_events,
                    "decisions": report.decisions,
                    "note": report.note,
                },
            )
        return report


def _states() -> Any:
    return bindparam("states", expanding=True)


def main() -> None:
    settings = RuntimeSettings(service=SERVICE, zone="eval")
    environ = os.environ
    env = EvalEnvironment.from_env(environ, settings)
    config = eval_config(settings.config_dir)
    url = environ.get("EVAL_DB_URL", "")
    logger = service_logger(SERVICE, settings, [url, environ.get("REGISTRY_EVALUATOR_TOKEN", "")])
    registry = RegistryReader(
        environ.get("REGISTRY_API_URL", ""),
        environ.get("REGISTRY_EVALUATOR_TOKEN", ""),
        logger,
        httpx.Client(timeout=10.0, trust_env=False),
    )
    scheduler = Scheduler(Database(url), registry, env, config, logger)
    beat = Path(environ.get("QFR_HEARTBEAT_FILE") or "/tmp/heartbeat")
    logger.logger.info("service_started", payload={"phase": 3, "code_version": env.code_version})
    while True:
        try:
            scheduler.tick()
        except Exception:
            logger.logger.exception("scheduler_tick_failed", outcome="failed")
        heartbeat(beat, scheduler.clock.now())
        time.sleep(config.scheduler.interval_seconds)


if __name__ == "__main__":
    main()
