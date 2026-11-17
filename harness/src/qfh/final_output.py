"""Version-pinned review of completed research output, without factor-definition churn.

The small algebra checker proves only the declared unit conversion. Independent
review still owns interpretation of prose; this is not the official research gate.
"""

from __future__ import annotations

import ast
import fcntl
from fractions import Fraction
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from qfh.evidence import canonical
from qfh.shared_state import (
    Board,
    BoardPolicy,
    CandidateDefinition,
    Citation,
    Decision,
    Record,
    atomic_new,
)
from qfh.unit_prose import relationships


class UnitInput(Record):
    variable: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_]{0,80}$")
    base_units_per_reported_unit: int = Field(ge=1, le=10**12)
    citation: Citation


class UnitContract(Record):
    numerator: UnitInput
    denominator: UnitInput
    base_unit: Literal["CNY"]

    @model_validator(mode="after")
    def distinct(self):
        if self.numerator.variable == self.denominator.variable:
            raise ValueError("unit inputs must be distinct")
        return self


class UnitClaims(Record):
    # Exact integer fractions avoid tolerances and ambiguous 'scale by' language.
    target_per_raw_numerator: int = Field(ge=1)
    target_per_raw_denominator: int = Field(ge=1)
    raw_per_target_numerator: int = Field(ge=1)
    raw_per_target_denominator: int = Field(ge=1)
    raw_direction: Literal["overstates", "understates", "equal"]


class CompletedOutput(Record):
    definition: CandidateDefinition
    decisions: list[Decision]
    citations: list[Citation] = Field(min_length=1)
    rationale: str = Field(min_length=1)
    unresolved: list[str]
    unit_claims: UnitClaims | None = None


class OutputEpisode(Record):
    episode_id: str = Field(pattern=r"^[a-z0-9-]{1,100}$")
    category: Literal["diagnostic"] = "diagnostic"
    synthetic_evidence: Literal[True] = True
    actors: dict[str, Literal["author", "reviewer", "supervisor"]]
    sources: dict[str, str] = Field(min_length=1)
    initial_output: CompletedOutput
    import_origin: dict  # Exact origin artifact and file hashes, operator supplied.
    units: UnitContract
    policy: BoardPolicy


class OutputIssue(Record):
    path: str = Field(pattern=r"^/")
    quote: str = Field(
        min_length=1,
        description="Exact excerpt for a text field. For a non-text "
        "field, its complete canonical JSON value; for example path /unit_claims "
        "with quote null (the four-character string) when claims are missing.",
    )
    explanation: str = Field(min_length=1)
    citations: list[Citation] = Field(min_length=1)


CHECKS = {"formula_units", "explanations", "source_support", "scope_and_limits"}


class FinalReview(Record):
    output_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    verdict: Literal["needs_revision", "reviewed_with_limits"]
    checks: dict[
        Literal["formula_units", "explanations", "source_support", "scope_and_limits"], str
    ]
    issues: list[OutputIssue] = Field(max_length=6)
    limitations: list[str] = Field(min_length=1, max_length=6)

    @model_validator(mode="after")
    def complete(self):
        if set(self.checks) != CHECKS or any(not x.strip() for x in self.checks.values()):
            raise ValueError("all completed-output review checks are required")
        if bool(self.issues) != (self.verdict == "needs_revision"):
            raise ValueError("verdict must agree with the presence of blocking issues")
        return self


class Resolution(Record):
    issue_index: int = Field(ge=0)
    action: Literal["correct", "qualify"]
    reason: str = Field(min_length=1)


class OutputAmendment(Record):
    parent_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    review_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    output: CompletedOutput
    resolutions: list[Resolution] = Field(min_length=1, max_length=6)


def expression_units(expression: str):
    """Parse a bounded multiplication/division monomial. Never execute model code."""
    if len(expression) > 1000:
        raise ValueError("unit expression is too long")
    try:
        tree = ast.parse(expression, mode="eval")
    except (SyntaxError, RecursionError) as error:
        raise ValueError("invalid unit expression") from error
    if sum(1 for _ in ast.walk(tree)) > 80:
        raise ValueError("unit expression is too complex")

    def visit(node):
        if isinstance(node, ast.Name):
            return Fraction(1), {node.id: 1}
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            if not 1e-12 <= node.value <= 10**12:
                raise ValueError("unit constant outside bounds")
            # Preserve the written decimal, not a float-rounded approximation.
            # Bound the AST value first to reject huge/underflowing exponents
            # without constructing arbitrarily large Fraction integers.
            value = (
                Fraction(node.value)
                if type(node.value) is int
                else Fraction(ast.get_source_segment(expression, node).replace("_", ""))
            )
            if not 0 < value <= 10**12 or value.denominator > 10**12:
                raise ValueError("unit constant outside bounds")
            return value, {}
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Mult, ast.Div)):
            left, lp = visit(node.left)
            right, rp = visit(node.right)
            sign = -1 if isinstance(node.op, ast.Div) else 1
            powers = {k: lp.get(k, 0) + sign * rp.get(k, 0) for k in lp.keys() | rp.keys()}
            coefficient = left / right if sign == -1 else left * right
            if max(coefficient.numerator.bit_length(), coefficient.denominator.bit_length()) > 256:
                raise ValueError("unit coefficient outside bounds")
            return coefficient, {k: v for k, v in powers.items() if v}
        raise ValueError("unit expression allows only positive constants, names, * and /")

    return visit(tree.body)


