import json
from pathlib import Path

import pytest

from qfh.final_output import (
    CompletedOutput,
    FinalBoard,
    FinalReview,
    OutputAmendment,
    OutputEpisode,
    expression_units,
    unit_proof,
)


def episode():
    case = json.loads((Path(__file__).parents[1] / "cases/module-units.json").read_bytes())
    definition = {
        **case["initial"],
        "expression": "profit_reported / capitalization_reported * 1e-4",
        "input_units": "profit in ten thousand CNY; capitalization in hundred million CNY",
    }
    return OutputEpisode(
        episode_id="test-output",
        actors={
            "supervisor": "supervisor",
            "reviewer-1": "reviewer",
            "reviewer-3": "reviewer",
            "author-2": "author",
        },
        sources=case["sources"],
        initial_output=CompletedOutput(
            definition=definition,
            decisions=[],
            citations=[{"evidence_id": "income", "quote": "10000 CNY"}],
            rationale="The raw ratio understates the target by 10000.",
            unresolved=["No returns supplied."],
        ),
        import_origin={"fixture": True},
        units={
            "base_unit": "CNY",
            "numerator": {
                "variable": "profit_reported",
                "base_units_per_reported_unit": 10000,
                "citation": {"evidence_id": "income", "quote": "10000 CNY"},
            },
            "denominator": {
                "variable": "capitalization_reported",
                "base_units_per_reported_unit": 100000000,
                "citation": {"evidence_id": "capital", "quote": "100000000 CNY"},
            },
        },
        policy={"max_events": 64, "max_findings": 12, "max_versions": 3, "max_text_length": 24000},
    )


def rejection(board):
    head = board.snapshot("reviewer-1")["head"]
    return FinalReview(
        output_id=head["id"],
        verdict="needs_revision",
        checks={
            k: "Inspected the completed output."
            for k in ("formula_units", "explanations", "source_support", "scope_and_limits")
        },
        issues=[
            {
                "path": "/rationale",
                "quote": "understates",
                "explanation": "Raw is target times 10000.",
                "citations": [
                    {"evidence_id": "income", "quote": "10000 CNY"},
                    {"evidence_id": "capital", "quote": "100000000 CNY"},
                ],
            }
        ],
        limitations=["Diagnostic only."],
    )


def correction(board, review):
    scope = board.snapshot("author-2")
    output = {
        **scope["head"]["output"],
        "rationale": "The raw ratio overstates the target by 10000.",
        "unit_claims": scope["unit_proof"]["expected_claims"],
    }
    return OutputAmendment(
        parent_id=scope["head"]["id"],
        review_id=review["id"],
        output=output,
        resolutions=[{"issue_index": 0, "action": "correct", "reason": "Correct unit direction."}],
    )


def test_completed_review_amendment_and_exact_finalization(tmp_path):
    board = FinalBoard.create(tmp_path, episode())
    original = board.snapshot("supervisor")["head"]
    review = board.review("reviewer-1", rejection(board))
    with pytest.raises(ValueError, match="clean independent"):
        board.finalize("supervisor", original["id"], review["id"])
    amended = board.amend("author-2", correction(board, review))
    assert amended["body"]["definition_change"] is False
    assert amended["body"]["output"]["definition"] == original["output"]["definition"]
    assert "understates" in FinalBoard(tmp_path).episode.initial_output.rationale
    with pytest.raises(ValueError, match="current exact"):
        board.review(
            "reviewer-3", rejection(board).model_copy(update={"output_id": original["id"]})
        )
    passing = rejection(board).model_copy(update={"verdict": "reviewed_with_limits", "issues": []})
    reviewed = board.review("reviewer-3", passing)
    board.finalize("supervisor", amended["id"], reviewed["id"])
    with pytest.raises(ValueError, match="finalized"):
        board.amend("author-2", correction(board, review))


