"""Independent decimal implementation for auditing frozen case calculations."""

import json
import math
from collections import Counter
from decimal import Decimal, localcontext

from qfh.shared_state import digest


def decimal_scores(rows, spec):
    """Deliberately does not call the production factor calculator or statistics library."""
    result = []
    with localcontext() as ctx:
        ctx.prec = 50
        length = spec["lookback"]
        window = max(length, spec["volatility_window"] or 0)
        for symbol in sorted({r["symbol"] for r in rows}):
            own = sorted((r for r in rows if r["symbol"] == symbol), key=lambda r: r["date"])
            prices = [Decimal(str(r["close"])) for r in own]
            changes = {i: prices[i] / prices[i - 1] - 1 for i in range(1, len(own))}
            for i, row in enumerate(own):
                reason, score = None, None
                if i < window:
                    reason = "insufficient_past_observations"
                elif spec["max_absolute_daily_return"] is not None and any(
                    abs(changes[j]) > Decimal(str(spec["max_absolute_daily_return"]))
                    for j in range(i - window + 1, i + 1)
                ):
                    reason = "past_return_bound"
                else:
                    value = spec["direction"] * (prices[i] / prices[i - length] - 1)
                    if spec["normalization"] == "realized_volatility":
                        n = spec["volatility_window"]
                        items = [changes[j] for j in range(i - n + 1, i + 1)]
                        average = sum(items) / n
                        variance = sum((v - average) ** 2 for v in items) / (n - 1)
                        if variance == 0:
                            reason = "zero_trailing_volatility"
                        else:
                            value /= variance.sqrt() * Decimal(length).sqrt()
                    score = None if reason else float(value)
                result.append(
                    {
                        "symbol": symbol,
                        "signal_date": row["date"],
                        "execution_date": own[i + 1]["date"] if i + 1 < len(own) else None,
                        "score": score,
                        "excluded_reason": reason,
                    }
                )
    return result


def close(a, b):
    assert (a is None and b is None) or (
        a is not None and b is not None and math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-12)
    ), (a, b)


def summary_checks(summary, rows):
    for symbol, actual in summary["by_symbol"].items():
        own = [r for r in rows if r["symbol"] == symbol]
        values = [r["score"] for r in own if r["score"] is not None]
        n = len(values)
        mean = sum(values) / n if n else None
        assert actual["eligible_signals"] == n
        assert actual["signals_with_next_observed_close"] == sum(
            r["score"] is not None and r["execution_date"] is not None for r in own
        )
        assert actual["exclusions"] == dict(
            Counter(r["excluded_reason"] for r in own if r["excluded_reason"] is not None)
        )
        close(actual["mean_score"], mean)
        close(actual["mean_absolute_score"], sum(map(abs, values)) / n if n else None)
        close(actual["maximum_absolute_score"], max(map(abs, values), default=None))
        close(
            actual["sample_sd_score"],
            math.sqrt(sum((v - mean) ** 2 for v in values) / (n - 1)) if n > 1 else None,
        )


def audit(directory):
    policy = json.loads((directory / "package.json").read_bytes())
    episode = policy["episode"]
    rows = episode["rows"]
    assert digest(rows) == episode["data_snapshot_sha256"]
    baseline = decimal_scores(rows, episode["initial_spec"])
    if not episode["synthetic_evidence"]:
        summary_checks(json.loads(episode["sources"]["initial_inspection"]), baseline)
        for symbol in episode["symbols"]:
            lines = episode["sources"]["prices_" + symbol.replace(".", "_")].splitlines()[1:]
            assert lines == [
                f"{r['symbol']},{r['date']},{r['close']}" for r in rows if r["symbol"] == symbol
            ]
    calculations = []
    events = [
        json.loads(p.read_bytes()) for p in sorted((directory / "board").glob("event-*.json"))
    ]
    for path in sorted(directory.glob("calculation-*.json")):
        saved = json.loads(path.read_bytes())
        computed = decimal_scores(rows, saved["spec"])
        assert len(computed) == len(saved["rows"])
        event = next(e for e in events if path.stem == "calculation-" + e["id"])
        assert {k: v for k, v in saved.items() if k != "rows"} == event["body"]
        assert digest(saved["spec"]) == saved["spec_sha256"]
        assert digest(saved["rows"]) == saved["summary"]["score_rows_sha256"]
        for expected, actual in zip(computed, saved["rows"], strict=True):
            close(expected["score"], actual["score"])
            assert {k: v for k, v in actual.items() if k != "score"} == {
                k: v for k, v in expected.items() if k != "score"
            }
        summary_checks(saved["summary"], computed)
        # Temporal check: changing the last close cannot change any earlier score.
        changed = [dict(r) for r in rows]
        last = max(r["date"] for r in rows)
        for row in changed:
            if row["date"] == last:
                row["close"] *= 2
        prefix = decimal_scores(changed, saved["spec"])
        assert [r for r in prefix if r["signal_date"] < last] == [
            r for r in computed if r["signal_date"] < last
        ]
        calculations.append(
            {
                "path": path.name,
                "spec": saved["spec"],
                "rows_recomputed": len(computed),
                "status": "pass",
            }
        )
    return {
        "status": "pass",
        "method": "independent 50-digit Decimal calculation",
        "snapshot_sha256": episode["data_snapshot_sha256"],
        "baseline_rows": len(baseline),
        "calculations": calculations,
        "checks": [
            "source CSV equals frozen rows",
            "raw/normalized scores and eligibility",
            "sample SD n-1",
            "per-symbol summaries",
            "execution timing",
        ]
        + (["future perturbation of inspected specifications"] if calculations else []),
        "limits": "Arithmetic only. Source interpretations, rationale and claimed improvements "
        "require separate semantic review. No performance test.",
    }
