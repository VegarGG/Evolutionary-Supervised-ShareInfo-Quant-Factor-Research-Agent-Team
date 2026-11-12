"""Deterministic arithmetic on granted development closes; no strategy execution."""

import hashlib
from datetime import date
from decimal import Decimal, localcontext
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from qfh.evidence import canonical


class ArithmeticProtocol(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    protocol: str
    decimal_precision: int = Field(ge=16, le=64)
    execution_lag: int = Field(ge=1, le=10)
    label_horizon: int = Field(ge=1, le=10)


class MeasurementRef(BaseModel):
    """Select host-calculated facts. Model-authored values are not accepted."""

    model_config = ConfigDict(extra="forbid")
    measurement_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    keys: list[str] = Field(min_length=1, max_length=32)


def calculate_observations(evidence_id, rows, lookbacks, protocol):
    rows = sorted(rows, key=lambda row: row["date"])
    dates = [date.fromisoformat(row["date"]).isoformat() for row in rows]
    prices = [Decimal(str(row["close"])) for row in rows]
    if len(rows) < 2 or len(set(dates)) != len(dates):
        raise ValueError("at least two distinct observation dates required")
    if len({row["symbol"] for row in rows}) != 1:
        raise ValueError("arithmetic requires a single symbol")
    if any(not p.is_finite() or p <= 0 for p in prices):
        raise ValueError("finite positive closes required")
    if not lookbacks or any(not isinstance(n, int) or n < 1 for n in lookbacks):
        raise ValueError("positive observation lookbacks required")
    facts = {}

    def fact(key, value, unit):
        facts[key] = {"value": str(value), "unit": unit}

    with localcontext() as context:
        context.prec = protocol.decimal_precision
        returns = [prices[i] / prices[i - 1] - 1 for i in range(1, len(prices))]
        mean = sum(returns) / len(returns)
        ordered = sorted(returns)
        middle = len(ordered) // 2
        median = ordered[middle] if len(ordered) % 2 else sum(ordered[middle - 1 : middle + 1]) / 2
        fact("sample.observations", len(prices), "count")
        fact("sample.first_date", dates[0], "date")
        fact("sample.last_date", dates[-1], "date")
        fact("sample.net_return", prices[-1] / prices[0] - 1, "return_fraction")
        fact("sample.minimum_close", min(prices), "price")
        fact("sample.maximum_close", max(prices), "price")
        fact("returns.count", len(returns), "count")
        fact("returns.mean", mean, "return_fraction")
        fact("returns.median", median, "return_fraction")
        fact("returns.positive_count", sum(r > 0 for r in returns), "count")
        fact("returns.negative_count", sum(r < 0 for r in returns), "count")
        fact("returns.zero_count", sum(r == 0 for r in returns), "count")
        if len(returns) > 1:
            variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
            fact("returns.sample_stdev", variance.sqrt(), "return_fraction")
        for i, value in enumerate(returns, start=1):
            fact(f"daily_return.{dates[i]}", value, "return_fraction")
        alignment = {}
        for n in sorted(set(lookbacks)):
            signals = list(range(n, len(prices)))
            eligible = [
                i
                for i in signals
                if i + protocol.execution_lag + protocol.label_horizon < len(prices)
            ]
            fact(f"lag.{n}.signal_count", len(signals), "count")
            fact(f"lag.{n}.aligned_case_count", len(eligible), "count")
            if signals:
                fact(f"lag.{n}.first_signal_date", dates[signals[0]], "date")
                fact(f"lag.{n}.latest_return", prices[-1] / prices[-n - 1] - 1, "return_fraction")
            alignment[str(n)] = []
            for i in signals:
                execution = i + protocol.execution_lag
                end = execution + protocol.label_horizon
                fact(f"lag.{n}.return.{dates[i]}", prices[i] / prices[i - n] - 1, "return_fraction")
                alignment[str(n)].append(
                    {
                        "signal_date": dates[i],
                        "lookback_start_date": dates[i - n],
                        "execution_date": dates[execution] if execution < len(dates) else None,
                        "label_end_date": dates[end] if end < len(dates) else None,
                        "label_available": end < len(dates),
                    }
                )
        payload = {
            "evidence_id": evidence_id,
            "protocol": protocol.model_dump(),
            "calculator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "facts": facts,
            "alignment": alignment,
            "interpretation": "Observed development-sample arithmetic only. Returns are fractions, "
            "not percentages. Lags count returned observations; exchange-calendar completeness "
            "is unverified. No strategy P&L, backtest, preregistration or gate result is computed.",
        }
    return {**payload, "measurement_id": hashlib.sha256(canonical(payload)).hexdigest()}
