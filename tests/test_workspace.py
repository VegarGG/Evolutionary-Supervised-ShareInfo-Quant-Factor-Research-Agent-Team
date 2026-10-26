"""Foundation smoke test; no service or licensed data dependency."""

import importlib
import sys


def test_python312_and_workspace_imports():
    assert sys.version_info[:2] == (3, 12)
    for name in ("qfr_core", "qfr_registry", "qfr_research", "qfr_eval", "qfr_mcp"):
        assert importlib.import_module(name).__doc__
