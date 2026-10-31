"""Output-quality checks for research notes (PLAN Sections 7.6 and 8.10, P8.2).

A research note is Markdown plus structured claims that cite released report ids. The
evaluator checks it deterministically at intake and releases one note report:

  LENGTH_LIMIT         the Markdown, the claims or the citations exceed the protocol's
                       research_note limits;
  CITATION_UNKNOWN     a cited report id was never released;
  CLAIM_FIELD_UNKNOWN  a claim names a field that its report does not release as a number;
  CLAIM_MISMATCH       a claimed value is further from the released value than half the
                       rounding step that field was released at;
  UNDISCLOSED_WINDOW   the note names the holdout window (W3, holdout), whose metrics
                       are never released.

The checks read only the note and reports research already holds, never a private value
or a window date, so a result tells research nothing it could not work out itself. There
is no model-graded score; an advisory rubric may come later and would never be a gate.
"""

import math
import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pydantic import JsonValue
from qfr_core.contracts import NoteCheckCode, NoteContent, ResearchNoteManifest
from sqlalchemy import text
from sqlalchemy.engine import Connection

# The policy rounding step each released number is rounded to (Section 9.2). Fields not
# listed here (complexity) are released exactly and must match exactly.
FIELD_STEPS = {
    "rankic_mean": "rankic",
    "decay_profile": "rankic",
    "yearly_rankic": "rankic",
    "size_neutral_rankic": "rankic",
    "answer_rankic": "rankic",
    "rankic_ir": "ir",
    "strategy_ir": "ir",
    "ls_net_sharpe": "sharpe",
    "strategy_net_sharpe": "sharpe",
    "forward_sharpe_bucket": "sharpe",
    "hit_ratio": "shares",
    "top_turnover": "shares",
    "strategy_drawdown_bucket": "shares",
    "monotonicity": "correlations",
    "rank_autocorrelation": "correlations",
    "max_library_correlation": "correlations",
    "family_best_rankic": "ladder_best",
}
TOLERANCE = 1e-9
# W3 is the holdout: research gets one bit about it (ADVANCED or NOT_ADVANCED) and never
# a number, so a note that names it is describing something it cannot have seen.
HOLDOUT = re.compile(r"\b(?:w3|hold[- ]?out)\b", re.IGNORECASE)


@dataclass(frozen=True)
class NoteCheck:
    content: NoteContent
    unknown_reports: list[str]
    detail: list[dict[str, JsonValue]]

    @property
    def passed(self) -> bool:
        return self.content.status == "PASS"


def released_number(content: dict[str, Any], field: str) -> float | None:
    """The released number at field (name or name.key), or None when there is none."""
    name, _, key = field.partition(".")
    value: Any = content.get(name)
    if key:
        value = value.get(key) if isinstance(value, dict) else None
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if math.isfinite(value) else None


def claim_matches(claimed: float, released: float, step: float | None) -> bool:
    tolerance = TOLERANCE if step is None else step / 2 + TOLERANCE
    return abs(claimed - released) <= tolerance


def _roundings(conn: Connection, refs: set[str]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for ref in refs:
        policy_id, _, version = ref.partition("/")
        config = conn.execute(
            text("SELECT config FROM eval.release_policies WHERE id = :i AND version = :v"),
            {"i": policy_id, "v": version},
        ).scalar()
        out[ref] = dict((config or {}).get("rounding") or {})
    return out


def check_note(
    conn: Connection, manifest: ResearchNoteManifest, limits: dict[str, Any]
) -> NoteCheck:
    note = manifest.implementation
    checks: set[NoteCheckCode] = set()
    detail: list[dict[str, JsonValue]] = []

    if (
        len(note.markdown) > int(limits["max_markdown_chars"])
        or len(note.claims) > int(limits["max_claims"])
        or len(note.cited_report_ids) > int(limits["max_citations"])
    ):
        checks.add(NoteCheckCode.LENGTH_LIMIT)
        detail.append(
            {
                "check": "LENGTH_LIMIT",
                "markdown_chars": len(note.markdown),
                "claims": len(note.claims),
                "citations": len(note.cited_report_ids),
            }
        )

    if HOLDOUT.search(note.markdown) or HOLDOUT.search(manifest.title):
        checks.add(NoteCheckCode.UNDISCLOSED_WINDOW)
        detail.append({"check": "UNDISCLOSED_WINDOW"})

    rows = conn.execute(
        text(
            "SELECT report_id, report_type, policy_ref, content FROM eval.released_reports "
            "WHERE report_id = ANY(:ids)"
        ),
        {"ids": list(note.cited_report_ids)},
    ).all()
    reports: dict[UUID, Any] = {row.report_id: row for row in rows}
    unknown = [str(r) for r in note.cited_report_ids if r not in reports]
    if unknown:
        checks.add(NoteCheckCode.CITATION_UNKNOWN)
        detail.append({"check": "CITATION_UNKNOWN", "report_ids": list(unknown)})

    rounding = _roundings(conn, {row.policy_ref for row in rows})
    failed: list[int] = []
    for index, claim in enumerate(note.claims):
        report = reports.get(claim.report_id)
        if report is None:
            failed.append(index)  # its citation is already CITATION_UNKNOWN
            continue
        released = released_number(dict(report.content), claim.field)
        if released is None:
            checks.add(NoteCheckCode.CLAIM_FIELD_UNKNOWN)
            failed.append(index)
            detail.append(
                {"check": "CLAIM_FIELD_UNKNOWN", "claim": index, "report_type": report.report_type}
            )
            continue
        key = FIELD_STEPS.get(claim.field.partition(".")[0])
        step = None if key is None else rounding[report.policy_ref].get(key)
        if not claim_matches(claim.value, released, step):
            checks.add(NoteCheckCode.CLAIM_MISMATCH)
            failed.append(index)
            detail.append(
                {"check": "CLAIM_MISMATCH", "claim": index, "claimed": claim.value,
                 "released": released, "step": step}
            )  # fmt: skip

    content = NoteContent(
        type="note",
        status="FAIL" if checks else "PASS",
        checks=sorted(checks, key=lambda c: c.value),
        citations=len(note.cited_report_ids),
        claims=len(note.claims),
        claims_matched=len(note.claims) - len(failed),
        failed_claims=failed,
    )
    return NoteCheck(content, unknown, detail)
