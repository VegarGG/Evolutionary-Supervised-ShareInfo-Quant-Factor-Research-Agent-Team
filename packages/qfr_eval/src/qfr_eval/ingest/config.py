"""Evaluation-side data configuration: configs/data/*.yaml and epoch files."""

from datetime import date
from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator
from qfr_core.config import EpochConfig

World = Literal["planted", "null", "decay"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SignalSpec(_Strict):
    """A planted signal: test infrastructure for benchmarks, never a default factor."""

    expression: str
    target_rankic: float = Field(gt=0, lt=0.2)
    worlds: list[World]
    switch_off: Literal["w2_midpoint"] | None = None


class UniverseSpec(_Strict):
    name: Literal["csi300"]
    size: int = Field(gt=0)
    annual_churn: float = Field(ge=0, lt=1)


class CalibrationSpec(_Strict):
    tolerance: float = Field(gt=0)
    max_rounds: int = Field(ge=1)
    max_iterations: int = Field(ge=1)
    alpha_max: float = Field(gt=0)


class SyntheticConfig(_Strict):
    """PLAN 6.6 defaults. Every random draw derives from seed (or calibration_seed)."""

    generator: Literal["qfr-synthetic/1"]
    version: str
    epoch: str
    seed: int
    calibration_seed: int
    start: date
    instruments: int = Field(ge=40)
    trading_days: int = Field(ge=300)
    industries: int = Field(ge=1)
    market_mean: float
    market_sd: float = Field(gt=0)
    industry_sd: float = Field(ge=0)
    beta: tuple[float, float]
    idio_df: int = Field(gt=2)
    idio_vol: tuple[float, float]
    volume_ar: float = Field(ge=0, lt=1)
    volume_sd: float = Field(gt=0)
    volume_abs_return_corr: float = Field(ge=0, le=1)
    log_volume_mean: tuple[float, float]
    initial_price: tuple[float, float]
    universe: UniverseSpec
    late_listing_share: float = Field(ge=0, lt=1)
    delistings: int = Field(ge=0)
    suspension_start_prob: float = Field(ge=0, lt=1)
    suspension_max_days: int = Field(ge=1)
    price_limit: float = Field(gt=0, lt=1)
    dividend_prob_per_year: float = Field(ge=0, le=1)
    dividend_ratio: tuple[float, float]
    split_prob_per_year: float = Field(ge=0, le=1)
    split_ratios: list[float]
    calibration: CalibrationSpec
    signals: dict[str, SignalSpec]

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if self.universe.size >= self.instruments:
            raise ValueError("the universe must leave non-members to rotate in")
        for low, high in (self.beta, self.idio_vol, self.initial_price, self.dividend_ratio):
            if not low <= high:
                raise ValueError("ranges must be ordered (low, high)")
        return self

    def with_size(self, instruments: int, trading_days: int, universe: int) -> Self:
        """A smaller world for fast tests; everything else unchanged."""
        return self.model_copy(
            update={
                "instruments": instruments,
                "trading_days": trading_days,
                "universe": self.universe.model_copy(update={"size": universe}),
            }
        )


class CnIngestConfig(_Strict):
    """PLAN 6.1 and 6.2: investment_data releases in Qlib binary format."""

    source: Literal["investment_data"]
    version: str
    release_url: str
    archive_name: str
    manifest_name: str
    universes: list[Literal["csi300", "csi500"]]
    benchmark_symbol: str
    required_fields: list[str]
    optional_fields: list[str]
    max_archive_bytes: int = Field(gt=0)
    max_extracted_bytes: int = Field(gt=0)
    download_timeout_seconds: float = Field(gt=0)


def load_yaml(path: Path) -> dict[str, object]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must hold a mapping")
    return raw


def load_synthetic(config_dir: Path) -> SyntheticConfig:
    return SyntheticConfig.model_validate(load_yaml(config_dir / "data" / "synthetic_v1.yaml"))


def load_cn(config_dir: Path) -> CnIngestConfig:
    return CnIngestConfig.model_validate(load_yaml(config_dir / "data" / "cn_ingest_v1.yaml"))


def load_epoch(config_dir: Path, epoch_id: str) -> EpochConfig:
    return EpochConfig.model_validate(load_yaml(config_dir / "epochs" / f"{epoch_id}.yaml"))
