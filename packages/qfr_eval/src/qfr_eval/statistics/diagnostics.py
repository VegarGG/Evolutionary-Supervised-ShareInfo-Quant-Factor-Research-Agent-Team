"""Predeclared time/placebo diagnostics; never used to retune frozen candidates."""

from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np
import polars as pl
from qfr_core.metrics.core import Array
from scipy.stats import rankdata


@dataclass(frozen=True)
class CrossSections:
    identities: tuple[str, ...]
    codes: tuple[str, ...]
    returns: Array
    top_truth: np.ndarray
    bottom_truth: np.ndarray
    scores: dict[str, Array]
    top_selected: dict[str, np.ndarray]
    bottom_selected: dict[str, np.ndarray]


def aligned_cross_sections(outcomes: dict[str, pl.DataFrame]) -> CrossSections:
    if not outcomes:
        raise ValueError("named outcome arms required")
    first = next(iter(outcomes.values())).sort(["execution_date", "period_key", "code"])
    if first["model_cycle"].n_unique() != 1:
        raise ValueError("diagnostics cannot mix cycles")
    dates = (
        first.select("execution_date", "period_key").unique().sort(["execution_date", "period_key"])
    )
    keys = dates["period_key"].to_list()
    codes = sorted(first["code"].unique().to_list())
    order = {key: i for i, key in enumerate(keys)}
    values = {}
    for name, frame in outcomes.items():
        if (
            frame["model_cycle"].n_unique() != 1
            or frame["model_cycle"][0] != first["model_cycle"][0]
        ):
            raise ValueError("diagnostic cycles differ")
        if frame.select("period_key", "code").is_duplicated().any():
            raise ValueError("duplicate outcome identity")
        if (
            set(frame["period_key"]) != set(keys)
            or sorted(frame["code"].unique().to_list()) != codes
        ):
            raise ValueError("diagnostics require identical complete cohorts")
        frame = frame.with_columns(pl.col("period_key").replace_strict(order).alias("_order")).sort(
            ["_order", "code"]
        )
        if frame.height != len(keys) * len(codes):
            raise ValueError("missing outcome cross-section")
        if frame.select(
            pl.any_horizontal(
                pl.col("actual_return", "factor_score").is_null()
                | ~pl.col("actual_return", "factor_score").is_finite()
            ).any()
        ).item():
            raise ValueError("missing prediction or outcome")
        values[name] = {
            field: frame[field].to_numpy().reshape(len(keys), len(codes))
            for field in ["actual_return", "actual_bucket", "selection_bucket", "factor_score"]
        }
    reference = next(iter(values.values()))
    for bucket in ("top", "bottom"):
        if ((reference["actual_bucket"] == bucket).sum(axis=1) == 0).any():
            raise ValueError("empty realized extreme bucket")
    if any(
        not np.array_equal(v["actual_return"], reference["actual_return"])
        or not np.array_equal(v["actual_bucket"], reference["actual_bucket"])
        for v in values.values()
    ):
        raise ValueError("arms have different realized cross-sections")
    return CrossSections(
        tuple(keys),
        tuple(codes),
        reference["actual_return"],
        reference["actual_bucket"] == "top",
        reference["actual_bucket"] == "bottom",
        {k: v["factor_score"] for k, v in values.items()},
        {k: v["selection_bucket"] == "top" for k, v in values.items()},
        {k: v["selection_bucket"] == "bottom" for k, v in values.items()},
    )


def _arm_metrics(
    data: CrossSections, truth: Array, top: np.ndarray, bottom: np.ndarray
) -> dict[str, dict[str, float]]:
    y = rankdata(truth, method="average", axis=1)
    y -= y.mean(axis=1, keepdims=True)
    result = {}
    for arm, score in data.scores.items():
        ranked = rankdata(score, method="average", axis=1)
        ranked -= ranked.mean(axis=1, keepdims=True)
        top_recall = np.sum(data.top_selected[arm] * top, axis=1) / top.sum(axis=1)
        bottom_recall = np.sum(data.bottom_selected[arm] * bottom, axis=1) / bottom.sum(axis=1)
        denominator = np.sqrt(np.sum(ranked**2, axis=1) * np.sum(y**2, axis=1))
        if (denominator <= 0).any():
            raise ValueError("degenerate placebo cross-section")
        result[arm] = {
            "extreme_macro_recall": float(np.mean((top_recall + bottom_recall) / 2)),
            "rank_ic": float(np.mean(np.sum(ranked * y, axis=1) / denominator)),
        }
    return result


