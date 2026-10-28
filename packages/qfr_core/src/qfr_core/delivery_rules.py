"""Machine-readable pilot delivery requirements shared by admission and checking."""

import hashlib

from qfr_core.contracts.enums import Conclusion
from qfr_core.contracts.intake import InputBundle
from qfr_core.contracts.jobs import ExitGateSpecification, ResearchBrief
from qfr_core.data_layer.snapshots import canonical_json

PILOT_DELIVERY_CHECKS = (
    "frozen_context",
    "artifact_integrity",
    "required_deliverables",
    "released_evidence",
    "measurement_quality",
    "reproduction",
    "conclusion_support",
    "human_signoff",
)
PILOT_DELIVERY_SCHEMAS = frozenset({"ResearchNotePayload", "ArtifactManifest"})


def content_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def gate_hash(gate: ExitGateSpecification) -> str:
    return content_sha256(gate.model_dump(mode="json", exclude={"spec_hash"}))


def admission_hash(bundle: InputBundle, brief: ResearchBrief) -> str:
    return content_sha256(
        {"input_bundle": bundle.model_dump(mode="json"), "brief": brief.model_dump(mode="json")}
    )


def job_config_hash(bundle: InputBundle) -> str:
    return content_sha256(bundle.job_config.model_dump(mode="json"))


def validate_pilot_delivery_gate(gate: ExitGateSpecification) -> None:
    """Unknown or omitted requirements cannot be silently treated as satisfied."""
    if (
        gate.gate_type != "research_delivery"
        or gate.forward_evidence_required
        or gate.spec_hash != gate_hash(gate)
        or sorted(gate.required_checks) != sorted(PILOT_DELIVERY_CHECKS)
        or gate.reproducibility_criteria != ["exact_results_and_series_replay"]
        or gate.evidence_release_requirements != ["verified_released_reports_only"]
        or not gate.protocol_refs
        or len(set(gate.protocol_refs)) != len(gate.protocol_refs)
        or not set(gate.allowed_conclusions)
        <= {Conclusion.POSITIVE, Conclusion.NEGATIVE, Conclusion.EMPTY_SHORTLIST}
        or len(set(gate.allowed_conclusions)) != len(gate.allowed_conclusions)
    ):
        raise ValueError("unsupported or inconsistent pilot research-delivery gate")
    names = [item.name for item in gate.required_deliverables]
    if (
        len(set(names)) != len(names)
        or any(item.schema_ref not in PILOT_DELIVERY_SCHEMAS for item in gate.required_deliverables)
        or not any(
            item.required
            and item.evidence_refs_required
            and item.schema_ref == "ResearchNotePayload"
            for item in gate.required_deliverables
        )
    ):
        raise ValueError("pilot delivery requires a declared evidence-backed research note")
