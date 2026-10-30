"""Evaluate a canonical qfr-dsl/1 tree on the dense panel with Polars (PLAN Section 7.3).

The panel must be sorted by instrument and date. Time-series operators run per
instrument (`over("instrument")`), cross-sectional operators per date over the eligible
cross-section (`over("date")`). Every intermediate is float64 with nulls; NaN and
infinities become null, and division by a denominator below 1e-12 in absolute value
yields null. Each time-series or cross-sectional node is materialized as a temporary
column so window expressions are never nested.
"""

from collections.abc import Callable

import numpy as np
import polars as pl

from qfr_core.dsl.ast import BinOp, Call, Compare, Field, Neg, Node, Num, Window
from qfr_core.dsl.catalog import DIVISION_EPSILON, FIELD_COLUMNS, NEUTRALIZE_FIELD, OPERATORS
from qfr_core.dsl.catalog import min_valid as _min_valid
from qfr_core.eligibility import Eligibility
from qfr_core.operators import kernels

INSTRUMENT = "instrument"
DATE = "date"
_ELIGIBLE = "__eligible"

Kernel = Callable[[kernels.Array, int], kernels.Array]
PairKernel = Callable[[kernels.Array, kernels.Array, int], kernels.Array]

_KERNELS: dict[str, Kernel] = {
    "Std": kernels.std,
    "Var": kernels.variance,
    "TsZ": kernels.ts_zscore,
    "Skew": kernels.skew,
    "Kurt": kernels.kurt,
    "Slope": kernels.slope,
    "Rsq": kernels.rsq,
    "Resi": kernels.resi,
    "WMA": kernels.wma,
    "ArgMax": kernels.argmax,
    "ArgMin": kernels.argmin,
}
_PAIR_KERNELS: dict[str, PairKernel] = {"Corr": kernels.corr, "Cov": kernels.cov}


def clean(expr: pl.Expr) -> pl.Expr:
    """Null for NaN and infinities."""
    return pl.when(expr.is_finite()).then(expr).otherwise(None)


def safe_divide(numerator: pl.Expr, denominator: pl.Expr) -> pl.Expr:
    return clean(
        pl.when(denominator.abs() >= DIVISION_EPSILON).then(numerator / denominator).otherwise(None)
    )


def _series_kernel(kernel: Kernel, days: int) -> Callable[[pl.Series], pl.Series]:
    def run(series: pl.Series) -> pl.Series:
        values = series.cast(pl.Float64).to_numpy().astype(np.float64)
        return pl.Series(kernel(values, days), dtype=pl.Float64, nan_to_null=True)

    return run


def _pair_kernel(kernel: PairKernel, days: int) -> Callable[[pl.Series], pl.Series]:
    def run(series: pl.Series) -> pl.Series:
        a = series.struct.field("a").cast(pl.Float64).to_numpy().astype(np.float64)
        b = series.struct.field("b").cast(pl.Float64).to_numpy().astype(np.float64)
        return pl.Series(kernel(a, b, days), dtype=pl.Float64, nan_to_null=True)

    return run


def check_sorted(panel: pl.DataFrame) -> None:
    ordered = panel.select(
        (
            (pl.col(INSTRUMENT) > pl.col(INSTRUMENT).shift(1))
            | (
                (pl.col(INSTRUMENT) == pl.col(INSTRUMENT).shift(1))
                & (pl.col(DATE) > pl.col(DATE).shift(1))
            )
        )
        .slice(1)
        .all()
    ).item()
    if ordered is False:
        raise ValueError("the panel must be sorted by instrument and date without duplicates")


