"""Explicit live GLM-only module pilot; ordinary test commands never invoke this."""

import argparse
import json
from pathlib import Path

from qfh.module_experiment import run

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--private", required=True, type=Path)
    parser.add_argument("--case", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--variant", choices=("peer_review", "feedback_disabled"), required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.private.resolve(), args.case.resolve(), args.run_id, args.variant)))
