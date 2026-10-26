"""CI must fail on checks, exercise PostgreSQL and retain both-platform digest evidence."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_ci_has_postgres_checks_and_both_architectures():
    workflow = yaml.safe_load((ROOT / ".github/workflows/stage-0.yml").read_text())
    checks = workflow["jobs"]["checks"]
    assert checks["services"]["postgres"]["image"].startswith("postgres:16@sha256:")
    commands = "\n".join(step.get("run", "") for step in checks["steps"])
    assert "just check" in commands and "just test" in commands and "just up" in commands
    image_job = workflow["jobs"]["images"]
    assert {item["architecture"] for item in image_job["strategy"]["matrix"]["include"]} == {
        "amd64",
        "arm64",
    }
    assert any(
        step.get("with", {}).get("if-no-files-found") == "error" for step in image_job["steps"]
    )
    assert all(
        not step.get("continue-on-error", False) for step in checks["steps"] + image_job["steps"]
    )
    assert "Build success is not native runtime acceptance" in str(image_job)
