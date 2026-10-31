"""release-worker: the release engine (PLAN Sections 9.1 to 9.4, INV-12).

Every queued decision becomes a released report on the engine's next tick (every second
by default): research gets intake, screening, W1 and library reports as soon as the
evaluator records them, and nothing is held back for a batch time. Each report is built
only from whitelisted fields (the public ReleasedReport contract, extra fields forbidden),
W1 values are rounded to the policy granularity, diagnostics are enum codes, and every
report is validated against the public schema before it is written. Nothing else in the
evaluation zone writes released_reports.
"""

import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from pydantic import JsonValue
from qfr_core.config import RuntimeSettings
from qfr_core.contracts import IntakeContent, LibraryContent, ReleasedReport, W1Content
from qfr_core.correlation import bind, current
from qfr_core.ids import uuid7
from qfr_core.logging import JsonLogger
from sqlalchemy import text
from sqlalchemy.engine import Connection

from qfr_eval.configs import ActiveState, active_state, record_event
from qfr_eval.plugins import FactorPlugin, released_value_count
from qfr_eval.runtime import (
    Clock,
    Database,
    EvalConfig,
    SystemClock,
    eval_config,
    heartbeat,
    service_logger,
)

SERVICE = "release-worker"


@dataclass
class ReleaseReport:
    released: int = 0
    waiting: int = 0
    by_type: dict[str, int] = field(default_factory=dict)


class ReleaseEngine:
    def __init__(
        self, db: Database, config: EvalConfig, logger: JsonLogger, clock: Clock | None = None
    ) -> None:
        self.db, self.config, self.log = db, config, logger.logger
        self.clock = clock or SystemClock()

    def _build(
        self, conn: Connection, item: Any, state: ActiveState, at: datetime
    ) -> ReleasedReport | None:
        intake = conn.execute(
            text(
                "SELECT content_hash, family_id, program_id FROM eval.intake WHERE version_id = :v"
            ),
            {"v": item.version_id},
        ).first()
        if intake is None:
            return None  # A library change for a version not pulled yet waits.
        payload = dict(item.payload)
        refs = payload["refs"]  # pinned by the deciding service when it queued the report
        if item.report_type in ("intake", "screening"):
            content: Any = IntakeContent.model_validate(payload["content"])
        elif item.report_type == "library":
            content = LibraryContent.model_validate(payload["content"])
        else:
            content = FactorPlugin(state.protocol.config).release_w1(
                payload["raw"], state.policy.config
            )
        return ReleasedReport.model_validate(
            {
                "schema_version": "1",
                "report_id": uuid7(),
                "version_id": item.version_id,
                "content_hash": intake.content_hash,
                "family_id": intake.family_id,
                "program_id": intake.program_id,
                "policy_ref": state.policy_ref,
                "protocol_card_ref": state.protocol_card_ref,
                "released_at": at,
                "content": content,
            }
            | refs
        )

    def tick(self) -> ReleaseReport:
        report = ReleaseReport()
        with bind():
            now = self.clock.now()
            with self.db.transaction(lock=False) as conn:
                state = active_state(conn)
                if state is None:
                    return report
                due = conn.execute(
                    text(
                        "SELECT queue_id, report_type, version_id, record_id, payload "
                        "FROM eval.release_queue WHERE state = 'queued' AND due_at <= :now "
                        # queue_id (UUIDv7) breaks ties, so reports due together are
                        # released in the order they were queued: a version's intake
                        # before its screening before its W1.
                        "ORDER BY due_at, created_at, queue_id LIMIT :n FOR UPDATE SKIP LOCKED"
                    ),
                    {"now": now, "n": self.config.release.batch_limit},
                ).all()
                for item in due:
                    released = self._build(conn, item, state, now)
                    if released is None:
                        report.waiting += 1
                        continue
                    self._insert(conn, item, released, state, now)
                    report.released += 1
                    report.by_type[item.report_type] = report.by_type.get(item.report_type, 0) + 1
            if report.released or report.waiting:
                self.log.info(
                    "reports_released",
                    outcome="ok",
                    payload={
                        "released": report.released,
                        "waiting": report.waiting,
                        "by_type": report.by_type,
                    },
                )
        return report

    def _insert(
        self,
        conn: Connection,
        item: Any,
        released: ReleasedReport,
        state: ActiveState,
        at: datetime,
    ) -> None:
        document = released.model_dump(mode="json")
        conn.execute(
            text(
                "INSERT INTO eval.released_reports (report_id, queue_id, version_id, "
                "content_hash, family_id, program_id, report_type, policy_ref, "
                "protocol_card_ref, protocol_id, protocol_version, snapshot_id, code_version, "
                "content, report, released_at) VALUES (:id, :q, :v, :ch, :f, :p, :t, :pol, "
                ":card, :pid, :pv, :s, :code, CAST(:content AS jsonb), CAST(:report AS jsonb), :at)"
            ),
            {
                "id": released.report_id,
                "q": item.queue_id,
                "v": released.version_id,
                "ch": released.content_hash,
                "f": released.family_id,
                "p": released.program_id,
                "t": item.report_type,
                "pol": released.policy_ref,
                "card": released.protocol_card_ref,
                "pid": released.protocol_id,
                "pv": released.protocol_version,
                "s": released.data_snapshot_id,
                "code": released.evaluator_code_version,
                "content": released.content.model_dump_json(),
                "report": released.model_dump_json(),
                "at": at,
            },
        )
        conn.execute(
            text(
                "UPDATE eval.release_queue SET state = 'released', released_report_id = :r "
                "WHERE queue_id = :q"
            ),
            {"r": released.report_id, "q": item.queue_id},
        )
        if item.report_type == "w1":
            assert isinstance(released.content, W1Content)
            conn.execute(
                text(
                    "UPDATE eval.burn_meters SET released_values = released_values + :n, "
                    "updated_at = :at WHERE epoch_id = :e AND window_name = 'W1'"
                ),
                {"n": released_value_count(released.content), "at": at, "e": state.epoch.epoch_id},
            )
        record_event(
            conn, at, SERVICE, "report_released", "released_report", str(released.report_id),
            current()["request_id"],
            {"version_id": str(released.version_id), "report_type": item.report_type,
             "queue_id": str(item.queue_id), "document_keys": cast(JsonValue, sorted(document))},
        )  # fmt: skip


def main() -> None:
    settings = RuntimeSettings(service=SERVICE, zone="eval")
    config = eval_config(settings.config_dir)
    url = os.environ.get("EVAL_DB_URL", "")
    logger = service_logger(SERVICE, settings, [url])
    engine = ReleaseEngine(Database(url), config, logger)
    beat = Path(os.environ.get("QFR_HEARTBEAT_FILE") or "/tmp/heartbeat")
    logger.logger.info("service_started", payload={"phase": 3})
    while True:
        try:
            engine.tick()
        except Exception:
            logger.logger.exception("release_tick_failed", outcome="failed")
        heartbeat(beat, engine.clock.now())
        time.sleep(config.release.interval_seconds)


if __name__ == "__main__":
    main()
