"""The owner-only scan's matching rules (MCP-03, PLAN Section 9.6). The evidence numbers
are made up for the test."""

import json
from pathlib import Path
from uuid import UUID

import pytest
from qfr_mcp.scan import OwnerValueInText, matches, numbers, text_of_brief, verdict

ROUNDING = json.loads(Path("configs/public_cards.json").read_text())["policy"]["rounding"]
VERSION = UUID("01900000-0000-7000-8000-000000000001")
EVIDENCE = {
    "w1": {
        "metrics": {
            "sharpe": 1.3871,
            "rankic_mean": 0.031234,
            "rankic_ir": 0.4521,
            "turnover": 0.2734,
            "days": 120,
        },
        "gates": [{"name": "rankic_ir", "threshold": 0.15, "value": 0.4521}],
        "protocol_version": 3.25,
    }
}


def test_the_rounding_steps_this_test_assumes():
    assert ROUNDING["sharpe"] == 0.25 and ROUNDING["rankic"] == 0.005 and ROUNDING["ir"] == 0.02


@pytest.mark.parametrize(
    "text",
    [
        "The sharpe was 1.3871 last time.",  # full precision
        "Aim above 1.39.",  # the full value written to the text's two decimals
        "It released as 1.50.",  # sharpe at the release step (0.25)
        "Rank IC near 0.030 on W1.",  # rankic at its release step (0.005), not 0.031
        "IR of 0.46 is the bar.",  # rankic_ir at the ir step (0.02)
        "Turnover was 27.34% per day.",  # a percentage of a share
        "Keep -1.3871 in mind.",  # the sign does not hide it
    ],
)
def test_an_owner_value_in_any_written_form_is_found(text):
    hits, compared = matches(text, EVIDENCE, ROUNDING)
    assert hits == 1 and compared > 0, text


@pytest.mark.parametrize(
    "text",
    [
        "Use a 0.15 threshold like the public gate.",  # thresholds are public
        "Protocol 3.25 applies.",  # versions are not measurements
        "Try 1.4 next time.",  # one decimal is too coarse to compare
        "Use a 20-day window and 5 names.",  # integers are not compared
        "Version v1.39 of the notes.",  # a number inside a word is not a number
        "Aim for 0.00 drawdown.",  # zero is never a match
        "A sharpe of 2.75 would be nice.",  # no owner value is 2.75 at any precision
    ],
)
def test_public_and_unrelated_numbers_pass(text):
    hits, _ = matches(text, EVIDENCE, ROUNDING)
    assert hits == 0, text


def test_the_verdict_names_the_versions_but_never_the_value():
    with pytest.raises(OwnerValueInText) as raised:
        verdict("we saw 1.3871", {str(VERSION): EVIDENCE}, ROUNDING, [VERSION])
    assert raised.value.version_ids == [str(VERSION)] and raised.value.matches == 1
    assert "OWNER_ONLY_VALUE" in str(raised.value) and "1.3871" not in str(raised.value)


def test_a_passing_verdict_counts_what_was_compared():
    scan = verdict("A 0.15 gate and 2.75 hope.", {str(VERSION): EVIDENCE}, ROUNDING, [VERSION])
    assert scan.status == "passed" and scan.scanner == "qfr-mcp"
    assert scan.referenced_version_ids == [VERSION]
    assert scan.numbers_in_text == 2 and scan.values_compared == 5
    # A version the evaluator has not pulled yet has no owner values to compare.
    empty = verdict("we saw 1.3871", {str(VERSION): {}}, ROUNDING, [VERSION])
    assert empty.values_compared == 0


def test_numbers_and_brief_text():
    written = numbers("1.50, 27.34% and .5 but not 12")
    assert [(str(n.value), n.decimals) for n in written] == [
        ("1.50", 2),
        ("0.2734", 4),
        ("0.5", 1),
    ]
    text = text_of_brief(
        {
            "title": "T",
            "objective": "O",
            "seeds": {
                "notes": "N",
                "expressions": [
                    {"name": "s", "expression": "Rank($close) * 1.3871", "rationale": "R"}
                ],  # fmt: skip
            },
        }
    )
    assert text.split("\n") == ["T", "O", "N", "s", "Rank($close) * 1.3871", "R"]
    assert matches(text, EVIDENCE, ROUNDING)[0] == 1
