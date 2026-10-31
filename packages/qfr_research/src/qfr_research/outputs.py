"""Structured outputs of the research agents (PLAN Section 11.4).

Every field is required unless noted. These models are the agents' only way to hand
work back: the workflow validates them and writes the blackboard itself.
"""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Text = Annotated[str, StringConstraints(min_length=1, max_length=2000)]
Short = Annotated[str, StringConstraints(min_length=1, max_length=200)]
IslandId = Literal["I1", "I2", "I3", "I4", "I5", "I6"]
Sign = Literal[-1, 1]
Horizon = Literal[1, 5, 10, 20]
Score = Annotated[float, Field(ge=0, le=1)]
TaskType = Literal[
    "explore", "llm_mutation", "crossover", "repair", "syntactic_batch", "compose_strategy"
]


class Output(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Hypothesis(Output):
    title: Short
    observation: Text = Field(description="A generic pattern; never tickers, dates or events.")
    mechanism: Text = Field(description="Why it should persist.")
    expected_sign: Sign
    horizon_days: Horizon
    fields_required: list[Short] = Field(min_length=1)
    falsification: Text
    novelty_note: Text = Field(description="What is new relative to the similar hypotheses.")
    risks: Text
    island_id: IslandId
    tags: list[Short]


class HypothesisBatch(Output):
    hypotheses: list[Hypothesis] = Field(min_length=1, max_length=3)


class CandidateDraft(Output):
    hypothesis_id: UUID | None = Field(
        description="The hypothesis this draft implements (null only for repair tasks)."
    )
    expression: Annotated[str, StringConstraints(min_length=1, max_length=1000)]
    description: Text = Field(description="Maps each part of the expression to the mechanism.")
    expected_sign: Sign
    horizon_days: Horizon
    parameter_rationale: Text = Field(description="Why these windows.")
    operator: Literal["explore", "llm_mutation", "crossover", "repair"]
    parent_version_ids: list[UUID]
    change_summary: Text | None = Field(default=None, description="Required with a parent.")

    @model_validator(mode="after")
    def parent_change(self) -> Self:
        if self.parent_version_ids and not self.change_summary:
            raise ValueError("a draft with a parent needs a change_summary")
        return self


class EngineerOutput(Output):
    drafts: list[CandidateDraft] = Field(min_length=1, max_length=3)


class StrategyComponent(Output):
    version_id: UUID
    sign: Sign
    weight: float = Field(gt=0, multiple_of=0.01)


class StrategyPortfolio(Output):
    top_k: int = Field(ge=20, le=100)
    dropout: int = Field(ge=1, le=20)


class StrategyDraft(Output):
    components: list[StrategyComponent] = Field(min_length=1, max_length=8)
    portfolio: StrategyPortfolio
    composition_rationale: Text
    expected_horizon_days: Horizon
    parent_version_ids: list[UUID]
    change_summary: Text | None = None

    @model_validator(mode="after")
    def distinct(self) -> Self:
        ids = [c.version_id for c in self.components]
        if len(ids) != len(set(ids)):
            raise ValueError("components must name distinct versions")
        return self


class ReviewVerdict(Output):
    verdict: Literal["approve", "revise", "reject"]
    c1: Score = Field(description="Hypothesis-to-description alignment.")
    c2: Score = Field(description="Description-to-expression alignment.")
    plausibility: Score
    parsimony: Score
    originality: Score
    lookahead_risk: Score = Field(description="Lookahead or snooping risk; higher is riskier.")
    required_changes: list[Text] = Field(description="Mandatory for revise.")
    rationale: Text

    @model_validator(mode="after")
    def changes(self) -> Self:
        if self.verdict == "revise" and not self.required_changes:
            raise ValueError("a revise verdict lists its required changes")
        return self


class Implication(Output):
    hypothesis_id: UUID
    effect: Literal["supported", "weakened"]


class ReportInterpretation(Output):
    report_ids: list[UUID] = Field(min_length=1)
    what_was_tested: Text
    observed: Text = Field(description="Restates only released values.")
    diagnosis: Text = Field(description="Likely causes, labelled as conjecture.")
    implications: list[Implication]
    next_steps: list[Text] = Field(max_length=3)
    confidence: Literal["low", "medium", "high"]
    caveats: list[Text] = Field(min_length=1)

    @model_validator(mode="after")
    def acknowledges_limits(self) -> Self:
        text = " ".join(self.caveats).lower()
        if "coarsen" not in text or "multiple" not in text:
            raise ValueError("caveats must acknowledge coarsening and multiple testing")
        return self


class KnowledgeItem(Output):
    kind: Literal["failure_mode", "insight", "anti_pattern"]
    statement: Text
    evidence_report_ids: list[UUID] = Field(min_length=1)
    tags: list[Short]


class AnalystOutput(Output):
    interpretation: ReportInterpretation
    knowledge_items: list[KnowledgeItem] = Field(max_length=3)


class InterpretationChallenge(Output):
    interpretation_id: UUID
    issues: list[Text]
    verdict: Literal["accept", "amend"]
    amended_text: Text | None = None

    @model_validator(mode="after")
    def amendment(self) -> Self:
        if self.verdict == "amend" and not self.amended_text:
            raise ValueError("an amend verdict carries the amended text")
        return self


class PlanTask(Output):
    type: TaskType
    island_id: IslandId
    brief: Text
    parent_version_ids: list[UUID]
    hypothesis_id: UUID | None = None
    max_candidates: int = Field(ge=1, le=3)


class IslandPause(Output):
    island_id: IslandId
    reason: Text


class GenerationPlan(Output):
    objectives: list[Text] = Field(min_length=1)
    allocations: dict[IslandId, int]
    allocation_reasons: dict[IslandId, Text] = Field(
        description="A reason for every island whose allocation differs from the proposal."
    )
    tasks: list[PlanTask] = Field(min_length=1)
    islands_to_pause: list[IslandPause]
    rationale: Text
