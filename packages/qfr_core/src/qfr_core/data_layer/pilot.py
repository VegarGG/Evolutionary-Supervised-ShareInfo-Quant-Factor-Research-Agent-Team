"""Data-only adapters for the six frozen pilot inputs. No original runtime imports."""

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal, cast

import numpy as np
import polars as pl
from pydantic import PositiveInt

from qfr_core.contracts.base import Contract
from qfr_core.contracts.data import DateRange, ExposureAndQuality, QualityLabels
from qfr_core.contracts.enums import PITGrade
from qfr_core.data_layer.snapshots import TableInput, file_hash, normalize_table


class PilotConfig(Contract):
    revision: PositiveInt
    profile: Literal["pilot_industry_v1"]
    industry_count: PositiveInt
    benchmarks: list[str]
    fundamental_availability: dict[str, str]
    price_overlap_atol: float
    price_overlap_rtol: float
    feature_parity_atol: float
    feature_parity_rtol: float
    scores_and_ranks: Literal["exact"]
    exposure: Literal["previously_seen"]
    vintage_note: str
    membership_note: str
    new_supplier_requests: Literal[False]


@dataclass(frozen=True)
class PilotImport:
    tables: list[TableInput]
    exposure: ExposureAndQuality


def financial_availability(report: date, config: PilotConfig) -> date:
    rule = config.fundamental_availability.get(report.strftime("%m%d"))
    if rule is None:
        raise ValueError("unsupported pilot report period; availability unknown")
    following = rule.startswith("next-year-")
    month, day = map(int, rule.removeprefix("next-year-").split("-"))
    return date(report.year + int(following), month, day)


def _csv(path: Path) -> pl.DataFrame:
    frame = pl.read_csv(
        path,
        infer_schema_length=None,
        schema_overrides={"code": pl.String, "report_date": pl.String},
        null_values=["", "NaN", "nan"],
    )
    for column in ["date", "available_date"]:
        if column in frame.columns:
            frame = frame.with_columns(pl.col(column).str.to_date("%Y-%m-%d"))
    if "report_date" in frame.columns:
        frame = frame.with_columns(
            pl.col("report_date").str.strip_suffix(".0").str.to_date("%Y%m%d")
        )
    return frame


