"""The dense canonical panel shared by both zones (PLAN Section 6.3).

There is exactly one row per instrument per trading date between the instrument's first
and last observation, so rolling windows over rows are rolling windows over the market
calendar. A day without a trade (missing, zero volume or no close) is suspended: its
market fields are null, and returns and price limits refer to the last traded close.
"""

from collections.abc import Sequence
from datetime import date
from typing import Final

import polars as pl
from pydantic import JsonValue

from qfr_core.dsl.catalog import min_valid

INSTRUMENT: Final = "instrument"
DATE: Final = "date"

PANEL_SCHEMA: Final[dict[str, pl.DataType]] = {
    "date": pl.Date(),
    "instrument": pl.String(),
    "open": pl.Float64(),
    "high": pl.Float64(),
    "low": pl.Float64(),
    "close": pl.Float64(),
    "close_raw": pl.Float64(),
    "volume": pl.Float64(),
    "amount": pl.Float64(),
    "vwap": pl.Float64(),
    "factor": pl.Float64(),
    "ret_1d": pl.Float64(),
    "is_suspended": pl.Boolean(),
    "limit_up": pl.Boolean(),
    "limit_down": pl.Boolean(),
    "listed_days": pl.Int32(),
    "in_csi300": pl.Boolean(),
    "in_csi500": pl.Boolean(),
    "adv20": pl.Float64(),
}
UNIVERSES: Final = ("csi300", "csi500")
OBSERVATION_FIELDS: Final = ("open", "high", "low", "close", "volume", "amount", "factor")
MARKET_FIELDS: Final = ("open", "high", "low", "close", "vwap", "volume", "amount")
PRICE_FIELDS: Final = ("open", "high", "low", "close")

MEMBERSHIP_SCHEMA: Final[dict[str, pl.DataType]] = {
    "universe": pl.String(),
    "instrument": pl.String(),
    "start": pl.Date(),
    "end": pl.Date(),
}
CALENDAR_SCHEMA: Final[dict[str, pl.DataType]] = {
    "date": pl.Date(),
    "benchmark_ret": pl.Float64(),
}

# Board price limits (PLAN 6.3). ST names (5%) cannot be detected from this data.
CHINEXT_REFORM: Final = date(2020, 8, 24)
TICK: Final = 0.01
ADV_DAYS: Final = 20

# Raw-price convention check (PLAN 6.2): 99% of raw closes within this range.
RAW_CLOSE_RANGE: Final = (0.5, 5000.0)
RAW_CLOSE_SHARE_MIN: Final = 0.99
# Corporate-action flag (PLAN 6.2).
JUMP_RETURN: Final = 0.25
JUMP_GRACE_DAYS: Final = 5


class PanelError(ValueError):
    """Input data that cannot form a canonical panel."""


def board_limit() -> pl.Expr:
    """Daily price-limit fraction: STAR 20%, ChiNext 20% from 2020-08-24, otherwise 10%."""
    code = pl.col(INSTRUMENT)
    star = code.str.starts_with("SH688") | code.str.starts_with("SH689")
    chinext = code.str.starts_with("SZ300") | code.str.starts_with("SZ301")
    return (
        pl.when(star)
        .then(0.20)
        .when(chinext & (pl.col(DATE) >= CHINEXT_REFORM))
        .then(0.20)
        .otherwise(0.10)
    )


def round_price(value: pl.Expr) -> pl.Expr:
    """Exchange rounding to the 0.01 tick, half up. The tiny offset absorbs float error.

    The synthetic generator applies the same arithmetic, so its limit prices match.
    """
    return ((value / TICK) + 0.5 + 1e-9).floor() * TICK


def is_main_board() -> pl.Expr:
    code = pl.col(INSTRUMENT)
    return ~(
        code.str.starts_with("SH688")
        | code.str.starts_with("SH689")
        | code.str.starts_with("SZ300")
        | code.str.starts_with("SZ301")
    )


def _check_observations(observations: pl.DataFrame, calendar: pl.DataFrame) -> None:
    missing = [c for c in (DATE, INSTRUMENT, *OBSERVATION_FIELDS) if c not in observations.columns]
    if missing:
        raise PanelError(f"observations lack required columns: {', '.join(missing)}")
    duplicates = observations.select(pl.struct(INSTRUMENT, DATE).is_duplicated().sum()).item()
    if duplicates:
        raise PanelError(f"{duplicates} duplicate instrument dates in the observations")
    outside = observations.join(calendar, on=DATE, how="anti").height
    if outside:
        raise PanelError(f"{outside} observations fall on dates outside the trading calendar")


