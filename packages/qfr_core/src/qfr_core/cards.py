"""Public protocol and policy cards (PLAN Sections 8.2 and 9.6), built by whitelist.

The evaluator derives the cards from the active protocol, policy and quota versions and
serves them through feedback-api; scripts/build_public_cards.py writes the same cards
for the shipped configuration to configs/public_cards.json, which the registry, the
front door and the research workbench read. Window dates, holdout and acceptance gates,
simulation and monitoring settings, and burn thresholds never enter a card.
"""

import hashlib
from typing import Any

from pydantic import JsonValue

from qfr_core.config import canonical_json
from qfr_core.contracts import (
    AdvancementContent,
    DecisionContent,
    DiagnosticFlag,
    IntakeContent,
    LibraryContent,
    ReasonCode,
    SimulationContent,
    W1Content,
    W2Content,
)

PROTOCOL_FIELDS = (
    "protocol_id",
    "version",
    "universe",
    "eligibility",
    "label",
    "preprocessing",
    "quantiles",
    "costs",
    "reference_strategy",
    "strategy_bounds",
    "dsl",
    # The research workbench computes the same W0 fingerprints as the evaluator.
    "fingerprint",
)
PUBLIC_GATES = ("w1_factor", "w1_strategy", "w2_factor", "w2_strategy")
QUOTA_FIELDS = ("quota_id", "version", "family", "program", "global", "deferral_expiry_days")
REPORT_FIELDS: dict[str, list[str]] = {
    "intake": sorted(IntakeContent.model_fields),
    "screening": sorted(IntakeContent.model_fields),
    "w1": sorted(W1Content.model_fields),
    "w2": sorted(W2Content.model_fields),
    "advancement": sorted(AdvancementContent.model_fields),
    "sim": sorted(SimulationContent.model_fields),
    "decision": sorted(DecisionContent.model_fields),
    "library": sorted(LibraryContent.model_fields),
}


def protocol_card(protocol: dict[str, Any]) -> dict[str, JsonValue]:
    card: dict[str, JsonValue] = {key: protocol[key] for key in PROTOCOL_FIELDS}
    card["gates"] = {key: protocol["gates"][key] for key in PUBLIC_GATES}
    return card


def quota_card(quotas: dict[str, Any]) -> dict[str, JsonValue]:
    return {key: quotas[key] for key in QUOTA_FIELDS}


def policy_card(policy: dict[str, Any]) -> dict[str, JsonValue]:
    """The whole release policy plus the released fields and code vocabularies."""
    card: dict[str, JsonValue] = dict(policy)
    card["report_fields"] = {k: list(v) for k, v in REPORT_FIELDS.items()}
    card["reason_codes"] = [code.value for code in ReasonCode]
    card["diagnostic_flags"] = [flag.value for flag in DiagnosticFlag]
    return card


def compose_policy_card(
    policy: dict[str, JsonValue], quotas: dict[str, JsonValue] | None
) -> dict[str, JsonValue]:
    """The served policy card: what is released, when, and under which quotas."""
    return dict(policy) | {"quotas": quotas}


def card_sha256(card: dict[str, JsonValue]) -> str:
    return hashlib.sha256(canonical_json(card).encode()).hexdigest()


def build_cards(
    protocol: dict[str, Any], policy: dict[str, Any], quotas: dict[str, Any]
) -> dict[str, JsonValue]:
    return {
        "protocol": protocol_card(protocol),
        "policy": compose_policy_card(policy_card(policy), quota_card(quotas)),
    }
