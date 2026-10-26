"""Pilot metric identities and basket arithmetic, independent of any evaluation protocol."""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

import numpy as np
import polars as pl
from pydantic import Field, PositiveInt

from qfr_core.contracts.base import Contract
from qfr_core.contracts.reports import MetricValue
from qfr_core.metrics.core import correlation, measurement


class PilotMetricConfig(Contract):
    revision: PositiveInt
    profile: Literal["pilot_industry_v1"]
    industry_count: int = Field(ge=3)
    selection_fraction: float = Field(gt=0, lt=0.5)
    costs_bps: list[float]
    weight_tolerance: float = Field(gt=0)
    zero_epsilon: float = Field(gt=0)


def drift_weights(weights: Mapping[str, float], returns: Mapping[str, float]) -> dict[str, float]:
    if any(
        code not in returns or not math.isfinite(returns[code]) or returns[code] <= -1
        for code in weights
    ):
        raise ValueError("missing or invalid return needed for weight drift")
    amounts = {code: value * (1 + returns[code]) for code, value in weights.items()}
    total = sum(amounts.values())
    if total <= 0:
        raise ValueError("nonpositive basket wealth")
    return {code: value / total for code, value in amounts.items()}


def transition(
    target: Mapping[str, float], previous: Mapping[str, float], tolerance: float
) -> dict[str, float]:
    for weights in [target, previous]:
        if any(not math.isfinite(value) or value < 0 for value in weights.values()):
            raise ValueError("basket weights must be finite and nonnegative")
        if weights and not math.isclose(sum(weights.values()), 1, rel_tol=0, abs_tol=tolerance):
            raise ValueError("basket weights must sum to one")
    changes = [
        target.get(code, 0) - previous.get(code, 0)
        for code in sorted(target.keys() | previous.keys())
    ]
    buy, sell = sum(max(x, 0) for x in changes), sum(max(-x, 0) for x in changes)
    traded = buy + sell
    return {
        "traded_notional": traded,
        "one_way_turnover": (traded + abs(sum(previous.values()) - sum(target.values()))) / 2,
        "buy_notional": buy,
        "sell_notional": sell,
    }


@dataclass(frozen=True)
class PilotMetrics:
    metrics: dict[str, MetricValue]
    next_weights: dict[str, dict[str, float]]


