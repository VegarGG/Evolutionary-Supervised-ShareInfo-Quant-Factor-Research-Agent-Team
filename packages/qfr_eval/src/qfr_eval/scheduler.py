"""eval-scheduler (PLAN Sections 8.3, 8.8, 9.3, 10.1 and 10.4): pull, check, dedup,
apply quotas, enqueue, and move versions through the lifecycle after W1.

Every 60 seconds the scheduler
  1. activates the shipped configuration on first start, registers the current full
     snapshot and pins the epoch;
  2. pulls up to 100 versions after the intake cursor and writes an intake row for each;
  3. pulls pool events after the pool cursors and updates the library (Section 10.4);
  4. moves intake rows through schema and kind checks, a strategy's component checks,
     exact dedup, fingerprinting, behavioral dedup, quotas (with deferral and expiry)
     and fair enqueueing;
  5. queues W1 passes for W2 and admits, per family and W2 quota period, the version
     with the best W1 RankIC_IR (the others wait and expire after 4 weeks);
  6. admits W2 passes to the holdout once per version within the W3 budget;
  7. grants simulation slots for incubation, and keeps monitoring simulations running
     for library entries and accepted versions;
  8. keeps the W2 and W3 budgets on the burn meters and raises an alert when one is red;
  9. after the nightly time, clusters the W1 trial ledger for N_eff (Section 8.7).
Every decision's report is queued in the deciding transaction and released at once.
Pool changes never trigger an evaluation; a seed version is evaluated because it is a
published version. The scheduler decides alone what to pull and when: nothing outside
the evaluation zone can call it.
"""

import math
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import httpx
from pydantic import ValidationError
from qfr_core.config import QuotaConfig, RuntimeSettings, canonical_json
from qfr_core.contracts import ReasonCode
from qfr_core.correlation import bind, current
from qfr_core.ids import uuid7
from qfr_core.logging import JsonLogger
from qfr_core.metrics.fingerprint import Fingerprint, behavioral_similarity
from sqlalchemy import bindparam, text
from sqlalchemy.engine import Connection

from qfr_eval import queue
from qfr_eval.alerts import raise_alert
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
from qfr_eval.ingest.config import load_yaml
from qfr_eval.plugins import IN_FLIGHT_STATES, StrategyPlugin
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
from qfr_eval.sim import sim_settings
from qfr_eval.store import ArtifactStore
from qfr_eval.trials import cluster_trials
from qfr_eval.worker import MANIFEST, read_components

