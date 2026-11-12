"""One explicitly executed data transport check using credentials saved in DSH.

This is not an LLM research experiment. The native DSH tool loop is tested
separately; this check verifies authentication, response shape and measured usage.
"""

import argparse
import hashlib
import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path

import yaml

from qfh.data_gateway import DataPolicy, dispatch
from qfh.experiment import Resources, write_new


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--private", type=Path, default=Path(".qfh-private"))
    parser.add_argument("--provider", choices=("baostock", "ifind", "rqdata"), default="baostock")
    parser.add_argument("--run-id", default="baostock-data-pilot-001")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9-]{1,80}", args.run_id):
        parser.error("run id must be a safe lowercase identifier")
    root = Path(__file__).resolve().parents[1]
    policy_path = root / "configs/data-pilot.yaml"
    private = args.private.resolve()
    policy = DataPolicy.model_validate(yaml.safe_load(policy_path.read_text()))
    allowance = policy.provider_allowances.get(args.provider, policy)
    query = {"symbols": ["000001.XSHE"], "start": "2026-10-28", "end": "2026-10-30"}
    plan = {
        "run_id": args.run_id,
        "provider": args.provider,
        "query": query,
        "kind": "bars",
        "fields": ["close"],
        "adjustment": "none",
        "llm_calls": 0,
        "max_business_requests": allowance.max_business_requests,
        "max_auth_requests": allowance.max_auth_requests,
        "policy_sha256": hashlib.sha256(policy_path.read_bytes()).hexdigest(),
        "source_sha256": {
            str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in [
                Path(__file__),
                root / "src/qfh/data_gateway.py",
                root / "src/qfh/baostock_source.py",
            ]
        },
    }
    if not args.execute:
        print(json.dumps({"status": "prepared_no_requests", **plan}, indent=2))
        return
    # DSH's private store is the only supported input; never ask the user for a key path.
    credentials = {}
    if args.provider != "baostock":
        try:
            refs = yaml.safe_load((private / "ui-home/.credentials.yaml").read_text())["refs"]
            credentials = (
                json.loads(refs["QFH_IFIND_CREDENTIAL"])
                if args.provider == "ifind"
                else {"license": refs["QFH_RQDATA_LICENSE"]}
            )
        except Exception:
            raise SystemExit("Save the credential in DSH Settings > Research data first.") from None
    run_dir = private / "data" / "pilots" / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    if (run_dir / "started.json").exists():
        raise SystemExit("This attempt already exists; inspect it before starting another.")
    write_new(run_dir / "started.json", {**plan, "at": datetime.now(UTC).isoformat()})
    start = time.monotonic()
    try:
        with Resources(run_dir / "resources.jsonl", 0.5):
            result = dispatch(
                {
                    "run_id": args.run_id,
                    "provider": args.provider,
                    "kind": "bars",
                    "query": query,
                    "credentials": credentials,
                },
                policy,
                private / "data",
            )
        record = {
            "status": "completed",
            **plan,
            "latency_seconds": time.monotonic() - start,
            "at": datetime.now(UTC).isoformat(),
            "result": result,
            "data_checks": {
                "expected_three_rows": result["row_count"] == 3,
                "all_dates_present": [row["date"] for row in result["content"]]
                == ["2026-10-28", "2026-10-29", "2026-10-30"],
                "all_closes_positive": all(
                    row["close"] is not None and row["close"] > 0 for row in result["content"]
                ),
            },
        }
        if not all(record["data_checks"].values()):
            record["status"] = "data_quality_failed"
    except Exception as exc:
        # Keep the reservation and error class. Never print raw SDK/auth errors.
        record = {
            "status": "failed_or_unknown",
            **plan,
            "error_class": type(exc).__name__,
            "safe_error": str(exc) if args.provider == "baostock" else type(exc).__name__,
            "at": datetime.now(UTC).isoformat(),
            "latency_seconds": time.monotonic() - start,
        }
    write_new(run_dir / "result.json", record)
    print(json.dumps({k: v for k, v in record.items() if k != "result"}, indent=2))
    if record["status"] != "completed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
