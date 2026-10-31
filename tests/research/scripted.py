"""Scripted LLM scenarios (P4.12): PydanticAI FunctionModels that answer each research role
deterministically from the prompt, so a whole generation runs offline.

Nothing here reaches a provider: ScriptedModels is the ModelSource the research env uses
in tests, and the test session forbids real model requests (tests/research/conftest.py).
The expressions an engineer drafts are given by each test; there is no default.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any

from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from qfr_research.providers import ModelRef
from qfr_research.settings import ResearchConfig

UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
CAVEATS = [
    "Released values are coarsened, so small differences are not meaningful.",
    "Multiple testing: many candidates were tried in this family and program.",
]


@dataclass
class Script:
    """What the scripted roles answer. Each test names its own expressions."""

    expressions: list[tuple[str, int]]
    critic_verdicts: list[str] = field(default_factory=list)  # consumed in order, then approve
    candidates_per_task: int = 2
    engineer_uses_tool: bool = True
    strategy_top_k: int = 20  # the scripted strategy's portfolio, in strategy mode
    failing: set[str] = field(default_factory=set)  # "provider/model" refs that answer 503
    balance: dict[str, Any] = field(default_factory=lambda: {"available_balance": 50.0})
    calls: list[dict[str, Any]] = field(default_factory=list)

    def roles(self) -> list[str]:
        return [c["role"] for c in self.calls]


def priced(config: ResearchConfig) -> ResearchConfig:
    """The shipped configuration with test prices and a Moonshot concurrency limit. The
    shipped providers.yaml has no prices, so no model there may run until the owner sets
    them (the no-price-no-run rule)."""
    from dataclasses import replace

    from qfr_core.config import ProvidersConfig

    raw = config.providers.model_dump(mode="json")
    for profile in raw["providers"].values():
        for model in profile["models"].values():
            prices = model["price_cny_per_mtok"]
            for key in prices:
                prices[key] = {"in_miss": 2.0, "in_hit": 0.5, "cache_write": 2.0, "out": 8.0}.get(
                    key, prices[key]
                )
    raw["providers"]["kimi"]["account"] = {"concurrency_limit": 8}
    return replace(config, providers=ProvidersConfig.model_validate(raw))


def prompt_text(messages: list[ModelMessage]) -> str:
    parts = []
    for message in messages:
        if isinstance(message, ModelRequest):
            for part in message.parts:
                if isinstance(part, UserPromptPart) and isinstance(part.content, str):
                    parts.append(part.content)
    return "\n".join(parts)


def tool_returns(messages: list[ModelMessage], name: str) -> list[Any]:
    return [
        part.content
        for message in messages
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, ToolReturnPart) and part.tool_name == name
    ]


def answer(info: AgentInfo, value: dict[str, Any]) -> ModelResponse:
    """Structured output through the output tool, or JSON text in prompted mode."""
    if info.output_tools:
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, value)])
    return ModelResponse(parts=[TextPart(json.dumps(value))])


class ScriptedModels:
    """A ModelSource: one FunctionModel per role and model reference."""

    def __init__(self, config: ResearchConfig, script: Script) -> None:
        self.config, self.script = config, script

    def model(self, role: str, ref: ModelRef) -> FunctionModel:
        def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            return self.respond(role, ref, messages, info)

        return FunctionModel(respond, model_name=ref.model_id)

    async def list_models(self, provider: str) -> list[str]:
        return sorted(self.config.providers.providers[provider].models)  # type: ignore[index]

    async def balance(self, provider: str) -> dict[str, Any]:
        return dict(self.script.balance) if provider == "kimi" else {}

    # Answers ---------------------------------------------------------------------------

    def respond(
        self, role: str, ref: ModelRef, messages: list[ModelMessage], info: AgentInfo
    ) -> ModelResponse:
        text = prompt_text(messages)
        self.script.calls.append({"role": role, "model": str(ref)})
        if str(ref) in self.script.failing:
            raise ModelHTTPError(503, ref.model_id, {"error": "scripted outage"})
        schema = info.output_tools[0].parameters_json_schema if info.output_tools else {}
        if set(schema.get("properties", {})) == {"ok", "token"} or "connectivity check" in text:
            return answer(info, {"ok": True, "token": "qfr"})
        handler = getattr(self, f"_{role}")
        result: ModelResponse = handler(text, messages, info)
        return result

    def _supervisor(self, text: str, messages: list[ModelMessage], info: AgentInfo) -> Any:
        line = text.split("Proposal:\n", 1)[1].split("\n", 1)[0]
        proposal = json.loads(line)
        tasks = [
            {
                "type": "explore",
                "island_id": island,
                "brief": "Explore one mechanism for the island's theme.",
                "parent_version_ids": [],
                "hypothesis_id": None,
                "max_candidates": min(3, self.script.candidates_per_task),
            }
            for island in proposal["islands"]
        ]
        # Strategy modes: the compose_strategy tasks the engine proposed, unchanged.
        tasks += [t for t in proposal["tasks"] if t["type"] == "compose_strategy"]
        return answer(
            info,
            {
                "objectives": ["Test one mechanism per island."],
                "allocations": proposal["allocations"],
                "allocation_reasons": {},
                "tasks": tasks,
                "islands_to_pause": [],
                "rationale": "Follow the proposal with fewer candidates per task.",
            },
        )

    def _hypothesis(self, text: str, messages: list[ModelMessage], info: AgentInfo) -> Any:
        island = re.search(r"Island: (I\d)", text)
        return answer(
            info,
            {
                "hypotheses": [
                    {
                        "title": "Short-horizon overreaction reverses",
                        "observation": "Large recent moves tend to partially reverse.",
                        "mechanism": "Liquidity provision is rewarded after overreaction.",
                        "expected_sign": 1,
                        "horizon_days": 5,
                        "fields_required": ["close"],
                        "falsification": "No reversal after large moves out of sample.",
                        "novelty_note": "First hypothesis on this island.",
                        "risks": "Crowding and transaction costs.",
                        "island_id": island.group(1) if island else "I6",
                        "tags": ["reversal"],
                    }
                ]
            },
        )

    def _engineer(self, text: str, messages: list[ModelMessage], info: AgentInfo) -> Any:
        if "working in strategy mode" in text:
            return self._strategy(text, info)
        tools = {t.name for t in info.function_tools}
        expressions = self.script.expressions
        if (
            self.script.engineer_uses_tool
            and "dsl_validate" in tools
            and not tool_returns(messages, "dsl_validate")
        ):
            return ModelResponse(
                parts=[ToolCallPart("dsl_validate", {"expression": expressions[0][0]})]
            )
        found = re.search(rf"hypothesis_id ({UUID})", text)
        limit = re.search(r"into 1 to (\d+) qfr-dsl", text)
        count = int(limit.group(1)) if limit else 1
        drafts = [
            {
                "hypothesis_id": found.group(1) if found else None,
                "expression": expression,
                "description": "Each part maps to the reversal mechanism.",
                "expected_sign": sign,
                "horizon_days": 5,
                "parameter_rationale": "A one-week window matches the horizon.",
                "operator": "explore",
                "parent_version_ids": [],
                "change_summary": None,
            }
            for expression, sign in expressions[:count]
        ]
        return answer(info, {"drafts": drafts})

    def _strategy(self, text: str, info: AgentInfo) -> Any:
        """A StrategyDraft over every listed component, equally weighted."""
        listed = text.split("Available factor versions", 1)[1]
        most = re.search(r"from at most (\d+) published factor versions", text)
        ids = list(dict.fromkeys(re.findall(rf'"version_id": ?"({UUID})"', listed)))
        ids = ids[: int(most.group(1))] if most else ids
        assert ids, "the strategy prompt lists its components"
        weight = round(1 / len(ids), 2)
        return answer(
            info,
            {
                "components": [{"version_id": v, "sign": 1, "weight": weight} for v in ids],
                "portfolio": {"top_k": self.script.strategy_top_k, "dropout": 5},
                "composition_rationale": "Equal weights over the listed components.",
                "expected_horizon_days": 5,
                "parent_version_ids": ids,
                "change_summary": None,
            },
        )

    def _critic(self, text: str, messages: list[ModelMessage], info: AgentInfo) -> Any:
        verdict = self.script.critic_verdicts.pop(0) if self.script.critic_verdicts else "approve"
        return answer(
            info,
            {
                "verdict": verdict,
                "c1": 0.8,
                "c2": 0.8,
                "plausibility": 0.7,
                "parsimony": 0.8,
                "originality": 0.6,
                "lookahead_risk": 0.1,
                "required_changes": ["Use a shorter window."] if verdict == "revise" else [],
                "rationale": "The expression implements the hypothesis.",
            },
        )

    def _analyst(self, text: str, messages: list[ModelMessage], info: AgentInfo) -> Any:
        ids = list(dict.fromkeys(re.findall(rf'"report_id": "({UUID})"', text)))
        return answer(
            info,
            {
                "interpretation": {
                    "report_ids": ids,
                    "what_was_tested": "One factor on the W1 window.",
                    "observed": "The released values as reported.",
                    "diagnosis": "Conjecture: the reversal mechanism holds out of sample.",
                    "implications": [],
                    "next_steps": ["Try a neighbouring horizon."],
                    "confidence": "low",
                    "caveats": CAVEATS,
                },
                "knowledge_items": [
                    {
                        "kind": "insight",
                        "statement": "Short-horizon reversal survived W1.",
                        "evidence_report_ids": ids[:1],
                        "tags": ["reversal"],
                    }
                ],
            },
        )

    def _interp_review(self, text: str, messages: list[ModelMessage], info: AgentInfo) -> Any:
        found = re.search(rf'"interpretation_id": "({UUID})"', text)
        assert found is not None, "the review prompt names the interpretation"
        return answer(
            info, {"interpretation_id": found.group(1), "issues": [], "verdict": "accept"}
        )