def test_refuse_forgery_stale_writer_definition_and_claim_changes(tmp_path):
    board = FinalBoard.create(tmp_path, episode())
    review = rejection(board)
    with pytest.raises(ValueError, match="authorized"):
        board.review("author-2", review)
    forged = review.model_dump()
    forged["issues"][0]["quote"] = "invented"
    with pytest.raises(ValueError, match="excerpt"):
        board.review("reviewer-1", FinalReview.model_validate(forged))
    forged = review.model_dump()
    forged["issues"][0]["citations"][0]["quote"] = "invented"
    with pytest.raises(ValueError, match="citation"):
        board.review("reviewer-1", FinalReview.model_validate(forged))
    reviewed = board.review("reviewer-1", review)
    amendment = correction(board, reviewed).model_dump()
    amendment["output"]["definition"]["execution_rule"] = "Changed timing"
    with pytest.raises(ValueError, match="computational definition"):
        board.amend("author-2", OutputAmendment.model_validate(amendment))
    amendment = correction(board, reviewed).model_dump()
    amendment["output"]["unit_claims"]["raw_direction"] = "understates"
    with pytest.raises(ValueError, match="exact unit"):
        board.amend("author-2", OutputAmendment.model_validate(amendment))
    amendment = correction(board, reviewed).model_dump()
    amendment["resolutions"][0]["issue_index"] = 1
    with pytest.raises(ValueError, match="every issue"):
        board.amend("author-2", OutputAmendment.model_validate(amendment))


@pytest.mark.parametrize(
    "expression",
    [
        "profit_reported / capitalization_reported * 1e-4",
        "(profit_reported * 10000) / (capitalization_reported * 100000000)",
    ],
)
def test_unit_proof_exact_scaling(expression):
    e = episode()
    output = e.initial_output.model_copy(
        update={
            "definition": e.initial_output.definition.model_copy(update={"expression": expression})
        }
    )
    proof = unit_proof(output, e.units)
    assert proof["formula_ok"] and not proof["structured_claims_ok"]
    assert proof["expected_claims"]["raw_per_target_numerator"] == 10000
    assert proof["expected_claims"]["raw_direction"] == "overstates"


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('true')",
        "profit_reported + capitalization_reported",
        "profit_reported / 0",
        "profit_reported ** 100000000",
        "True",
        "1e300",
    ],
)
def test_expression_is_not_executable(expression):
    with pytest.raises(ValueError):
        expression_units(expression)


def test_clean_review_cannot_accept_missing_or_inverted_claims(tmp_path):
    board = FinalBoard.create(tmp_path, episode())
    clean = rejection(board).model_copy(update={"verdict": "reviewed_with_limits", "issues": []})
    with pytest.raises(ValueError, match="unit proof|unit contradiction"):
        board.review("reviewer-1", clean)


def test_review_can_target_missing_structured_claims_without_misattributing_text(tmp_path):
    initial = episode()
    initial = initial.model_copy(
        update={
            "initial_output": initial.initial_output.model_copy(
                update={"rationale": "Raw magnitude is 10000 times target magnitude."}
            )
        }
    )
    board = FinalBoard.create(tmp_path, initial)
    raw = rejection(board).model_dump()
    raw["issues"][0].update(
        path="/unit_claims", quote='"null"', explanation="Add exact unit claims."
    )
    with pytest.raises(ValueError, match="excerpt"):
        board.review("reviewer-1", FinalReview.model_validate(raw))
    raw["issues"][0]["quote"] = "null"
    recorded = board.review("reviewer-1", FinalReview.model_validate(raw))
    assert recorded["body"]["issues"][0]["path"] == "/unit_claims"


def test_final_review_cannot_pass_correct_claims_with_a_contradictory_rationale(tmp_path):
    initial = episode()
    bad = initial.initial_output.model_dump()
    bad["rationale"] = (
        "The raw stored ratio equals the intended dimensionless earnings yield "
        "times 10^-4. The raw ratio equals the target times 10000/1."
    )
    bad["unit_claims"] = unit_proof(initial.initial_output, initial.units)["expected_claims"]
    board = FinalBoard.create(
        tmp_path, initial.model_copy(update={"initial_output": CompletedOutput.model_validate(bad)})
    )
    clean = rejection(board).model_copy(update={"verdict": "reviewed_with_limits", "issues": []})
    with pytest.raises(ValueError, match="host-detected unit contradiction"):
        board.review("reviewer-1", clean)
    assert not board.snapshot("supervisor")["unit_proof"]["recognized_prose_ok"]


def test_unit_proof_does_not_round_a_nearly_correct_decimal_into_acceptance():
    initial = episode()
    output = initial.initial_output.model_copy(
        update={
            "definition": initial.initial_output.definition.model_copy(
                update={
                    "expression": "profit_reported / capitalization_reported * "
                    "0.000100000000000000000001"
                }
            )
        }
    )
    assert not unit_proof(output, initial.units)["formula_ok"]


def test_extreme_numeric_exponent_is_refused_before_fraction_allocation():
    with pytest.raises(ValueError, match="outside bounds"):
        expression_units("1e-999999999")
