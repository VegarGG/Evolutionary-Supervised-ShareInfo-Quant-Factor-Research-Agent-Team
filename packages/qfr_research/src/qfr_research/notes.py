"""The generation's research note (Phase 8, PLAN Sections 7.6 and 8.10).

Deterministic code: at the end of a generation the packager collects the generation's
final interpretations into one Markdown note, with the analyst's claims as structured
claims citing the released reports they restate. No model writes the note, so it says
exactly what the interpretations said. The claims are not checked here: the evaluator
checks them against the released reports and releases the result as a note report.
"""

from dataclasses import dataclass
from typing import Any

# The section that ends the Markdown when it is cut to the protocol's length limit.
TRUNCATED = "\n\n_The note was cut to the protocol's length limit._\n"


@dataclass(frozen=True)
class NoteLimits:
    max_markdown_chars: int
    max_claims: int
    max_citations: int

    @classmethod
    def from_card(cls, protocol: dict[str, Any]) -> "NoteLimits | None":
        """The active protocol's research_note limits; None when it accepts no notes."""
        section = protocol.get("research_note")
        if not isinstance(section, dict):
            return None
        return cls(
            int(section["max_markdown_chars"]),
            int(section["max_claims"]),
            int(section["max_citations"]),
        )


@dataclass(frozen=True)
class Interpretation:
    interpretation_id: str
    status: str  # final or amended
    body: dict[str, Any]


def _bullets(items: list[Any]) -> str:
    return "\n".join(f"- {item}" for item in items)


def section(item: Interpretation) -> str:
    body = item.body
    parts = [
        f"## {body['what_was_tested']}",
        f"Observed: {body['observed']}",
        f"Diagnosis (conjecture): {body['diagnosis']}",
    ]
    if body.get("next_steps"):
        parts.append("Next steps:\n" + _bullets(body["next_steps"]))
    parts.append(f"Confidence: {body['confidence']}")
    parts.append("Caveats:\n" + _bullets(body["caveats"]))
    if item.status == "amended" and body.get("amended_text"):
        parts.append(f"Amended on review: {body['amended_text']}")
    parts.append("Reports: " + ", ".join(f"`{r}`" for r in body["report_ids"]))
    return "\n\n".join(parts)


def build_note(seq: int, items: list[Interpretation], limits: NoteLimits) -> dict[str, Any] | None:
    """The note's implementation (qfr-note/1), or None when there is nothing to say.

    Interpretations are taken in order while their citations fit the limit; the claims
    are those of the interpretations taken, up to the limit; the Markdown is cut at the
    limit with a closing line saying so."""
    cited: list[str] = []
    claims: list[dict[str, Any]] = []
    sections: list[str] = []
    for item in items:
        reports = [str(r) for r in item.body["report_ids"]]
        new = [r for r in reports if r not in cited]
        if len(cited) + len(new) > limits.max_citations:
            break
        cited.extend(new)
        sections.append(section(item))
        for claim in item.body.get("claims") or []:
            if str(claim["report_id"]) in reports and len(claims) < limits.max_claims:
                claims.append(
                    {
                        "report_id": str(claim["report_id"]),
                        "field": claim["field"],
                        "value": float(claim["value"]),
                    }
                )
    if not cited:
        return None
    header = (
        f"# Research note: generation {seq}\n\n"
        f"{len(sections)} interpretation(s) of {len(cited)} released report(s). Every "
        "number restates a released, coarsened value; causes are conjecture."
    )
    markdown = "\n\n".join([header, *sections]) + "\n"
    if len(markdown) > limits.max_markdown_chars:
        markdown = markdown[: max(0, limits.max_markdown_chars - len(TRUNCATED))] + TRUNCATED
        markdown = markdown[: limits.max_markdown_chars]
    return {
        "language": "qfr-note/1",
        "markdown": markdown,
        "cited_report_ids": cited,
        "claims": claims,
    }
