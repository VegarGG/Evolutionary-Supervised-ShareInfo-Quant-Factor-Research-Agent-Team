"""Validate the private build artifact without importing the evaluator package."""

import json
from pathlib import Path

from jsonschema import Draft202012Validator
from pydantic import JsonValue


def validate_owner_evidence(value: dict[str, JsonValue], schema_path: Path) -> None:
    schema = json.loads(schema_path.read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(value)