def _membership_flags(
    dense: pl.DataFrame, membership: pl.DataFrame, calendar: pl.DataFrame
) -> pl.DataFrame:
    """Point-in-time flags from inclusive [start, end] membership intervals."""
    days = calendar.get_column(DATE)
    intervals = membership.with_columns(
        days.search_sorted(membership.get_column("start"), side="left").alias("first"),
        (days.search_sorted(membership.get_column("end"), side="right") - 1).alias("last"),
    ).filter(pl.col("last") >= pl.col("first"))
    member_days = (
        intervals.select(
            "universe",
            INSTRUMENT,
            pl.int_ranges("first", pl.col("last") + 1, dtype=pl.UInt32).alias("index"),
        )
        .explode("index", empty_as_null=False)
        .unique()
    )
    for universe in UNIVERSES:
        flags = member_days.filter(pl.col("universe") == universe).select(
            INSTRUMENT, "index", pl.lit(True).alias(f"in_{universe}")
        )
        dense = dense.join(flags, on=[INSTRUMENT, "index"], how="left").with_columns(
            pl.col(f"in_{universe}").fill_null(False)
        )
    return dense


def build_panel(
    observations: pl.DataFrame,
    calendar: Sequence[date] | pl.Series,
    membership: pl.DataFrame,
) -> pl.DataFrame:
    """Build the dense canonical panel from adjusted daily observations.

    observations: one row per traded or recorded instrument date with adjusted open,
    high, low, close, volume, amount, the adjustment factor and optionally vwap.
    membership: universe, instrument, start, end (inclusive) intervals.
    """
    cal = pl.DataFrame({DATE: pl.Series(calendar, dtype=pl.Date)}).sort(DATE)
    if cal.get_column(DATE).is_duplicated().any():
        raise PanelError("the trading calendar has duplicate dates")
    cal = cal.with_row_index("index")
    obs = observations.with_columns(pl.col(DATE).cast(pl.Date), pl.col(INSTRUMENT).cast(pl.String))
    _check_observations(obs, cal)
    if "vwap" not in obs.columns:
        obs = obs.with_columns(pl.lit(None, dtype=pl.Float64).alias("vwap"))
    obs = obs.select(
        DATE, INSTRUMENT, *[pl.col(c).cast(pl.Float64) for c in (*OBSERVATION_FIELDS, "vwap")]
    ).join(cal, on=DATE)

    spans = obs.group_by(INSTRUMENT).agg(
        pl.col("index").min().alias("first"), pl.col("index").max().alias("last")
    )
    dense = (
        spans.select(
            INSTRUMENT, pl.int_ranges("first", pl.col("last") + 1, dtype=pl.UInt32).alias("index")
        )
        .explode("index", empty_as_null=False)
        .join(cal, on="index")
        .join(obs.drop(DATE), on=[INSTRUMENT, "index"], how="left")
        .sort(INSTRUMENT, "index")
    )

    traded = (
        pl.col("close").is_not_null()
        & pl.col("close").is_finite()
        & pl.col("volume").is_not_null()
        & (pl.col("volume") > 0)
    ).fill_null(False)
    dense = dense.with_columns(
        (~traded).alias("is_suspended"),
        pl.col("factor").forward_fill().over(INSTRUMENT),
    )
    fallback_vwap = (pl.col("high") + pl.col("low") + pl.col("close")) / 3.0
    usable_vwap = pl.col("vwap").is_finite() & (pl.col("vwap") > 0)
    dense = dense.with_columns(
        *[
            pl.when(pl.col("is_suspended")).then(None).otherwise(pl.col(c)).alias(c)
            for c in ("open", "high", "low", "close", "volume", "amount")
        ],
        pl.when(pl.col("is_suspended"))
        .then(None)
        .when(usable_vwap)
        .then(pl.col("vwap"))
        .otherwise(fallback_vwap)
        .alias("vwap"),
    ).with_columns(
        (pl.col("close") / pl.col("factor")).alias("close_raw"),
        pl.int_range(pl.len(), dtype=pl.Int32).over(INSTRUMENT).alias("listed_days"),
    )

    previous_close = pl.col("close").forward_fill().shift(1).over(INSTRUMENT)
    # The ex-rights reference: the last traded adjusted close in today's raw terms. It
    # equals the previous raw close except on ex-dates, where the factor changes.
    reference = previous_close / pl.col("factor")
    limit = board_limit()
    up_price = round_price(reference * (1.0 + limit))
    down_price = round_price(reference * (1.0 - limit))
    dense = dense.with_columns(
        (pl.col("close") / previous_close - 1.0).alias("ret_1d"),
        (pl.col("close_raw") >= up_price - TICK / 2).fill_null(False).alias("limit_up"),
        (pl.col("close_raw") <= down_price + TICK / 2).fill_null(False).alias("limit_down"),
    ).with_columns(
        pl.col("amount")
        .rolling_mean(ADV_DAYS, min_samples=min_valid(ADV_DAYS))
        .over(INSTRUMENT)
        .alias("adv20")
    )
    dense = _membership_flags(dense, membership, cal)
    panel = dense.select([pl.col(name).cast(dtype) for name, dtype in PANEL_SCHEMA.items()]).sort(
        INSTRUMENT, DATE
    )
    finite = [
        pl.when(pl.col(c).is_finite()).then(pl.col(c)).otherwise(None).alias(c)
        for c, t in PANEL_SCHEMA.items()
        if t == pl.Float64()
    ]
    return panel.with_columns(finite)


