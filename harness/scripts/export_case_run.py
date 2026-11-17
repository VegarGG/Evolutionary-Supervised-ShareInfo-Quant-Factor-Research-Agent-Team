"""Export native case traces and independently recompute their descriptive arithmetic."""

import argparse
import json
from pathlib import Path

from export_adaptive_run import export

from qfh.case_audit import audit
from qfh.experiment import write_new

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--private", type=Path, required=True)
    parser.add_argument("--package-id", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--allow-unresolved", action="store_true")
    args = parser.parse_args()
    private = args.private.resolve()
    directory = private / "cases" / args.package_id
    output = args.output.resolve() if args.output else directory
    arithmetic = audit(directory)
    exported = export(
        private, args.package_id, output, case=True, allow_unresolved=args.allow_unresolved
    )
    write_new(output / "INDEPENDENT_ARITHMETIC.json", arithmetic)
    print(json.dumps({**exported, "arithmetic": arithmetic}, indent=2))
