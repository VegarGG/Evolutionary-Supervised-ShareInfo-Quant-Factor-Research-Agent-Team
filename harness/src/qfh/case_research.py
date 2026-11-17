"""Native DSH host for an open BaoStock case and a frozen-sequence control."""

from __future__ import annotations

import argparse
import fcntl
import json
import re
import sys
import uuid
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from qfh.adaptive_research import AdaptiveResearch
from qfh.budget import BudgetRefused
from qfh.case_contract import count_facts, encoded, page, prose_checks, reference, revision_texts
from qfh.case_evidence import (
    EvidenceFindings,
    EvidenceRevision,
    EvidenceTaskFindings,
    EvidenceTaskRevision,
    bound_comparisons,
    comparison_issues,
    comparisons,
    definition_issues,
    finding_issues,
)
from qfh.case_factor import FactorSpec, definition, inspect_factor, panel_quality, score_changed
from qfh.case_report import (
    LIMITS,
    StructuredReview,
    StructuredRevision,
    TaskFindings,
    TaskReview,
    TaskRevision,
    argument_issues,
    fact_keys,
    facts,
    make_report,
    render,
    universe_unit_issue,
)
from qfh.coding_plan import CodingPolicy
from qfh.module_experiment import output_schema
from qfh.research import Research
from qfh.shared_state import Board, Citation, Decision, Episode, Finding, Record, atomic_new, digest

TOOLS = {
    "case_board",
    "case_read",
    "case_task",
    "inspect_case_factor",
    "submit_case_findings",
    "revise_case_factor",
    "review_case_factor",
    "finalize_case",
}
STAGES = {
    "analyze": "Inspect all frozen sources and the initial/current factor. Identify concrete "
    "source-supported constraints and separately label hypotheses. Submit up to four findings. "
    "A cited observation can motivate an unproven testable hypothesis. Absence of proven alpha "
    "does not disqualify exploration. No prescribed correction; do not invent missing data, "
    "trading results or corporate actions.",
    "design": "Use the recorded findings and the same full evidence to propose one defensible "
    "executable factor revision, or explicitly retain the factor if no change is supported. "
    "Inspect the chosen specification, cite exact evidence, dispose of every current finding "
    "and distinguish an observed score change from unproven improvement. An exploratory "
    "candidate is a proposal for later evaluation, not deployment or proof of alpha. "
    "Explain why its applicability or research question follows from cited evidence. "
    "You may inspect a motivated alternative without adopting it; never force a change.",
    "review": "Review the exact current complete artifact, its executable inspection, claims, "
    "rationale, decisions and limits against the frozen sources. Report remaining issues. "
    "No performance or causality claim follows from descriptive score differences.",
}


class CaseEpisode(Episode):
    category: Literal["open_ended"] = "open_ended"
    synthetic_evidence: bool = False
    initial_spec: FactorSpec
    symbols: list[str]
    rows: list[dict]
    data_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    start: str
    end: str

    @model_validator(mode="after")
    def frozen_panel(self):
        panel_quality(self.rows, self.symbols, self.start, self.end)
        if digest(self.rows) != self.data_snapshot_sha256:
            raise ValueError("frozen panel hash differs")
        return self


class CasePolicy(Record):
    package_id: str = Field(pattern=r"^[a-z0-9-]{1,100}$")
    study_id: str
    variant: Literal["adaptive", "fixed"]
    authority: str
    question: str
    route_id: str
    model: Literal["glm-5.3-flash", "glm-5.3"] = "glm-5.3-flash"
    episode: CaseEpisode
    max_tasks: int = Field(ge=3, le=6)
    supervisor_requests: int = Field(ge=1, le=12)
    worker_requests: int = Field(ge=1, le=6)
    total_requests: int = Field(ge=1, le=36)
    max_output_tokens: int = Field(ge=128, le=32768)
    max_inspections: int = Field(ge=1, le=6)
    protocol: Literal["legacy", "bounded-v2", "structured-v3"] = "legacy"
    reference_mode: Literal["hashes", "task_bound"] = "hashes"
    evidence_contract: Literal["legacy", "typed-v1"] = "legacy"
    max_tool_bytes: int = Field(default=24000, ge=12000, le=24000)
    page_chars: int = Field(default=2500, ge=100, le=2500)
    worker_prompt_bytes: int = Field(default=65536, ge=24000, le=65536)

    @model_validator(mode="after")
    def valid_reference_mode(self):
        if self.reference_mode == "task_bound" and self.protocol != "structured-v3":
            raise ValueError("task-bound references require structured-v3")
        if self.evidence_contract == "typed-v1" and self.reference_mode != "task_bound":
            raise ValueError("typed evidence requires immutable task-bound references")
        return self


class FindingBatch(Record):
    findings: list[Finding] = Field(min_length=1, max_length=4)


class CaseRevision(Record):
    parent_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    spec: FactorSpec
    hypothesis: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    decisions: list[Decision]
    citations: list[Citation] = Field(min_length=1)
    limitations: list[str] = Field(min_length=1)
    count_claims: dict[str, dict[str, int]] | None = Field(
        default=None,
        description="For bounded-v2 copy count_facts from the exact chosen inspection. "
        "These are observed closes, required closes, warmup/additional exclusions, eligible "
        "signals and signals with a next close. Required window size is not warmup count.",
    )
    basis_review_id: str | None = Field(
        default=None,
        description="Null for the initial design. "
        "For a repair use the failed review ID of this exact parent.",
    )
    issue_resolutions: list[str] = Field(
        description="Empty list for initial design. For a repair, "
        "exactly one resolution per issue in the cited failed review, in the same order."
    )


class CaseReview(Record):
    candidate_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    verdict: Literal["reviewed_with_limits", "needs_revision"] = Field(
        description="reviewed_with_limits requires issues=[]; "
        "needs_revision requires at least one issue."
    )
    checks: dict[Literal["evidence_support", "spec_and_prose", "timing", "scope_and_limits"], str]
    issues: list[str] = Field(
        max_length=6,
        description="Concrete defects requiring a change. "
        "Ordinary disclosed caveats belong in limitations. Do not approve with open defects.",
    )
    citations: list[Citation] = Field(min_length=1)
    limitations: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def complete(self):
        if set(self.checks) != {"evidence_support", "spec_and_prose", "timing", "scope_and_limits"}:
            raise ValueError("all review checks are required")
        if any(not s.strip() for s in self.checks.values()):
            raise ValueError("review checks cannot be blank")
        if bool(self.issues) != (self.verdict == "needs_revision"):
            raise ValueError("review verdict must agree with issues")
        return self