def calendar_shift(
    data: CrossSections,
    *,
    baseline: str,
    candidate: str,
    minimum_distance: int,
    equality_atol: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    n = len(data.identities)
    shifts = [s for s in range(1, n) if min(s, n - s) >= minimum_distance]
    if not shifts or minimum_distance < 1:
        raise ValueError("insufficient calendar-shift resolution")
    rows: list[dict[str, Any]] = []
    for shift in [0, *shifts]:
        result = _arm_metrics(
            data,
            np.roll(data.returns, shift, axis=0),
            np.roll(data.top_truth, shift, axis=0),
            np.roll(data.bottom_truth, shift, axis=0),
        )
        result["candidate_minus_baseline"] = {
            m: result[candidate][m] - result[baseline][m] for m in result[baseline]
        }
        rows.extend(dict(variant=arm, shift=shift, **metrics) for arm, metrics in result.items())
    summary = []
    for arm in [*data.scores, "candidate_minus_baseline"]:
        observed = next(r for r in rows if r["variant"] == arm and r["shift"] == 0)
        for metric in ["extreme_macro_recall", "rank_ic"]:
            sample = np.array([r[metric] for r in rows if r["variant"] == arm and r["shift"] != 0])
            same = np.isclose(sample, observed[metric], atol=equality_atol, rtol=0)
            below = (sample < observed[metric]) & ~same
            above = (sample > observed[metric]) & ~same
            summary.append(
                dict(
                    variant=arm,
                    metric=metric,
                    mature_periods=n,
                    minimum_shift_distance=minimum_distance,
                    exact_available_shifts=len(shifts),
                    observed=observed[metric],
                    shifted_mean=float(sample.mean()),
                    shifted_min=float(sample.min()),
                    shifted_max=float(sample.max()),
                    shifted_q025=float(np.quantile(sample, 0.025)),
                    shifted_q975=float(np.quantile(sample, 0.975)),
                    shifts_below_observed=int(below.sum()),
                    shifts_equal_observed=int(same.sum()),
                    shifts_above_observed=int(above.sum()),
                    observed_empirical_midrank_percentile=100
                    * float(below.sum() + 0.5 * same.sum())
                    / len(shifts),
                    inferential_p_value_claimed=False,
                )
            )
    return summary, rows


def within_date_permutation(
    data: CrossSections, *, baseline: str, candidate: str, draws: int, seed: int
) -> dict[str, Any]:
    if draws < 1 or not data.identities:
        raise ValueError("permutation requires observations and configured draws")
    original = _arm_metrics(data, data.returns, data.top_truth, data.bottom_truth)
    observed = {m: original[candidate][m] - original[baseline][m] for m in original[baseline]}
    rng = np.random.Generator(np.random.PCG64(seed))
    exceed = {m: 0 for m in observed}
    for _ in range(draws):
        # One permutation per date, shared by ALL arms and metric/cost layers.
        permutation = np.stack([rng.permutation(len(data.codes)) for _ in data.identities])
        shuffled = [
            np.take_along_axis(a, permutation, axis=1)
            for a in (data.returns, data.top_truth, data.bottom_truth)
        ]
        result = _arm_metrics(data, *shuffled)
        for metric in observed:
            exceed[metric] += (
                result[candidate][metric] - result[baseline][metric] >= observed[metric]
            )
    return dict(
        seed=seed,
        draws=draws,
        resolution=1 / (draws + 1),
        observed=observed,
        empirical_upper_tail={m: (int(k) + 1) / (draws + 1) for m, k in exceed.items()},
        inferential_p_value_claimed=False,
    )


def exclude_year(frame: pl.DataFrame, metric: str, year: int) -> Array:
    """Keep removed slots as NaN; never join disconnected years into adjacent blocks."""
    keep = (frame["execution_date"].dt.year() != year) & (frame["exit_date"].dt.year() != year)
    return np.where(keep.to_numpy(), frame[metric].to_numpy(), np.nan)


def yearly_deltas(frame: pl.DataFrame, metric: str) -> dict[str, float | None]:
    result: dict[str, float | None] = {}
    for year in sorted(frame["execution_date"].dt.year().unique().to_list()):
        sub = frame.filter(
            (pl.col("execution_date") >= date(year, 1, 1))
            & (pl.col("exit_date") <= date(year, 12, 31))
        )
        mean = sub.select(pl.col(metric).cast(pl.Float64).mean()).item() if sub.height else None
        result[str(year)] = float(mean) if mean is not None else None
    return result
