"""Build-time contract generation; this script is not imported by the MCP service."""

import json
from pathlib import Path

from pydantic import TypeAdapter
from qfr_core.contracts import PUBLIC_CONTRACTS, DiagnosticFlag, ReasonCode
from qfr_eval.contracts import PRIVATE_CONTRACTS

root = Path(__file__).resolve().parents[1] / "schemas"
for visibility, contracts in (("public", PUBLIC_CONTRACTS), ("private", PRIVATE_CONTRACTS)):
    target = root / visibility
    target.mkdir(parents=True, exist_ok=True)
    for name, model in contracts.items():
        (target / f"{name}.json").write_text(
            json.dumps(model.model_json_schema(), sort_keys=True, indent=2) + "\n"
        )
for name, enum in (("reason_code", ReasonCode), ("diagnostic_flag", DiagnosticFlag)):
    (root / "public" / f"{name}.json").write_text(
        json.dumps(TypeAdapter(enum).json_schema(), sort_keys=True, indent=2) + "\n"
    )