class CaseBoard(Board):
    def __init__(self, directory):
        self.directory = directory
        self.episode = CaseEpisode.model_validate_json((directory / "episode.json").read_bytes())

    @property
    def bounded(self):
        package = self.directory.parent / "package.json"
        return package.exists() and json.loads(package.read_bytes()).get("protocol") in (
            "bounded-v2",
            "structured-v3",
        )

    @property
    def structured(self):
        package = self.directory.parent / "package.json"
        return (
            package.exists() and json.loads(package.read_bytes()).get("protocol") == "structured-v3"
        )

    def report(self, head, events):
        binding = head["body"]["structured_submission"]
        inspection = next(
            e for e in events if e["kind"] == "inspection" and e["id"] == binding["inspection_id"]
        )
        report = make_report(self.episode, head, self.calculation(self.spec_of(head)), inspection)
        if "comparison_refs" in binding:
            report["body"]["comparisons"] = bound_comparisons(
                binding["comparison_refs"], events, head["actor"], binding["parent_id"]
            )
            report["body"]["usage"] = (
                "The final host receipt includes settled team usage. Native footer is session-only."
            )
            report["sha256"] = digest(report["body"])
        return report

    @staticmethod
    def _open(events):
        if any(e["kind"] == "finalized" for e in events):
            raise ValueError("case is finalized")

    def spec_of(self, head):
        return (
            FactorSpec.model_validate(head["body"]["spec"])
            if "spec" in head["body"]
            else self.episode.initial_spec
        )

    def _citations(self, citations):
        for i, citation in enumerate(citations):
            source = self.episode.sources.get(citation.evidence_id)
            if source is None or not citation.quote.strip() or citation.quote not in source:
                raise ValueError(
                    f"citations[{i}] for {citation.evidence_id}: citation must quote "
                    "an authorized episode source exactly. Copy decoded source text; preserve "
                    "whitespace and do not include JSON-encoding backslashes. No fuzzy matching."
                )

    def calculation(self, spec):
        package = self.directory.parent / "package.json"
        typed = (
            package.exists()
            and json.loads(package.read_bytes()).get("evidence_contract") == "typed-v1"
        )
        return inspect_factor(
            self.episode.rows, spec, self.episode.initial_spec, tolerant_changes=typed
        )

    def counts(self, spec):
        calc = self.calculation(spec)
        return count_facts(self.episode.rows, spec, calc["rows"])

    def prose_proof(self, head):
        return prose_checks(revision_texts(head["body"]), self.counts(self.spec_of(head)))

    def snapshot(self, actor):
        snapshot = super().snapshot(actor)
        head = snapshot["head"]
        snapshot["current_spec"] = self.spec_of(head).model_dump()
        snapshot["inspection"] = self.calculation(self.spec_of(head))["summary"]
        snapshot["reviews"] = [e for e in snapshot["events"] if e["kind"] == "case_review"]
        snapshot["inspections"] = [e for e in snapshot["events"] if e["kind"] == "inspection"]
        snapshot["tasks"] = [
            e for e in snapshot["events"] if e["kind"] in ("task_started", "task_finished")
        ]
        snapshot["finalized"] = next(
            (e for e in snapshot["events"] if e["kind"] == "finalized"), None
        )
        if self.bounded:
            snapshot["count_facts"] = self.counts(self.spec_of(head))
            snapshot["prose_proof"] = self.prose_proof(head)
        if self.structured and head["kind"] == "revision":
            snapshot["structured_report"] = self.report(head, snapshot["events"])
        # Task traces remain in the immutable board, not duplicated in every prompt.
        del snapshot["events"]
        return snapshot

    def final_review(self, actor, review, *, structured=None):
        self._actor(actor, {"reviewer"})
        self._citations(review.citations)
        with self.locked() as events:
            self._open(events)
            head = self._head(events)
            if head["id"] != review.candidate_id:
                raise ValueError("review must target the exact current candidate")
            if self.structured:
                report = self.report(head, events)
                if not structured or structured.report_sha256 != report["sha256"]:
                    raise ValueError("review must bind the exact complete report hash")
                if review.verdict == "reviewed_with_limits":
                    raw = head["body"]["structured_submission"]
                    proposal = (
                        EvidenceRevision if "comparison_refs" in raw else StructuredRevision
                    ).model_validate(raw)
                    issues = argument_issues(proposal, report["body"]["facts"])
                    if isinstance(proposal, EvidenceRevision):
                        issues.extend(comparison_issues(proposal))
                        issues.extend(definition_issues(proposal))
                    if issues:
                        raise ValueError("structured report issues: " + json.dumps(issues))
            if self.bounded and review.verdict == "reviewed_with_limits":
                proof = self.prose_proof(head)
                review_proof = prose_checks(
                    {
                        **review.checks,
                        **{f"limitations[{i}]": text for i, text in enumerate(review.limitations)},
                    },
                    self.counts(self.spec_of(head)),
                )
                proof["issues"].extend(review_proof["issues"])
                proof["recognized_prose_ok"] &= review_proof["recognized_prose_ok"]
                if not proof["recognized_prose_ok"]:
                    raise ValueError(
                        "clean review conflicts with host count/prose checks: " + json.dumps(proof)
                    )
            if any(
                e["kind"] == "case_review" and e["body"]["candidate_id"] == head["id"]
                for e in events
            ):
                raise ValueError("candidate already reviewed")
            return self._append(
                events,
                actor,
                "case_review",
                {
                    **review.model_dump(),
                    **({"structured_review": structured.model_dump()} if structured else {}),
                },
            )

    def revision(self, actor, revision, *, structured=None):
        self._actor(actor, {"author"})
        self._citations(revision.citations)
        with self.locked() as events:
            self._open(events)
            head = self._head(events)
            if revision.parent_id != head["id"]:
                raise ValueError("stale candidate parent")
            if (
                sum(e["kind"] in ("initial_candidate", "revision") for e in events)
                >= self.episode.policy.max_versions
            ):
                raise ValueError("candidate version allowance exhausted")
            findings = {
                e["id"]: e
                for e in events
                if e["kind"] == "finding" and e["body"]["candidate_id"] == head["id"]
            }
            ids = [d.finding_id for d in revision.decisions]
            if len(set(ids)) != len(ids) or set(ids) != set(findings):
                raise ValueError("record exactly one decision per current-parent finding")
            prior_review = next(
                (
                    e
                    for e in events
                    if e["kind"] == "case_review" and e["id"] == revision.basis_review_id
                ),
                None,
            )
            if revision.basis_review_id and (
                not prior_review
                or prior_review["body"]["candidate_id"] != head["id"]
                or prior_review["body"]["verdict"] != "needs_revision"
            ):
                raise ValueError("repair must cite a failed review of this parent")
            if len(revision.issue_resolutions) != (
                len(prior_review["body"]["issues"]) if prior_review else 0
            ):
                raise ValueError("resolve every cited review issue in order")
            calc = self.calculation(revision.spec)
            if self.bounded and revision.count_claims != self.counts(revision.spec):
                raise ValueError(
                    "count_claims must equal count_facts from the exact chosen inspection"
                )
            if self.structured:
                if structured is None:
                    raise ValueError("structured submission required")
                inspection = next(
                    (
                        e
                        for e in events
                        if e["kind"] == "inspection"
                        and e["id"] == structured.inspection_id
                        and e["actor"] == actor
                    ),
                    None,
                )
                pinned = facts(self.episode, calc)
                if not inspection or inspection["body"]["spec"] != revision.spec.model_dump():
                    raise ValueError("report must cite the designer's exact inspection")
                if structured.facts_sha256 != digest(pinned):
                    raise ValueError("facts hash differs from chosen inspection")
                issues = argument_issues(structured, pinned)
                if isinstance(structured, EvidenceRevision):
                    bound_comparisons(structured.comparison_refs, events, actor, head["id"])
                    issues.extend(comparison_issues(structured))
                    issues.extend(definition_issues(structured))
                if issues:
                    raise ValueError("structured proposal issues: " + json.dumps(issues))
            parent_calc = self.calculation(self.spec_of(head))
            changed = sum(
                score_changed(a, b, tolerant=isinstance(structured, EvidenceRevision))
                for a, b in zip(calc["rows"], parent_calc["rows"], strict=True)
            )
            adopted = [
                findings[d.finding_id] for d in revision.decisions if d.disposition == "adopt"
            ]
            supported = [
                f["id"]
                for f in adopted
                if f["body"]["status"] == "supported" and f["actor"] != actor
            ]
            motivated = (
                [
                    f["id"]
                    for f in adopted
                    if f["actor"] != actor
                    and f["body"]["citations"]
                    and f["body"]["status"] == "hypothesis"
                ]
                if self.bounded
                else []
            )
            if revision.spec != self.spec_of(head) and (
                not changed or not (supported or motivated or prior_review)
            ):
                raise ValueError(
                    "factor change needs changed scores/eligibility and cited peer evidence"
                )
            return self._append(
                events,
                actor,
                "revision",
                {
                    **revision.model_dump(),
                    **({"structured_submission": structured.model_dump()} if structured else {}),
                    "definition": definition(
                        revision.spec, self.episode.symbols, revision.hypothesis
                    ).model_dump(),
                    "change_kind": "factor" if changed else "explanation_or_retained",
                    "changed_rows_from_parent": changed,
                    "peer_finding_ids": supported,
                    **(
                        {
                            "peer_hypothesis_ids": motivated,
                            "adoption_scope": "exploratory_research_only",
                        }
                        if self.bounded
                        else {}
                    ),
                    "inspection": calc["summary"],
                    "semantic_status": "pending independent audit; source citations alone "
                    "do not prove interpretation",
                },
            )

    def finalize(self, actor, output_id, review_id):
        self._actor(actor, {"supervisor"})
        with self.locked() as events:
            self._open(events)
            head = self._head(events)
            review = next(
                (e for e in events if e["id"] == review_id and e["kind"] == "case_review"), None
            )
            if (
                head["id"] != output_id
                or not review
                or review["body"]["candidate_id"] != output_id
                or review["body"]["verdict"] != "reviewed_with_limits"
            ):
                raise ValueError("finalization requires a clean exact-current-version review")
            if head["kind"] != "revision":
                raise ValueError(
                    "designer must submit an explicit revision or retained-candidate assessment"
                )
            if self.bounded and not self.prose_proof(head)["recognized_prose_ok"]:
                raise ValueError("recognized count/prose defects prevent finalization")
            report = self.report(head, events) if self.structured else None
            if (
                report
                and review["body"].get("structured_review", {}).get("report_sha256")
                != report["sha256"]
            ):
                raise ValueError("finalization requires an exact structured report review")
            return self._append(
                events,
                actor,
                "finalized",
                {
                    "output_id": output_id,
                    **({"report_sha256": report["sha256"]} if report else {}),
                    "review_id": review_id,
                    "status": "research_prototype_pending_independent_audit",
                    "substantive_change": any(
                        e["kind"] == "revision" and e["body"]["change_kind"] == "factor"
                        for e in events
                    ),
                    "evaluation_or_publication": False,
                },
            )


