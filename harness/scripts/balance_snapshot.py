"""One private, read-only account observation; never an automatic ledger reset."""

import argparse
import json
import re
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal

import httpx
import yaml
from pydantic import BaseModel, ConfigDict

from qfh.budget import admission_open


class Balance(BaseModel):
    model_config = ConfigDict(extra="ignore", allow_inf_nan=False)
    currency: Literal["CNY", "USD"]
    total_balance: Decimal
    granted_balance: Decimal
    topped_up_balance: Decimal


class Account(BaseModel):
    model_config = ConfigDict(extra="ignore")
    is_available: bool
    balance_infos: list[Balance]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--pricing",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "configs/deepseek-flash-pricing-2026-11-12.yaml",
    )
    args = parser.parse_args()
    if not admission_open(datetime.now(UTC)):
        raise SystemExit("Account observation deferred until the authorized Beijing window.")
    policy = yaml.safe_load(args.pricing.read_text())["billing_observation"]
    if policy["endpoint"] != "https://api.deepseek.com/user/balance":
        raise SystemExit("Only the official read-only DeepSeek balance endpoint is permitted.")
    keys = set(re.findall(r"sk-[A-Za-z0-9_-]{20,}", args.key_file.read_text()))
    if len(keys) != 1:
        raise SystemExit("Expected one operator-held DeepSeek credential.")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Claim a fresh evidence file before any request; an uncertain attempt is
    # retained and cannot be silently rerun over the same observation.
    with args.output.open("x") as output:
        args.output.chmod(0o600)
        record = {
            "started_at": datetime.now(UTC).isoformat(),
            "method": "GET",
            "endpoint": policy["endpoint"],
            "status": "attempting",
            "purpose": "Account balance comparison only; no inference or ledger mutation.",
        }
        output.write(json.dumps(record) + "\n")
        output.flush()
        try:
            with httpx.Client(
                timeout=policy["timeout_seconds"], trust_env=False, follow_redirects=False
            ) as client:
                with client.stream(
                    "GET", policy["endpoint"], headers={"Authorization": "Bearer " + keys.pop()}
                ) as response:
                    response.raise_for_status()
                    raw = bytearray()
                    for chunk in response.iter_bytes():
                        raw.extend(chunk)
                        if len(raw) > policy["max_response_bytes"]:
                            raise ValueError("balance response exceeded limit")
            body = Account.model_validate_json(raw).model_dump(mode="json")
            output.write(
                json.dumps(
                    {
                        "finished_at": datetime.now(UTC).isoformat(),
                        "status": "success",
                        "account": body,
                    }
                )
                + "\n"
            )
            print(
                json.dumps(
                    {
                        "status": "recorded",
                        "inference_requests": 0,
                        "balance_read_requests": 1,
                        "is_available": body["is_available"],
                    }
                )
            )
        except Exception as exc:
            output.write(
                json.dumps(
                    {
                        "finished_at": datetime.now(UTC).isoformat(),
                        "status": "failed",
                        "reason": type(exc).__name__,
                    }
                )
                + "\n"
            )
            raise SystemExit(
                "Balance observation failed; retained attempt, no automatic retry."
            ) from None


if __name__ == "__main__":
    main()
