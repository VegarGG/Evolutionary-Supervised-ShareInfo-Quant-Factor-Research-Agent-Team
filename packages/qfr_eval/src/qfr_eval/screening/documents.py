"""Deterministic document checks against already released evidence only.

The caller supplies a verified released-only view. This module neither queries
private measurements nor signs, schedules or publishes any report. Numeric
claims use a typed JSON envelope; free prose is not treated as verified analysis.
"""

import io
import math
import re
from dataclasses import dataclass

import polars as pl
from psycopg import Connection
from qfr_core.contracts.artifacts import DocumentImplementation, ResearchNotePayload
from qfr_core.contracts.enums import ArtifactKind, ReasonCode
from qfr_core.contracts.execution import ResearchNoteDocument, RunnerInput, RunnerOutput
from qfr_core.contracts.publication import PublishedArtifact
from qfr_core.contracts.reports import ReleasedReport
from qfr_core.runner_tables import pack_table

from qfr_eval.scheduler.dedup import digest
from qfr_eval.screening.adapters import OutputAdapter
from qfr_eval.screening.models import ScreeningExecutionPolicy
from qfr_eval.screening.records import ScreeningOutcome


@dataclass(frozen=True)
class ReleasedEvidence:
    reports: dict[str, ReleasedReport]
    # Precision belongs to the report's frozen release policy, never the author.
    granularities: dict[tuple[str, tuple[str, ...]], float]
    citation_refs: frozenset[str]

    @classmethod
    def from_database(
        cls,
        conn: Connection,
        program: str,
        report_ids: list[str],
        *,
        granularities: dict[tuple[str, tuple[str, ...]], float],
        citation_refs: frozenset[str],
    ) -> "ReleasedEvidence":
        reports = {}
        for row in conn.execute(
            "SELECT payload,artifact_version_id,content_hash,protocol_version,dataset_version_id,"
            "evaluator_version FROM eval.released_reports WHERE payload->>'program_id'=%s "
            "AND payload->>'report_id'=ANY(%s)",
            [program, report_ids],
        ):
            report = ReleasedReport.model_validate(row[0])
            identity = report.identity
            if (
                identity.artifact_version_id,
                identity.content_hash,
                identity.protocol_version,
                identity.dataset_version_id,
                identity.evaluator_version,
            ) != (str(row[1]), *row[2:]):
                raise ValueError("released evidence identity differs from its immutable row")
            reports[report.report_id] = report
        return cls(reports, granularities, citation_refs)


