"""Operator catalog and fixed language rules of qfr-dsl/1 (PLAN Sections 7.2 and 7.3).

The values here define the language itself, so research and the evaluator can never
disagree about them. Tunable limits (complexity caps, allowed windows) come from the
protocol configuration instead; see qfr_core.dsl.analysis.DslLimits.
"""

import math
from dataclasses import dataclass
from typing import Literal

LANGUAGE: Literal["qfr-dsl/1"] = "qfr-dsl/1"

# Section 7.2: fields and the panel column that backs each one.
FIELD_COLUMNS: dict[str, str] = {
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "vwap": "vwap",
    "volume": "volume",
    "amount": "amount",
    "ret": "ret_1d",
    "adv20": "adv20",
    "close_raw": "close_raw",
}

# Section 7.2: non-window constants lie in [-10, 10] with at most 2 decimals.
CONSTANT_MIN = -10.0
CONSTANT_MAX = 10.0
CONSTANT_DECIMALS = 2

# Section 7.3: numeric rules.
DIVISION_EPSILON = 1e-12
VALIDITY_FRACTION = 0.8
FULL_VALIDITY_BELOW = 5

# Section 7.3: SignedPower exponents and the field Neutralize reads implicitly.
SIGNED_POWER_EXPONENTS = (0.5, 2.0, 3.0)
NEUTRALIZE_FIELD = "adv20"

ParamKind = Literal["series", "operand", "window", "const"]
OpKind = Literal["ts", "cs", "elementwise"]
Lookback = Literal["shift", "rolling", "none"]


@dataclass(frozen=True, slots=True)
class OpSpec:
    name: str
    kind: OpKind
    params: tuple[ParamKind, ...]
    min_window: int = 1
    lookback: Lookback = "none"
    commutative: bool = False

    @property
    def window_positions(self) -> tuple[int, ...]:
        return tuple(i for i, p in enumerate(self.params) if p == "window")


def _ts(name: str, min_window: int, lookback: Lookback = "rolling", pair: bool = False) -> OpSpec:
    params: tuple[ParamKind, ...] = ("series", "series", "window") if pair else ("series", "window")
    return OpSpec(name, "ts", params, min_window, lookback)


_SPECS = [
    _ts("Ref", 1, "shift"),
    _ts("Delta", 1, "shift"),
    _ts("Pct", 1, "shift"),
    _ts("Mean", 1),
    _ts("Sum", 1),
    _ts("Std", 2),
    _ts("Var", 2),
    _ts("Min", 1),
    _ts("Max", 1),
    _ts("Med", 1),
    _ts("EMA", 1),
    _ts("WMA", 1),
    _ts("TsRank", 2),
    _ts("TsZ", 2),
    _ts("ArgMax", 1),
    _ts("ArgMin", 1),
    _ts("Corr", 2, pair=True),
    _ts("Cov", 2, pair=True),
    _ts("Slope", 2),
    _ts("Rsq", 3),
    _ts("Resi", 3),
    _ts("Skew", 3),
    # Sample excess kurtosis needs four valid points; window 5 keeps ceil(0.8 * 5) = 4.
    _ts("Kurt", 5),
    OpSpec("Rank", "cs", ("series",)),
    OpSpec("Zscore", "cs", ("series",)),
    OpSpec("Demean", "cs", ("series",)),
    OpSpec("Scale", "cs", ("series",)),
    OpSpec("Neutralize", "cs", ("series",)),
    OpSpec("Abs", "elementwise", ("operand",)),
    OpSpec("Sign", "elementwise", ("operand",)),
    OpSpec("Log", "elementwise", ("operand",)),
    OpSpec("Sqrt", "elementwise", ("operand",)),
    OpSpec("SignedPower", "elementwise", ("operand", "const")),
    OpSpec("Clip", "elementwise", ("operand", "const", "const")),
    OpSpec("Max2", "elementwise", ("operand", "operand"), commutative=True),
    OpSpec("Min2", "elementwise", ("operand", "operand"), commutative=True),
    OpSpec("If", "elementwise", ("operand", "operand", "operand")),
]

OPERATORS: dict[str, OpSpec] = {spec.name: spec for spec in _SPECS}
COMMUTATIVE_BINARY = frozenset({"+", "*"})
CORR_COV = frozenset({"Corr", "Cov"})


def min_valid(days: int) -> int:
    """Section 7.3 validity rule: ceil(0.8 d) valid inputs when d >= 5, else all d."""
    if days < FULL_VALIDITY_BELOW:
        return days
    return math.ceil(VALIDITY_FRACTION * days)


def lookback_days(spec: OpSpec, days: int) -> int:
    """Trading days before t that one operator application reads.

    Ref, Delta and Pct read the value d days ago. A rolling window of d values ending
    at t reads d - 1 earlier days. Fields contribute nothing: they are panel columns.
    """
    if spec.lookback == "shift":
        return days
    if spec.lookback == "rolling":
        return days - 1
    return 0
