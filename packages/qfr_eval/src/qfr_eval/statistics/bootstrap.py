"""Deterministic paired time blocks; separate historical-oracle and official policies."""

import hashlib
import math
from typing import Literal

import numpy as np
from pydantic import NonNegativeInt, PositiveInt
from qfr_core.contracts.base import Contract, Sha256
from qfr_core.metrics.core import Array

from qfr_eval.protocols.models import BootstrapConfig, Cycle


class Interval(Contract):
    status: Literal["estimated", "insufficient_data"]
    estimate: float | None
    ci_lower: float | None
    ci_upper: float | None
    standard_error: float | None
    valid_periods: NonNegativeInt
    time_slots: NonNegativeInt
    block_length: PositiveInt
    draws: NonNegativeInt
    valid_draws: NonNegativeInt
    seed: NonNegativeInt
    confidence: float
    index_sha256: Sha256 | None
    small_sample_warning: bool


def derived_seed(seed: int, *identity: str) -> int:
    return int.from_bytes(
        hashlib.sha256("|".join([str(seed), *identity]).encode()).digest()[:8], "big"
    )


def automatic_block_length(n: int, floor: int) -> int:
    if n < 0 or floor < 1:
        raise ValueError("invalid sample count or cycle floor")
    root = 0
    while root**3 < n:
        root += 1
    return max(floor, root)


def block_indices(n: int, length: int, draws: int, seed: int) -> np.ndarray:
    if n < 1 or not 1 <= length <= n or draws < 1:
        raise ValueError("invalid circular block dimensions")
    starts = np.random.Generator(np.random.PCG64(seed)).integers(
        0, n, size=(draws, math.ceil(n / length))
    )
    return ((starts[:, :, None] + np.arange(length)) % n).reshape(draws, -1)[:, :n]


def index_hash(indices: np.ndarray) -> str:
    return hashlib.sha256(indices.astype("<i8").tobytes()).hexdigest()


def _interval(
    values: Array,
    *,
    length: int,
    draws: int,
    seed: int,
    confidence: float,
    minimum_periods: int,
    minimum_blocks: int,
    oracle: bool,
) -> Interval:
    x = np.asarray(values, dtype=float)
    if x.ndim != 1 or np.isinf(x).any() or not 0 < confidence < 1 or length < 1 or draws < 0:
        raise ValueError("invalid bootstrap input")
    n, finite = len(x), int(np.isfinite(x).sum())
    length = min(length, max(1, n))
    warning = finite < minimum_periods or finite // length < minimum_blocks
    base = dict(
        estimate=float(np.nanmean(x)) if finite else None,
        valid_periods=finite,
        time_slots=n,
        block_length=length,
        draws=draws,
        seed=seed,
        confidence=confidence,
        small_sample_warning=warning,
    )
    missing = dict(
        status="insufficient_data",
        ci_lower=None,
        ci_upper=None,
        standard_error=None,
        valid_draws=0,
        index_sha256=None,
    )
    if finite < 3 or draws < 100 or (not oracle and (warning or finite != n or np.ptp(x) == 0)):
        return Interval.model_validate({**base, **missing})
    indices = block_indices(n, length, draws, seed)
    samples = x[indices]
    counts = np.isfinite(samples).sum(axis=1)
    means = np.divide(
        np.nansum(samples, axis=1), counts, out=np.full(draws, np.nan), where=counts > 0
    )
    valid = means[np.isfinite(means)]
    if not len(valid):
        return Interval.model_validate({**base, **missing, "index_sha256": index_hash(indices)})
    # Historical oracle explicitly discards wholly missing draws. Official input
    # requires the complete frozen cohort and never discards a failed draw.
    se = float(valid.std(ddof=1))
    if not oracle and (len(valid) != draws or se <= 0 or not math.isfinite(se)):
        return Interval.model_validate({**base, **missing, "index_sha256": index_hash(indices)})
    alpha = (1 - confidence) / 2
    low, high = map(float, np.quantile(valid, [alpha, 1 - alpha]))
    return Interval.model_validate(
        {
            **base,
            "status": "estimated",
            "ci_lower": low,
            "ci_upper": high,
            "standard_error": se,
            "valid_draws": len(valid),
            "index_sha256": index_hash(indices),
        }
    )


def oracle_interval(
    values: Array, *, length: int, draws: int, seed: int, confidence: float = 0.95
) -> Interval:
    return _interval(
        values,
        length=length,
        draws=draws,
        seed=seed,
        confidence=confidence,
        minimum_periods=10,
        minimum_blocks=5,
        oracle=True,
    )


def official_interval(
    values: Array, config: BootstrapConfig, cycle: Cycle, *, seed: int
) -> Interval:
    if config.draws < 10000 or not config.automatic:
        raise ValueError("official intervals require >=10000 draws and automatic blocks")
    length = automatic_block_length(len(values), config.block_floors[cycle])
    return _interval(
        values,
        length=length,
        draws=config.draws,
        seed=seed,
        confidence=config.confidence,
        minimum_periods=config.minimum_periods,
        minimum_blocks=config.minimum_blocks,
        oracle=False,
    )


def sensitivity_intervals(
    values: Array, config: BootstrapConfig, cycle: Cycle, *, seed: int
) -> list[Interval]:
    primary = automatic_block_length(len(values), config.block_floors[cycle])
    lengths = sorted(
        {max(config.block_floors[cycle], math.ceil(primary / 2)), primary, primary * 2}
    )
    return [
        _interval(
            values,
            length=length,
            draws=config.draws,
            seed=seed,
            confidence=config.confidence,
            minimum_periods=config.minimum_periods,
            minimum_blocks=config.minimum_blocks,
            oracle=False,
        )
        for length in lengths
    ]
