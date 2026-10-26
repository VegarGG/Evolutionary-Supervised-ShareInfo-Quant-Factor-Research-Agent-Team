"""Causal Polars operator execution, materializing nested windows in dependency order."""

import math
from collections.abc import Sequence
from functools import partial
from typing import cast

import numpy as np
import polars as pl

from qfr_core.data_layer.snapshots import normalize_table
from qfr_core.dsl.language import (
    CROSS,
    TIME_BINARY,
    TIME_UNARY,
    DSLConfig,
    Node,
    analyze,
    canonicalize,
    parse,
)


def _divide(a: pl.Expr, b: pl.Expr, epsilon: float) -> pl.Expr:
    return pl.when(b.abs() >= epsilon).then(a / b).otherwise(None)


def _window(name: str, series: pl.Series, distance: int, epsilon: float) -> float | None:
    values = series.to_numpy()
    good = np.isfinite(values)
    clean = values[good]
    if not len(clean):
        return None
    if name == "WMA":
        weights = np.arange(distance - len(values) + 1, distance + 1)[good]
        return float(np.dot(weights, clean) / weights.sum())
    if name == "TsRank":
        if not good[-1]:
            return None
        return float(
            (np.sum(clean < values[-1]) + (np.sum(clean == values[-1]) + 1) / 2) / len(clean)
        )
    if name in {"ArgMax", "ArgMin"}:
        target = clean.max() if name == "ArgMax" else clean.min()
        return float(len(values) - 1 - np.flatnonzero(values == target)[-1])
    if len(clean) < 2:
        return None
    time = np.arange(len(values), dtype=np.float64)[good]
    centered = time - time.mean()
    slope = float(np.dot(centered, clean - clean.mean()) / np.dot(centered, centered))
    if name == "Slope":
        return slope
    prediction = clean.mean() + slope * centered
    if name == "Resi":
        return (
            float(values[-1] - (clean.mean() + slope * (len(values) - 1 - time.mean())))
            if good[-1]
            else None
        )
    variance = float(np.sum((clean - clean.mean()) ** 2))
    if name == "Rsq":
        return (
            1 - float(np.sum((clean - prediction) ** 2)) / variance if variance >= epsilon else None
        )
    raise ValueError(f"unknown rolling callback: {name}")


def _neutralize(series: Sequence[pl.Series], epsilon: float) -> pl.Series:
    y, adv = (value.to_numpy() for value in series)
    good = np.isfinite(y) & np.isfinite(adv) & (adv > 0)
    output = np.full(len(y), np.nan)
    if np.count_nonzero(good) >= 2:
        x = np.log(adv[good])
        centered = x - x.mean()
        variance = float(centered @ centered)
        if variance >= epsilon:
            slope = float(centered @ (y[good] - y[good].mean()) / variance)
            output[good] = y[good] - (y[good].mean() + slope * centered)
    return pl.Series(output, nan_to_null=True)


def _time_operator(name: str, inputs: list[str], distance: int, config: DSLConfig) -> pl.Expr:
    x = pl.col(inputs[0])
    min_samples = (
        distance
        if distance < config.full_window_below
        else math.ceil(config.rolling_valid_fraction * distance)
    )
    eps = config.zero_epsilon
    if name in {"Ref", "Delta", "Pct"}:
        prior = x.shift(distance)
        value = (
            prior if name == "Ref" else x - prior if name == "Delta" else _divide(x, prior, eps) - 1
        )
        return value.over("instrument")
    standard = {
        "Mean": "rolling_mean",
        "Sum": "rolling_sum",
        "Std": "rolling_std",
        "Var": "rolling_var",
        "Min": "rolling_min",
        "Max": "rolling_max",
        "Med": "rolling_median",
    }
    if name in standard:
        value = cast(pl.Expr, getattr(x, standard[name])(distance, min_samples=min_samples))
    elif name in TIME_BINARY:
        y = pl.col(inputs[1])
        both = x.is_not_null() & y.is_not_null()
        function = pl.rolling_corr if name == "Corr" else pl.rolling_cov
        value = function(
            pl.when(both).then(x),
            pl.when(both).then(y),
            window_size=distance,
            min_samples=min_samples,
            ddof=1,
        )
    elif name == "EMA":
        value = x.ewm_mean(
            alpha=2 / (distance + 1), adjust=False, min_samples=distance, ignore_nulls=False
        )
        enough = x.is_not_null().cast(pl.Int32).rolling_sum(distance, min_samples=1) >= min_samples
        value = pl.when(enough).then(value).otherwise(None)
    elif name == "TsZ":
        value = _divide(
            x - x.rolling_mean(distance, min_samples=min_samples),
            x.rolling_std(distance, min_samples=min_samples),
            eps,
        )
    elif name in {"Skew", "Kurt"}:
        value = (
            x.rolling_skew(distance, min_samples=min_samples, bias=False)
            if name == "Skew"
            else x.rolling_kurtosis(distance, min_samples=min_samples, bias=False, fisher=True)
        )
    else:
        value = x.rolling_map(
            partial(_window, name, distance=distance, epsilon=eps),
            distance,
            min_samples=min_samples,
        )
    return value.over("instrument")


