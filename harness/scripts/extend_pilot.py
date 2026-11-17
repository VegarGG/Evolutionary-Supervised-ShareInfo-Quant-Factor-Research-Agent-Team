"""Record an owner-authorized pilot-session extension without resetting any ledger."""

import argparse
import json
from pathlib import Path

import yaml

from qfh.research import PilotExtension, Research


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--private", type=Path, required=True)
    parser.add_argument("--amendment", type=Path, required=True)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "configs/research-trial.yaml",
    )
    args = parser.parse_args()
    research = Research(args.config.resolve(), args.private.resolve())
    extension = PilotExtension.model_validate(yaml.safe_load(args.amendment.read_text()))
    record = research.extend_allowance(extension)
    print(json.dumps({"amendment": record, "allowance": research.allowance()}))


if __name__ == "__main__":
    main()