def import_pilot(package: Path, fixtures: Path, config: PilotConfig) -> PilotImport:
    inventory = json.loads((package / "SHA256SUMS.json").read_text())["files"]
    frames: dict[str, pl.DataFrame] = {}
    hashes: dict[str, str] = {}
    qualities: dict[str, QualityLabels] = {}
    for metadata_file in sorted((fixtures / "manifests").glob("*.json")):
        metadata = json.loads(metadata_file.read_text())
        asset = metadata["asset_id"]
        relative = metadata["path"]
        path = package / relative
        if not path.resolve().is_relative_to(package.resolve()) or path.is_symlink():
            raise ValueError("pilot source escapes package")
        actual = file_hash(path)
        if actual != metadata["sha256"] or actual != inventory[relative]["sha256"]:
            raise ValueError(f"frozen source hash mismatch: {asset}")
        frame = _csv(path)
        if frame.height != metadata["rows"] or frame.columns != metadata["columns"]:
            raise ValueError(f"frozen source shape mismatch: {asset}")
        frames[asset], hashes[asset] = frame, actual
        membership = metadata["membership_status"]
        qualities[asset] = QualityLabels(
            timing_grade=PITGrade(metadata["timing_grade"] or "D"),
            timing_basis=metadata["timing_basis"] or "Static labels; timing not applicable",
            vintage_status="unknown",
            vintage_notes=config.vintage_note,
            membership_grade=PITGrade.D if membership == "backfilled" else None,
            membership_status=membership,
            membership_notes=config.membership_note
            if membership == "backfilled"
            else "Static code labels or observation calendar",
        )
    required = {
        "index_prices",
        "evaluation_prices",
        "features",
        "industry_signal_panel",
        "stock_finance",
        "trading_calendar",
        "industry_labels",
    }
    if set(frames) != required:
        raise ValueError("pilot requires exactly six inputs and its label map")
    labels = frames["industry_labels"].rename({"original_industry": "industry"})
    if (
        labels.height != config.industry_count
        or labels["code"].n_unique() != config.industry_count
        or labels["industry"].n_unique() != config.industry_count
        or set(labels["code"]) & set(config.benchmarks)
    ):
        raise ValueError("invalid pilot industry universe")
    features = frames["features"]
    mapping = features.select("code", "industry").unique().sort("code")
    if not mapping.equals(labels.select("code", "industry").sort("code")):
        raise ValueError("pilot industry mapping differs from labels")
    raw = frames["industry_signal_panel"].join(
        labels.select("code", "industry"), on="industry", how="left", validate="m:1"
    )
    if (
        not raw.select("date", "code")
        .sort("date", "code")
        .equals(features.select("date", "code").sort("date", "code"))
    ):
        raise ValueError("pilot raw and feature keys differ")
    prices = frames["index_prices"]
    expected_codes = set(labels["code"]) | set(config.benchmarks)
    if set(prices["code"]) != expected_codes or (prices["close"] <= 0).any():
        raise ValueError("missing pilot index or invalid price")
    overlap = prices.join(frames["evaluation_prices"], on=["date", "code"], suffix="_evaluation")
    if not np.allclose(
        overlap["close"].to_numpy(),
        overlap["close_evaluation"].to_numpy(),
        rtol=config.price_overlap_rtol,
        atol=config.price_overlap_atol,
    ):
        raise ValueError("evaluation price overlap differs")
    tables = []

    def add(
        name: str,
        frame: pl.DataFrame,
        asset: str,
        grain: tuple[str, ...],
        date_column: str | None = "date",
        available: str | None = "available_date",
        visible: bool = True,
    ) -> None:
        tables.append(
            TableInput(
                name,
                normalize_table(frame, grain),
                grain,
                qualities[asset],
                "Licensed iFinD; authorized local use; no supplier requests",
                date_column,
                available,
                {asset: hashes[asset]},
                visible,
            )
        )

    for name, asset in [
        ("prices_daily", "index_prices"),
        ("evaluation_prices", "evaluation_prices"),
        ("calendar", "trading_calendar"),
    ]:
        frame = frames[asset].with_columns(pl.col("date").alias("available_date"))
        add(
            name,
            frame,
            asset,
            ("date",) if name == "calendar" else ("code", "date"),
            visible=name != "evaluation_prices",
        )
    for name, frame, asset in [
        ("panel_weekly", raw, "industry_signal_panel"),
        ("features", features, "features"),
    ]:
        if frame.filter(pl.col("available_date") > pl.col("date")).height:
            raise ValueError("financial availability follows observation date")
        # The market row is known on its date. Keep its financial availability separately;
        # missing financial values stay null. Do not discard market warm-up observations.
        if frame.filter(
            pl.col("available_date").is_null()
            & pl.any_horizontal(pl.col(["revenue_yoy", "profit_yoy", "roe"]).is_not_null())
        ).height:
            raise ValueError("financial values with unknown availability")
        frame = frame.rename({"available_date": "fundamentals_available_date"}).with_columns(
            pl.col("date").alias("available_date")
        )
        add(name, frame, asset, ("code", "date"))
    finance = frames["stock_finance"].with_columns(
        pl.col("report_date").alias("date"),
        pl.Series(
            "available_date",
            [
                financial_availability(cast(date, d), config)
                for d in frames["stock_finance"]["report_date"]
            ],
        ),
    )
    add("fundamentals", finance, "stock_finance", ("code", "date"))
    add(
        "membership",
        finance.select("code", "industry", "date", "available_date").with_columns(
            pl.lit("backfilled").alias("membership_status")
        ),
        "stock_finance",
        ("code", "date"),
    )
    add("universe", labels, "industry_labels", ("code",), None, None)
    exposure = ExposureAndQuality(
        history="previously_seen",
        inspected_periods=[
            DateRange(start=cast(date, prices["date"].min()), end=cast(date, prices["date"].max()))
        ],
        training_tuning_history="All supplied history previously inspected; frozen accepted P1",
        provider_knowledge_exposure="unknown",
        quality=qualities["features"],
        licence_constraints=["Licensed iFinD caches; no new requests"],
        unknowns=[config.vintage_note, config.membership_note],
    )
    return PilotImport(tables, exposure)
