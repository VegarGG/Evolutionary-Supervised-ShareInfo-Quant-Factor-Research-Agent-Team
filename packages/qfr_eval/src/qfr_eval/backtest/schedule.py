"""Publication-aware pilot decisions, including missing and immature slots."""

import calendar
from bisect import bisect_right
from datetime import date, timedelta
from typing import Any

import polars as pl
from qfr_core.pilot.baseline import Cycle, P0History, sample_dates


def period_end(day: date, quarterly: bool = False) -> date:
    month = 3 * ((day.month - 1) // 3 + 1) if quarterly else day.month
    return date(day.year, month, calendar.monthrange(day.year, month)[1])


def publications(dates: list[date]) -> list[dict[str, Any]]:
    dates = sorted(set(dates))
    events, seen = [], None
    for cutoff in dates:
        friday = cutoff + timedelta(days=(4 - cutoff.weekday()) % 7)
        events.append(
            dict(
                model_cycle="weekly",
                period_key=f"{friday - timedelta(days=6)}/{friday}",
                publication_date=cutoff,
                reference_date=cutoff,
            )
        )
        months = [d for d in dates if d <= cutoff and period_end(d) <= cutoff]
        quarters = [d for d in dates if d <= cutoff and period_end(d, True) <= cutoff]
        if not months:
            continue
        last = months[-1]
        key = f"{last.year}-{last.month:02}"
        if key == seen:
            continue
        seen = key
        for cycle in ["monthly", "quarterly"] if quarters else ["monthly"]:
            events.append(
                dict(
                    model_cycle=cycle, period_key=key, publication_date=cutoff, reference_date=last
                )
            )
    return events


def build_schedule(
    dates: list[date],
    calendar_frame: pl.DataFrame,
    *,
    start: date,
    end: date,
) -> list[dict[str, Any]]:
    if calendar_frame["date"].n_unique() != calendar_frame.height:
        raise ValueError("duplicate exchange calendar day")
    open_days = sorted(calendar_frame.filter(pl.col("is_open").cast(pl.Boolean))["date"].to_list())
    weekly: dict[date, date] = {}
    for day in open_days:
        friday = day + timedelta(days=(4 - day.weekday()) % 7)
        if day >= min(dates) and friday <= end:
            weekly[friday] = day
    actual = {(r["model_cycle"], r["period_key"]): r for r in publications(dates)}
    expected = {(r["model_cycle"], r["period_key"]): r for r in publications(list(weekly.values()))}
    rows = []
    for key in sorted(actual.keys() | expected.keys()):
        a, e = actual.get(key), expected.get(key)
        source = a or e
        assert source is not None
        row = dict(source)
        pub = row["publication_date"]
        if pub > end:
            continue
        pos = bisect_right(open_days, pub)
        execution = open_days[pos] if pos < len(open_days) else None
        if execution is not None and execution < start or execution is None and pub < start:
            continue
        cohort = (
            "outside_window_calendar_proven"
            if execution is None
            else "within_window"
            if start <= execution <= end
            else "outside_window"
        )
        row.update(
            snapshot_available=a is not None,
            expected_publication_date=e["publication_date"] if e else None,
            execution_date=execution,
            in_execution_cohort=cohort == "within_window",
            execution_cohort_class=cohort,
            carry_in=pub < start,
            publication_delay_days=(pub - e["publication_date"]).days if a and e else None,
        )
        rows.append(row)
    return sorted(rows, key=lambda r: (r["publication_date"], r["model_cycle"], r["period_key"]))


def snapshot(
    history: P0History,
    panel: pl.DataFrame,
    cutoff: date,
    cycle: Cycle,
) -> pl.DataFrame:
    frame = history.signals[cycle]
    dates = sorted(panel["date"].unique().to_list())
    months = [d for d in dates if d <= cutoff and period_end(d) <= cutoff]
    if cycle == "weekly":
        selected = frame.filter(pl.col("date") == cutoff)
    elif not months:
        return frame.head(0)
    else:
        candidates = frame.filter(pl.col("date") <= months[-1])
        if candidates.is_empty():
            return frame.head(0)
        selected = candidates.filter(pl.col("date") == candidates["date"].max())
    if selected.is_empty():
        return selected
    source = selected["date"][0]
    if cycle == "quarterly":
        quarters = [
            d
            for d in sample_dates(panel, "quarterly")
            if d <= months[-1] and period_end(d, True) <= cutoff
        ]
        if not quarters:
            return frame.head(0)
        source = quarters[-1]
    return selected.sort("rank").with_columns(pl.lit(source).alias("feature_source_date"))