class _Evaluator:
    def __init__(self, panel: pl.DataFrame, eligibility: Eligibility, tree: Node) -> None:
        check_sorted(panel)
        needed = {FIELD_COLUMNS[name] for name in _fields(tree)}
        self.frame = panel.select(
            pl.col(INSTRUMENT),
            pl.col(DATE),
            *[pl.col(c).cast(pl.Float64) for c in sorted(needed)],
            eligibility.mask().alias(_ELIGIBLE),
        )
        self.minimum = eligibility.cross_section_min
        self.counter = 0

    def materialize(self, expr: pl.Expr) -> pl.Expr:
        name = f"__n{self.counter}"
        self.counter += 1
        # Lazy collection enables common-subexpression elimination for the guards.
        self.frame = self.frame.lazy().with_columns(clean(expr).alias(name)).collect()
        return pl.col(name)

    def expr(self, node: Node) -> pl.Expr:
        if isinstance(node, Num):
            return pl.lit(node.value, dtype=pl.Float64)
        if isinstance(node, Field):
            return pl.col(FIELD_COLUMNS[node.name])
        if isinstance(node, Neg):
            return clean(-self.expr(node.operand))
        if isinstance(node, BinOp):
            left, right = self.expr(node.left), self.expr(node.right)
            if node.op == "+":
                return clean(left + right)
            if node.op == "-":
                return clean(left - right)
            if node.op == "*":
                return clean(left * right)
            return safe_divide(left, right)
        if isinstance(node, Compare):
            left, right = self.expr(node.left), self.expr(node.right)
            compared = {
                ">": left > right,
                "<": left < right,
                ">=": left >= right,
                "<=": left <= right,
            }[node.op]
            return compared.cast(pl.Float64)
        if isinstance(node, Window):
            raise ValueError("windows are evaluated by their operator")
        return self.call(node)

    def call(self, node: Call) -> pl.Expr:
        spec = OPERATORS[node.name]
        if spec.kind == "ts":
            return self.time_series(node)
        if spec.kind == "cs":
            return self.cross_section(node)
        return self.elementwise(node)

    def time_series(self, node: Call) -> pl.Expr:
        window = node.args[-1]
        assert isinstance(window, Window)
        days = window.days
        need = _min_valid(days)
        if node.name in _PAIR_KERNELS:
            a = self.materialize(self.expr(node.args[0]))
            b = self.materialize(self.expr(node.args[1]))
            pair = pl.struct(a.alias("a"), b.alias("b"))
            run = _pair_kernel(_PAIR_KERNELS[node.name], days)
            out = pair.map_batches(run, return_dtype=pl.Float64).over(INSTRUMENT)
            return self.materialize(out)
        x = self.materialize(self.expr(node.args[0]))
        name = node.name
        if name in _KERNELS:
            run_one = _series_kernel(_KERNELS[name], days)
            out = x.map_batches(run_one, return_dtype=pl.Float64).over(INSTRUMENT)
        elif name == "Ref":
            out = x.shift(days).over(INSTRUMENT)
        elif name == "Delta":
            out = x - x.shift(days).over(INSTRUMENT)
        elif name == "Pct":
            out = safe_divide(x, x.shift(days).over(INSTRUMENT)) - 1.0
        elif name == "Mean":
            out = x.rolling_mean(days, min_samples=need).over(INSTRUMENT)
        elif name == "Sum":
            out = x.rolling_sum(days, min_samples=need).over(INSTRUMENT)
        elif name == "Min":
            out = x.rolling_min(days, min_samples=need).over(INSTRUMENT)
        elif name == "Max":
            out = x.rolling_max(days, min_samples=need).over(INSTRUMENT)
        elif name == "Med":
            out = x.rolling_median(days, min_samples=need).over(INSTRUMENT)
        elif name == "EMA":
            out = x.ewm_mean(
                alpha=2.0 / (days + 1), adjust=False, min_samples=days, ignore_nulls=True
            ).over(INSTRUMENT)
        elif name == "TsRank":
            rank = self.materialize(
                x.rolling_rank(days, method="average", min_samples=need).over(INSTRUMENT)
            )
            count = self.materialize(
                x.is_not_null().cast(pl.Float64).rolling_sum(days, min_samples=1).over(INSTRUMENT)
            )
            out = safe_divide(rank - 1.0, count - 1.0)
        else:
            raise ValueError(f"unhandled time-series operator {name}")
        return self.materialize(out)

    def cross_section(self, node: Call) -> pl.Expr:
        # Window aggregates are materialized one at a time: guards that repeat a window
        # expression would otherwise recompute it.
        source = self.materialize(self.expr(node.args[0]))
        x = self.materialize(pl.when(pl.col(_ELIGIBLE)).then(source).otherwise(None))
        if node.name == "Neutralize":
            size = pl.col(FIELD_COLUMNS[NEUTRALIZE_FIELD])
            log_size = pl.when(size > 0).then(size.log()).otherwise(None)
            joint = x.is_not_null() & log_size.is_not_null()
            x = self.materialize(pl.when(joint).then(x).otherwise(None))
            u = self.materialize(pl.when(joint).then(log_size).otherwise(None))
        count = self.materialize(x.count().over(DATE).cast(pl.Float64))
        enough = count >= self.minimum
        if node.name == "Rank":
            rank = self.materialize(x.rank("average").over(DATE))
            out = safe_divide(rank - 1.0, count - 1.0)
        elif node.name in {"Zscore", "Demean"}:
            dev = self.materialize(x - x.mean().over(DATE))
            if node.name == "Demean":
                out = dev
            else:
                squares = self.materialize((dev**2).sum().over(DATE))
                spread = self.materialize((squares / (count - 1.0)).sqrt())
                out = safe_divide(dev, spread)
        elif node.name == "Scale":
            total = self.materialize(x.abs().sum().over(DATE))
            out = safe_divide(x, total)
        elif node.name == "Neutralize":
            dx = self.materialize(x - x.mean().over(DATE))
            du = self.materialize(u - u.mean().over(DATE))
            cross = self.materialize((dx * du).sum().over(DATE))
            squares = self.materialize((du**2).sum().over(DATE))
            beta = self.materialize(safe_divide(cross, squares))
            out = dx - beta * du
        else:
            raise ValueError(f"unhandled cross-sectional operator {node.name}")
        return self.materialize(pl.when(enough).then(out).otherwise(None))

    def elementwise(self, node: Call) -> pl.Expr:
        args = [self.expr(a) for a in node.args]
        name = node.name
        if name == "Abs":
            return args[0].abs()
        if name == "Sign":
            return args[0].sign().cast(pl.Float64)
        if name == "Log":
            return pl.when(args[0] > 0).then(args[0].log()).otherwise(None)
        if name == "Sqrt":
            return pl.when(args[0] >= 0).then(args[0].sqrt()).otherwise(None)
        if name == "SignedPower":
            exponent = node.args[1]
            assert isinstance(exponent, Num)
            return clean(args[0].sign() * args[0].abs().pow(exponent.value))
        if name == "Clip":
            low, high = node.args[1], node.args[2]
            assert isinstance(low, Num) and isinstance(high, Num)
            return args[0].clip(low.value, high.value)
        if name in {"Max2", "Min2"}:
            either_null = args[0].is_null() | args[1].is_null()
            combined = (
                pl.max_horizontal(args[0], args[1])
                if name == "Max2"
                else pl.min_horizontal(args[0], args[1])
            )
            return pl.when(either_null).then(None).otherwise(combined)
        if name == "If":
            condition = args[0]
            return (
                pl.when(condition.is_null())
                .then(None)
                .when(condition != 0)
                .then(args[1])
                .otherwise(args[2])
            )
        raise ValueError(f"unhandled element-wise operator {name}")


def _fields(node: Node) -> set[str]:
    found: set[str] = set()
    if isinstance(node, Field):
        found.add(node.name)
    if isinstance(node, Call):
        if node.name == "Neutralize":
            found.add(NEUTRALIZE_FIELD)
        for arg in node.args:
            found |= _fields(arg)
    elif isinstance(node, (BinOp, Compare)):
        found |= _fields(node.left) | _fields(node.right)
    elif isinstance(node, Neg):
        found |= _fields(node.operand)
    return found


def evaluate(panel: pl.DataFrame, tree: Node, eligibility: Eligibility) -> pl.Series:
    """Factor values aligned with the panel's rows, as a float64 Series named "factor"."""
    evaluator = _Evaluator(panel, eligibility, tree)
    result = evaluator.materialize(evaluator.expr(tree).cast(pl.Float64))
    return evaluator.frame.select(result.alias("factor")).to_series()
