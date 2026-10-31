"""Decay monitoring detectors (PLAN Section 10.4, P8.7).

The v1 rule (in qfr_eval.sim) alarms when the rolling s x RankIC_mean stays below a
threshold for a run of days. Phase 8 adds a one-sided (lower) CUSUM on the daily forward
s x RankIC of a monitoring simulation, against the level the evaluation measured:

    S_0 = 0,   S_t = max(0, S_{t-1} + (mu0 - x_t - k) / sigma),   alarm when S_t >= h

mu0 is s x RankIC_mean and sigma the standard deviation of the daily RankIC
(|RankIC_mean / RankIC_IR|) of the version's W1 measurement (its re-measurement on the
new W1 after a rollover) made before monitoring began: the level it was admitted on,
over the longest window. W2 and the holdout are shorter and only decide pass or fail.
k = k_fraction x mu0, so the statistic drifts down by k / sigma a day
while the factor keeps its measured level and up by (mu0 - k) / sigma once it has fully
decayed. With k_fraction = 1/2 the detector is tuned to a complete loss of the signal.
h is in units of sigma. Days without a value leave the statistic unchanged.

Both detectors run on every monitoring tick and raise their own alert (decay:{sim} and
decay:cusum:{sim}), so the owner sees which one fired and when.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CusumReference:
    """The level monitoring compares with: an official record's s x RankIC."""

    record_id: str
    stage: str
    mu0: float
    sigma: float


@dataclass(frozen=True)
class CusumResult:
    alarm_index: int | None  # the first day whose statistic reached h
    statistic: float  # at the alarm, else at the last day
    peak: float
    days: int  # days with a value


def reference_from_metrics(
    record_id: str, stage: str, metrics: dict[str, Any], sign: int
) -> CusumReference | None:
    """mu0 and sigma from a record's RankIC mean and IR; None when they cannot anchor a
    one-sided detector (no positive signed mean, or no finite spread)."""
    mean, ir = metrics.get("rankic_mean"), metrics.get("rankic_ir")
    if mean is None or ir is None:
        return None
    mean, ir = float(mean), float(ir)
    if not (math.isfinite(mean) and math.isfinite(ir)) or ir == 0.0:
        return None
    mu0, sigma = sign * mean, abs(mean / ir)
    if mu0 <= 0 or not math.isfinite(sigma) or sigma <= 0:
        return None
    return CusumReference(record_id, stage, mu0, sigma)


def lower_cusum(
    values: Sequence[float], reference: CusumReference, k_fraction: float, h: float
) -> CusumResult:
    """Run the lower CUSUM over signed daily values (NaN for a missing day)."""
    k = k_fraction * reference.mu0
    s = peak = 0.0
    days = 0
    for index, x in enumerate(values):
        if not math.isfinite(x):
            continue
        days += 1
        s = max(0.0, s + (reference.mu0 - x - k) / reference.sigma)
        peak = max(peak, s)
        if s >= h:
            return CusumResult(index, s, peak, days)
    return CusumResult(None, s, peak, days)