def pilot_metrics(
    predictions: pl.DataFrame,
    realized: pl.DataFrame,
    *,
    benchmark_return: float,
    config: PilotMetricConfig,
    previous_weights: Mapping[str, Mapping[str, float]] | None = None,
    liquidate: bool = False,
) -> PilotMetrics:
    """Inputs are one already-mature period; caller owns timing and released/official policy."""
    needed = {"code", "industry", "factor_score", "original", "rank", "selected"}
    if not needed <= set(predictions.columns) or not {"code", "industry", "return"} <= set(
        realized.columns
    ):
        raise ValueError("pilot metric input schema incomplete")
    if (
        realized.height != config.industry_count
        or realized["code"].n_unique() != config.industry_count
    ):
        raise ValueError("pilot reference universe mismatch")
    n = predictions.height
    count = math.ceil(n * config.selection_fraction)
    actual_count = math.ceil(config.industry_count * config.selection_fraction)
    if n < 2 or predictions["code"].n_unique() != n or predictions.schema["selected"] != pl.Boolean:
        raise ValueError("invalid pilot predictions")
    if sorted(predictions["rank"].to_list()) != list(range(1, n + 1)):
        raise ValueError("pilot ranks must be consecutive and unique")
    values = predictions.select("factor_score", "original").to_numpy()
    if (
        not np.isfinite(values).all()
        or not np.isfinite(realized["return"].to_numpy()).all()
        or not math.isfinite(benchmark_return)
    ):
        raise ValueError("missing period evidence; do not evaluate an immature period")
    joined = realized.join(predictions, on=["code", "industry"], how="left", validate="1:1")
    if joined["factor_score"].count() != n:
        raise ValueError("prediction mapping differs from reference universe")
    actual = realized.sort(["return", "industry"], descending=[True, False])
    true_top, true_bottom = (
        set(actual.head(actual_count)["code"]),
        set(actual.tail(actual_count)["code"]),
    )
    top = set(predictions.filter(pl.col("selected"))["code"])
    bottom = set(predictions.filter(pl.col("rank") > n - count)["code"])
    if len(top) != count or len(bottom) != count or top & bottom:
        raise ValueError("invalid or overlapping pilot selections")
    returns = dict(zip(realized["code"].to_list(), realized["return"].to_list(), strict=True))
    actual_class = {
        code: "top" if code in true_top else "bottom" if code in true_bottom else "middle"
        for code in returns
    }
    predicted_class = {
        code: "top" if code in top else "bottom" if code in bottom else "middle"
        for code in predictions["code"]
    }
    hits_top, hits_bottom = len(top & true_top), len(bottom & true_bottom)
    correct = {code: predicted_class.get(code) == bucket for code, bucket in actual_class.items()}
    recalls = [
        sum(correct[c] for c in returns if actual_class[c] == bucket)
        / sum(actual_class[c] == bucket for c in returns)
        for bucket in ["top", "middle", "bottom"]
    ]
    top_return, bottom_return = (
        float(np.mean([returns[c] for c in sorted(top)])),
        float(np.mean([returns[c] for c in sorted(bottom)])),
    )
    equal = float(np.mean(list(returns.values())))
    directional_top = sum(returns[c] > benchmark_return for c in top)
    directional_bottom = sum(returns[c] < benchmark_return for c in bottom)
    valid = joined.filter(pl.col("factor_score").is_not_null())
    raw = {
        "top_hits": float(hits_top),
        "bottom_hits": float(hits_bottom),
        "top_precision": hits_top / count,
        "bottom_precision": hits_bottom / count,
        "top_recall": hits_top / actual_count,
        "bottom_recall": hits_bottom / actual_count,
        "extreme_macro_recall": (hits_top + hits_bottom) / (2 * actual_count),
        "three_class_accuracy": sum(correct.values()) / config.industry_count,
        "three_class_balanced_accuracy": float(np.mean(recalls)),
        "directional_accuracy_vs_csi500": (directional_top + directional_bottom) / (2 * count),
        "directional_balanced_accuracy_vs_csi500": (
            directional_top / count + directional_bottom / count
        )
        / 2,
        "rank_ic": correlation(
            valid["factor_score"].to_numpy(),
            valid["return"].to_numpy(),
            ranked=True,
            epsilon=config.zero_epsilon,
        ),
        "action_rank_ic": correlation(
            valid["original"].to_numpy(),
            valid["return"].to_numpy(),
            ranked=True,
            epsilon=config.zero_epsilon,
        ),
        "top_return": top_return,
        "bottom_return": bottom_return,
        "equal31_return": equal,
        "top_bottom_spread": top_return - bottom_return,
        "top_excess_csi500": top_return - benchmark_return,
        "top_excess_equal31": top_return - equal,
        "coverage": n / config.industry_count,
    }
    next_weights = {}
    for side, codes, gross_return in [("top", top, top_return), ("bottom", bottom, bottom_return)]:
        target = {code: 1 / len(codes) for code in sorted(codes)}
        movement = transition(
            target, (previous_weights or {}).get(side, {}), config.weight_tolerance
        )
        raw.update({side + "_" + key: value for key, value in movement.items()})
        for cost in config.costs_bps:
            rate = cost / 10000
            if not math.isfinite(cost) or cost < 0 or rate * movement["traded_notional"] >= 1:
                raise ValueError("invalid or capital-exhausting cost scenario")
            net = (1 - rate * movement["traded_notional"]) * (1 + gross_return)
            if liquidate:
                net *= 1 - rate
            raw[f"{side}_net_return_{cost:g}bps"] = net - 1
            if side == "top":
                raw[f"top_excess_equal31_net_{cost:g}bps"] = net - 1 - equal
        next_weights[side] = {} if liquidate else drift_weights(target, returns)
    return PilotMetrics({name: measurement(value) for name, value in raw.items()}, next_weights)
