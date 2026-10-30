import json
from pathlib import Path

import jsonschema
import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import TypeAdapter, ValidationError
from qfr_core.contracts import PUBLIC_CONTRACTS, DiagnosticFlag, ReasonCode, ReleasedReport
from qfr_eval.contracts import PRIVATE_CONTRACTS

CONTRACTS = PUBLIC_CONTRACTS | PRIVATE_CONTRACTS


@pytest.mark.parametrize("name", CONTRACTS)
def test_every_contract_has_valid_invalid_examples_and_matching_json_schema(name):
    model = CONTRACTS[name]
    examples = Path("tests/contracts")
    valid = json.loads((examples / f"{name}.valid.json").read_text())
    invalid = json.loads((examples / f"{name}.invalid.json").read_text())
    model.model_validate(valid)
    with pytest.raises(ValidationError):
        model.model_validate(invalid)
    visibility = "private" if name in PRIVATE_CONTRACTS else "public"
    schema = json.loads((Path("schemas") / visibility / f"{name}.json").read_text())
    assert schema == model.model_json_schema()
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(valid, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(invalid, schema)


@pytest.mark.parametrize(
    "name,enum", [("reason_code", ReasonCode), ("diagnostic_flag", DiagnosticFlag)]
)
def test_enum_examples(name, enum):
    adapter = TypeAdapter(enum)
    adapter.validate_json((Path("tests/contracts") / f"{name}.valid.json").read_text())
    with pytest.raises(ValidationError):
        adapter.validate_json((Path("tests/contracts") / f"{name}.invalid.json").read_text())


@given(st.floats(allow_nan=False, allow_infinity=False))
def test_rel_05_private_holdout_values_cannot_enter_public_reports(value):
    report = json.loads(Path("tests/contracts/released_report.valid.json").read_text())
    report["content"]["w3_rankic"] = value
    with pytest.raises(ValidationError):
        ReleasedReport.model_validate(report)


def test_no_free_text_error_or_timing_channel_in_public_report():
    report = json.loads(Path("tests/contracts/released_report.valid.json").read_text())
    for key in ("stack", "error_message", "duration_ms", "window_dates", "daily_nav"):
        with pytest.raises(ValidationError):
            ReleasedReport.model_validate(report | {key: "arbitrary"})
