"""Feedback sync (P4.4, PLAN Sections 11.6 and 16.2).

Pulls the reports released since the program's cursor from the GET-only Feedback API,
stores read-only copies in report_cache and links them to the program, the job, the
version and the candidate and hypothesis that produced it. Seed versions published by
setup carry no program id, so their reports are fetched by version id. Every new report
is a REPORT_RECEIVED trace step. The cursor moves forward only.
"""

import hashlib
from dataclasses import dataclass
from uuid import UUID

from qfr_core.config import canonical_json
from qfr_core.contracts import ReleasedReport
from qfr_core.ids import uuid7
from sqlalchemy import text
from sqlalchemy.engine import Connection

from qfr_research.db import dumps
from qfr_research.env import ResearchEnv
from qfr_research.store import Ctx


@dataclass(frozen=True)
class SyncResult:
    new_reports: list[ReleasedReport]
    cursor: UUID | None


class FeedbackSync:
    def __init__(self, env: ResearchEnv) -> None:
        self.env = env
        self.page_limit = env.config.service.feedback.page_limit

    def sync(self, ctx: Ctx) -> SyncResult:
        env = self.env
        if env.feedback is None:
            raise RuntimeError("FEEDBACK_UNCONFIGURED: FEEDBACK_API_URL is not set")
        with env.db.read() as conn:
            cursor_row = conn.execute(
                text("SELECT last_report_id FROM feedback_cursor WHERE program_id = :p"),
                {"p": ctx.program_id},
            ).first()
            seeds: list[str] | None = conn.execute(
                text("SELECT seed_version_ids FROM research_jobs WHERE job_id = :j"),
                {"j": ctx.job_id},
            ).scalar_one()
        cursor = cursor_row.last_report_id if cursor_row else None
        fetched: list[ReleasedReport] = []
        while True:
            page = env.feedback.reports(
                program_id=ctx.program_id, after_id=cursor, limit=self.page_limit
            )
            fetched += page.items
            if page.items:
                cursor = page.items[-1].report_id
            if page.next_after_id is None:
                break
        for version_id in seeds or []:
            fetched += env.feedback.reports(version_id=version_id, limit=self.page_limit).items
        new: list[ReleasedReport] = []
        with env.db.transaction() as conn:
            for report in fetched:
                if self._store(conn, ctx, report):
                    new.append(report)
            conn.execute(
                text(
                    "INSERT INTO feedback_cursor (program_id, last_released_at, last_report_id, "
                    "updated_at) VALUES (:p, :at, :r, :now) ON CONFLICT (program_id) DO UPDATE "
                    "SET last_released_at = coalesce(EXCLUDED.last_released_at, "
                    "feedback_cursor.last_released_at), last_report_id = "
                    "coalesce(EXCLUDED.last_report_id, feedback_cursor.last_report_id), "
                    "updated_at = EXCLUDED.updated_at"
                ),
                {
                    "p": ctx.program_id,
                    "at": max((r.released_at for r in fetched), default=None),
                    "r": cursor,
                    "now": env.clock.now(),
                },
            )
        env.logger.logger.info(
            "feedback_synced",
            outcome="ok",
            payload={"fetched": len(fetched), "new": len(new)},
            **ctx.log_ids(),
        )
        return SyncResult(new, cursor)

    def _store(self, conn: Connection, ctx: Ctx, report: ReleasedReport) -> bool:
        content = report.model_dump(mode="json")
        inserted = conn.execute(
            text(
                "INSERT INTO report_cache (report_id, program_id, version_id, report_type, "
                "released_at, content, content_hash, fetched_at) VALUES (:r, :p, :v, :t, :at, "
                "CAST(:c AS jsonb), :h, :now) ON CONFLICT (report_id) DO NOTHING RETURNING 1"
            ),
            {
                "r": report.report_id,
                "p": report.program_id,
                "v": report.version_id,
                "t": report.content.type,
                "at": report.released_at,
                "c": dumps(content),
                "h": hashlib.sha256(canonical_json(content).encode()).hexdigest(),
                "now": self.env.clock.now(),
            },
        ).first()
        if inserted is None:
            return False
        links: list[tuple[str, UUID | None]] = [
            ("version", report.version_id),
            ("program", ctx.program_id),
            ("job", ctx.job_id),
        ]
        origin = conn.execute(
            text(
                "SELECT c.candidate_id, c.hypothesis_id FROM candidate_versions v "
                "JOIN candidates c ON c.candidate_id = v.candidate_id WHERE v.version_id = :v"
            ),
            {"v": report.version_id},
        ).first()
        if origin is not None:
            links += [("candidate", origin.candidate_id), ("hypothesis", origin.hypothesis_id)]
        for entity_type, entity_id in links:
            if entity_id is None:
                continue
            conn.execute(
                text(
                    "INSERT INTO report_links (link_id, report_id, entity_type, entity_id, "
                    "created_at) VALUES (:l, :r, :t, :e, :now) ON CONFLICT DO NOTHING"
                ),
                {
                    "l": uuid7(),
                    "r": report.report_id,
                    "t": entity_type,
                    "e": entity_id,
                    "now": self.env.clock.now(),
                },
            )
        candidate = origin.candidate_id if origin is not None else None
        self.env.trace.step(
            conn,
            "REPORT_RECEIVED",
            ctx.with_(candidate_id=candidate, task_id=None),
            actor="feedback-sync",
            version_id=report.version_id,
            inputs={"report_id": str(report.report_id), "report_type": report.content.type},
            payload={"released_at": report.released_at.isoformat(), "content": content["content"]},
        )
        return True


def reports_for(conn: Connection, version_id: UUID) -> list[ReleasedReport]:
    rows = conn.execute(
        text(
            "SELECT content FROM report_cache WHERE version_id = :v ORDER BY released_at, report_id"
        ),
        {"v": version_id},
    ).all()
    return [ReleasedReport.model_validate(r.content) for r in rows]
