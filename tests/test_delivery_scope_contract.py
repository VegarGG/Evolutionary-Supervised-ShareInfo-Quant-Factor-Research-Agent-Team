"""Delivery scope versioning preserves signed legacy bytes and freezes roles."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from qfr_core.contracts.jobs import ExitGateSpecification, PilotDeliveryAssessment, ResearchBrief
from qfr_core.delivery_rules import gate_hash, validate_pilot_assessment

ROOT = Path(__file__).resolve().parents[1]


def sample(name):
    return json.loads((ROOT / f"contracts/examples/{name}.valid.json").read_bytes())


def test_legacy_gate_serialization_and_hash_are_unchanged():
    raw = sample("ExitGateSpecification")
    gate = ExitGateSpecification.model_validate(raw)
    assert gate.schema_version == "1" and gate.assessment_scope is None
    assert gate.model_dump(mode="json") == raw
    assert gate_hash(gate) == "0675302f082f216e704f07345f9ca700a055e67fa1232237b88bfcc44f17626a"
    assert "assessment_scope" not in gate.model_dump_json()


@pytest.mark.parametrize("version,scope", [("2", None), ("1", "present")])
def test_gate_version_requires_the_corresponding_scope(version, scope):
    raw = sample("ExitGateSpecification")
    raw.update(
        schema_version=version,
        assessment_scope=sample("PilotDeliveryAssessment") if scope else None,
    )
    with pytest.raises(ValidationError, match="version 2"):
        ExitGateSpecification.model_validate(raw)


@pytest.mark.parametrize("issue", ["empty", "overlap", "duplicate", "promotion"])
def test_empty_or_ambiguous_assessment_cannot_be_frozen(issue):
    scope = sample("PilotDeliveryAssessment")
    if issue == "empty":
        scope["assessed_artifact_refs"] = []
    elif issue == "overlap":
        scope["reference_artifact_refs"] = scope["assessed_artifact_refs"]
    elif issue == "duplicate":
        scope["assessed_artifact_refs"] *= 2
    if issue == "promotion":
        gate = sample("ExitGateSpecification")
        gate.update(schema_version="2", assessment_scope=scope, gate_type="investment_promotion")
        with pytest.raises(ValidationError, match="research delivery only"):
            ExitGateSpecification.model_validate(gate)
    else:
        with pytest.raises(ValidationError):
            PilotDeliveryAssessment.model_validate(scope)


def test_reference_roles_preserve_all_original_baselines_and_cannot_hide_other_candidates():
    raw = sample("ResearchBrief")
    scope = sample("PilotDeliveryAssessment")
    raw["exit_gate"].update(schema_version="2", assessment_scope=scope)
    assessed = scope["assessed_artifact_refs"][0]["artifact_version_id"]
    baseline = scope["reference_artifact_refs"][0]["artifact_version_id"]
    raw["baseline_artifact_ids"] = [assessed, baseline]
    validate_pilot_assessment(ResearchBrief.model_validate(raw))
    for invalid in ([assessed], [assessed, baseline, "omitted-baseline"]):
        raw["baseline_artifact_ids"] = invalid
        with pytest.raises(ValueError, match="retain all baselines"):
            validate_pilot_assessment(ResearchBrief.model_validate(raw))