class CaseResearch(AdaptiveResearch):
    accepted_submission_kinds = {"finding_batch", "revision", "case_review"}

    def __init__(self, config, private, package):
        self.research = Research(config, private)
        self.policy = CasePolicy.model_validate_json(package.read_bytes())
        if self.policy.episode.synthetic_evidence and not (private / "OFFLINE_ONLY").is_file():
            raise ValueError("synthetic case requires an explicit offline-only workspace")
        self.directory = private / "cases" / self.policy.package_id
        self.directory.mkdir(parents=True, exist_ok=True)
        atomic_new(self.directory / "package.json", self.policy.model_dump(exclude_unset=True))
        self.board = CaseBoard.create(self.directory / "board", self.policy.episode)
        self.bindings = self.directory / "bindings"
        self.bindings.mkdir(exist_ok=True)
        with self.research.db() as db:
            self.route = CodingPolicy.model_validate(self.research.active_model_route(db))
        if self.route.id != self.policy.route_id or self.route.model != self.policy.model:
            raise ValueError("case requires its frozen explicitly authorized GLM model route")
        if self.research.ledger.snapshot()["provider_admission"]["providers"] != ["glm_coding"]:
            raise ValueError("case requires GLM-only provider admission")

    def step(self, actor):
        return f"case:{self.policy.package_id}:{actor}"

    def admit(self, session):
        if self.policy.protocol == "legacy":
            return super().admit(session)
        with (self.directory / ".admission.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            path = self._binding_path(session)
            if not path.exists():
                root = self.directory / "root.json"
                if root.exists():
                    raise BudgetRefused("one native supervisor per package; no paid replay")
                member = {"session_id": session, "actor": "supervisor", "role": "supervisor"}
                atomic_new(root, member)
                atomic_new(path, member)
            else:
                member = self.member(session)
            with self.board.locked() as events:
                if any(
                    e["kind"] == "task_finished" and e["body"]["child_id"] == session
                    for e in events
                ):
                    raise BudgetRefused("native worker finished; no paid replay")
                accepted = any(
                    e["actor"] == member["actor"] and e["kind"] in self.accepted_submission_kinds
                    for e in events
                )
                terminal = member["role"] == "supervisor" and (
                    any(e["kind"] == "finalized" for e in events)
                    or any(
                        e["kind"] == "task_finished" and e["body"]["status"] != "completed"
                        for e in events
                    )
                )
                if (
                    self.policy.evidence_contract == "typed-v1"
                    and member["role"] == "supervisor"
                    and any(e["kind"] == "finalized" for e in events)
                ):
                    raise BudgetRefused("final host receipt concludes this turn; no paid summary")
            # A separate immutable one-request grant cannot be spent on regular work.
            # Both phases still debit the same aggregate group and original cash ledger.
            acknowledgement = accepted or terminal
            step = self.step(member["actor"]) + (":ack" if acknowledgement else "")
            maximum = (
                1
                if acknowledgement
                else (
                    self.policy.supervisor_requests
                    if member["role"] == "supervisor"
                    else self.policy.worker_requests
                )
            )
            self.research.ledger.grant_step(
                step,
                self.policy.package_id,
                maximum,
                self.policy.total_requests,
                self.policy.authority,
            )
            return step

    def check_completion_reserve(self, db, step):
        """Called inside the cash reservation transaction, so concurrent requests cannot race it."""
        if self.policy.protocol == "legacy":
            return
        count = db.execute(
            "SELECT COUNT(*) FROM calls c JOIN step_grants g ON c.step=g.step WHERE g.group_id=?",
            (self.policy.package_id,),
        ).fetchone()[0]
        # Serial native tasks: protect one worker acknowledgement and one supervisor
        # acknowledgement. Worker ack consumes its slot, root ack consumes the last.
        reserved = (
            0 if step == self.step("supervisor") + ":ack" else 1 if step.endswith(":ack") else 2
        )
        if count >= self.policy.total_requests - reserved:
            raise BudgetRefused("remaining group requests reserved for terminal acknowledgements")

    @staticmethod
    def referenced(events, handle, kind):
        kinds = {
            "candidate": {"initial_candidate", "revision"},
            "finding": {"finding"},
            "review": {"case_review"},
            "inspection": {"inspection"},
        }
        if not isinstance(handle, str) or not re.fullmatch(kind + r":[1-9][0-9]*", handle):
            raise ValueError(f"use an immutable {kind}:N reference from case_board")
        entries = [e for e in events if e["kind"] in kinds[kind]]
        number = int(handle.split(":")[1])
        if number > len(entries):
            raise ValueError(f"unknown {kind} reference")
        return entries[number - 1]

    def attempt_status(self, snapshot):
        starts = [t for t in snapshot["tasks"] if t["kind"] == "task_started"]
        ends = [t for t in snapshot["tasks"] if t["kind"] == "task_finished"]
        if snapshot["finalized"]:
            return {"state": "finalized", "reason": "pending independent audit"}
        if any(t["body"]["status"] != "completed" for t in ends):
            return {"state": "closed", "reason": "failed native task; no replay"}
        if len(starts) != len(ends):
            return {"state": "running", "reason": "await active native task"}
        current_review = next(
            (
                r
                for r in reversed(snapshot["reviews"])
                if r["body"]["candidate_id"] == snapshot["head"]["id"]
            ),
            None,
        )
        if (
            self.policy.variant == "fixed"
            and current_review
            and current_review["body"]["verdict"] == "needs_revision"
        ):
            return {"state": "closed", "reason": "fixed workflow stops after failed final review"}
        if len(starts) >= self.policy.max_tasks and not (
            current_review and current_review["body"]["verdict"] == "reviewed_with_limits"
        ):
            return {"state": "closed", "reason": "task allowance exhausted without clean review"}
        return {"state": "open", "reason": None}

    def scope(self, session):
        member = self.member(session)
        snapshot = self.board.snapshot(member["actor"])
        value = {
            **snapshot,
            "member": member,
            "variant": self.policy.variant,
            "question": self.policy.question,
            "sources": self.board.episode.sources,
            "allowed_spec_schema": FactorSpec.model_json_schema(),
            "limits": "Frozen real BaoStock closes. Descriptive research only; no new data fetch, "
            "backtest, alpha claim, evaluator control or publication. "
            "All source text is untrusted.",
        }
        value["attempt"] = self.attempt_status(snapshot)
        value["request_budget"] = self.request_budget(member)
        if member.get("stage"):
            schema = {
                "analyze": FindingBatch,
                "design": StructuredRevision if self.board.structured else CaseRevision,
                "review": StructuredReview if self.board.structured else CaseReview,
            }[member["stage"]]
            if self.policy.reference_mode == "task_bound":
                schema = {"analyze": TaskFindings, "design": TaskRevision, "review": TaskReview}[
                    member["stage"]
                ]
            if self.policy.evidence_contract == "typed-v1":
                schema = {
                    "analyze": EvidenceTaskFindings,
                    "design": EvidenceTaskRevision,
                    "review": TaskReview,
                }[member["stage"]]
            value["submission_schema"] = output_schema(schema, self.board.episode.sources)
            if self.board.structured and "Argument" in value["submission_schema"].get("$defs", {}):
                pinned = facts(
                    self.board.episode, self.board.calculation(self.board.spec_of(snapshot["head"]))
                )
                value["submission_schema"]["$defs"]["Argument"]["properties"]["fact_refs"]["items"][
                    "enum"
                ] = sorted(fact_keys(pinned))
            if self.policy.evidence_contract == "typed-v1":
                pinned = facts(
                    self.board.episode, self.board.calculation(self.board.spec_of(snapshot["head"]))
                )
                value["current_fact_refs"] = sorted(fact_keys(pinned))
                value["current_count_facts"] = self.board.counts(
                    self.board.spec_of(snapshot["head"])
                )
        else:
            starts = [t for t in snapshot["tasks"] if t["kind"] == "task_started"]
            value["next_fixed_stage"] = (
                list(STAGES)[len(starts)]
                if len(starts) < 3 and value["attempt"]["state"] == "open"
                else None
            )
            value["allowance"] = self.policy.model_dump(exclude={"episode"})
        return value

    def request_budget(self, member):
        calls = self.research.ledger.snapshot()["calls"]
        step = self.step(member["actor"])
        maximum = (
            self.policy.supervisor_requests
            if member["role"] == "supervisor"
            else self.policy.worker_requests
        )
        work = sum(c["step"] == step for c in calls)
        group = sum(c["step"].startswith(f"case:{self.policy.package_id}:") for c in calls)
        return {
            "scope": "as_of_this_tool_call; not a final usage summary",
            "work_requests_max": maximum,
            "work_requests_recorded": work,
            "work_requests_remaining": max(0, maximum - work),
            "acknowledgement_requests_max": 0
            if self.policy.protocol == "legacy"
            or (self.policy.evidence_contract == "typed-v1" and member["role"] == "supervisor")
            else 1,
            "group_requests_remaining": max(0, self.policy.total_requests - group),
            "instruction": "Plan evidence reads and submission within work requests. "
            "Use complete inline evidence; multiple case_read calls may share one response. "
            "After acceptance end on the reserved acknowledgement; do not perform new work.",
        }

    def resources(self, snapshot):
        resources = {"source:" + key: text for key, text in self.board.episode.sources.items()}
        for key in ("versions", "findings", "reviews", "tasks", "inspections"):
            resources.update({"event:" + event["id"]: event for event in snapshot[key]})
        if "structured_report" in snapshot:
            resources["report:" + snapshot["head"]["id"]] = snapshot["structured_report"]
        if "prose_proof" in snapshot:
            resources["check:" + snapshot["head"]["id"]] = snapshot["prose_proof"]
        return resources

    def view(self, session, *, worker=False):
        scope = self.scope(session)
        resources = self.resources(scope)
        limit = self.policy.worker_prompt_bytes if worker else self.policy.max_tool_bytes
        # No full task traces or duplicated version bodies in the model's status view.
        value = {
            k: v
            for k, v in scope.items()
            if k
            not in (
                "sources",
                "head",
                "versions",
                "findings",
                "reviews",
                "tasks",
                "inspections",
                "structured_report",
            )
        }
        for key in ("head", "versions", "findings", "reviews", "tasks", "inspections"):
            values = [scope[key]] if key == "head" else scope[key]
            refs = [
                {
                    **reference("event:" + e["id"], e, self.policy.page_chars),
                    "id": e["id"],
                    "kind": e["kind"],
                    "actor": e["actor"],
                }
                for e in values
            ]
            if self.policy.reference_mode == "task_bound":
                for index, ref in enumerate(refs):
                    ref["event_ref"] = f"event:{values[index]['sequence']}"
                    if key in ("head", "versions"):
                        number = next(
                            i for i, e in enumerate(scope["versions"], 1) if e["id"] == ref["id"]
                        )
                        ref["candidate_ref"] = f"candidate:{number}"
                    elif key in ("findings", "reviews"):
                        ref["finding_ref" if key == "findings" else "review_ref"] = (
                            f"finding:{index + 1}" if key == "findings" else f"review:{index + 1}"
                        )
            value[key] = refs[0] if key == "head" else refs
        value["sources"] = [
            reference("source:" + k, v, self.policy.page_chars)
            for k, v in self.board.episode.sources.items()
        ]
        if "prose_proof" in scope:
            proof = scope["prose_proof"]
            value["prose_proof"] = {
                **reference("check:" + scope["head"]["id"], proof, self.policy.page_chars),
                "recognized_prose_ok": proof["recognized_prose_ok"],
                "issue_count": len(proof["issues"]),
            }
        if "structured_report" in scope:
            report = scope["structured_report"]
            value["structured_report"] = {
                **reference("report:" + scope["head"]["id"], report, self.policy.page_chars),
                "report_sha256": report["sha256"],
            }
        value["reporting_contract"] = (
            "structured-v3: use inspection_id and facts_sha256 instead of "
            "copying numbers/spec/counts. "
            "Qualitative hypothesis/rationale have text plus fact_refs "
            "(units, timing, scope, spec or metric IDs). "
            "No digits in qualitative text/decision reasons/resolutions; "
            "numeric source quotes are allowed. "
            "Reviewer must read the complete structured_report and bind its report_sha256. "
            "Checks are enums; do not restate computed values. "
            "Host supplies all standard limitations. "
            "Read the whole candidate, including decisions and cited source interpretation; "
            "hashes alone "
            "do not establish semantic validity. Any further claim in chat is unreviewed."
            if self.board.structured
            else "Use the supplied submission schema."
        )
        if self.policy.reference_mode == "task_bound":
            value["reporting_contract"] += (
                " Task-bound references: candidate_id/parent_id='assigned' means the immutable "
                "candidate delivered to this task, never whichever candidate is globally latest. "
                "Use inspection_id='inspection:N' from your own receipt "
                "and facts_sha256='inspection'. "
                "Review uses report_sha256='assigned', binding the complete report "
                "delivered to you. "
                "Host resolves these labels to exact hashes and refuses stale tasks. "
                "Do not copy source/event/episode hashes into submission references. "
                "Only enumerated fact_refs are valid; a review issue is a defect, "
                "not a disclosed caveat. "
                "Decisions use finding:N references from the finding list. For repairs use "
                "basis_review_id='failed_assigned_review'; otherwise null. Supervisor delegates "
                "using finding:N/review:N basis_ids and finalizes with candidate:N and review:N. "
                "For paging, case_read accepts the event_ref or finding/review/candidate handle. "
                "These handles name immutable entries within this case; "
                "the ledger stores full hashes."
            )
        if self.policy.evidence_contract == "typed-v1":
            value["current_fact_refs"] = scope.get("current_fact_refs", [])
            value["current_count_facts"] = scope.get("current_count_facts", {})
            value["reporting_contract"] += (
                " typed-v1: Findings use current_fact_refs and qualitative statements; no numeric "
                "copies or count equations. The host counts warmup exclusions separately from "
                "closes required per signal. Every inspection includes exact comparisons against "
                "the assigned candidate, with named SD measure and paired or separate observation "
                "cohort. Include chosen comparison_refs in the revision, or [] if unused. "
                "Changed-score counts exclude floating-point noise (relative tolerance 1e-10, "
                "absolute tolerance 1e-12); eligibility changes always count. "
                "Host renders comparative results; qualitative text and decisions explain "
                "motivation and uncertainty, not measured increases/decreases. Finalization "
                "concludes the supervisor turn natively with settled team usage; no model summary."
            )
        value["read_instruction"] = (
            "Inline values are complete. Read every needed non-inline resource with case_read; "
            "concatenate all its pages. Event IDs and source hashes pin immutable content. "
            "Do not infer omitted content from a reference."
        )
        value["completion_allowance"] = (
            "Work requests and one terminal acknowledgement per actor are separate; "
            "both count toward the aggregate. After accepted submission end briefly; "
            "no additional work tools."
        )
        if self.policy.evidence_contract == "typed-v1":
            value["completion_allowance"] = (
                "Workers have one reserved acknowledgement after acceptance. Supervisor "
                "finalization concludes its native turn with host-rendered settled usage; "
                "no additional paid supervisor acknowledgement. All calls share the group cap."
            )
        if len(encoded(value)) > limit:
            raise ValueError("case manifest exceeds tool bound")
        # Prefer the exact artifact/review over historical versions. Include full sources
        # and peer findings when they fit; large resources remain accessible by pages.
        refs = [
            *([value["structured_report"]] if "structured_report" in value else []),
            value["head"],
            *([value["prose_proof"]] if "prose_proof" in value else []),
            *reversed(value["reviews"]),
            *value["findings"],
            *value["sources"],
            *value["inspections"],
        ]
        for ref in refs:
            ref["inline"] = resources[ref["resource_id"]]
            if len(encoded(value)) > limit:
                del ref["inline"]
        return value

    def read(self, session, resource_id, number):
        resources = self.resources(self.scope(session))
        if self.policy.reference_mode == "task_bound":
            with self.board.locked() as events:
                if re.fullmatch(r"event:[1-9][0-9]{0,4}", resource_id):
                    event = next((e for e in events if e["sequence"] == int(resource_id[6:])), None)
                    if event is None:
                        raise ValueError("unknown event reference")
                    resource_id = "event:" + event["id"]
                elif re.fullmatch(r"(?:candidate|finding|review):[1-9][0-9]{0,4}", resource_id):
                    event = self.referenced(events, resource_id, resource_id.split(":")[0])
                    resource_id = "event:" + event["id"]
        if resource_id not in resources:
            raise ValueError("unknown authorized case resource")
        value = page(resource_id, resources[resource_id], number, self.policy.page_chars)
        value["request_budget"] = self.request_budget(self.member(session))
        if len(encoded(value)) > self.policy.max_tool_bytes:
            raise ValueError("case page exceeds tool bound")
        return value

    def begin(self, session, stage, task, basis_ids):
        if self.member(session)["role"] != "supervisor" or stage not in STAGES:
            raise ValueError("only supervisor can delegate a case stage")
        if not isinstance(task, str) or len(task) > 6000 or not task.strip():
            raise ValueError("bounded nonempty assignment required")
        with self.board.locked() as events:
            self.board._open(events)
            if self.policy.reference_mode == "task_bound":
                if not isinstance(basis_ids, list):
                    raise ValueError("basis_ids must be a list of finding/review references")
                basis_ids = [
                    self.referenced(
                        events, ref, "finding" if str(ref).startswith("finding:") else "review"
                    )["id"]
                    for ref in basis_ids
                ]
            starts = [e for e in events if e["kind"] == "task_started"]
            finishes = {e["body"]["child_id"] for e in events if e["kind"] == "task_finished"}
            if any(e["body"]["child_id"] not in finishes for e in starts):
                raise ValueError("wait for the active native task")
            if any(
                e["kind"] == "task_finished" and e["body"]["status"] != "completed" for e in events
            ):
                raise ValueError("a failed native task closes this bounded attempt")
            if len(starts) >= self.policy.max_tasks:
                raise ValueError("case task allowance exhausted")
            if not starts and stage != "analyze":
                raise ValueError("first task must analyze the source evidence")
            if self.policy.variant == "fixed":
                if len(starts) >= 3 or stage != list(STAGES)[len(starts)]:
                    raise ValueError(
                        "fixed workflow requires analyze then design then review; no follow-up"
                    )
                task = STAGES[stage]
            elif starts:
                available = {e["id"] for e in events if e["kind"] in ("finding", "case_review")}
                if not basis_ids or set(basis_ids) - available:
                    raise ValueError("adaptive follow-up must cite observed findings or a review")
            head = self.board._head(events)
            if stage == "review" and head["kind"] != "revision":
                raise ValueError("final reviewer needs a designer artifact")
            role = "author" if stage == "design" else "reviewer"
            actor, child = f"{role}-{len(starts) + 1}", f"qfh-case-{uuid.uuid4()}"
            member = {"session_id": child, "actor": actor, "role": role, "stage": stage}
            if self.policy.reference_mode == "task_bound":
                member["assigned_candidate_id"] = head["id"]
            atomic_new(self._binding_path(child), member)
            event = self.board._append(
                events,
                "supervisor",
                "task_started",
                {
                    "actor": actor,
                    "child_id": child,
                    "stage": stage,
                    "role": role,
                    "assignment": task,
                    "basis_ids": basis_ids if self.policy.variant == "adaptive" else [],
                    "output_id": head["id"],
                },
            )
        self.admit(child)
        return {
            "child_id": child,
            "actor": actor,
            "assignment": task,
            "route": {"model": self.route.model, "reasoning_effort": self.route.reasoning_effort},
            "prompt": json.dumps(
                {
                    "task_id": event["id"],
                    "assignment": task,
                    "scope": self.view(child, worker=True),
                    "instructions": STAGES[stage]
                    + " Submit the exact submission_schema with the assigned tool. "
                    "Citations contain decoded literal source text, not extra JSON backslashes. "
                    "Keep observations distinct from optional research hypotheses; claims of "
                    "necessity, exclusivity or improved comparability need evidence. "
                    "Read non-inline sources/artifacts with case_read before using them. "
                    "After acceptance the one reserved acknowledgement is only to end briefly; "
                    "correct rejected JSON inside the work allowance. "
                    "Never invent metrics. The supplied prices and complete snapshot summaries "
                    "are the only sources.",
                },
                ensure_ascii=False,
            ),
        }

    def inspect(self, session, raw):
        member = self.member(session)
        spec = FactorSpec.model_validate_json(raw)
        with self.board.locked() as events:
            self.board._open(events)
            if any(
                e["actor"] == member["actor"] and e["kind"] in self.accepted_submission_kinds
                for e in events
            ):
                raise ValueError("accepted worker must acknowledge and end; no further inspections")
            if sum(e["kind"] == "inspection" for e in events) >= self.policy.max_inspections:
                raise ValueError("factor inspection allowance exhausted")
            own_number = (
                sum(e["kind"] == "inspection" and e["actor"] == member["actor"] for e in events) + 1
            )
            calc = self.board.calculation(spec)
            extra = {}
            if self.policy.evidence_contract == "typed-v1":
                head = self.board._head(events)
                if member.get("assigned_candidate_id") != head["id"]:
                    raise ValueError("inspection requires the current assigned candidate")
                extra = {
                    "comparison_parent_id": head["id"],
                    "comparisons": comparisons(
                        self.board.calculation(self.board.spec_of(head)), calc
                    ),
                }
            event = self.board._append(
                events,
                member["actor"],
                "inspection",
                {**{k: v for k, v in calc.items() if k != "rows"}, **extra},
            )
            atomic_new(self.directory / f"calculation-{event['id']}.json", calc)
        return {
            "inspection_id": event["id"],
            **(
                {"inspection_ref": f"inspection:{own_number}"}
                if self.policy.reference_mode == "task_bound"
                else {}
            ),
            **event["body"],
            **(
                {
                    "comparison_refs": [
                        f"inspection:{own_number}/{key}" for key in extra["comparisons"]
                    ]
                }
                if extra
                else {}
            ),
            "count_facts": self.board.counts(spec),
            **(
                {
                    "facts": facts(self.board.episode, calc),
                    "facts_sha256": digest(facts(self.board.episode, calc)),
                }
                if self.board.structured
                else {}
            ),
        }

    def finish(self, session, child, result):
        report = super().finish(session, child, result)
        # Keep native receipt first and small; the complete board remains immutable.
        return {
            "task": report["task"],
            "attempt": self.attempt_status(report["board"]),
            "head_id": report["board"]["head"]["id"],
            "instruction": "Read case_board for current artifacts and sources.",
        }

    def resolve_references(self, member, op, raw):
        schema = {"findings": TaskFindings, "revise": TaskRevision, "review": TaskReview}[op]
        if self.policy.evidence_contract == "typed-v1":
            schema = {
                "findings": EvidenceTaskFindings,
                "revise": EvidenceTaskRevision,
                "review": TaskReview,
            }[op]
        value = schema.model_validate_json(raw).model_dump()
        with self.board.locked() as events:
            self.board._open(events)
            target = member["assigned_candidate_id"]
            head = self.board._head(events)
            task = next(
                e
                for e in events
                if e["kind"] == "task_started" and e["body"]["child_id"] == member["session_id"]
            )
            if head["id"] != target or task["body"]["output_id"] != target:
                raise ValueError("assigned candidate is stale; no retargeting is allowed")
            resolved = {"candidate_id": target}
            if op == "findings":
                for finding in value["findings"]:
                    finding["candidate_id"] = target
            elif op == "revise":
                own = [
                    e for e in events if e["kind"] == "inspection" and e["actor"] == member["actor"]
                ]
                index = int(value["inspection_id"].split(":")[1]) - 1
                if index >= len(own):
                    raise ValueError("inspection reference is not an inspection by this task")
                inspected = own[index]
                if self.policy.evidence_contract == "typed-v1":
                    resolved_refs = []
                    for ref in value["comparison_refs"]:
                        match = re.fullmatch(r"inspection:([1-6])/(.+)", ref)
                        if not match or int(match[1]) > len(own):
                            raise ValueError("use a comparison_ref from your inspection receipt")
                        resolved_refs.append(own[int(match[1]) - 1]["id"] + "/" + match[2])
                    value["comparison_refs"] = resolved_refs
                    resolved["comparison_refs"] = resolved_refs
                for decision in value["decisions"]:
                    decision["finding_id"] = self.referenced(
                        events, decision["finding_id"], "finding"
                    )["id"]
                if value["basis_review_id"] is not None:
                    failed = [
                        e
                        for e in events
                        if e["kind"] == "case_review"
                        and e["body"]["candidate_id"] == target
                        and e["body"]["verdict"] == "needs_revision"
                    ]
                    if len(failed) != 1:
                        raise ValueError("assigned candidate has no unique failed review")
                    value["basis_review_id"] = failed[0]["id"]
                pinned = facts(
                    self.board.episode,
                    self.board.calculation(FactorSpec.model_validate(inspected["body"]["spec"])),
                )
                value.update(
                    parent_id=target, inspection_id=inspected["id"], facts_sha256=digest(pinned)
                )
                resolved.update(
                    inspection_id=value["inspection_id"],
                    facts_sha256=value["facts_sha256"],
                    decision_finding_ids=[d["finding_id"] for d in value["decisions"]],
                    basis_review_id=value["basis_review_id"],
                )
            else:
                value.update(
                    candidate_id=target, report_sha256=self.board.report(head, events)["sha256"]
                )
                resolved["report_sha256"] = value["report_sha256"]
            self.board._append(
                events,
                member["actor"],
                "submission_bound",
                {
                    "op": op,
                    "task_id": task["id"],
                    "raw_payload_sha256": digest(json.loads(raw)),
                    "resolved_references": resolved,
                    "mode": "task_bound",
                    "authority": "Host resolves declared task labels; never rewrites model "
                    "research content or retargets stale work.",
                },
            )
        return json.dumps(value)

    def submit(self, session, op, payload):
        member = self.member(session)
        expected = {"analyze": "findings", "design": "revise", "review": "review"}
        if expected.get(member.get("stage")) != op:
            raise ValueError("submission tool does not match the assigned native stage")
        with self.board.locked() as events:
            if any(
                e["kind"] == "task_finished" and e["body"]["child_id"] == session for e in events
            ):
                raise ValueError("worker already finished")
            if any(
                e["actor"] == member["actor"] and e["kind"] in self.accepted_submission_kinds
                for e in events
            ):
                raise ValueError("worker already submitted")
        raw_payload = payload
        try:
            if self.policy.reference_mode == "task_bound":
                payload = self.resolve_references(member, op, payload)
            if op == "findings":
                batch = (
                    EvidenceFindings
                    if self.policy.evidence_contract == "typed-v1"
                    else FindingBatch
                ).model_validate_json(payload)
                for f in batch.findings:
                    if self.board.structured and (issue := universe_unit_issue(f.statement)):
                        raise ValueError(issue)
                    if self.board.structured:
                        issues = prose_checks({"statement": f.statement}, {})["issues"]
                        if self.policy.evidence_contract == "typed-v1":
                            head = self.board.snapshot(member["actor"])["head"]
                            issues += finding_issues(
                                f,
                                facts(
                                    self.board.episode,
                                    self.board.calculation(self.board.spec_of(head)),
                                ),
                            )
                        if issues:
                            raise ValueError("finding issues: " + json.dumps(issues))
                    self.board._citations(f.citations)
                    if f.candidate_id != self.board.snapshot(member["actor"])["head"]["id"]:
                        raise ValueError("findings must target the current candidate")
                with self.board.locked() as events:
                    self.board._open(events)
                    current = self.board._head(events)["id"]
                    prior = {e["id"]: e for e in events if e["kind"] == "finding"}
                    if len(prior) + len(batch.findings) > self.board.episode.policy.max_findings:
                        raise ValueError("finding allowance exhausted")
                    if len(events) + len(batch.findings) + 1 > self.board.episode.policy.max_events:
                        raise ValueError("board event allowance exhausted")
                    for f in batch.findings:
                        self.board._text_bounds(f.model_dump())
                        if f.candidate_id != current or any(
                            i not in prior or prior[i]["body"]["candidate_id"] != current
                            for i in f.contradicts
                        ):
                            raise ValueError("finding or conflict references a different candidate")
                    findings = []
                    for f in batch.findings:
                        entry = self.board._append(
                            events, member["actor"], "finding", f.model_dump()
                        )
                        events.append(entry)
                        findings.append(entry)
                    event = self.board._append(
                        events,
                        member["actor"],
                        "finding_batch",
                        {"finding_ids": [f["id"] for f in findings]},
                    )
            elif op == "revise":
                structured = (
                    (
                        EvidenceRevision
                        if self.policy.evidence_contract == "typed-v1"
                        else StructuredRevision
                    ).model_validate_json(payload)
                    if self.board.structured
                    else None
                )
                if structured:
                    with self.board.locked() as events:
                        inspected = next(
                            (
                                e
                                for e in events
                                if e["kind"] == "inspection"
                                and e["id"] == structured.inspection_id
                                and e["actor"] == member["actor"]
                            ),
                            None,
                        )
                    if inspected is None:
                        raise ValueError(
                            "designer inspection ID missing or belongs to another actor"
                        )
                    spec = FactorSpec.model_validate(inspected["body"]["spec"])
                    revision = CaseRevision(
                        parent_id=structured.parent_id,
                        spec=spec,
                        hypothesis=structured.hypothesis.text,
                        rationale=structured.rationale.text,
                        decisions=structured.decisions,
                        citations=structured.citations,
                        limitations=LIMITS,
                        count_claims=self.board.counts(spec),
                        basis_review_id=structured.basis_review_id,
                        issue_resolutions=structured.issue_resolutions,
                    )
                else:
                    revision = CaseRevision.model_validate_json(payload)
                with self.board.locked() as events:
                    if not any(
                        e["kind"] == "inspection"
                        and e["actor"] == member["actor"]
                        and e["body"]["spec"] == revision.spec.model_dump()
                        for e in events
                    ):
                        raise ValueError(
                            "designer must inspect the exact chosen specification first"
                        )
                event = self.board.revision(member["actor"], revision, structured=structured)
            else:
                structured = (
                    StructuredReview.model_validate_json(payload) if self.board.structured else None
                )
                review = (
                    CaseReview(
                        candidate_id=structured.candidate_id,
                        verdict=structured.verdict,
                        checks=structured.checks,
                        issues=structured.issues,
                        citations=structured.citations,
                        limitations=LIMITS,
                    )
                    if structured
                    else CaseReview.model_validate_json(payload)
                )
                event = self.board.final_review(member["actor"], review, structured=structured)
            return {"status": "accepted", "artifact": event}
        except ValueError as error:
            with self.board.locked() as events:
                self.board._append(
                    events,
                    member["actor"],
                    "submission_rejected",
                    {"op": op, "payload": raw_payload, "error": str(error)[:4000]},
                )
            return {"status": "rejected", "error": str(error)[:4000]}

    def finalize(self, session, output_id, review_id):
        usage = None
        if self.policy.evidence_contract == "typed-v1":
            from qfh.case_usage import settled_usage

            usage = settled_usage(self)
        if self.policy.reference_mode == "task_bound":
            with self.board.locked() as events:
                output_id = self.referenced(events, output_id, "candidate")["id"]
                review_id = self.referenced(events, review_id, "review")["id"]
        result = super().finalize(session, output_id, review_id)
        result.pop("output", None)
        if self.board.structured:
            scope = self.board.snapshot("supervisor")
            report = scope["structured_report"]
            atomic_new(self.directory / "FINAL_REPORT.json", report)
            result["report_reference"] = {
                "sha256": report["sha256"],
                "resource_id": "report:" + output_id,
            }
            result["report_text"] = render(report, review_id)
        result["instruction"] = (
            "Return only the candidate ID and pending independent audit status. "
            "Do not add a new unreviewed narrative or a performance claim."
        )
        if usage is not None:
            from qfh.case_usage import render_usage

            atomic_new(self.directory / "FINAL_USAGE.json", usage)
            result["settled_team_usage"] = usage
            result["report_text"] += "\n\n" + render_usage(usage)
            result["conclude_turn"] = True
            result["instruction"] = (
                "Host final receipt concludes the native turn; no model summary."
            )
        return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--private", type=Path, required=True)
    parser.add_argument("--package", type=Path, required=True)
    args = parser.parse_args()
    try:
        request = json.load(sys.stdin)
        host = CaseResearch(args.config, args.private, args.package)
        session, op, body = request["session_id"], request["op"], request.get("args", {})
        if op == "scope":
            result = host.view(session)
        elif op == "read":
            result = host.read(session, body["resource_id"], body.get("page", 0))
        elif op == "begin":
            result = host.begin(session, body["stage"], body["task"], body["basis_ids"])
        elif op == "finish":
            result = host.finish(session, body["child_id"], body["result"])
        elif op == "inspect":
            result = host.inspect(session, body["json"])
        elif op in ("findings", "revise", "review"):
            result = host.submit(session, op, body["json"])
            if result["status"] == "accepted":
                event = result["artifact"]
                result = {
                    "status": "accepted",
                    "artifact": {"id": event["id"], "kind": event["kind"]},
                    "instruction": "End briefly now. "
                    "The reserved next request is acknowledgement only.",
                }
        elif op == "finalize":
            result = host.finalize(session, body["output_id"], body["review_id"])
        else:
            raise ValueError("unknown case operation")
        print(json.dumps({"ok": True, "result": result}))
    except (ValueError, KeyError, OSError) as error:
        print(json.dumps({"ok": False, "error": str(error)}))


if __name__ == "__main__":
    main()
