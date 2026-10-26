"""Opt-in local Qlib release ingestion; no qlib dependency or implicit supplier request."""

import re
import shutil
import tarfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePosixPath
from typing import cast

import numpy as np
import polars as pl
from numpy.typing import NDArray
from pydantic import Field, PositiveInt

from qfr_core.contracts.base import Contract
from qfr_core.data_layer.snapshots import dense_panel, file_hash


class StockImportConfig(Contract):
    revision: PositiveInt
    enabled: bool
    required_fields: list[str]
    optional_fields: list[str]
    universes: list[str]
    primary_universe: str
    benchmark: str
    raw_close_min: float
    raw_close_max: float
    raw_close_fraction: float = Field(gt=0, le=1)
    main_limit: float = Field(gt=0, lt=1)
    growth_limit: float = Field(gt=0, lt=1)
    chinext_reform: date
    corporate_action_return_flag: float = Field(gt=0)
    ipo_grace_days: PositiveInt
    max_archive_bytes: PositiveInt
    max_archive_files: PositiveInt


@dataclass(frozen=True)
class StockImport:
    panel: pl.DataFrame
    calendar: pl.DataFrame
    membership: pl.DataFrame
    benchmark: pl.DataFrame
    conventions: dict[str, str]


def extract_release(
    archive: Path,
    expected_sha256: str,
    destination: Path,
    config: StockImportConfig,
    *,
    authorization_ref: str | None,
) -> Path:
    if not authorization_ref:
        raise PermissionError("CN ingest requires an explicit authorization reference")
    if file_hash(archive) != expected_sha256:
        raise ValueError("release SHA-256 mismatch")
    if destination.exists():
        raise FileExistsError("release extraction needs a fresh destination")
    with tarfile.open(archive, "r:*") as source:
        members = source.getmembers()
        if (
            len(members) > config.max_archive_files
            or sum(m.size for m in members) > config.max_archive_bytes
        ):
            raise ValueError("archive expansion exceeds configured limits")
        names = set()
        for member in members:
            path = PurePosixPath(member.name)
            if (
                path.is_absolute()
                or ".." in path.parts
                or "\\" in member.name
                or not (member.isfile() or member.isdir())
                or member.name in names
            ):
                raise ValueError("unsafe archive member")
            names.add(member.name)
        destination.mkdir(parents=True)
        try:
            source.extractall(destination, members=members, filter="data")
        except BaseException:
            shutil.rmtree(destination)
            raise
    return destination


def _inside(root: Path, path: Path) -> Path:
    if not path.resolve().is_relative_to(root.resolve()) or path.is_symlink():
        raise ValueError("Qlib file escapes import root")
    return path


def read_binary(path: Path, days: int) -> NDArray[np.float64]:
    raw = path.read_bytes()
    if len(raw) < 8 or len(raw) % 4:
        raise ValueError(f"invalid Qlib binary length: {path.name}")
    values = np.frombuffer(raw, dtype="<f4")
    offset = float(values[0])
    if not np.isfinite(offset) or offset != int(offset) or offset < 0:
        raise ValueError("invalid Qlib calendar offset")
    start = int(offset)
    if start + len(values) - 1 > days:
        raise ValueError("Qlib field exceeds calendar")
    result = np.full(days, np.nan, dtype=np.float64)
    result[start : start + len(values) - 1] = values[1:]
    if np.isinf(result).any():
        raise ValueError("infinite Qlib field")
    return result


