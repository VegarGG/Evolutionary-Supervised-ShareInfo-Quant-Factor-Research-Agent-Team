"""Public JSON Schema parity, malformed payload rejection and trust invariants."""

import json
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import TypeAdapter, ValidationError
from qfr_core.contracts.artifacts import ArtifactManifest
from qfr_core.contracts.data import AssetReference, QualityLabels
from qfr_core.contracts.delivery import DeliveryReceipt, ExportManifest
from qfr_core.contracts.intake import InputBundle
from qfr_core.contracts.jobs import ExitGateSpecification, JobRecord
from qfr_core.contracts.reports import MetricValue, ReleasedReport

from scripts.generate_contracts import public_contracts

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = public_contracts()


def sample(name):
    return json.loads((ROOT / f"contracts/examples/{name}.valid.json").read_text())


@pytest.mark.parametrize("name", sorted(CONTRACTS))
def test_public_schema_valid_and_invalid_examples(name):
    model = CONTRACTS[name]
    valid = sample(name)
    invalid = json.loads((ROOT / f"contracts/examples/{name}.invalid.json").read_text())
    schema = json.loads((ROOT / f"contracts/jsonschema/{name}.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    TypeAdapter(model).validate_python(valid)
    validator.validate(valid)
    with pytest.raises(ValidationError):
        TypeAdapter(model).validate_python(invalid)
    assert list(validator.iter_errors(invalid))


@pytest.mark.parametrize("kind", ["factor", "model", "strategy", "research_note", "data_product"])
def test_artifact_kind_examples(kind):
    manifest = ArtifactManifest.model_validate_json(
        (ROOT / f"contracts/examples/artifact_kinds/{kind}.json").read_text()
    )
    assert manifest.kind.value == kind == manifest.payload.kind


@pytest.mark.parametrize("kind", ["idea", "factor", "model", "strategy", "bundle"])
def test_all_intake_kinds_can_be_unresolved_without_fake_execution(kind):
    body = sample("InputBundle")
    body["input_kind"] = kind
    body["definition"] = sample(kind.title() + "Definition")
    assert InputBundle.model_validate(body).execution_contract is None
    body["readiness"] = "ready"
    with pytest.raises(ValidationError, match="unresolved"):
        InputBundle.model_validate(body)


def test_idea_does_not_accept_fake_execution():
    body = sample("InputBundle")
    body["execution_contract"] = sample("ExecutionContract")
    with pytest.raises(ValidationError, match="fabricated"):
        InputBundle.model_validate(body)


def test_completed_job_requires_exact_independent_verified_receipt():
    body = sample("JobRecord")
    body["state"] = "completed"
    with pytest.raises(ValidationError, match="independent"):
        JobRecord.model_validate(body)
    body["receipt"] = dict(sample("ReceiptReference"), result="pass", signature_verified=True)
    JobRecord.model_validate(body)
    body["receipt"]["job_id"] = "another-job"
    with pytest.raises(ValidationError, match="independent"):
        JobRecord.model_validate(body)


def test_promotion_needs_forward_evidence_and_signoff():
    body = sample("ExitGateSpecification")
    body["gate_type"] = "investment_promotion"
    with pytest.raises(ValidationError, match="forward evidence"):
        ExitGateSpecification.model_validate(body)


@pytest.mark.parametrize("field", ["w3_metrics", "private_protocol", "raw_error", "run_timings"])
def test_rel_04_05_private_fields_rejected_at_both_levels(field):
    body = sample("ReleasedReport")
    body[field] = {"value": 1}
    with pytest.raises(ValidationError):
        ReleasedReport.model_validate(body)
    del body[field]
    body["content"][field] = {"value": 1}
    with pytest.raises(ValidationError):
        ReleasedReport.model_validate(body)


def test_prior_version_score_is_never_current_child_measurement():
    body = sample("ReleasedReport")
    body["content"]["scalar"]["origin_artifact_version_id"] = "older-version"
    with pytest.raises(ValidationError, match="originating"):
        ReleasedReport.model_validate(body)
    body["content"]["scalar"]["attribution"] = "lineage_best"
    ReleasedReport.model_validate(body)


def test_separate_quality_labels_and_missing_metrics():
    body = sample("QualityLabels")
    body["membership_grade"] = "A"
    with pytest.raises(ValidationError, match="grade D"):
        QualityLabels.model_validate(body)
    with pytest.raises(ValidationError, match="reason"):
        MetricValue(value=None, missing_reason=None)


@given(st.sampled_from(["../secret", "/private/data", "a/../../secret", "a\\b", "https://x"]))
def test_import_reference_cannot_escape_declared_root(path):
    with pytest.raises(ValidationError):
        AssetReference(transport="mounted_import", reference_id="declared", relative_path=path)


@given(st.sampled_from([float("nan"), float("inf"), float("-inf")]))
def test_measurements_must_be_finite(value):
    with pytest.raises(ValidationError):
        MetricValue(value=value, missing_reason=None)


def test_failed_checks_and_private_exports_cannot_pass():
    body = sample("DeliveryReceipt")
    body["checks"][0]["result"] = "fail"
    with pytest.raises(ValidationError, match="failed required check"):
        DeliveryReceipt.model_validate(body)
    body = sample("ExportManifest")
    body["files"][0]["kind"] = "private_protocol"
    with pytest.raises(ValidationError):
        ExportManifest.model_validate(body)
