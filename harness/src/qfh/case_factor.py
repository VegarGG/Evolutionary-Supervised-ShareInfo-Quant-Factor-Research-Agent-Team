"""Restricted trailing-price research calculations; no labels or official evaluation."""

from __future__ import annotations

import math
import statistics
from datetime import date
from typing import Literal

from pydantic import Field, model_validator

from qfh.shared_state import CandidateDefinition, Record, digest


class FactorSpec(Record):
    lookback: int = Field(ge=2, le=20, strict=True)
    direction: Literal[-1, 1]
    normalization: Literal["none", "realized_volatility"]
    volatility_window: int | None = Field(ge=5, le=20)
    max_absolute_daily_return: float | None = Field(gt=0, le=0.5, allow_inf_nan=False)

    @model_validator(mode="after")
    def meaningful(self):
        if (self.normalization == "none") != (self.volatility_window is None):
            raise ValueError("raw return has no volatility window; normalized return requires one")
        if type(self.direction) is not int:
            raise ValueError("direction must be integer -1 or 1")
        return self


def panel_quality(rows, symbols, start, end):
    seen = set()
    counts = dict.fromkeys(symbols, 0)
    dates = {s: set() for s in symbols}
    for row in rows:
        if set(row) != {"symbol", "date", "close"}:
            raise ValueError("panel schema differs")
        key = row["symbol"], row["date"]
        day = date.fromisoformat(row["date"])
        if (
            key in seen
            or key[0] not in counts
            or not date.fromisoformat(start) <= day <= date.fromisoformat(end)
            or type(row["close"]) not in (int, float)
            or not math.isfinite(row["close"])
            or row["close"] <= 0
        ):
            raise ValueError("invalid, duplicate or out-of-scope panel row")
        seen.add(key)
        counts[key[0]] += 1
        dates[key[0]].add(key[1])
    common = set.intersection(*dates.values()) if dates else set()
    union = set.union(*dates.values()) if dates else set()
    return {
        "grain": "one symbol/observed-date; close in CNY/share, unadjusted",
        "rows": len(rows),
        "rows_by_symbol": counts,
        "duplicate_keys": 0,
        "invalid_or_null_close": 0,
        "common_dates": len(common),
        "union_dates": len(union),
        "missing_from_observed_union": {s: sorted(union - days) for s, days in dates.items()},
        "first": min(union) if union else None,
        "last": max(union) if union else None,
        "calendar_limit": "Observed union is not an exchange calendar; absences are not "
        "proof of a market closure or suspension. No filling or corporate-action inference.",
    }


def price_profile(rows):
    result = {}
    for symbol in sorted({r["symbol"] for r in rows}):
        own = sorted((r for r in rows if r["symbol"] == symbol), key=lambda r: r["date"])
        returns = [b["close"] / a["close"] - 1 for a, b in zip(own, own[1:], strict=False)]
        result[symbol] = {
            "observations": len(own),
            "return_observations": len(returns),
            "minimum_close": min(r["close"] for r in own),
            "maximum_close": max(r["close"] for r in own),
            "mean_one_observation_return": statistics.mean(returns) if returns else None,
            "sample_sd_one_observation_return": statistics.stdev(returns)
            if len(returns) >= 2
            else None,
            "max_absolute_one_observation_return": max(map(abs, returns), default=None),
            "zero_return_count": returns.count(0),
        }
    return result


def definition(spec, symbols, hypothesis):
    return CandidateDefinition(
        name="Trailing close-return research candidate",
        expression=f"{spec.direction} * (close[t]/close[t-{spec.lookback}] - 1)"
        + (
            f" / (sample_sd(last {spec.volatility_window} one-observation simple returns)"
            f" * sqrt({spec.lookback}))"
            if spec.normalization != "none"
            else ""
        ),
        input_units="Unadjusted close in CNY/share; simple returns and final score dimensionless.",
        availability_rule="Use only observed closes at or before signal close t. "
        "Current historical download is not a vintage archive.",
        signal_rule="Signal after close t; require "
        f"{max(spec.lookback, spec.volatility_window or 0) + 1} "
        "trailing observations, positive volatility when normalized. "
        + (
            f"Exclude at t if any one-observation absolute return in that trailing window "
            f"exceeds {spec.max_absolute_daily_return}; bound is a fraction, not percent points."
            if spec.max_absolute_daily_return is not None
            else "No extra return-magnitude eligibility exclusion."
        ),
        execution_rule="No earlier than next observed close after t; last-row signal has no "
        "execution observation. No tradability or performance claim.",
        universe=", ".join(symbols) + "; fixed convenience sample, not a point-in-time universe.",
        hypothesis=hypothesis,
    )


def scores(rows, spec):
    values = []
    window = max(spec.lookback, spec.volatility_window or 0)
    for symbol in sorted({r["symbol"] for r in rows}):
        own = sorted((r for r in rows if r["symbol"] == symbol), key=lambda r: r["date"])
        returns = [b["close"] / a["close"] - 1 for a, b in zip(own, own[1:], strict=False)]
        for i, row in enumerate(own):
            reason, score = None, None
            if i < window:
                reason = "insufficient_past_observations"
            elif (
                spec.max_absolute_daily_return is not None
                and max(abs(r) for r in returns[i - window : i]) > spec.max_absolute_daily_return
            ):
                reason = "past_return_bound"
            else:
                score = spec.direction * (row["close"] / own[i - spec.lookback]["close"] - 1)
                if spec.volatility_window:
                    vol = statistics.stdev(returns[i - spec.volatility_window : i])
                    if vol == 0:
                        reason, score = "zero_trailing_volatility", None
                    else:
                        score /= vol * math.sqrt(spec.lookback)
            values.append(
                {
                    "symbol": symbol,
                    "signal_date": row["date"],
                    "execution_date": own[i + 1]["date"] if i + 1 < len(own) else None,
                    "score": score,
                    "excluded_reason": reason,
                }
            )
    return values


def inspect_factor(rows, spec, baseline):
    calculated, original = scores(rows, spec), scores(rows, baseline)
    changed = sum(
        a["score"] != b["score"] or a["excluded_reason"] != b["excluded_reason"]
        for a, b in zip(calculated, original, strict=True)
    )
    by_symbol = {}
    for symbol in sorted({r["symbol"] for r in rows}):
        own = [r for r in calculated if r["symbol"] == symbol]
        valid = [r["score"] for r in own if r["score"] is not None]
        by_symbol[symbol] = {
            "eligible_signals": len(valid),
            "signals_with_next_observed_close": sum(
                r["score"] is not None and r["execution_date"] is not None for r in own
            ),
            "mean_score": statistics.mean(valid) if valid else None,
            "sample_sd_score": statistics.stdev(valid) if len(valid) >= 2 else None,
            "mean_absolute_score": statistics.mean(map(abs, valid)) if valid else None,
            "maximum_absolute_score": max(map(abs, valid), default=None),
            "exclusions": {
                reason: sum(r["excluded_reason"] == reason for r in own)
                for reason in sorted({r["excluded_reason"] for r in own if r["excluded_reason"]})
            },
        }
    return {
        "spec": spec.model_dump(),
        "spec_sha256": digest(spec.model_dump()),
        "rows": calculated,
        "summary": {
            "by_symbol": by_symbol,
            "changed_score_or_eligibility_rows_from_initial": changed,
            "score_rows_sha256": digest(calculated),
            "limits": "Descriptive scores only. No forward labels, PnL, alpha, formal evaluation "
            "or proof that a revision is better. Sample SD uses n-1; windows use past observed "
            "rows, with no filling. Historical price jumps cannot identify corporate actions.",
        },
    }
