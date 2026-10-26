"""Outer pairing: identity mismatches remain visible and never receive a valid delta."""

import math
from datetime import date

import polars as pl

KEYS = ["model_cycle", "period_key"]


def pair_periods(
    baseline: pl.DataFrame, challenger: pl.DataFrame, metrics: list[str], *, strict: bool = True
) -> pl.DataFrame:
    needed = {*KEYS, "execution_date", "exit_date", "eligible_pool_hash", *metrics}
    for frame in (baseline, challenger):
        if not needed <= set(frame.columns) or frame.select(KEYS).is_duplicated().any():
            raise ValueError("pairing needs unique identities and declared evidence columns")
        if frame.select(pl.any_horizontal(pl.col(KEYS).is_null()).any()).item():
            raise ValueError("null decision identity")
    a = {tuple(r[k] for k in KEYS): r for r in baseline.iter_rows(named=True)}
    b = {tuple(r[k] for k in KEYS): r for r in challenger.iter_rows(named=True)}
    rows = []
    for identity in sorted(a.keys() | b.keys()):
        left, right = a.get(identity), b.get(identity)
        source = left or right
        assert source is not None
        status = "matched"
        if left is None:
            status = "missing_baseline"
        elif right is None:
            status = "missing_challenger"
        elif any(left[k] != right[k] for k in ("execution_date", "exit_date")):
            status = "timing_mismatch"
        elif (
            not left["eligible_pool_hash"]
            or left["eligible_pool_hash"] != right["eligible_pool_hash"]
        ):
            status = "eligible_pool_mismatch"
        elif left.get("split") != right.get("split"):
            status = "split_mismatch"
        if strict and status.endswith("mismatch"):
            raise ValueError(status)
        row = {k: source[k] for k in KEYS}
        row.update(
            execution_date=source["execution_date"],
            exit_date=source["exit_date"],
            split=source.get("split"),
            pair_status=status,
        )
        for metric in metrics:
            av, bv = left.get(metric) if left else None, right.get(metric) if right else None
            row[metric + "_baseline"], row[metric + "_challenger"] = av, bv
            row["delta_" + metric] = (
                bv - av
                if status == "matched"
                and av is not None
                and bv is not None
                and math.isfinite(av)
                and math.isfinite(bv)
                else None
            )
        rows.append(row)
    return pl.DataFrame(rows, infer_schema_length=None).sort(
        ["model_cycle", "execution_date", "period_key"]
    )


def window_periods(frame: pl.DataFrame, start: date, end: date) -> pl.DataFrame:
    """Only reporting denominators are purged; portfolio state was already carried."""
    return frame.filter((pl.col("execution_date") >= start) & (pl.col("exit_date") <= end))
