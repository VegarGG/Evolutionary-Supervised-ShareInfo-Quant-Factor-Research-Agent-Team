"""Pinned descriptive reports. Models supply judgments, never authoritative metric copies."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import Field, model_validator

from qfh.case_contract import count_facts, prose_checks
from qfh.case_factor import FactorSpec, definition
from qfh.shared_state import Citation, Decision, Finding, Record, digest

CHECKS = ("evidence_support", "spec_and_prose", "timing", "scope_and_limits")
LIMITS = [
    "Development sample only; this inspected data cannot become an untouched holdout.",
    "An available next observed close does not establish tradability, fills or transaction costs.",
    "Raw return and volatility-normalized return are both dimensionless; scaling changes "
    "magnitude, not units.",
    "No forward labels, returns after execution, alpha, causality or superiority were measured.",
    "Unadjusted historical closes are not vintage data or evidence of corporate actions.",
    "The observed-date sample is neither an exchange calendar "
    "nor a representative market universe.",
]


class Argument(Record):
    text: str = Field(
        min_length=1,
        max_length=1600,
        description="Qualitative hypothesis or interpretation, not a metric table. Do not copy "
        "numbers, units or execution counts here; reference host fact IDs in fact_refs. "
        "A reference establishes provenance, not proof of the interpretation.",
    )
    fact_refs: list[str] = Field(min_length=1, max_length=12)


class ReportCitation(Citation):
    quote: str = Field(min_length=1, max_length=600)


class ReportDecision(Decision):
    reason: str = Field(min_length=1, max_length=200)


class StructuredRevision(Record):
    parent_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    inspection_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    facts_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    hypothesis: Argument
    rationale: Argument
    decisions: list[ReportDecision] = Field(max_length=12)
    citations: list[ReportCitation] = Field(min_length=1, max_length=6)
    basis_review_id: str | None
    issue_resolutions: list[str]


class StructuredReview(Record):
    candidate_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    verdict: Literal["reviewed_with_limits", "needs_revision"]
    checks: dict[
        Literal["evidence_support", "spec_and_prose", "timing", "scope_and_limits"],
        Literal["consistent", "needs_revision"],
    ]
    issues: list[str] = Field(
        max_length=6,
        description="Only defects that require changing the candidate. Disclosed ordinary "
        "limitations are already supplied by the host and do not belong here. "
        "reviewed_with_limits requires issues=[] and every check consistent.",
    )
    citations: list[Citation] = Field(min_length=1)

    @model_validator(mode="after")
    def consistent(self):
        if set(self.checks) != set(CHECKS):
            raise ValueError("all structured review checks are required")
        failed = "needs_revision" in self.checks.values()
        if failed != bool(self.issues) or failed != (self.verdict == "needs_revision"):
            raise ValueError("review checks, issues and verdict must agree")
        return self


class TaskFinding(Finding):
    candidate_id: Literal["assigned"]


class TaskFindings(Record):
    findings: list[TaskFinding] = Field(min_length=1, max_length=4)


class TaskDecision(ReportDecision):
    finding_id: str = Field(pattern=r"^finding:[1-9][0-9]*$")


class TaskRevision(StructuredRevision):
    parent_id: Literal["assigned"]
    inspection_id: str = Field(
        pattern=r"^inspection:[1-6]$",
        description="Use inspection_ref from your chosen inspect_case_factor receipt.",
    )
    facts_sha256: Literal["inspection"]
    decisions: list[TaskDecision] = Field(max_length=12)
    basis_review_id: Literal["failed_assigned_review"] | None


class TaskReview(StructuredReview):
    candidate_id: Literal["assigned"]
    report_sha256: Literal["assigned"]


def fact_keys(pinned):
    return {"units", "timing", "scope", "spec", "changed_rows_from_initial", *pinned["metrics"]}


def facts(episode, calculation):
    """All values come from host calculations; hashes bind the entire data/spec contract."""
    spec = FactorSpec.model_validate(calculation["spec"])
    counts = count_facts(episode.rows, spec, calculation["rows"])
    metrics = {}
    for symbol, own in counts.items():
        for key, value in own.items():
            metrics[f"{symbol}.{key}"] = {"value": value, "unit": "count"}
        for key, value in calculation["summary"]["by_symbol"][symbol].items():
            if key.endswith("score"):
                metrics[f"{symbol}.{key}"] = {"value": value, "unit": "dimensionless"}
    return {
        "schema": "qfh.descriptive-facts.v1",
        "data_snapshot_sha256": episode.data_snapshot_sha256,
        "spec": calculation["spec"],
        "spec_sha256": calculation["spec_sha256"],
        "score_rows_sha256": calculation["summary"]["score_rows_sha256"],
        "units": {
            "close": "CNY/share",
            "raw_return": "dimensionless",
            "normalized_return": "dimensionless",
            "score": "dimensionless",
        },
        "timing": {
            "signal": "after_observed_close_t",
            "earliest_price_observation": "next_observed_close",
            "tradability": "not_established",
            "fills": "not_measured",
            "costs": "not_measured",
            "future_evaluation_label": "from_execution_close_to_later_horizon_close",
        },
        "scope": {
            "data_use": "development_only",
            "performance": "not_evaluated",
            "superiority": "not_established",
            "corporate_actions": "not_identified",
        },
        "metrics": metrics,
        "changed_rows_from_initial": calculation["summary"][
            "changed_score_or_eligibility_rows_from_initial"
        ],
        "limits": LIMITS,
    }


def universe_unit_issue(text):
    """A known false heading in this single-unit close/return case, not all prose."""
    if re.search(
        r"\bunits(?:\s+and\s+scale)?\s+(?:are|remain)\s+(?:heterogeneous|different)\s+"
        r"across\s+(?:(?:the|this)\s+)?(?:fixed\s+)?(?:universe|symbols|names)\b",
        text,
        re.I,
    ):
        return (
            "Across this universe close units are CNY/share and return scores are "
            "dimensionless; observed magnitudes or dispersion may differ, not their units"
        )
    return None


def argument_issues(submission, pinned):
    """Fail known counterexamples; never describe this bounded check as semantic proof."""
    texts = {"hypothesis": submission.hypothesis.text, "rationale": submission.rationale.text}
    texts.update({f"decisions[{i}]": d.reason for i, d in enumerate(submission.decisions)})
    texts.update({f"issue_resolutions[{i}]": s for i, s in enumerate(submission.issue_resolutions)})
    issues = []
    allowed = fact_keys(pinned)
    for name in ("hypothesis", "rationale"):
        if set(getattr(submission, name).fact_refs) - allowed:
            issues.append(f"{name}: unknown fact reference")
    for path, text in texts.items():
        if issue := universe_unit_issue(text):
            issues.append(f"{path}: {issue}")
        # Digits in citations, hashes, specs and reference fields are allowed. Free text
        # cannot become a second, slightly different metric store.
        if re.search(r"\d", text):
            issues.append(f"{path}: use fact_refs, not numeric copies in qualitative text")
        if re.search(
            r"\b(?:now|becomes?|became|made|makes?)\s+(?:the\s+scores?\s+)?dimensionless\b",
            text,
            re.I,
        ):
            issues.append(f"{path}: both raw and normalized returns are dimensionless")
        if re.search(
            r"\b(?:signals?|trades?)\s+(?:(?:are|is)\s+)?(?:executable|tradable)\b", text, re.I
        ):
            issues.append(f"{path}: tradability is not established by close observations")
        # Recorded control: SD max/min ratios were similar while absolute ranges
        # differed greatly. Do not silently choose the interpretation that passes.
        # This catches that bounded claim grammar, not arbitrary comparison prose.
        for sentence in re.split(r"[.;\n]", text.lower()):
            equal_width = re.search(
                r"\b(?:spread|dispersion)(?:\s+across\s+the\s+names)?\s+"
                r"(?:stays?|remains?)\s+(?:(?:about|roughly|approximately)\s+)?as\s+wide\b",
                sentence,
            )
            named_measure = re.search(
                r"\b(?:ratio|difference)\s+(?:of\s+)?(?:the\s+)?"
                r"(?:maximum|max)\s+(?:to|and|minus)\s+(?:the\s+)?(?:minimum|min)\b",
                sentence,
            )
            if equal_width and not named_measure:
                issues.append(
                    f"{path}: name the dispersion comparison measure, such as the ratio "
                    "of maximum to minimum SD, or remove the unqualified width claim"
                )
    issues.extend(
        i["reason"] if "reason" in i else str(i) for i in prose_checks(texts, {})["issues"]
    )
    return issues


def make_report(episode, head, calculation, inspection):
    pinned = facts(episode, calculation)
    body = {
        "schema": "qfh.research-report.v1",
        "candidate_id": head["id"],
        "facts": pinned,
        "facts_sha256": digest(pinned),
        "definition": definition(
            FactorSpec.model_validate(calculation["spec"]),
            episode.symbols,
            "Model hypothesis appears separately below; it is not a computed result.",
        ).model_dump(),
        "calculation_provenance": {
            "engine": "deterministic_host",
            "inspection_id": inspection["id"],
            "requested_by": inspection["actor"],
            "readers_are_not_calculation_authors": True,
        },
        "model_proposal": head["body"]["structured_submission"],
        "source_sha256": {key: digest(value) for key, value in episode.sources.items()},
        "acceptance": "pending_exact_report_review_and_independent_audit",
        "usage": "Not included: final acknowledgements have not settled. "
        "Native footer is session-only; team totals belong in the post-run audit.",
    }
    return {"sha256": digest(body), "body": body}


def render(report, review_id):
    """Plain text is supported by the native DSH tool renderer; no model rewriting."""
    body, pinned = report["body"], report["body"]["facts"]
    lines = [
        "QRH structured research report",
        "Pending independent audit; no official acceptance.",
        f"Candidate: {body['candidate_id']}",
        f"Report SHA256: {report['sha256']}",
        f"Exact-report review: {review_id}",
        "",
        "COMPUTED FACTS",
        body["definition"]["expression"],
        body["definition"]["input_units"],
        f"Rows changed from initial: {pinned['changed_rows_from_initial']}",
    ]
    for key in sorted(pinned["metrics"]):
        metric = pinned["metrics"][key]
        lines.append(f"{key}: {metric['value']} [{metric['unit']}]")
    if "comparisons" in body:
        lines.append(
            "Changed-score count excludes numerical noise: relative tolerance 1e-10, "
            "absolute tolerance 1e-12; eligibility changes always count."
        )
        lines.extend(["", "COMPUTED COMPARISONS — host calculations"])
        for item in body["comparisons"]:
            lines.extend(
                [
                    f"Measure: {item['measure']}; cohort: {item['cohort']}",
                    f"Left candidate: {item['left_candidate_id']}; "
                    f"right inspection: {item['right_inspection_id']}",
                    f"Left: {item['left_value']}; right: {item['right_value']}; "
                    f"direction: {item['direction_right_vs_left']}",
                    f"Identical observation keys: {item['same_observations']}",
                    "Counts left/right: "
                    + ", ".join(
                        f"{s} {v['count']}/{item['right_by_symbol'][s]['count']}"
                        for s, v in item["left_by_symbol"].items()
                    ),
                    item["limits"],
                ]
            )
    lines.extend(
        [
            "",
            "EVIDENCE LIMITS",
            *pinned["limits"],
            "",
            "CALCULATION PROVENANCE",
            f"Host inspection requested by {body['calculation_provenance']['requested_by']}; "
            "reading this receipt is not executing a new calculation.",
            "",
            "MODEL PROPOSAL — qualitative interpretation, not an established result",
        ]
    )
    for name in ("hypothesis", "rationale"):
        arg = body["model_proposal"][name]
        lines.extend([f"{name}: {arg['text']}", "Fact references: " + ", ".join(arg["fact_refs"])])
    lines.extend(["", "FINDING DISPOSITIONS — model reasoning"])
    for item in body["model_proposal"]["decisions"]:
        lines.append(f"{item['finding_id']}: {item['disposition']} — {item['reason']}")
    lines.extend(["", "CITED SOURCE EXCERPTS — provenance, not proof of interpretation"])
    for item in body["model_proposal"]["citations"]:
        lines.append(f"{item['evidence_id']}: {item['quote']}")
    lines.extend(["", "USAGE SCOPE", body["usage"]])
    return "\n".join(lines)
