"""Typed descriptive comparisons and finding facts, computed by the host."""

import re
import statistics

from pydantic import Field

from qfh.case_contract import prose_checks
from qfh.case_report import StructuredRevision, TaskFinding, TaskRevision, fact_keys
from qfh.shared_state import Finding, Record, digest


class EvidenceFinding(Finding):
    fact_refs: list[str] = Field(min_length=1, max_length=12)


class EvidenceTaskFinding(TaskFinding):
    statement: str = Field(
        min_length=1,
        description="Qualitative observation or hypothesis only; no numeric copies or count "
        "equations. Refer to supplied current_fact_refs for counts, units and scope. "
        "Citations may quote source numbers exactly.",
    )
    fact_refs: list[str] = Field(min_length=1, max_length=12)


class EvidenceFindings(Record):
    findings: list[EvidenceFinding] = Field(min_length=1, max_length=4)


class EvidenceTaskFindings(Record):
    findings: list[EvidenceTaskFinding] = Field(min_length=1, max_length=4)


class EvidenceRevision(StructuredRevision):
    comparison_refs: list[str] = Field(max_length=8)


class EvidenceTaskRevision(TaskRevision):
    comparison_refs: list[str] = Field(
        max_length=8,
        description="Use exact comparison_refs returned by your inspections, or [] when "
        "making no comparison. Host renders the named measure, both specifications and "
        "cohort. Do not restate comparative results in qualitative text or decisions.",
    )


def finding_issues(finding, pinned):
    issues = prose_checks({"statement": finding.statement}, {})["issues"]
    if re.search(r"\d", finding.statement):
        issues.append("use fact_refs instead of numeric copies or arithmetic in findings")
    if set(finding.fact_refs) - fact_keys(pinned):
        issues.append("unknown current-candidate fact reference")
    return issues


def comparison_issues(submission):
    """Enforce the measured-comparison boundary for the recorded claim family."""
    texts = [
        ("hypothesis.text", submission.hypothesis.text),
        ("rationale.text", submission.rationale.text),
    ]
    texts += [(f"decisions[{i}].reason", d.reason) for i, d in enumerate(submission.decisions)]
    texts += [(f"issue_resolutions[{i}]", t) for i, t in enumerate(submission.issue_resolutions)]
    issues = []
    for field, text in texts:
        # A parameter equality in one clause says nothing about dispersion in
        # another. This is a bounded claim grammar, not a semantic proof.
        for sentence in re.split(r"[.,;\n]", text.lower()):
            subject = re.search(
                r"\b(?:spread|dispersion|deviation|sd|comparability|comparable)\b", sentence
            )
            assertion = re.search(
                r"\b(?:compress\w*|narrow\w*|widen\w*|reduc\w*|increas\w*|decreas\w*|"
                r"improv\w*|unchanged|equal\w*|similar|same|wide|higher|lower|larger|smaller)\b",
                sentence,
            )
            unproven = re.search(
                r"\b(?:might|may|could|hypothesis|unproven|not established|not measured|"
                r"(?:do not|does not|did not|cannot|can't) establish)\b",
                sentence,
            )
            if subject and assertion and not unproven:
                issues.append(
                    f"Measured comparison in {field}: {sentence.strip()!r}. "
                    "Use comparison_refs; host supplies the measure, values and cohort."
                )
    return issues


def definition_issues(submission):
    """Catch the recorded explicit denominator omission, not generic vol shorthand."""
    issues = []
    for name in ("hypothesis", "rationale"):
        text = getattr(submission, name).text.lower()
        explicit = re.search(
            r"\b(?:now|is|are) divided by (?:the )?trailing daily[- ]return "
            r"(?:standard deviation|sd)\b",
            text,
        )
        complete = re.search(r"sqrt\s*\(\s*lookback|square.root.{0,40}lookback", text)
        if explicit and not complete:
            issues.append(
                f"Incomplete normalization definition in {name}.text: the recorded formula "
                "also divides by sqrt(lookback). Reference the host spec and keep "
                "motivation qualitative, or state the complete source definition."
            )
    return issues


def comparisons(left, right):
    """Compare per-symbol sample SDs; never infer performance or unit conversion."""
    panels = [
        {(r["symbol"], r["signal_date"]): r["score"] for r in c["rows"] if r["score"] is not None}
        for c in (left, right)
    ]
    common = set(panels[0]) & set(panels[1])
    symbols = sorted({r["symbol"] for r in left["rows"]})
    result = {}
    for cohort in ("paired_eligible_symbol_dates", "each_spec_eligible_symbol_dates"):
        keys = [common, common] if cohort.startswith("paired") else [set(p) for p in panels]
        sides = []
        for panel, selected in zip(panels, keys, strict=True):
            by_symbol = {}
            for symbol in symbols:
                own = sorted(k for k in selected if k[0] == symbol)
                by_symbol[symbol] = {
                    "count": len(own),
                    "dates_sha256": digest([k[1] for k in own]),
                    "sample_sd": statistics.stdev(panel[k] for k in own) if len(own) >= 2 else None,
                }
            sides.append(by_symbol)
        for measure in ("score_sd_max_minus_min", "score_sd_max_over_min"):
            values = []
            for side in sides:
                sds = [s["sample_sd"] for s in side.values()]
                if any(s is None for s in sds) or not sds:
                    value = None
                elif measure.endswith("minus_min"):
                    value = max(sds) - min(sds)
                else:
                    value = max(sds) / min(sds) if min(sds) > 0 else None
                values.append(value)
            a, b = values
            direction = (
                "undefined"
                if a is None or b is None
                else "equal"
                if a == b
                else "increased"
                if b > a
                else "decreased"
            )
            result[f"{cohort}.{measure}"] = {
                "measure": measure,
                "cohort": cohort,
                "left_spec_sha256": left["spec_sha256"],
                "right_spec_sha256": right["spec_sha256"],
                "left_by_symbol": sides[0],
                "right_by_symbol": sides[1],
                "left_value": a,
                "right_value": b,
                "direction_right_vs_left": direction,
                "same_observations": keys[0] == keys[1],
                "limits": "Descriptive only. Absolute SD ranges depend on score scaling. "
                "Unequal cohorts confound specification and sample changes. Neither measure "
                "establishes comparability, superiority, alpha or a change of physical units.",
            }
    return result


def bound_comparisons(refs, events, actor, parent_id):
    result = []
    for ref in refs:
        ident, key = ref.split("/", 1)
        event = next((e for e in events if e["id"] == ident and e["kind"] == "inspection"), None)
        if (
            not event
            or event["actor"] != actor
            or event["body"].get("comparison_parent_id") != parent_id
        ):
            raise ValueError("comparison must bind this task's inspection and assigned candidate")
        if key not in event["body"].get("comparisons", {}):
            raise ValueError("unknown comparison measure/cohort reference")
        result.append(
            {
                "left_candidate_id": parent_id,
                "right_inspection_id": ident,
                "reference": ref,
                **event["body"]["comparisons"][key],
            }
        )
    if len(set(refs)) != len(refs):
        raise ValueError("duplicate comparison references")
    return result
