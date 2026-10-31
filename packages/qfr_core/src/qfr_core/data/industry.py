"""Point-in-time industry classification (PLAN Section 6.1 S3, P8.6).

A snapshot may carry one classification scheme in industry.parquet: rows of (scheme,
instrument, start, end, industry), each an inclusive interval in which the instrument
belongs to that industry. Intervals of one instrument never overlap, so a name has at
most one industry on any date; a date outside every interval has none. Like the index
membership it is point in time, so a reclassification shows up only from its effective
date.

Both zones carry the table. The research copy is clipped at the cutoff, exactly as the
membership is, so it reveals nothing about later reclassifications.

Sources: a CSV the owner provides for China A-shares (columns instrument, start, end,
industry; instrument ids as SH600000 or 600000.SH; an empty end means "still in force"
and is closed at the last date of the data), and the synthetic generator's own sectors.
"""

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Final

import numpy as np
import polars as pl
from numpy.typing import NDArray

from qfr_core.data.panel import INSTRUMENT

INDUSTRY_FILE: Final = "industry.parquet"
INDUSTRY_SCHEMA: Final[dict[str, pl.DataType]] = {
    "scheme": pl.String(),
    "instrument": pl.String(),
    "start": pl.Date(),
    "end": pl.Date(),
    "industry": pl.String(),
}
NO_INDUSTRY: Final = -1
_SCHEME = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,39}$")
_CODE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.&/()-]{0,63}$")
_QLIB_ID = re.compile(r"^(SH|SZ|BJ)\d{6}$")
_SUFFIX_ID = re.compile(r"^(\d{6})\.(SH|SZ|BJ)$")


class IndustryError(ValueError):
    """An industry table that cannot be used as a point-in-time classification."""


def normalize_instrument(value: str) -> str:
    """SH600000 stays; 600000.SH becomes SH600000 (the Qlib ids the panel uses)."""
    text = value.strip().upper()
    if _QLIB_ID.match(text):
        return text
    match = _SUFFIX_ID.match(text)
    if match:
        return f"{match.group(2)}{match.group(1)}"
    raise IndustryError(f"unrecognized instrument id {value!r}")


def check_industry(frame: pl.DataFrame) -> str:
    """Validate the table and return its scheme."""
    if dict(frame.schema) != INDUSTRY_SCHEMA:
        raise IndustryError("the industry table does not have the canonical columns")
    if frame.is_empty():
        raise IndustryError("the industry table is empty")
    if frame.null_count().sum_horizontal().item():
        raise IndustryError("the industry table has missing values")
    schemes = frame.get_column("scheme").unique().to_list()
    if len(schemes) != 1 or not _SCHEME.match(schemes[0]):
        raise IndustryError("an industry table holds exactly one well-formed scheme")
    bad = [c for c in frame.get_column("industry").unique().to_list() if not _CODE.match(c)]
    if bad:
        raise IndustryError(f"malformed industry codes: {sorted(bad)[:5]}")
    if frame.filter(pl.col("end") < pl.col("start")).height:
        raise IndustryError("an industry interval ends before it starts")
    overlaps = (
        frame.sort(INSTRUMENT, "start")
        .with_columns(pl.col("end").shift(1).over(INSTRUMENT).alias("previous_end"))
        .filter(pl.col("previous_end") >= pl.col("start"))
    )
    if overlaps.height:
        names = overlaps.get_column(INSTRUMENT).unique().sort().to_list()[:5]
        raise IndustryError(f"overlapping industry intervals for {names}")
    return str(schemes[0])


def read_industry_csv(path: Path, scheme: str, last_day: date) -> pl.DataFrame:
    """An owner-provided classification CSV as the canonical table. Open intervals end
    at last_day; intervals starting after it are dropped."""
    if not _SCHEME.match(scheme):
        raise IndustryError(f"malformed scheme name {scheme!r}")
    raw = pl.read_csv(path, infer_schema=False)
    missing = [c for c in ("instrument", "start", "end", "industry") if c not in raw.columns]
    if missing:
        raise IndustryError(f"{path.name} lacks columns: {', '.join(missing)}")
    try:
        frame = raw.select(
            pl.lit(scheme).alias("scheme"),
            pl.col("instrument")
            .map_elements(normalize_instrument, return_dtype=pl.String)
            .alias(INSTRUMENT),
            pl.col("start").str.strip_chars().str.to_date("%Y-%m-%d").alias("start"),
            pl.when(pl.col("end").str.strip_chars().fill_null("") == "")
            .then(None)
            .otherwise(pl.col("end").str.strip_chars())
            .str.to_date("%Y-%m-%d")
            .fill_null(last_day)
            .alias("end"),
            pl.col("industry").str.strip_chars().alias("industry"),
        )
    except pl.exceptions.PolarsError as error:
        raise IndustryError(f"{path.name}: {error}") from None
    frame = clip(frame, last_day)
    check_industry(frame)
    return frame


def clip(frame: pl.DataFrame, end: date) -> pl.DataFrame:
    """The table as known on `end`: later intervals dropped, open ones closed at `end`."""
    return (
        frame.filter(pl.col("start") <= end)
        .with_columns(pl.min_horizontal(pl.col("end"), pl.lit(end)).alias("end"))
        .select(list(INDUSTRY_SCHEMA))
        .sort(INSTRUMENT, "start")
    )


@dataclass(frozen=True)
class IndustryCodes:
    """Industry per cell: an index into names, or NO_INDUSTRY."""

    scheme: str
    names: list[str]
    codes: NDArray[np.int64]  # (T, N)

    def coverage(self, mask: NDArray[np.bool_]) -> float | None:
        """The share of the masked cells that have an industry."""
        total = int(mask.sum())
        return float((mask & (self.codes >= 0)).sum()) / total if total else None


def industry_codes(frame: pl.DataFrame, dates: list[date], instruments: list[str]) -> IndustryCodes:
    """Lay the intervals out on the market's date-by-instrument grid. Codes number the
    industry names in sorted order, so they are stable for a given table."""
    scheme = check_industry(frame)
    names = frame.get_column("industry").unique().sort().to_list()
    code_of = {name: i for i, name in enumerate(names)}
    column = {name: j for j, name in enumerate(instruments)}
    codes = np.full((len(dates), len(instruments)), NO_INDUSTRY, dtype=np.int64)
    days = np.array(dates, dtype="datetime64[D]")
    for instrument, start, end, industry in frame.select(
        INSTRUMENT, "start", "end", "industry"
    ).iter_rows():
        j = column.get(instrument)
        if j is None:
            continue
        first = int(np.searchsorted(days, np.datetime64(start, "D"), side="left"))
        last = int(np.searchsorted(days, np.datetime64(end, "D"), side="right"))
        codes[first:last, j] = code_of[industry]
    return IndustryCodes(scheme, names, codes)
