"""BND-04: enforce the actual import graph, including indirect imports."""

import subprocess
import sys
from pathlib import Path


def test_bnd_04_import_contracts():
    result = subprocess.run(
        [str(Path(sys.executable).parent / "lint-imports")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Contracts: 5 kept, 0 broken" in result.stdout


def test_bnd_04_detects_an_actual_forbidden_import(tmp_path):
    import os
    import shutil

    root = Path(__file__).resolve().parents[2]
    for name in ["qfr_core", "qfr_registry", "qfr_research", "qfr_eval", "qfr_mcp"]:
        shutil.copytree(
            root / "packages" / name / "src" / name,
            tmp_path / name,
            ignore=shutil.ignore_patterns("__pycache__"),
        )
    shutil.copy(root / ".importlinter", tmp_path / ".importlinter")
    with (tmp_path / "qfr_research/__init__.py").open("a") as stream:
        stream.write("\nimport qfr_eval.records\n")
    result = subprocess.run(
        [str(Path(sys.executable).parent / "lint-imports")],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(tmp_path)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "Research never imports evaluation BROKEN" in result.stdout
