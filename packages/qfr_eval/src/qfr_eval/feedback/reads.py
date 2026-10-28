"""Only released views through feedback_ro; private tables are never queried."""

import hashlib
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any
from uuid import UUID

import psycopg
from psycopg import Connection
from psycopg.pq import TransactionStatus
from pydantic import ValidationError
from qfr_core.access import ServicePrincipal
from qfr_core.contracts.feedback import (
    ArtifactFeedback,
    FeedbackReadPolicy,
    PublicCards,
    ReportKind,
    ReportPage,
)
from qfr_core.contracts.reports import PublicProtocolCard, PublicReleasePolicyCard, ReleasedReport
from qfr_core.data_layer.snapshots import canonical_json
from qfr_core.signatures import EvidenceVerifier


class FeedbackUnavailable(Exception):
    pass


class FeedbackNotFound(Exception):
    pass


class InvalidFeedbackRead(Exception):
    pass


class FeedbackReader:
    def __init__(
        self,
        connect: Callable[[], Connection],
        policy: FeedbackReadPolicy,
        *,
        verifier: EvidenceVerifier,
    ):
        self.connect, self.policy = connect, policy
        self.verifier = verifier

    @contextmanager
    def scoped(self, principal: ServicePrincipal) -> Iterator[Connection]:
        if principal.audience != "feedback" or principal.roles != {"reader"}:
            raise PermissionError("feedback reader authority required")
        try:
            with self.connect() as conn:
                if conn.info.transaction_status != TransactionStatus.IDLE:
                    raise FeedbackUnavailable("feedback connection is not idle")
                with conn.transaction():
                    conn.execute("SET TRANSACTION READ ONLY")
                    if conn.execute("SELECT current_user,current_database()").fetchone() != (
                        "feedback_ro",
                        "eval_db",
                    ):
                        raise FeedbackUnavailable("feedback requires its read-only database role")
                    conn.execute(
                        "SELECT set_config('qfr.program_ids',%s,true)",
                        [",".join(sorted(principal.programs))],
                    )
                    conn.execute(
                        "SELECT set_config('statement_timeout',%s,true)",
                        [str(self.policy.statement_timeout_ms)],
                    )
                    yield conn
        except (psycopg.Error, ValidationError, ValueError, KeyError) as error:
            raise FeedbackUnavailable("released evidence is unavailable") from error

    def _row(self, row: tuple[Any, ...], principal: ServicePrincipal) -> ReleasedReport:
        if row[6] is None:
            raise FeedbackUnavailable("released evidence exceeds read bounds")
        report = self.verifier.report(ReleasedReport.model_validate(row[6]))
        identity = report.identity
        if (
            report.report_id,
            identity.artifact_version_id,
            identity.content_hash,
            identity.protocol_version,
            identity.dataset_version_id,
            identity.evaluator_version,
        ) != tuple(str(x) for x in row[:6]) or report.program_id not in principal.programs:
            raise FeedbackUnavailable("released evidence identity differs")
        return report

    def _select(self) -> str:
        # Bound deserialization of corrupt/oversized stored payloads as well as
        # the final HTTP response. No raw exception or private row is returned.
        return (
            "SELECT id,artifact_version_id,content_hash,protocol_version,"
            "dataset_version_id,evaluator_version,CASE WHEN "
            "octet_length(released_content::text)<=%s THEN released_content ELSE NULL END,"
            "release_seq FROM feedback.released_reports_v "
        )

    def _bounded(self, value: Any) -> None:
        if len(canonical_json(value.model_dump(mode="json"))) > self.policy.max_page_bytes:
            raise FeedbackUnavailable("released response exceeds read bounds")

    def get(self, principal: ServicePrincipal, identity: UUID) -> ReleasedReport:
        with self.scoped(principal) as conn:
            row = conn.execute(
                self._select() + "WHERE id=%s", [self.policy.max_page_bytes, identity]
            ).fetchone()
            if row is None:
                raise FeedbackNotFound("released report unavailable")
            result = self._row(row, principal)
            self._bounded(result)
            return result

    def _page(
        self,
        conn: Connection,
        principal: ServicePrincipal,
        *,
        after_id: UUID | None,
        since: datetime | None,
        version_id: UUID | None,
        family_id: UUID | None,
        kind: ReportKind | None,
        limit: int,
    ) -> ReportPage:
        if not 1 <= limit <= self.policy.max_page_size:
            raise InvalidFeedbackRead("invalid report page limit")
        predicates: list[str] = []
        parameters: list[object] = [self.policy.max_page_bytes]
        if after_id is not None:
            cursor = conn.execute(
                "SELECT release_seq FROM feedback.released_reports_v WHERE id=%s", [after_id]
            ).fetchone()
            if cursor is None:
                raise FeedbackNotFound("released cursor unavailable")
            predicates.append("release_seq>%s")
            parameters.append(cursor[0])
        if since is not None:
            if since.utcoffset() is None:
                raise InvalidFeedbackRead("aware report timestamp required")
            predicates.append("(released_content->>'released_at')::timestamptz>=%s")
            parameters.append(since)
        for clause, value in [
            ("artifact_version_id=%s", version_id),
            ("released_content->>'family_id'=%s", str(family_id) if family_id else None),
            ("released_content->'content'->>'type'=%s", kind),
        ]:
            if value is not None:
                predicates.append(clause)
                parameters.append(value)
        rows = conn.execute(
            self._select()
            + ("WHERE " + " AND ".join(predicates) if predicates else "")
            + " ORDER BY release_seq LIMIT %s",
            [*parameters, limit + 1],
        ).fetchall()
        items = [self._row(row, principal) for row in rows[:limit]]
        page = ReportPage(
            schema_version="1",
            items=items,
            next_after_id=UUID(items[-1].report_id) if items else after_id,
            has_more=len(rows) > limit,
        )
        self._bounded(page)
        return page

    def page(
        self,
        principal: ServicePrincipal,
        *,
        after_id: UUID | None = None,
        since: datetime | None = None,
        version_id: UUID | None = None,
        family_id: UUID | None = None,
        kind: ReportKind | None = None,
        limit: int,
    ) -> ReportPage:
        with self.scoped(principal) as conn:
            return self._page(
                conn,
                principal,
                after_id=after_id,
                since=since,
                version_id=version_id,
                family_id=family_id,
                kind=kind,
                limit=limit,
            )

    def status(
        self,
        principal: ServicePrincipal,
        version_id: UUID,
        *,
        after_id: UUID | None = None,
        limit: int,
    ) -> ArtifactFeedback:
        with self.scoped(principal) as conn:
            timeline = self._page(
                conn,
                principal,
                after_id=after_id,
                since=None,
                version_id=version_id,
                family_id=None,
                kind=None,
                limit=limit,
            )
            row = conn.execute(
                self._select() + "WHERE artifact_version_id=%s ORDER BY release_seq DESC LIMIT 1",
                [self.policy.max_page_bytes, version_id],
            ).fetchone()
            result = ArtifactFeedback(
                schema_version="1",
                artifact_version_id=version_id,
                latest_released=self._row(row, principal) if row else None,
                timeline=timeline,
            )
            self._bounded(result)
            return result

    def cards(
        self, principal: ServicePrincipal, *, kind: str, ref: str | None = None
    ) -> PublicCards:
        if kind not in ("policy", "protocol"):
            raise InvalidFeedbackRead("invalid card kind")
        model = PublicReleasePolicyCard if kind == "policy" else PublicProtocolCard
        with self.scoped(principal) as conn:
            # kind is a closed internal enum, never raw SQL from the request.
            rows = conn.execute(
                "SELECT card_ref,content_sha256,CASE WHEN octet_length(payload::text)<=%s "
                "THEN payload ELSE NULL END FROM feedback."
                + kind
                + "_card_v "
                + ("WHERE card_ref=%s " if ref else "")
                + "ORDER BY card_ref LIMIT %s",
                [
                    self.policy.max_page_bytes,
                    *([ref] if ref else []),
                    self.policy.max_page_size + 1,
                ],
            ).fetchall()
            if len(rows) > self.policy.max_page_size:
                raise InvalidFeedbackRead("select a specific public card reference")
            cards = []
            for card_ref, sha, body in rows:
                if body is None or hashlib.sha256(canonical_json(body)).hexdigest() != sha:
                    raise FeedbackUnavailable("public card hash differs")
                card = model.model_validate(body)
                if card_ref != (
                    card.policy_ref
                    if isinstance(card, PublicReleasePolicyCard)
                    else card.card_ref or card.protocol_version
                ):
                    raise FeedbackUnavailable("public card identity differs")
                cards.append(card)
            if ref and not cards:
                raise FeedbackNotFound("public card unavailable")
            result = PublicCards.model_validate(
                dict(
                    schema_version="1",
                    policies=cards if kind == "policy" else [],
                    protocols=cards if kind == "protocol" else [],
                )
            )
            self._bounded(result)
            return result
