"""Generate every public model/enum schema and structural examples deterministically."""

import argparse
import importlib
import json
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, TypeAdapter
from qfr_core.configuration import ConfigDocument
from qfr_core.contracts.base import Contract

from scripts.contract_examples import examples

ROOT = Path(__file__).resolve().parents[1]
MODULES = [
    "signing",
    "access",
    "feedback",
    "artifacts",
    "blackboard",
    "data",
    "delivery",
    "enums",
    "execution",
    "intake",
    "jobs",
    "providers",
    "publication",
    "reports",
]


def public_contracts():
    contracts = {"ConfigDocument": ConfigDocument}
    for name in MODULES:
        module = importlib.import_module(f"qfr_core.contracts.{name}")
        for value in vars(module).values():
            if (
                isinstance(value, type)
                and value.__module__ == module.__name__
                and issubclass(value, (Contract, Enum))
            ):
                contracts[value.__name__] = value
    return contracts


def generate(check=False):
    samples = {}
    variants = {}

    def collect(value):
        if isinstance(value, BaseModel):
            samples.setdefault(type(value).__name__, value.model_dump(mode="json"))
            if type(value).__name__ == "ArtifactManifest":
                variants[value.kind.value] = value.model_dump(mode="json")
            for name in type(value).model_fields:
                collect(getattr(value, name))
        elif isinstance(value, list):
            for child in value:
                collect(child)
        elif isinstance(value, dict):
            for child in value.values():
                collect(child)

    for sample in examples(ROOT):
        collect(sample)
    outputs = {}
    for name, contract in sorted(public_contracts().items()):
        schema = TypeAdapter(contract).json_schema()
        if issubclass(contract, Enum):
            valid = next(iter(contract)).value
            invalid = "__invalid_enum_value__"
        else:
            if name not in samples:
                raise ValueError(f"Public contract has no valid example: {name}")
            valid = samples[name]
            invalid = dict(valid)
            required = schema.get("required", [])
            if required:
                invalid.pop(required[0])
            else:
                invalid["unexpected_field"] = True
        outputs[f"contracts/jsonschema/{name}.schema.json"] = schema
        outputs[f"contracts/examples/{name}.valid.json"] = valid
        outputs[f"contracts/examples/{name}.invalid.json"] = invalid
    for kind, sample in variants.items():
        outputs[f"contracts/examples/artifact_kinds/{kind}.json"] = sample
    outputs["contracts/public-contracts.json"] = sorted(public_contracts())
    for filename, content in outputs.items():
        path = ROOT / filename
        rendered = json.dumps(content, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        if check:
            if not path.exists() or path.read_text() != rendered:
                raise SystemExit(f"Generated contract drift: {filename}")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(rendered)
    action = "verified" if check else "written"
    print(f"{len(public_contracts())} contracts; {len(variants)} kinds; files {action}.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    generate(parser.parse_args().check)