def unit_proof(output: CompletedOutput, contract: UnitContract):
    target = Fraction(
        contract.numerator.base_units_per_reported_unit,
        contract.denominator.base_units_per_reported_unit,
    )
    raw = 1 / target
    prose = relationships(output.model_dump(), target)
    claims = UnitClaims(
        target_per_raw_numerator=target.numerator,
        target_per_raw_denominator=target.denominator,
        raw_per_target_numerator=raw.numerator,
        raw_per_target_denominator=raw.denominator,
        raw_direction="overstates" if raw > 1 else "understates" if raw < 1 else "equal",
    )
    try:
        coefficient, powers = expression_units(output.definition.expression)
        formula_ok = coefficient == target and powers == {
            contract.numerator.variable: 1,
            contract.denominator.variable: -1,
        }
        error = None
    except ValueError as exc:
        formula_ok, error = False, str(exc)
    return {
        "formula_ok": formula_ok,
        "recognized_prose_ok": all(check["passed"] for check in prose),
        "recognized_prose_checks": prose,
        "prose_coverage_limit": "Limited explicit English raw/target equalities and magnitude "
        "direction statements only. Unknown wording still needs independent semantic review. "
        "Do not retain an obsolete equality as a quote in current output; cite its parent version.",
        "structured_claims_ok": output.unit_claims == claims,
        "expected_claims": claims.model_dump(),
        "relations": {
            "target": f"raw * ({target.numerator}/{target.denominator})",
            "raw": f"target * ({raw.numerator}/{raw.denominator})",
        },
        "direction_basis": "Magnitude for nonzero ratios. Signed algebra is unchanged; "
        "overstates does not mean a negative ratio is numerically larger. Zero remains zero. "
        "Division requires nonzero capitalization.",
        "source_citations": [
            contract.numerator.citation.model_dump(),
            contract.denominator.citation.model_dump(),
        ],
        "expression_error": error,
        "limits": "Exact declared unit algebra only; not a semantic proof of arbitrary prose.",
    }


def at_pointer(body, path):
    value = body
    try:
        for part in path.split("/")[1:]:
            part = part.replace("~1", "/").replace("~0", "~")
            value = value[int(part)] if isinstance(value, list) else value[part]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ValueError("review path does not identify an output field") from exc
    return value


