"""Executable development contrast, with explicit geometry and uncertainty states.

This is not a strategy, portfolio, official evaluator or publication interface.
The live ten-row pilot cannot satisfy the configured inference sample floor.
"""

import hashlib
import random
from datetime import date
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from qfh.evidence import canonical


class ContrastSpec(BaseModel):
    """One resolved rule; no alternatives, code strings or implicit parameters."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    family: Literal["close_return_contrast"]
    lookback: int = Field(strict=True, ge=1)
    comparison: Literal["lt", "gt"]
    threshold: Decimal = Field(allow_inf_nan=False, max_digits=16, decimal_places=12)
    tie_policy: Literal["control"]
    label_horizon: int = Field(strict=True, ge=1)
    expected_direction: Literal["higher", "lower"]
    effect_margin: Decimal = Field(ge=0, allow_inf_nan=False, max_digits=16, decimal_places=12)


class StatisticalProtocol(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    protocol: Literal["development-contrast-v1"]
    decimal_precision: int = Field(ge=16, le=64)
    execution_lag: Literal[1]
    max_lookback: int = Field(ge=1)
    max_label_horizon: int = Field(ge=1)
    max_threshold_magnitude: Decimal = Field(gt=0, allow_inf_nan=False)
    max_effect_margin: Decimal = Field(gt=0, allow_inf_nan=False)
    minimum_bucket_size: int = Field(ge=2)
    minimum_blocks: int = Field(ge=2)
    method: Literal["moving_block_percentile"]
    confidence_level: Decimal = Field(gt=0, lt=1, allow_inf_nan=False)
    block_length: int = Field(ge=1)
    bootstrap_replicates: int = Field(ge=100, le=10000)
    seed: int
    maximum_observations: int = Field(ge=2, le=100000)


def resolved_definition(spec, protocol):
    if spec.lookback > protocol.max_lookback or spec.label_horizon > protocol.max_label_horizon:
        raise ValueError("lookback or label horizon exceeds the specification policy")
    if (
        spec.threshold.copy_abs() > protocol.max_threshold_magnitude
        or spec.effect_margin > protocol.max_effect_margin
    ):
        raise ValueError("threshold or effect margin exceeds the specification policy")
    definition = spec.model_dump(mode="json")
    # Numerically equivalent spellings produce the same specification identity.
    for key in ("threshold", "effect_margin"):
        value = getattr(spec, key)
        text = format(value, "f")
        definition[key] = (text.rstrip("0").rstrip(".") if "." in text else text) if value else "0"
    return definition


def interval_outcome(lower, upper, margin):
    """Geometry of a nominal interval, never hypothesis confirmation/disproof."""
    if lower > upper:
        raise ValueError("reversed interval")
    if lower > margin:
        return "interval_above_margin"
    if upper < margin:
        return "interval_below_margin"
    return "inconclusive"


def percentile(values, probability):
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def contrast(pairs, direction):
    groups = [
        [value for signal, value in pairs if signal == selected] for selected in (True, False)
    ]
    if any(not group for group in groups):
        return None
    difference = sum(groups[0]) / len(groups[0]) - sum(groups[1]) / len(groups[1])
    return difference if direction == "higher" else -difference


def infer_contrast(pairs, spec, protocol, block_length):
    """Joint moving blocks preserve signal/label pairing; no resampling retries."""
    counts = [sum(signal == group for signal, _ in pairs) for group in (True, False)]
    reasons = [
        name
        for count, name in zip(
            counts, ("signal_bucket_below_minimum", "control_bucket_below_minimum"), strict=True
        )
        if count < protocol.minimum_bucket_size
    ]
    if len(pairs) < block_length * protocol.minimum_blocks:
        reasons.append("too_few_blocks")
    if reasons:
        return {
            "outcome": "insufficient_data",
            "reason_codes": reasons,
            "effect": None,
            "interval": None,
            "bootstrap_replicates_run": 0,
        }
    rng = random.Random(protocol.seed)
    estimates = []
    for _ in range(protocol.bootstrap_replicates):
        draw = []
        while len(draw) < len(pairs):
            start = rng.randrange(len(pairs) - block_length + 1)
            draw.extend(pairs[start : start + block_length])
        value = contrast(draw[: len(pairs)], spec.expected_direction)
        if value is None:
            return {
                "outcome": "resampling_unavailable",
                "reason_codes": ["empty_bootstrap_bucket"],
                "effect": None,
                "interval": None,
                "bootstrap_replicates_run": len(estimates) + 1,
            }
        estimates.append(value)
    tail = (1 - protocol.confidence_level) / 2
    lower, upper = percentile(estimates, tail), percentile(estimates, 1 - tail)
    return {
        "outcome": interval_outcome(lower, upper, spec.effect_margin),
        "reason_codes": [],
        "effect": str(contrast(pairs, spec.expected_direction)),
        "interval": {"lower": str(lower), "upper": str(upper), "unit": "return_fraction"},
        "bootstrap_replicates_run": len(estimates),
    }


def render_formula(spec, protocol, block_length):
    comparator = "<" if spec.comparison == "lt" else ">"
    orientation = "+1" if spec.expected_direction == "higher" else "-1"
    return (
        f"r_t = close_t / close_(t-{spec.lookback}) - 1; "
        f"signal_t = 1[r_t {comparator} {spec.threshold}]; "
        "equality goes to control. Signal known at close_t; execution at close_(t+1); "
        f"label_t = close_(t+1+{spec.label_horizon}) / close_(t+1) - 1. "
        "Indices count returned observations; exchange-calendar verification is required. "
        f"Effect = {orientation} * (mean(label | signal) - mean(label | control)); "
        f"effect margin = {spec.effect_margin}; "
        f"minimum per bucket = {protocol.minimum_bucket_size}; "
        f"minimum blocks = {protocol.minimum_blocks}. Joint non-wrapping moving-block percentile "
        f"interval, coverage {protocol.confidence_level}, block length {block_length}, "
        f"replicates {protocol.bootstrap_replicates}, seed {protocol.seed}. "
        "Insufficient support: insufficient_data. Interval wholly above/below margin: "
        "interval_above_margin/interval_below_margin; otherwise inconclusive. "
        "No confirmation, disconfirmation, profitability, independence or absence-of-effect claim."
    )


def assess_specification(evidence_id, rows, spec, protocol):
    definition = resolved_definition(spec, protocol)
    ordered = sorted(rows, key=lambda r: r["date"])
    dates = [date.fromisoformat(r["date"]).isoformat() for r in ordered]
    prices = [Decimal(str(r["close"])) for r in ordered]
    if not 2 <= len(rows) <= protocol.maximum_observations or len(set(dates)) != len(dates):
        raise ValueError("distinct dated observations within the configured size bound required")
    if len({r["symbol"] for r in rows}) != 1 or any(not p.is_finite() or p <= 0 for p in prices):
        raise ValueError("one symbol and finite positive closes required")
    # Normalize spelling before rendering and hashing the full executable definition.
    spec = ContrastSpec.model_validate(definition)
    block_length = max(protocol.block_length, spec.label_horizon)
    identity = {
        "evidence_id": evidence_id,
        "definition": definition,
        "protocol": protocol.model_dump(mode="json"),
        "effective_block_length": block_length,
        "calculator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    with localcontext() as context:
        context.prec = protocol.decimal_precision
        pairs, alignment = [], []
        ties = 0
        for i in range(spec.lookback, len(prices)):
            execution, end = (
                i + protocol.execution_lag,
                i + protocol.execution_lag + spec.label_horizon,
            )
            trailing = prices[i] / prices[i - spec.lookback] - 1
            selected = (
                trailing < spec.threshold if spec.comparison == "lt" else trailing > spec.threshold
            )
            available = end < len(prices)
            if available:
                pairs.append((selected, prices[end] / prices[execution] - 1))
                ties += trailing == spec.threshold
            alignment.append(
                {
                    "signal_date": dates[i],
                    "execution_date": dates[execution] if execution < len(dates) else None,
                    "label_end_date": dates[end] if available else None,
                    "label_available": available,
                }
            )
        eligible = [r for r in alignment if r["label_available"]]
        adjacent = list(zip(eligible, eligible[1:], strict=False))
        overlap = sum(
            max(a["execution_date"], b["execution_date"])
            < min(a["label_end_date"], b["label_end_date"])
            for a, b in adjacent
        )
        touching = sum(a["label_end_date"] == b["execution_date"] for a, b in adjacent)
        payload = {
            **identity,
            "specification_id": hashlib.sha256(canonical(identity)).hexdigest(),
            "canonical_formula": render_formula(spec, protocol, block_length),
            "support": {
                "signal_candidates": len(alignment),
                "aligned_cases": len(pairs),
                "dropped_tail_cases": len(alignment) - len(pairs),
                "signal_bucket": sum(s for s, _ in pairs),
                "control_bucket": sum(not s for s, _ in pairs),
                "ties_assigned_to_control": ties,
            },
            "label_geometry": {
                "adjacent_pairs": len(adjacent),
                "positive_overlap_pairs": overlap,
                "touching_endpoint_pairs": touching,
                "serial_independence": "not_established",
            },
            "alignment": alignment,
            "inference": infer_contrast(pairs, spec, protocol, block_length),
            "analysis_phase": "post_observation_exploration",
            "limits": [
                "Development contrast, not a strategy P&L, official evaluation or publication.",
                "Nominal interval requires suitable stationarity/dependence assumptions; "
                "coverage is not certified.",
                "No adjustment for post-observation selection or multiple hypotheses; "
                "not confirmatory.",
                "Effect margin is a contrast threshold, not a transaction-cost "
                "or profitability model.",
                "Zero threshold and explicit ties-to-control are valid choices, "
                "not automatically defective.",
                "Unadjusted historical closes; exchange calendar and point-in-time "
                "vintage unverified.",
            ],
        }
    return {**payload, "assessment_id": hashlib.sha256(canonical(payload)).hexdigest()}