SERVICE = "eval-scheduler"
PRINCIPAL = "eval-scheduler"
POOL_STATUS = {"seed": "seed", "approved": "active", "retired": "retired"}
# Versions that passed dedup and still count for behavioral comparisons.
ADMITTED = (
    "Deferred", "Screening", "ScreenFailed", "W1Evaluated", "W1GateFailed", "W2Queued",
    "W2Failed", "W2Expired", "HoldoutCheck", "NotAdvanced", "AwaitingSlot", "Incubating",
    "AcceptanceReview", "Accepted", "Rejected", "Monitoring", "Retired",
)  # fmt: skip
# A family's W2 pick waits while one of its versions is on its way to a W1 result.
W1_PENDING = ("Discovered", "Held", "Fingerprinting", "Screening")
LIVE_SIMS = ("waiting", "running", "paused")


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
        deployment = load_yaml(env.config_dir / "deployment.yaml")
        self.tz = ZoneInfo(str(deployment["timezone"]))
        schedule = deployment["schedule"]
        assert isinstance(schedule, dict)
        hour, minute = (int(x) for x in str(schedule["nightly_local"]).split(":"))
        self.nightly_at = (hour, minute)

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
        job_id = conn.execute(
            text(
                "UPDATE eval.intake SET state = :s, reason_code = :rc, duplicate_of = :dup, "
                "similarity = :sim, decided_at = CASE WHEN :final THEN :at ELSE decided_at END, "
                f"updated_at = :at {extra} WHERE version_id = :v RETURNING job_id"
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
        ).scalar()
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
        # The line carries the version and, for research's versions, the job (LOG-03).
        with bind(version_id=str(row.version_id), job_id=str(job_id) if job_id else None):
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
                    "kind, manifest, state FROM eval.intake WHERE state = 'Discovered' "
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
                if manifest.kind == "strategy" and not self._components_ready(
                    conn, row, manifest, now, state, report
                ):
                    continue
                self._fingerprint_job(conn, row, state, now, report)

    def _components_ready(
        self,
        conn: Connection,
        row: Any,
        manifest: Any,
        now: datetime,
        state: ActiveState,
        report: TickReport,
    ) -> bool:
        """A strategy goes on only when every component is a published factor that passed
        screening (Section 7.8). While a component is still on its way through intake or
        screening the strategy is held; otherwise it is rejected with COMPONENT_INVALID."""
        components = read_components(conn, manifest)
        waiting = [
            v for v, c in components.items() if c.kind == "factor" and c.state in IN_FLIGHT_STATES
        ]
        if waiting and len(components) == len(manifest.implementation.components):
            if row.state != "Held":
                conn.execute(
                    text(
                        "UPDATE eval.intake SET state = 'Held', hold_reason = :h, "
                        "updated_at = :at WHERE version_id = :v"
                    ),
                    {
                        "h": "waiting for components to finish screening",
                        "at": now,
                        "v": row.version_id,
                    },
                )
                report.count("Held")
            return False
        plugin = StrategyPlugin(state.protocol.config, manifest)
        if plugin.component_checks({k: (c.kind, c.state) for k, c in components.items()}):
            self._decide(
                conn, row, "IntakeRejected", ReasonCode.COMPONENT_INVALID, now, state, report,
                status="FAIL", extra=", hold_reason = NULL",
            )  # fmt: skip
            return False
        return True

    def process_held(self, report: TickReport, state: ActiveState) -> None:
        """Strategies held for their components are checked again every tick."""
        now = self.clock.now()
        with self.db.transaction() as conn:
            rows = conn.execute(
                text(
                    "SELECT version_id, published_seq, family_id, program_id, manifest, state "
                    "FROM eval.intake WHERE state = 'Held' ORDER BY published_seq"
                )
            ).all()
            for row in rows:
                manifest = MANIFEST.validate_python(row.manifest.get("manifest"))
                if self._components_ready(conn, row, manifest, now, state, report):
                    conn.execute(
                        text("UPDATE eval.intake SET hold_reason = NULL WHERE version_id = :v"),
                        {"v": row.version_id},
                    )
                    self._fingerprint_job(conn, row, state, now, report)

    def _fingerprint_job(
        self, conn: Connection, row: Any, state: ActiveState, now: datetime, report: TickReport
    ) -> None:
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
        """Behavioral dedup, strictly in published order (serialized by the lock). A
        version is compared with admitted versions of its own kind: a strategy is a
        portfolio, so its composite is not a duplicate of the factor it is built on."""
        now = self.clock.now()
        threshold = float(state.protocol.config["dedup"]["behavioral_similarity_min"])
        epoch_id = state.epoch.epoch_id
        with self.db.transaction() as conn:
            rows = conn.execute(
                text(
                    "SELECT i.version_id, i.published_seq, i.family_id, i.program_id, i.kind, "
                    "q.state AS job_state FROM eval.intake i LEFT JOIN eval.queue_jobs q "
                    "ON q.version_id = i.version_id AND q.kind = 'fingerprint' "
                    "WHERE i.state = 'Fingerprinting' ORDER BY i.published_seq"
                )
            ).all()
            admitted = [
                (r.version_id, r.kind)
                for r in conn.execute(
                    text(
                        "SELECT version_id, kind FROM eval.intake WHERE state IN :states "
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
                    for other_id, other_kind in admitted:
                        if other_kind != row.kind:
                            continue
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
                admitted.append((row.version_id, row.kind))

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

    # After W1: the W2 queue, the holdout, slots and monitoring (Sections 8.8, 10.1) ----

    def _usage(
        self, conn: Connection, scope: str, key: str, window: str, since: datetime | None
    ) -> int:
        used: int = conn.execute(
            text(
                "SELECT count(*) FROM eval.quota_usage WHERE scope = :s AND key = :k "
                "AND window_name = :w AND (CAST(:since AS timestamptz) IS NULL "
                "OR used_at > :since)"
            ),
            {"s": scope, "k": key, "w": window, "since": since},
        ).scalar_one()
        return int(used)

    def _use(
        self,
        conn: Connection,
        scopes: list[tuple[str, str]],
        window: str,
        version_id: UUID,
        state: ActiveState,
        now: datetime,
    ) -> None:
        for scope, key in scopes:
            conn.execute(
                text(
                    "INSERT INTO eval.quota_usage (usage_id, scope, key, window_name, "
                    "version_id, used_at, quota_ref) VALUES (:id, :s, :k, :w, :v, :at, :q)"
                ),
                {
                    "id": uuid7(),
                    "s": scope,
                    "k": key,
                    "w": window,
                    "v": version_id,
                    "at": now,
                    "q": state.quotas.ref,
                },
            )

    def _job_payload(self, row: Any, state: ActiveState) -> dict[str, Any]:
        return {
            "version_id": str(row.version_id),
            "epoch_id": state.epoch.epoch_id,
            "snapshot_id": state.epoch.snapshot_id,
            "correlation": current(),
        }

    def process_w2(self, report: TickReport, state: ActiveState) -> None:
        """W1 passes join the W2 queue. Per family and W2 quota period the evaluator picks
        the waiting version with the best W1 RankIC_IR (sign-adjusted); the others wait
        and expire after the configured weeks (Section 8.8). W2 runs are rationed by the
        family, program and epoch quotas (Section 9.3)."""
        now = self.clock.now()
        quotas = QuotaConfig.model_validate(state.quotas.config)
        family_days = timedelta(days=int(quotas.family["w2_days"]))
        wait = timedelta(days=int(quotas.family["w2_wait_days"]))
        epoch_id = state.epoch.epoch_id
        request_id = current()["request_id"]
        with self.db.transaction() as conn:
            queued = conn.execute(
                text(
                    "UPDATE eval.intake SET state = 'W2Queued', w2_queued_at = :at, "
                    "updated_at = :at WHERE state = 'W1Evaluated' RETURNING version_id"
                ),
                {"at": now},
            ).all()
            for row in queued:
                report.count("W2Queued")
                record_event(
                    conn, now, PRINCIPAL, "w2_queued", "intake", str(row.version_id),
                    request_id, {},
                )  # fmt: skip
            expired = conn.execute(
                text(
                    "UPDATE eval.intake SET state = 'W2Expired', updated_at = :at "
                    "WHERE state = 'W2Queued' AND w2_admitted_at IS NULL "
                    "AND w2_queued_at <= :cutoff RETURNING version_id"
                ),
                {"at": now, "cutoff": now - wait},
            ).all()
            for row in expired:
                report.count("W2Expired")
                record_event(
                    conn, now, PRINCIPAL, "w2_expired", "intake", str(row.version_id),
                    request_id, {"wait_days": int(quotas.family["w2_wait_days"])},
                )  # fmt: skip
            pending = {
                r.family_id
                for r in conn.execute(
                    text(
                        "SELECT DISTINCT family_id FROM eval.intake WHERE state IN :states"
                    ).bindparams(_states()),
                    {"states": W1_PENDING},
                ).all()
            }
            candidates = conn.execute(
                text(
                    "SELECT i.version_id, i.family_id, i.program_id, i.published_seq, "
                    "(r.metrics ->> 'rankic_ir')::double precision AS ir, "
                    "(r.summary ->> 'sign')::integer AS sign FROM eval.intake i "
                    "JOIN eval.official_records r ON r.version_id = i.version_id "
                    "AND r.stage = 'w1' AND r.epoch_id = :e WHERE i.state = 'W2Queued' "
                    "AND i.w2_admitted_at IS NULL ORDER BY i.published_seq"
                ),
                {"e": epoch_id},
            ).all()
            best: dict[Any, Any] = {}
            for row in candidates:
                if row.family_id in pending:
                    continue
                score = -math.inf if row.ir is None else (row.sign or 1) * row.ir
                current_best = best.get(row.family_id)
                if current_best is None or score > current_best[0]:
                    best[row.family_id] = (score, row)
            for _, row in sorted(best.values(), key=lambda item: item[1].published_seq):
                scopes = [("family", str(row.family_id)), ("global", epoch_id)]
                if self._usage(conn, "family", str(row.family_id), "W2", now - family_days) >= int(
                    quotas.family["w2_count"]
                ):
                    continue
                if row.program_id is not None:
                    if self._usage(
                        conn, "program", str(row.program_id), "W2", now - timedelta(days=7)
                    ) >= int(quotas.program["w2_weekly"]):
                        continue
                    scopes.append(("program", str(row.program_id)))
                if self._usage(conn, "global", epoch_id, "W2", None) >= int(
                    quotas.global_limits["w2_per_epoch"]
                ):
                    report.note = "the epoch's W2 budget is used up"
                    break
                self._use(conn, scopes, "W2", row.version_id, state, now)
                queue.enqueue(
                    conn, "w2", row.version_id, row.family_id, self._job_payload(row, state), now
                )
                conn.execute(
                    text(
                        "UPDATE eval.intake SET w2_admitted_at = :at, updated_at = :at "
                        "WHERE version_id = :v"
                    ),
                    {"at": now, "v": row.version_id},
                )
                report.count("W2Admitted")
                record_event(
                    conn, now, PRINCIPAL, "w2_admitted", "intake", str(row.version_id),
                    request_id, {"w1_rankic_ir": row.ir},
                )  # fmt: skip

    def process_holdout(self, report: TickReport, state: ActiveState) -> None:
        """W2 passes go to the private W3 holdout once per version, within the epoch's W3
        budget (Sections 9.3 and 10.1)."""
        now = self.clock.now()
        quotas = QuotaConfig.model_validate(state.quotas.config)
        epoch_id = state.epoch.epoch_id
        with self.db.transaction() as conn:
            rows = conn.execute(
                text(
                    "SELECT version_id, family_id FROM eval.intake WHERE state = 'HoldoutCheck' "
                    "AND holdout_admitted_at IS NULL ORDER BY updated_at, published_seq"
                )
            ).all()
            for row in rows:
                if self._usage(conn, "global", epoch_id, "W3", None) >= int(
                    quotas.global_limits["w3_per_epoch"]
                ):
                    report.note = "the epoch's W3 budget is used up"
                    break
                self._use(conn, [("global", epoch_id)], "W3", row.version_id, state, now)
                queue.enqueue(
                    conn, "holdout", row.version_id, row.family_id,
                    self._job_payload(row, state), now,
                )  # fmt: skip
                conn.execute(
                    text(
                        "UPDATE eval.intake SET holdout_admitted_at = :at, updated_at = :at "
                        "WHERE version_id = :v"
                    ),
                    {"at": now, "v": row.version_id},
                )
                report.count("HoldoutAdmitted")
                record_event(
                    conn, now, PRINCIPAL, "holdout_admitted", "intake", str(row.version_id),
                    current()["request_id"], {},
                )  # fmt: skip

    def _replay_allowed(self, conn: Connection, state: ActiveState) -> bool:
        source = conn.execute(
            text("SELECT manifest ->> 'source' FROM eval.data_snapshots WHERE snapshot_id = :s"),
            {"s": state.epoch.snapshot_id},
        ).scalar()
        return state.epoch.replay_start is not None and source == "synthetic"

    def _create_sim(
        self,
        conn: Connection,
        row: Any,
        state: ActiveState,
        purpose: str,
        now: datetime,
        entry_id: UUID | None = None,
    ) -> UUID:
        protocol = state.protocol.config
        manifest = MANIFEST.validate_python(row.manifest.get("manifest"))
        published = row.manifest.get("published_at")
        local_today = now.astimezone(self.tz).date()
        published_day = (
            datetime.fromisoformat(str(published)).astimezone(self.tz).date()
            if published
            else local_today
        )
        # No backfill: the first trading day after publication and admission (10.2).
        not_before = max(published_day, local_today) + timedelta(days=1)
        sim_id = uuid7()
        conn.execute(
            text(
                "INSERT INTO eval.sim_accounts (sim_id, version_id, kind, purpose, mode, "
                "epoch_id, protocol_ref, settings, capital, not_before, required_days, status, "
                "entry_id, created_at, updated_at, request_id) VALUES (:id, :v, :k, :p, :m, :e, "
                ":ref, CAST(:settings AS jsonb), :cap, :nb, :req, 'waiting', :entry, :at, :at, "
                ":r)"
            ),
            {
                "id": sim_id,
                "v": row.version_id,
                "k": manifest.kind,
                "p": purpose,
                "m": self.config.simulation.mode,
                "e": state.epoch.epoch_id,
                "ref": state.protocol.ref,
                "settings": canonical_json(sim_settings(protocol, manifest)),
                "cap": float(protocol["simulation"]["capital_cny"]),
                "nb": not_before,
                "req": int(protocol["simulation"]["trading_days"])
                if purpose == "incubation"
                else None,
                "entry": entry_id,
                "at": now,
                "r": current()["request_id"],
            },
        )
        record_event(
            conn, now, PRINCIPAL, "sim_created", "sim_account", str(sim_id),
            current()["request_id"],
            {"version_id": str(row.version_id), "purpose": purpose,
             "mode": self.config.simulation.mode, "not_before": not_before.isoformat()},
        )  # fmt: skip
        return sim_id

    def grant_slots(self, report: TickReport, state: ActiveState) -> None:
        """Holdout passes wait in AwaitingSlot until one of the concurrent incubation slots
        is free, then incubate (W4) in the configured mode (Section 10.1)."""
        now = self.clock.now()
        quotas = QuotaConfig.model_validate(state.quotas.config)
        slots = int(quotas.global_limits["simulation_slots"])
        with self.db.transaction() as conn:
            if self.config.simulation.mode == "replay" and not self._replay_allowed(conn, state):
                report.note = "replay mode needs a synthetic snapshot and an epoch replay tail"
                self.log.error("replay_refused", outcome="failed", payload={"note": report.note})
                return
            live: int = conn.execute(
                text(
                    "SELECT count(*) FROM eval.sim_accounts WHERE purpose = 'incubation' "
                    "AND status IN :states"
                ).bindparams(_states()),
                {"states": LIVE_SIMS},
            ).scalar_one()
            rows = conn.execute(
                text(
                    "SELECT version_id, manifest FROM eval.intake WHERE state = 'AwaitingSlot' "
                    "ORDER BY updated_at, published_seq"
                )
            ).all()
            for row in rows:
                if int(live) >= slots:
                    break
                self._create_sim(conn, row, state, "incubation", now)
                conn.execute(
                    text(
                        "UPDATE eval.intake SET state = 'Incubating', updated_at = :at "
                        "WHERE version_id = :v"
                    ),
                    {"at": now, "v": row.version_id},
                )
                live = int(live) + 1
                report.count("Incubating")

    def sync_monitoring(self, report: TickReport, state: ActiveState) -> None:
        """Forward simulation keeps running for approved library entries and accepted
        versions (Section 10.4); a retired entry's monitoring stops."""
        now = self.clock.now()
        with self.db.transaction() as conn:
            if self.config.simulation.mode == "replay" and not self._replay_allowed(conn, state):
                return
            targets = conn.execute(
                text(
                    "SELECT i.version_id, i.manifest, i.state, l.entry_id, l.status AS pool_status "
                    "FROM eval.intake i LEFT JOIN eval.library l ON l.version_id = i.version_id "
                    "WHERE (l.status = 'active' OR i.state IN ('Accepted', 'Monitoring')) "
                    "AND NOT EXISTS (SELECT 1 FROM eval.sim_accounts s WHERE s.version_id = "
                    "i.version_id AND s.purpose = 'monitoring' AND s.status IN "
                    "('waiting', 'running', 'paused', 'failed')) ORDER BY i.published_seq"
                )
            ).all()
            for row in targets:
                if row.pool_status == "retired":
                    continue
                self._create_sim(conn, row, state, "monitoring", now, row.entry_id)
                report.count("MonitoringStarted")
            conn.execute(
                text(
                    "UPDATE eval.intake SET state = 'Monitoring', updated_at = :at "
                    "WHERE state = 'Accepted' AND EXISTS (SELECT 1 FROM eval.sim_accounts s "
                    "WHERE s.version_id = eval.intake.version_id AND s.purpose = 'monitoring')"
                ),
                {"at": now},
            )
            retired = conn.execute(
                text(
                    "SELECT s.sim_id, s.version_id, s.last_day FROM eval.sim_accounts s "
                    "JOIN eval.library l ON l.version_id = s.version_id "
                    "WHERE s.purpose = 'monitoring' AND l.status = 'retired' "
                    "AND s.status IN :states"
                ).bindparams(_states()),
                {"states": LIVE_SIMS},
            ).all()
            for sim in retired:
                conn.execute(
                    text(
                        "UPDATE eval.sim_accounts SET status = 'stopped', updated_at = :at, "
                        "finished_at = :at WHERE sim_id = :s"
                    ),
                    {"at": now, "s": sim.sim_id},
                )
                conn.execute(
                    text(
                        "INSERT INTO eval.sim_events (event_id, sim_id, at, day, kind, payload, "
                        "request_id) VALUES (:id, :s, :at, :d, 'STOPPED', "
                        "CAST(:p AS jsonb), :r)"
                    ),
                    {
                        "id": uuid7(),
                        "s": sim.sim_id,
                        "at": now,
                        "d": sim.last_day,
                        "p": canonical_json({"reason": "library entry retired"}),
                        "r": current()["request_id"],
                    },
                )
                report.count("MonitoringStopped")
            conn.execute(
                text(
                    "UPDATE eval.intake SET state = 'Retired', updated_at = :at "
                    "WHERE state = 'Monitoring' AND version_id IN (SELECT version_id "
                    "FROM eval.library WHERE status = 'retired')"
                ),
                {"at": now},
            )

    def update_burn(self, report: TickReport, state: ActiveState) -> None:
        """W2 and W3 budgets on the burn meters; a red meter raises an alert (9.4)."""
        now = self.clock.now()
        quotas = QuotaConfig.model_validate(state.quotas.config)
        budgets = {
            "W2": int(quotas.global_limits["w2_per_epoch"]),
            "W3": int(quotas.global_limits["w3_per_epoch"]),
        }
        epoch_id = state.epoch.epoch_id
        with self.db.transaction() as conn:
            for window, budget in budgets.items():
                conn.execute(
                    text(
                        "UPDATE eval.burn_meters SET budget = :b, updated_at = :at, "
                        "status = CASE WHEN queries_used >= :b THEN 'red' ELSE 'green' END "
                        "WHERE epoch_id = :e AND window_name = :w AND (budget IS DISTINCT "
                        "FROM :b OR (queries_used >= :b AND status <> 'red'))"
                    ),
                    {"b": budget, "at": now, "e": epoch_id, "w": window},
                )
            red = conn.execute(
                text(
                    "SELECT window_name, trials, queries_used, budget FROM eval.burn_meters "
                    "WHERE epoch_id = :e AND status = 'red'"
                ),
                {"e": epoch_id},
            ).all()
            for meter in red:
                alert = raise_alert(
                    conn, "burn", f"burn:{epoch_id}:{meter.window_name}",
                    {"epoch_id": epoch_id, "window": meter.window_name, "trials": meter.trials,
                     "queries_used": meter.queries_used, "budget": meter.budget,
                     "note": "schedule an epoch rollover (Section 10.6)"},
                    now, PRINCIPAL, current()["request_id"], logger=self.logger,
                )  # fmt: skip
                if alert is not None:
                    report.count("BurnAlert")

    def nightly(self, report: TickReport, state: ActiveState) -> None:
        """After the nightly time, cluster the W1 trial ledger for N_eff (Section 8.7)."""
        now = self.clock.now()
        local = now.astimezone(self.tz)
        hour, minute = self.nightly_at
        due = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if local < due:
            due -= timedelta(days=1)
        g = state.protocol.config["gates"]["acceptance"]
        with self.db.transaction() as conn:
            last = conn.execute(
                text(
                    "SELECT max(computed_at) FROM eval.trial_cluster_runs WHERE epoch_id = :e "
                    "AND window_name = 'W1'"
                ),
                {"e": state.epoch.epoch_id},
            ).scalar()
            if last is not None and last >= due:
                return
            trials: int = conn.execute(
                text(
                    "SELECT count(*) FROM eval.trial_ledger WHERE epoch_id = :e "
                    "AND window_name = 'W1'"
                ),
                {"e": state.epoch.epoch_id},
            ).scalar_one()
            if not trials:
                return
            run = cluster_trials(
                conn, self.store, state.epoch.epoch_id, "W1", float(g["cluster_similarity"]),
                int(g["neff_family_fallback_trials"]), now, current()["request_id"],
            )  # fmt: skip
        report.count("ClusterRun")
        self.log.info(
            "trials_clustered",
            outcome="ok",
            payload={"method": run.method, "trials": run.trials, "n_eff": run.n_eff},
        )

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
                self.process_held(report, state)
                self.process_fingerprinted(report, state)
                self.process_deferred(report, state)
                self.process_w2(report, state)
                self.process_holdout(report, state)
                self.grant_slots(report, state)
                self.sync_monitoring(report, state)
                self.update_burn(report, state)
                self.nightly(report, state)
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
    logger.logger.info("service_started", payload={"phase": 6, "code_version": env.code_version})
    while True:
        try:
            scheduler.tick()
        except Exception:
            logger.logger.exception("scheduler_tick_failed", outcome="failed")
        heartbeat(beat, scheduler.clock.now())
        time.sleep(config.scheduler.interval_seconds)


if __name__ == "__main__":
    main()
