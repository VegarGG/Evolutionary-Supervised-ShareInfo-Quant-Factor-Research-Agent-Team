"""Explicit Stage 1 original-package oracle replay, never an artifact execution service.

Requires Docker, the locally cached pinned image, original packages and a separate
directory containing their exact dependencies. There is no download, install or fallback.
"""

import argparse
import json
import os
import subprocess
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packages", type=Path, required=True)
    parser.add_argument("--dependencies", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads((ROOT / "configs/pilot/oracle_runtime.json").read_text())
    if not args.dependencies.is_dir():
        parser.error("Original pinned dependency directory is required")
    # An existing output is never removed or overwritten.
    args.output.mkdir(parents=True, exist_ok=False)
    for model in ("P0", "P1"):
        package = args.packages / f"{model}_English_Delivery_20261022"
        if not (package / f"run_{model.lower()}.py").is_file():
            raise FileNotFoundError(f"Missing original package: {package}")
        output = args.output / model
        output.mkdir()
        name = "qfr-stage1-oracle-" + uuid.uuid4().hex[:12]
        command = [
            "docker",
            "run",
            "--rm",
            "--pull=never",
            "--network=none",
            "--read-only",
            "--name",
            name,
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            f"--pids-limit={config['pids']}",
            f"--cpus={config['cpus']}",
            f"--memory={config['memory']}",
            "--tmpfs",
            "/tmp:" + config["tmpfs"],
            "--env=PYTHONPATH=/deps",
            "--env=PYTHONDONTWRITEBYTECODE=1",
            "--env=OPENBLAS_NUM_THREADS=1",
            "--mount",
            f"type=bind,src={package.resolve()},dst=/bundle,readonly",
            "--mount",
            f"type=bind,src={args.dependencies.resolve()},dst=/deps,readonly",
            "--mount",
            f"type=bind,src={ROOT / 'scripts/capture_pilot_features.py'},"
            "dst=/harness/capture.py,readonly",
            "--mount",
            f"type=bind,src={output.resolve()},dst=/out",
            config["image"],
            "python",
            "/harness/capture.py",
            model,
        ]
        try:
            subprocess.run(command, check=True, timeout=config["timeout_seconds"])
        except subprocess.TimeoutExpired:
            subprocess.run(["docker", "rm", "-f", name], check=True, capture_output=True)
            raise
        receipt = json.loads((output / "replay/run_receipt.json").read_text())
        checks = receipt["business_csvs_byte_identical"]
        if (
            receipt["status"] != "passed"
            or len(checks) != 24
            or not all(item["byte_identical"] for item in checks)
            or receipt["new_model_fits"]
            or receipt["new_provider_requests"]
        ):
            raise RuntimeError(f"{model} original-package oracle failed")
        print(f"{model}: PASS; 24 exact CSVs, zero fits/provider requests", flush=True)


if __name__ == "__main__":
    main()
