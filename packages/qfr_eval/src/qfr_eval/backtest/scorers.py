"""Trusted frozen P0/P1 scorers; no import or execution of uploaded source code."""

from dataclasses import dataclass

import numpy as np
import polars as pl
from qfr_core.metrics.core import Array
from qfr_core.pilot.baseline import Cycle, P0History, p0_history, p0_scores
from qfr_core.pilot.features import enrich_p0, price_features

from qfr_eval.protocols.models import FrozenProtocol


@dataclass(frozen=True)
class ScorerSpec:
    variant: str
    reversal_weight: float
    weekly_reversal_lag: int
    other_reversal_lag: int
    momentum_lookback: int


def built_in_history(
    features: pl.DataFrame,
    prices: pl.DataFrame,
    codes: list[str],
    protocol: FrozenProtocol,
    *,
    spec: ScorerSpec | None = None,
    allow_empty_history: bool = False,
) -> tuple[pl.DataFrame, P0History]:
    if features.filter(pl.col("available_date") > pl.col("date")).height:
        raise ValueError("fundamental availability exceeds observation date")
    panel = enrich_p0(features, prices, protocol.features)
    panel = price_features(panel, prices, codes, protocol.features)
    if spec is None:
        return panel, p0_history(panel, protocol.p0, allow_empty=allow_empty_history)
    if not 0 <= spec.reversal_weight <= 1:
        raise ValueError("invalid frozen scorer weight")
    # Extra neighbour features NEVER relax the original six-feature readiness mask.
    ready = panel["v4_ready"].to_numpy()
    alternative = protocol.features.model_copy(
        update={
            "reverse_windows": sorted({spec.weekly_reversal_lag, spec.other_reversal_lag}),
            "momentum_windows": [spec.momentum_lookback],
        }
    )
    extra = price_features(features, prices, codes, alternative)
    scores: dict[Cycle, Array] = {}
    for cycle in ("weekly", "monthly", "quarterly"):
        lag = spec.weekly_reversal_lag if cycle == "weekly" else spec.other_reversal_lag
        values = (
            spec.reversal_weight * extra[f"v4_p_reverse{lag}"].to_numpy()
            + (1 - spec.reversal_weight)
            * extra[f"v4_p_momentum{spec.momentum_lookback}_20"].to_numpy()
        )
        if not np.isfinite(values[ready]).all():
            raise ValueError("original-ready scorer has missing alternate features")
        scores[cycle] = np.where(ready, values, p0_scores(panel, cycle, protocol.p0))
    return panel, p0_history(panel, protocol.p0, scores, allow_empty=allow_empty_history)