def check_note(
    artifact: PublishedArtifact,
    data: bytes,
    policy: ScreeningExecutionPolicy,
    released: ReleasedEvidence,
) -> ScreeningOutcome:
    checks = {
        "schema": "fail",
        "citations": "not_applicable",
        "released_values": "not_applicable",
        "temporal": "not_applicable",
    }

    def result(passed: bool, code: ReasonCode = ReasonCode.SCHEMA_INVALID) -> ScreeningOutcome:
        return ScreeningOutcome.model_validate(
            dict(
                schema_version="1",
                kind="research_note",
                execution="document",
                status="passed" if passed else "failed",
                reason_codes=[] if passed else [code],
                coverage=None,
                causality=None,
                output_sha256=None,
                document_checks=checks,
            )
        )

    manifest = artifact.manifest
    payload, implementation = manifest.payload, manifest.implementation
    if (
        manifest.kind != ArtifactKind.RESEARCH_NOTE
        or not isinstance(payload, ResearchNotePayload)
        or not isinstance(implementation, DocumentImplementation)
        or payload.document_asset_id != implementation.asset_id
        or not data
        or len(data) > policy.note_bytes
    ):
        return result(False)
    try:
        if implementation.format == "json":
            note = ResearchNoteDocument.model_validate_json(data)
        elif implementation.format == "markdown":
            body = data.decode("utf-8")
            title = body.splitlines()[0].removeprefix("# ").strip()
            note = ResearchNoteDocument(
                schema_version="1",
                title=title,
                body=body,
                citation_refs=[],
                numeric_claims=[],
            )
        else:
            return result(False, ReasonCode.KIND_UNSUPPORTED)
        # No NLP-based claim extraction in official quality checks. Unsupported
        # numeric prose must be moved into the auditable structured claim array.
        if (
            not note.body.strip()
            or not note.title.strip()
            or re.search(r"\d", note.body + note.title)
        ):
            return result(False)
        if re.search(r"(?:eval_db|/eval/|/evidence/|\bW[023]\b)", note.body):
            return result(False, ReasonCode.FORBIDDEN_CONSTRUCT)
    except (ValueError, UnicodeError, IndexError):
        return result(False)
    checks["schema"] = "pass"
    checks["citations"] = "fail"
    if (
        len(payload.citation_refs) != len(set(payload.citation_refs))
        or len(payload.released_report_refs) != len(set(payload.released_report_refs))
        or set(note.citation_refs) != set(payload.citation_refs)
        or not set(payload.citation_refs) <= released.citation_refs | released.reports.keys()
        or not set(payload.released_report_refs) <= released.reports.keys()
    ):
        return result(False, ReasonCode.DECLARATION_MISMATCH)
    for report_id in set(payload.released_report_refs) | (
        set(payload.citation_refs) & released.reports.keys()
    ):
        report = released.reports[report_id]
        if report.report_id != report_id or report.program_id != manifest.provenance.program_id:
            return result(False, ReasonCode.DECLARATION_MISMATCH)
    checks["citations"] = "pass"
    checks["released_values"] = "fail"
    for claim in note.numeric_claims:
        if claim.report_id not in payload.released_report_refs:
            return result(False, ReasonCode.DECLARATION_MISMATCH)
        value: object = released.reports[claim.report_id].model_dump(mode="json")
        # Only content fields may be numeric claims, never audit times or ids.
        if not claim.field_path or claim.field_path[0] != "content":
            return result(False, ReasonCode.DECLARATION_MISMATCH)
        for part in claim.field_path:
            if not isinstance(value, dict) or part not in value:
                return result(False, ReasonCode.DECLARATION_MISMATCH)
            value = value[part]
        granularity = released.granularities.get((claim.report_id, tuple(claim.field_path)))
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or granularity is None
            or not math.isfinite(granularity)
            or granularity <= 0
            or abs(claim.value - value) > granularity / 2
        ):
            return result(False, ReasonCode.DECLARATION_MISMATCH)
    checks["released_values"] = "pass"
    return result(True)


def check_data_document(
    artifact: PublishedArtifact,
    data: bytes,
    request: RunnerInput,
    adapter: OutputAdapter,
    policy: ScreeningExecutionPolicy,
) -> tuple[ScreeningOutcome, RunnerOutput | None]:
    implementation = artifact.manifest.implementation
    checks = {
        "schema": "fail",
        "temporal": "not_applicable",
        "citations": "not_applicable",
        "released_values": "not_applicable",
    }
    output = None
    coverage = None
    status = "failed"
    reason: list[ReasonCode] = [ReasonCode.SCHEMA_INVALID]
    try:
        if (
            not isinstance(implementation, DocumentImplementation)
            or not data
            or len(data) > policy.note_bytes
        ):
            raise ValueError("unsupported document size or representation")
        if implementation.format == "json":
            output = RunnerOutput.model_validate_json(data)
        elif implementation.format in ("csv", "parquet"):
            frame = (
                pl.read_csv(
                    io.BytesIO(data),
                    n_rows=policy.document_rows + 1,
                    try_parse_dates=True,
                    schema_overrides={"date": pl.Date, "code": pl.String, "close": pl.Float64},
                )
                if implementation.format == "csv"
                else pl.read_parquet(io.BytesIO(data), n_rows=policy.document_rows + 1)
            )
            output = RunnerOutput(
                schema_version="1",
                kind=ArtifactKind.DATA_PRODUCT,
                tables={"output": pack_table(frame)},
            )
        else:
            raise ValueError("unsupported data-product document format")
        if sum(len(t.rows) for t in output.tables.values()) > policy.document_rows:
            raise ValueError("data-product row resource bound exceeded")
        checks["schema"] = "pass"
        checks["temporal"] = "fail"
        coverage = adapter.quality(output, request)
        adapter.project(output, request)
        if coverage.status == "passed":
            checks["temporal"] = "pass"
            status, reason = "passed", []
        else:
            status, reason = coverage.status, coverage.reason_codes
    except (ValueError, KeyError, TypeError, pl.exceptions.PolarsError):
        pass
    return ScreeningOutcome.model_validate(
        dict(
            schema_version="1",
            kind="data_product",
            execution="document",
            status=status,
            reason_codes=reason,
            coverage=coverage,
            causality=None,
            output_sha256=digest(output.model_dump(mode="json")) if output else None,
            document_checks=checks,
        )
    ), output
