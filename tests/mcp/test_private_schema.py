import json
from pathlib import Path

import pytest
from jsonschema import ValidationError
from qfr_mcp.evidence_validation import validate_owner_evidence


def test_owner_evidence_is_validated_from_build_artifact():
    value = json.loads(Path("tests/contracts/owner_evidence.valid.json").read_text())
    schema = Path("schemas/private/owner_evidence.json")
    validate_owner_evidence(value, schema)
    with pytest.raises(ValidationError):
        validate_owner_evidence(value | {"visibility": "research"}, schema)
