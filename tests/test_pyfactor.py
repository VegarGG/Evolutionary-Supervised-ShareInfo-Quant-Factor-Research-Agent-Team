"""qfr-python/1 static rules (P8.1): the first layer in front of the sandbox."""

from pathlib import Path

import pytest
import yaml
from qfr_core.pyfactor import (
    BANNED_ATTRIBUTES,
    PythonLimits,
    canonical_hash,
    check_source,
    declaration_errors,
)

PROTOCOL = yaml.safe_load(Path("configs/protocols/cn_csi300_daily_v1.yaml").read_text())
LIMITS = PythonLimits.from_protocol(PROTOCOL)

GOOD = '''"""Volume-scaled reversal."""
import numpy as np
import math

WINDOW = 10


def zscore(x):
    mu = np.nanmean(x, axis=1, keepdims=True)
    sd = np.nanstd(x, axis=1, keepdims=True)
    return np.where(sd > 0, (x - mu) / sd, np.nan)


def factor(close, volume, eligible):
    out = np.full_like(close, np.nan)
    ret = close[WINDOW:] / close[:-WINDOW] - 1
    out[WINDOW:] = -ret * np.log1p(volume[WINDOW:]) / math.sqrt(WINDOW)
    return np.where(eligible, zscore(out), np.nan)
'''


def errors(source: str) -> list[str]:
    return [e.code for e in check_source(source, LIMITS).errors]


def test_a_well_formed_module_passes_and_names_its_fields():
    check = check_source(GOOD, LIMITS)
    assert check.ok, check.errors
    assert check.analysis is not None
    assert check.analysis.fields == ["close", "volume"]
    assert check.analysis.parameters == ["close", "volume", "eligible"]
    assert check.analysis.uses_eligible


def test_the_canonical_hash_ignores_comments_docstrings_and_formatting():
    import ast

    reformatted = GOOD.replace('"""Volume-scaled reversal."""', "# a comment").replace(
        "WINDOW = 10", "WINDOW  =  10   # ten days"
    )
    assert canonical_hash(ast.parse(GOOD)) == canonical_hash(ast.parse(reformatted))
    changed = GOOD.replace("WINDOW = 10", "WINDOW = 11")
    assert canonical_hash(ast.parse(GOOD)) != canonical_hash(ast.parse(changed))


@pytest.mark.parametrize(
    "body",
    [
        "import os\ndef factor(close):\n    return close",
        "import numpy\ndef factor(close):\n    return close",
        "import socket as np\ndef factor(close):\n    return close",
        "from numpy import save\ndef factor(close):\n    return close",
        "import numpy as np\ndef factor(close):\n    return np.load('x')",
        "import numpy as np\ndef factor(close):\n    np.save('x', close)\n    return close",
        "import numpy as np\ndef factor(close):\n    close.tofile('x')\n    return close",
        "import numpy as np\ndef factor(close):\n    return np.random.rand(*close.shape)",
        "def factor(close):\n    return open('/etc/passwd')",
        "def factor(close):\n    return __import__('os')",
        "def factor(close):\n    return close.__class__",
        "def factor(close):\n    return getattr(close, 'tofile')",
        "def factor(close):\n    return eval('1')",
        "def factor(close):\n    exec('x = 1')\n    return close",
        "def factor(close):\n    return globals()",
        "def factor(close):\n    return vars(close)",
        "def factor(close):\n    return type(close)",
        "def factor(close):\n    g = (x for x in [1])\n    return g.gi_frame.f_back",
        "def factor(close):\n    return '{0.__class__}'.format(close)",
        "def factor(close):\n    return f'{close}'",
        "def factor(close):\n    try:\n        return close\n    except Exception:\n        pass",
        "def factor(close):\n    with close:\n        return close",
        "def factor(close):\n    raise ValueError()",
        "def factor(close):\n    global x\n    return close",
        "class A:\n    pass\ndef factor(close):\n    return close",
        "async def factor(close):\n    return close",
        "def factor(close):\n    yield close",
        "print('hi')\ndef factor(close):\n    return close",
        "x = [1, 2]\ndef factor(close):\n    return close",
        "def factor(close):\n    return b'abc'",
        "def factor(close):\n    np = 1\n    return close",
        "import numpy as np\ndef factor(close):\n    np.nanmean = None\n    return close",
        "def factor(close, **kwargs):\n    return close",
        "def factor(close, *args):\n    return close",
        "@staticmethod\ndef factor(close):\n    return close",
        "def factor(close):\n    return close.ctypes",
        "def factor(close):\n    return close.base",
        "def factor(date, close):\n    return close",
        "def factor(instrument):\n    return instrument",
        "def factor(eligible):\n    return eligible",
        "def factor(close, close):\n    return close",
        "def factor(close=None):\n    return close",
        "def helper(close):\n    return close",
        "def factor(close):\n    return close\ndef factor(close):\n    return close",
    ],
)
def test_forbidden_constructs_are_refused_statically(body):
    check = check_source(body, LIMITS)
    assert not check.ok
    assert {e.code for e in check.errors} <= {"FORBIDDEN_CONSTRUCT", "PARSE_ERROR"}


def test_parse_errors_and_size_limits():
    assert errors("def factor(close:\n") == ["PARSE_ERROR"]
    long = "def factor(close):\n    return close\n" + "#" * LIMITS.max_source_chars
    assert errors(long) == ["COMPLEXITY_LIMIT"]
    wide = "def factor(close):\n    return [" + ", ".join(["close"] * 2100) + "]\n"
    assert errors(wide) == ["COMPLEXITY_LIMIT"]
    for deep in (
        "def factor(close):\n    return " + " + ".join(["close"] * 1200) + "\n",
        "def factor(close):\n    return " + "-" * 5000 + "close\n",
        "def factor(close):\n    return " + "[" * 90 + "close" + "]" * 90 + "\n",
    ):
        assert errors(deep) == ["COMPLEXITY_LIMIT"]


def test_declarations_must_match_the_parameters_and_respect_the_lookback_cap():
    analysis = check_source(GOOD, LIMITS).analysis
    assert analysis is not None
    assert declaration_errors(analysis, ["close", "volume"], 10, 250) == []
    codes = [e.code for e in declaration_errors(analysis, ["close"], 10, 250)]
    assert codes == ["DECLARATION_MISMATCH"]
    codes = [e.code for e in declaration_errors(analysis, ["close", "volume"], 400, 250)]
    assert codes == ["COMPLEXITY_LIMIT"]


def test_frame_and_buffer_attributes_are_on_the_ban_list():
    for name in ("gi_frame", "f_back", "f_globals", "tb_frame", "co_code", "tobytes", "ctypes"):
        assert name in BANNED_ATTRIBUTES