def _cross_operator(name: str, value: pl.Expr, eligible: pl.Expr, config: DSLConfig) -> pl.Expr:
    x = pl.when(eligible).then(value).otherwise(None)
    if name == "Rank":
        return _divide(
            x.rank(method="average").over("date"), x.count().over("date"), config.zero_epsilon
        )
    if name == "Zscore":
        return _divide(x - x.mean().over("date"), x.std(ddof=1).over("date"), config.zero_epsilon)
    if name == "Demean":
        return x - x.mean().over("date")
    if name == "Scale":
        return _divide(x, x.abs().sum().over("date"), config.zero_epsilon)
    if name == "Neutralize":
        return pl.map_groups(
            [x, pl.col("adv20")],
            partial(_neutralize, epsilon=config.zero_epsilon),
            return_dtype=pl.Float64,
            returns_scalar=False,
        ).over("date")
    raise ValueError(f"unknown cross-sectional operator: {name}")


def evaluate(
    expression: str | Node,
    panel: pl.DataFrame,
    config: DSLConfig,
    *,
    eligible_column: str | None = None,
) -> pl.DataFrame:
    """Return instrument/date/value in canonical order. Policy is explicit and versioned."""
    node = parse(expression, config) if isinstance(expression, str) else expression
    analyze(node, config)
    node = canonicalize(node, config)
    if any(name.startswith("__qfr_dsl_") for name in panel.columns):
        raise ValueError("reserved DSL temporary column")
    if eligible_column is not None and panel.schema.get(eligible_column) != pl.Boolean:
        raise ValueError("eligible cross-section requires a Boolean column")
    frame = normalize_table(panel, ["instrument", "date"])
    cache: dict[Node, str] = {}
    eligibility = pl.col(eligible_column).fill_null(False) if eligible_column else pl.lit(True)

    def run(item: Node) -> str:
        nonlocal frame
        if item in cache:
            return cache[item]
        if item.op == "field":
            field = "ret_1d" if item.value == "$ret" else item.value[1:]
            if field not in frame.columns or not frame.schema[field].is_numeric():
                raise ValueError(f"missing or nonnumeric field: {field}")
            result = pl.col(field).cast(pl.Float64)
        elif item.op == "number":
            result = pl.lit(float(item.value))
        elif item.op in TIME_UNARY | TIME_BINARY:
            distance = int(item.args[-1].value)
            result = _time_operator(item.op, [run(c) for c in item.args[:-1]], distance, config)
        else:
            inputs = [pl.col(run(c)) for c in item.args]
            x = inputs[0]
            if item.op in CROSS:
                if item.op == "Neutralize" and "adv20" not in frame.columns:
                    raise ValueError("Neutralize requires adv20")
                result = _cross_operator(item.op, x, eligibility, config)
            elif item.op in {"+", "-", "*", "/", ">", "<", ">=", "<="}:
                y = inputs[1]
                result = {
                    "+": lambda: x + y,
                    "-": lambda: x - y,
                    "*": lambda: x * y,
                    "/": lambda: _divide(x, y, config.zero_epsilon),
                    ">": lambda: x > y,
                    "<": lambda: x < y,
                    ">=": lambda: x >= y,
                    "<=": lambda: x <= y,
                }[item.op]()
            elif item.op == "neg":
                result = -x
            elif item.op in {"Abs", "Sign", "Log", "Sqrt"}:
                result = {"Abs": x.abs, "Sign": x.sign, "Log": x.log, "Sqrt": x.sqrt}[item.op]()
            elif item.op == "SignedPower":
                result = x.sign() * x.abs().pow(inputs[1])
            elif item.op == "Clip":
                result = x.clip(inputs[1], inputs[2])
            elif item.op in {"Max2", "Min2"}:
                function = pl.max_horizontal if item.op == "Max2" else pl.min_horizontal
                result = pl.when(x.is_not_null() & inputs[1].is_not_null()).then(function(*inputs))
            elif item.op == "If":
                result = pl.when(x.is_not_null()).then(
                    pl.when(x != 0).then(inputs[1]).otherwise(inputs[2])
                )
            else:
                raise ValueError(f"unsupported operator: {item.op}")
        name = f"__qfr_dsl_{len(cache)}"
        frame = frame.with_columns(result.cast(pl.Float64).alias(name))
        frame = frame.with_columns(
            pl.when(pl.col(name).is_finite()).then(pl.col(name)).otherwise(None).alias(name)
        )
        cache[item] = name
        return name

    output = run(node)
    return frame.select("instrument", "date", pl.col(output).alias("value"))
