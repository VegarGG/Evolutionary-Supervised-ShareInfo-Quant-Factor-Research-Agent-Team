"""Run the remaining bounded pilot treatments sequentially; never bypass admission."""

from __future__ import annotations

import argparse
from pathlib import Path

from qfh.experiment import run


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--private", type=Path, required=True)
    parser.add_argument("--key-file", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    schedule = [(variant, 1) for variant in ("independent", "self_revision", "review", "debate")]
    schedule += [(variant, repeat) for repeat in (2, 3) for variant in ("single", "blackboard")]
    for variant, repeat in schedule:
        result = run(
            root / "configs/phase1.yaml",
            root / "fixtures/diagnostic-availability.json",
            variant,
            f"availability-{variant.replace('_', '-')}-{repeat:03}",
            args.private.resolve(),
            args.key_file.resolve(),
        )
        print(result["status"], result["run_id"], flush=True)
        if result["status"] == "waiting_for_window":
            break


if __name__ == "__main__":
    main()
