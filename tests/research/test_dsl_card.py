"""The DSL reference card for prompts is generated from the operator registry and the
protocol's limits (P4.6), and its syntax examples are valid qfr-dsl/1."""

import hashlib
from pathlib import Path

from qfr_core.config import public_protocol_section
from qfr_core.dsl import DslLimits, validate
from qfr_core.dsl.catalog import FIELD_COLUMNS, OPERATORS
from qfr_research.dsl_card import EXAMPLES, build_card

LIMITS = DslLimits.from_protocol(public_protocol_section(Path("configs"), "dsl"))


def test_the_syntax_examples_are_valid_under_the_protocol_limits():
    for example in EXAMPLES:
        check = validate(example, LIMITS)
        assert check.ok, (example, check.errors)


def test_the_card_names_every_field_and_operator_and_the_limits():
    card = build_card(LIMITS)
    for name in FIELD_COLUMNS:
        assert f"- ${name}:" in card.text, name
    for name in OPERATORS:
        assert f"- {name}(" in card.text, name
    assert f"At most {LIMITS.max_nodes} nodes" in card.text
    assert f"Maximum lookback {LIMITS.max_lookback_days} trading days" in card.text


def test_the_card_version_is_the_hash_of_its_text_and_is_stable():
    card = build_card(LIMITS)
    assert card.version == hashlib.sha256(card.text.encode()).hexdigest()
    assert build_card(LIMITS) == card
