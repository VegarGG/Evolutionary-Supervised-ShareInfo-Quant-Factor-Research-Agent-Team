"""Behavioral fingerprints (PLAN Section 7.5).

A fingerprint is the factor's cross-sectional ranks over the eligible set on 40 fixed
dates, sampled once per epoch from W0 with the protocol seed. Both zones see W0, so
both compute identical fingerprints. Similarity between two factors is the mean over
those dates of the absolute Spearman correlation on common names.
"""

from dataclasses import dataclass
from datetime import date

import numpy as np

from qfr_core.metrics.matrix import Array, Market, rank_rows, row_spearman


def fingerprint_dates(w0_dates: list[date], count: int, seed: int) -> list[date]:
    """count distinct W0 trading dates drawn with numpy's default generator."""
    if count > len(w0_dates):
        raise ValueError("W0 has fewer trading dates than fingerprint dates")
    picks = np.random.default_rng(seed).choice(len(w0_dates), size=count, replace=False)
    return [w0_dates[i] for i in sorted(int(p) for p in picks)]


@dataclass(frozen=True)
class Fingerprint:
    """Ranks on the fingerprint dates, keyed by instrument so zones can be compared."""

    dates: list[date]
    instruments: list[str]
    ranks: Array  # (len(dates), len(instruments)); NaN where not eligible or no value.

    def aligned(self, instruments: list[str]) -> Array:
        index = {name: i for i, name in enumerate(self.instruments)}
        out = np.full((len(self.dates), len(instruments)), np.nan)
        for j, name in enumerate(instruments):
            if name in index:
                out[:, j] = self.ranks[:, index[name]]
        return out


def fingerprint(factor: Array, market: Market, dates: list[date]) -> Fingerprint:
    position = {day: i for i, day in enumerate(market.dates)}
    missing = [d for d in dates if d not in position]
    if missing:
        raise ValueError(f"fingerprint dates missing from the market: {missing[:3]}")
    rows = [position[d] for d in dates]
    values = np.where(market.eligible[rows], factor[rows], np.nan)
    ranks = rank_rows(values)
    keep = np.isfinite(ranks).any(axis=0)
    names = [name for name, k in zip(market.instruments, keep, strict=True) if k]
    return Fingerprint(list(dates), names, ranks[:, keep])


def behavioral_similarity(a: Fingerprint, b: Fingerprint, minimum: int = 2) -> float | None:
    if a.dates != b.dates:
        raise ValueError("fingerprints from different date samples are not comparable")
    names = sorted(set(a.instruments) | set(b.instruments))
    values = np.abs(row_spearman(a.aligned(names), b.aligned(names), minimum))
    finite = values[np.isfinite(values)]
    return float(finite.mean()) if finite.size else None