class FinalBoard(Board):
    def __init__(self, directory: Path):
        self.directory = directory
        self.episode = OutputEpisode.model_validate_json((directory / "episode.json").read_bytes())

    @classmethod
    def create(cls, directory, episode):
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / ".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            atomic_new(directory / "episode.json", episode.model_dump())
            board = cls(directory)
            board._citations([episode.units.numerator.citation, episode.units.denominator.citation])
            board._citations(episode.initial_output.citations)
            if not board._events():
                board._append(
                    [], "operator", "imported_output", episode.initial_output.model_dump()
                )
        return board

    @staticmethod
    def _head(events):
        return next(
            e for e in reversed(events) if e["kind"] in ("imported_output", "output_amendment")
        )

    @staticmethod
    def output(head):
        body = head["body"]
        return CompletedOutput.model_validate(body["output"] if "output" in body else body)

    @staticmethod
    def _open(events):
        if any(e["kind"] == "finalized" for e in events):
            raise ValueError("episode finalized; no artifact or task replay")

    def snapshot(self, actor):
        self._actor(actor, {"author", "reviewer", "supervisor"})
        with self.locked() as events:
            head = self._head(events)
            return {
                "episode_id": self.episode.episode_id,
                "head": {
                    "id": head["id"],
                    "actor": head["actor"],
                    "output": self.output(head).model_dump(),
                },
                "sources": self.episode.sources,
                "unit_proof": unit_proof(self.output(head), self.episode.units),
                "reviews": [e for e in events if e["kind"] == "final_review"],
                "tasks": [e for e in events if e["kind"] in ("task_started", "task_finished")],
                "finalized": next((e for e in events if e["kind"] == "finalized"), None),
            }

    def review(self, actor, review: FinalReview):
        self._actor(actor, {"reviewer"})
        with self.locked() as events:
            self._open(events)
            head = self._head(events)
            if head["id"] != review.output_id:
                raise ValueError("review must target the current exact output")
            if any(
                e["kind"] == "final_review" and e["body"]["output_id"] == head["id"] for e in events
            ):
                raise ValueError("this output already has a completed review")
            output = self.output(head)
            for issue in review.issues:
                observed = at_pointer(output.model_dump(), issue.path)
                matches = (
                    issue.quote in observed
                    if isinstance(observed, str)
                    else issue.quote == canonical(observed).decode()
                )
                if not issue.quote.strip() or not matches:
                    raise ValueError("review excerpt must match the targeted output field")
                self._citations(issue.citations)
            proof = unit_proof(output, self.episode.units)
            failures = [x for x in proof["recognized_prose_checks"] if not x["passed"]]
            for failure in failures:
                if not any(
                    issue.path == failure["path"]
                    and (issue.quote in failure["quote"] or failure["quote"] in issue.quote)
                    for issue in review.issues
                ):
                    raise ValueError(
                        "review must address the host-detected unit contradiction: " + str(failure)
                    )
            if review.verdict == "reviewed_with_limits" and not (
                proof["formula_ok"]
                and proof["structured_claims_ok"]
                and proof["recognized_prose_ok"]
            ):
                raise ValueError("unit proof/structured claims must pass before a clean review")
            return self._append(events, actor, "final_review", review.model_dump())

    def amend(self, actor, amendment: OutputAmendment):
        self._actor(actor, {"author"})
        self._citations(amendment.output.citations)
        with self.locked() as events:
            self._open(events)
            head = self._head(events)
            if head["id"] != amendment.parent_id:
                raise ValueError("stale output parent")
            review = next(
                (
                    e
                    for e in events
                    if e["id"] == amendment.review_id and e["kind"] == "final_review"
                ),
                None,
            )
            if (
                not review
                or review["body"]["output_id"] != head["id"]
                or review["body"]["verdict"] != "needs_revision"
            ):
                raise ValueError("amendment requires a failed review on its exact parent")
            ids = [r.issue_index for r in amendment.resolutions]
            if sorted(ids) != list(range(len(review["body"]["issues"]))):
                raise ValueError("resolve every issue exactly once")
            before, after = self.output(head), amendment.output
            for key in CandidateDefinition.model_fields.keys() - {"hypothesis"}:
                if getattr(before.definition, key) != getattr(after.definition, key):
                    raise ValueError(
                        "explanation correction cannot change the computational definition"
                    )
            if [(d.finding_id, d.disposition) for d in before.decisions] != [
                (d.finding_id, d.disposition) for d in after.decisions
            ]:
                raise ValueError("preserve original contribution identities and dispositions")
            if before == after:
                raise ValueError("amendment must change the output")
            if (
                sum(e["kind"] in ("imported_output", "output_amendment") for e in events)
                >= self.episode.policy.max_versions
            ):
                raise ValueError("output version allowance exhausted")
            proof = unit_proof(after, self.episode.units)
            if not (
                proof["formula_ok"]
                and proof["structured_claims_ok"]
                and proof["recognized_prose_ok"]
            ):
                raise ValueError(
                    "amended output must pass the exact unit contract; recognized "
                    "prose contradictions: "
                    + str([x for x in proof["recognized_prose_checks"] if not x["passed"]])
                )
            return self._append(
                events,
                actor,
                "output_amendment",
                {
                    **amendment.model_dump(),
                    "unit_proof": proof,
                    "definition_change": False,
                    "changed_fields": [
                        k
                        for k in before.model_dump()
                        if before.model_dump()[k] != after.model_dump()[k]
                    ],
                },
            )

    def finalize(self, actor, output_id, review_id):
        self._actor(actor, {"supervisor"})
        with self.locked() as events:
            self._open(events)
            head = self._head(events)
            review = next(
                (e for e in events if e["id"] == review_id and e["kind"] == "final_review"), None
            )
            if (
                head["id"] != output_id
                or not review
                or review["body"]["output_id"] != output_id
                or review["body"]["verdict"] != "reviewed_with_limits"
            ):
                raise ValueError(
                    "finalization requires a clean independent review of the current output"
                )
            proof = unit_proof(self.output(head), self.episode.units)
            if not (
                proof["formula_ok"]
                and proof["structured_claims_ok"]
                and proof["recognized_prose_ok"]
            ):
                raise ValueError("unit proof failed")
            return self._append(
                events,
                actor,
                "finalized",
                {
                    "output_id": output_id,
                    "review_id": review_id,
                    "unit_proof": proof,
                    "status": "reviewed_diagnostic_only",
                    "evaluation_or_publication": False,
                },
            )