def check_schema(frame: pl.DataFrame, schema: dict[str, pl.DataType], name: str) -> None:
    actual = dict(frame.schema)
    if list(actual) != list(schema) or any(actual[c] != t for c, t in schema.items()):
        raise PanelError(f"{name} does not match the canonical schema")


def sanity_checks(panel: pl.DataFrame) -> dict[str, JsonValue]:
    """Ingest sanity checks (PLAN 6.2). Errors raise; flags are counted for the manifest."""
    check_schema(panel, PANEL_SCHEMA, "the panel")
    duplicates = panel.select(pl.struct(INSTRUMENT, DATE).is_duplicated().sum()).item()
    if duplicates:
        raise PanelError(f"{duplicates} duplicate instrument dates in the panel")
    non_positive = panel.select(
        pl.sum_horizontal([(pl.col(c) <= 0).fill_null(False) for c in PRICE_FIELDS]).sum()
    ).item()
    if non_positive:
        raise PanelError(f"{non_positive} non-positive adjusted prices")
    negative_volume = panel.select((pl.col("volume") < 0).fill_null(False).sum()).item()
    if negative_volume:
        raise PanelError(f"{negative_volume} negative volumes")
    raw = panel.get_column("close_raw").drop_nulls()
    low, high = RAW_CLOSE_RANGE
    in_range = ((raw >= low) & (raw <= high)).cast(pl.Float64).mean()
    share = float(in_range) if isinstance(in_range, float) else 0.0
    if share < RAW_CLOSE_SHARE_MIN:
        raise PanelError(
            f"only {share:.4f} of raw closes lie in [{low}, {high}] CNY; "
            "the adjusted / factor convention does not hold"
        )
    jumps = panel.filter(
        is_main_board()
        & (pl.col("listed_days") >= JUMP_GRACE_DAYS)
        & (pl.col("ret_1d").abs() > JUMP_RETURN)
    ).select(INSTRUMENT, pl.col(DATE).cast(pl.String))
    sample: list[JsonValue] = [list(row) for row in jumps.head(20).iter_rows()]
    return {
        "raw_close_share_in_range": round(share, 6),
        "corporate_action_flags": jumps.height,
        "corporate_action_sample": sample,
        "suspended_rows": int(panel.get_column("is_suspended").sum()),
        "limit_up_rows": int(panel.get_column("limit_up").sum()),
        "limit_down_rows": int(panel.get_column("limit_down").sum()),
    }


def equal_weight_benchmark(panel: pl.DataFrame, universe: str = "csi300") -> pl.DataFrame:
    """Equal-weight mean ret_1d over traded universe members, per date."""
    member = pl.col(f"in_{universe}") & ~pl.col("is_suspended")
    return (
        panel.group_by(DATE)
        .agg(pl.col("ret_1d").filter(member).mean().alias("benchmark_ret"))
        .sort(DATE)
    )
