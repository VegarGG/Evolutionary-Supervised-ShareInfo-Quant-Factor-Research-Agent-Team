"""Reader for the Qlib binary data format (PLAN Section 6.2), without the qlib package.

- calendars/day.txt: one trading date per line, ascending.
- instruments/<universe>.txt: tab-separated symbol, start date, end date. A symbol may
  appear on several lines if it re-entered the index (point-in-time membership).
- features/<symbol>/<field>.day.bin: little-endian float32. Element 0 is the start
  index into the calendar; the rest are values for consecutive calendar dates.
"""

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import polars as pl

from qfr_core.data.panel import DATE, INSTRUMENT

BIN_SUFFIX = ".day.bin"


class QlibError(ValueError):
    """The directory does not follow the Qlib binary format."""


def _parse_date(text: str, where: str) -> date:
    try:
        return date.fromisoformat(text.strip()[:10])
    except ValueError:
        raise QlibError(f"{where}: {text.strip()!r} is not a date") from None


@dataclass(frozen=True)
class QlibDirectory:
    root: Path

    @classmethod
    def locate(cls, base: Path, depth: int = 3) -> "QlibDirectory":
        """Find the directory holding calendars/day.txt at or below base."""
        candidates = [base, *[p for p in base.rglob("*") if p.is_dir()]]
        for path in sorted(candidates, key=lambda p: (len(p.parts), str(p))):
            if len(path.relative_to(base).parts) > depth:
                continue
            if (path / "calendars" / "day.txt").is_file() and (path / "features").is_dir():
                return cls(path)
        raise QlibError(f"no Qlib directory (calendars/day.txt and features/) under {base}")

    def calendar(self) -> list[date]:
        lines = (self.root / "calendars" / "day.txt").read_text(encoding="utf-8").splitlines()
        days = [_parse_date(line, "calendars/day.txt") for line in lines if line.strip()]
        if not days:
            raise QlibError("calendars/day.txt is empty")
        if any(b <= a for a, b in zip(days, days[1:], strict=False)):
            raise QlibError("calendars/day.txt is not strictly ascending")
        return days

    def membership(self, universe: str) -> pl.DataFrame:
        path = self.root / "instruments" / f"{universe}.txt"
        if not path.is_file():
            raise QlibError(f"instruments/{universe}.txt is missing")
        rows: list[tuple[str, str, date, date]] = []
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) < 3:
                raise QlibError(f"instruments/{universe}.txt line {number}: expected 3 fields")
            where = f"instruments/{universe}.txt line {number}"
            start, end = _parse_date(parts[1], where), _parse_date(parts[2], where)
            if end < start:
                raise QlibError(f"{where}: end precedes start")
            rows.append((universe, parts[0].strip().upper(), start, end))
        return pl.DataFrame(
            rows,
            schema={"universe": pl.String, INSTRUMENT: pl.String, "start": pl.Date, "end": pl.Date},
            orient="row",
        )

    def symbols(self) -> list[str]:
        return sorted(p.name.upper() for p in (self.root / "features").iterdir() if p.is_dir())

    def _symbol_dir(self, symbol: str) -> Path:
        for name in (symbol.lower(), symbol.upper(), symbol):
            path = self.root / "features" / name
            if path.is_dir():
                return path
        raise QlibError(f"features/{symbol.lower()} is missing")

    def fields(self, symbol: str) -> set[str]:
        return {
            p.name[: -len(BIN_SUFFIX)]
            for p in self._symbol_dir(symbol).iterdir()
            if p.name.endswith(BIN_SUFFIX)
        }

    def read_field(self, symbol: str, field: str, calendar_size: int) -> tuple[int, np.ndarray]:
        path = self._symbol_dir(symbol) / f"{field}{BIN_SUFFIX}"
        raw = np.fromfile(path, dtype="<f4")
        if raw.size == 0:
            raise QlibError(f"{path.name} for {symbol} is empty")
        start = float(raw[0])
        if not start.is_integer() or start < 0:
            raise QlibError(f"{symbol} {field}: start index {start} is not a calendar index")
        index = int(start)
        values = raw[1:].astype(np.float64)
        if index + values.size > calendar_size:
            raise QlibError(f"{symbol} {field}: data runs past the end of the calendar")
        return index, values

    def frame(
        self, symbol: str, fields: list[str], calendar: list[date], required: list[str]
    ) -> pl.DataFrame:
        """One row per calendar date covered by any field; rows without a close dropped."""
        present = self.fields(symbol)
        missing = [f for f in required if f not in present]
        if missing:
            raise QlibError(f"{symbol} lacks required fields: {', '.join(missing)}")
        series: dict[str, tuple[int, np.ndarray]] = {
            f: self.read_field(symbol, f, len(calendar)) for f in fields if f in present
        }
        first = min(i for i, _ in series.values())
        last = max(i + v.size for i, v in series.values())
        columns: dict[str, object] = {
            DATE: calendar[first:last],
            INSTRUMENT: [symbol.upper()] * (last - first),
        }
        for name in fields:
            full = np.full(last - first, np.nan)
            if name in series:
                index, values = series[name]
                full[index - first : index - first + values.size] = values
            columns[name] = full
        out = pl.DataFrame(columns, nan_to_null=True)
        if "close" in out.columns:
            out = out.filter(pl.col("close").is_not_null())
        return out