def read_qlib(
    root: Path,
    config: StockImportConfig,
    *,
    authorization_ref: str | None,
    release_tag: str,
    archive_sha256: str,
) -> StockImport:
    if not authorization_ref:
        raise PermissionError("CN ingest is inactive without explicit authorization")
    if not release_tag or not re.fullmatch(r"[0-9a-f]{64}", archive_sha256):
        raise ValueError("release tag and verified archive hash required")
    calendar_path = _inside(root, root / "calendars/day.txt")
    dates = [
        date.fromisoformat(s.strip()) for s in calendar_path.read_text().splitlines() if s.strip()
    ]
    if not dates or dates != sorted(set(dates)):
        raise ValueError("calendar dates must be nonempty, unique and increasing")
    intervals: list[dict[str, object]] = []
    for universe in config.universes:
        if not re.fullmatch(r"[a-z0-9_]+", universe):
            raise ValueError("invalid universe name")
        path = _inside(root, root / "instruments" / f"{universe}.txt")
        if not path.exists():
            if universe == config.primary_universe:
                raise ValueError(f"missing primary universe: {universe}")
            continue
        for line in path.read_text().splitlines():
            symbol, start, end = line.split()
            symbol = symbol.upper()
            if not re.fullmatch(r"(?:SH|SZ)\d{6}", symbol):
                raise ValueError("invalid exchange-prefixed instrument")
            first, last = date.fromisoformat(start), date.fromisoformat(end)
            if last < first:
                raise ValueError("reversed membership interval")
            intervals.append(dict(instrument=symbol, start=first, end=last, universe=universe))
    membership = pl.DataFrame(intervals)
    if not membership.height or membership.is_duplicated().any():
        raise ValueError("missing or duplicate membership intervals")
    symbols = sorted(set(membership["instrument"].to_list()))
    frames = []
    for symbol in symbols:
        folder = _inside(root, root / "features" / symbol.lower())
        fields = {}
        for name in config.required_fields + config.optional_fields:
            if not re.fullmatch(r"[a-z0-9_]+", name):
                raise ValueError("invalid Qlib field name")
            path = _inside(root, folder / f"{name}.day.bin")
            if not path.exists():
                if name in config.required_fields:
                    raise ValueError(f"missing required field {symbol}.{name}")
                continue
            fields[name] = read_binary(path, len(dates))
        frame = pl.DataFrame(
            {"date": dates, "instrument": [symbol] * len(dates), **fields}, nan_to_null=True
        )
        observed = frame.filter(pl.col("close").is_not_null())
        if observed.height:
            frames.append(observed)
    if not frames:
        raise ValueError("release has no observed closes")
    calendar = pl.DataFrame({"date": dates})
    panel = dense_panel(pl.concat(frames, how="diagonal_relaxed"), calendar)
    raw = panel["close_raw"].drop_nulls()
    fraction = cast(float | None, raw.is_between(config.raw_close_min, config.raw_close_max).mean())
    if fraction is None or fraction < config.raw_close_fraction:
        raise ValueError("raw-price convention failed sanity check")
    for universe in config.universes:
        selected = membership.filter(pl.col("universe") == universe)
        flags = (
            panel.select("date", "instrument")
            .join(selected, on="instrument", how="left")
            .group_by("date", "instrument")
            .agg(
                pl.col("date")
                .is_between(pl.col("start"), pl.col("end"))
                .any()
                .fill_null(False)
                .alias(f"in_{universe}")
            )
        )
        panel = panel.join(flags, on=["date", "instrument"], how="left")
    panel = panel.sort("instrument", "date")
    growth = pl.col("instrument").str.starts_with("SH688") | (
        pl.col("instrument").str.starts_with("SZ30") & (pl.col("date") >= config.chinext_reform)
    )
    raw_return = pl.col("close_raw") / pl.col("close_raw").shift(1).over("instrument") - 1
    threshold = pl.when(growth).then(config.growth_limit).otherwise(config.main_limit)
    panel = panel.with_columns(
        (raw_return >= threshold - 1e-7).fill_null(False).alias("limit_up"),
        (raw_return <= -threshold + 1e-7).fill_null(False).alias("limit_down"),
        (
            (pl.col("ret_1d").abs() > config.corporate_action_return_flag)
            & ~growth
            & (pl.col("listed_days") > config.ipo_grace_days)
        )
        .fill_null(False)
        .alias("corporate_action_flag"),
    )
    benchmark_path = _inside(root, root / "features" / config.benchmark.lower() / "close.day.bin")
    if benchmark_path.exists():
        benchmark = pl.DataFrame(
            {"date": dates, "close": read_binary(benchmark_path, len(dates))}, nan_to_null=True
        ).with_columns((pl.col("close") / pl.col("close").shift(1) - 1).alias("return"))
        benchmark_name = config.benchmark
    else:
        benchmark = (
            panel.filter(pl.col(f"in_{config.primary_universe}"))
            .group_by("date")
            .agg(pl.col("ret_1d").mean().alias("return"))
            .sort("date")
        )
        benchmark_name = "equal-weight primary-universe return (index unavailable)"
    return StockImport(
        panel,
        calendar,
        membership,
        benchmark,
        {
            "prices": "adjusted; raw=adjusted/factor",
            "benchmark": benchmark_name,
            "release_tag": release_tag,
            "archive_sha256": archive_sha256,
            "authorization_ref": authorization_ref,
            "source": "authorized local Qlib release",
            "limitation": (
                "ST status unavailable; 5% ST limits cannot be detected; vintages unverified"
            ),
        },
    )
