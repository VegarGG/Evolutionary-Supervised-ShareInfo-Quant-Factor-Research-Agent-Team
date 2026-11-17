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


def changed_rows(computed, original, *, tolerant=False):
    return sum(
        a["excluded_reason"] != b["excluded_reason"]
        or (
            a["score"] != b["score"]
            if not tolerant or a["score"] is None or b["score"] is None
            else not math.isclose(a["score"], b["score"], rel_tol=1e-10, abs_tol=1e-12)
        )
        for a, b in zip(computed, original, strict=True)
    )


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
        computed_body = {k: v for k, v in saved.items() if k != "rows"}
        extra = set(event["body"]) - set(computed_body)
        assert extra in (set(), {"comparison_parent_id", "comparisons"})
        assert computed_body == {k: v for k, v in event["body"].items() if k not in extra}
        assert digest(saved["spec"]) == saved["spec_sha256"]
        assert digest(saved["rows"]) == saved["summary"]["score_rows_sha256"]
        for expected, actual in zip(computed, saved["rows"], strict=True):
            close(expected["score"], actual["score"])
            assert {k: v for k, v in actual.items() if k != "score"} == {
                k: v for k, v in expected.items() if k != "score"
            }
        summary_checks(saved["summary"], computed)
        changed_count = changed_rows(
            computed, baseline, tolerant=policy.get("evidence_contract") == "typed-v1"
        )
        assert saved["summary"]["changed_score_or_eligibility_rows_from_initial"] == changed_count
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
                "changed_rows_from_initial": changed_count,
                "status": "pass",
            }
        )
    report_check = audit_report(directory, episode, events)
    return {
        "status": "pass",
        "method": "independent 50-digit Decimal calculation",
        "snapshot_sha256": episode["data_snapshot_sha256"],
        "baseline_rows": len(baseline),
        "calculations": calculations,
        "structured_report": report_check,
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


def audit_report(directory, episode, events):
    """Check the saved report independently of its builder and renderer."""
    path = directory / "FINAL_REPORT.json"
    if not path.exists():
        return {"status": "not_finalized_or_legacy"}
    report = json.loads(path.read_bytes())
    body = report["body"]
    assert digest(body) == report["sha256"]
    final = next(e for e in events if e["kind"] == "finalized")["body"]
    assert final["report_sha256"] == report["sha256"]
    head = next(e for e in events if e["id"] == final["output_id"])
    review = next(e for e in events if e["id"] == final["review_id"])
    assert review["body"]["structured_review"]["report_sha256"] == report["sha256"]
    assert body["candidate_id"] == head["id"]
    assert body["model_proposal"] == head["body"]["structured_submission"]
    receipt = body["calculation_provenance"]
    inspection = next(e for e in events if e["id"] == receipt["inspection_id"])
    assert receipt["engine"] == "deterministic_host"
    assert receipt["requested_by"] == inspection["actor"] == head["actor"]
    pinned = body["facts"]
    assert digest(pinned) == body["facts_sha256"] == body["model_proposal"]["facts_sha256"]
    assert pinned["data_snapshot_sha256"] == episode["data_snapshot_sha256"]
    assert pinned["spec"] == inspection["body"]["spec"] == head["body"]["spec"]
    assert pinned["spec_sha256"] == digest(pinned["spec"]) == inspection["body"]["spec_sha256"]
    assert pinned["score_rows_sha256"] == inspection["body"]["summary"]["score_rows_sha256"]
    assert pinned["units"] == {
        "close": "CNY/share",
        "raw_return": "dimensionless",
        "normalized_return": "dimensionless",
        "score": "dimensionless",
    }
    assert pinned["timing"]["tradability"] == "not_established"
    assert pinned["timing"]["fills"] == pinned["timing"]["costs"] == "not_measured"
    assert pinned["scope"]["data_use"] == "development_only"
    assert body["source_sha256"] == {k: digest(v) for k, v in episode["sources"].items()}
    expected = {}
    computed = decimal_scores(episode["rows"], pinned["spec"])
    original = decimal_scores(episode["rows"], episode["initial_spec"])
    changed = changed_rows(computed, original, tolerant="comparisons" in body)
    assert pinned["changed_rows_from_initial"] == changed
    assert (
        inspection["body"]["summary"]["changed_score_or_eligibility_rows_from_initial"] == changed
    )
    for symbol in episode["symbols"]:
        own = [r for r in computed if r["symbol"] == symbol]
        warmup = sum(r["excluded_reason"] == "insufficient_past_observations" for r in own)
        n = sum(r["score"] is not None for r in own)
        counts = {
            "observed_closes": len(own),
            "closes_required_per_signal": max(
                pinned["spec"]["lookback"], pinned["spec"]["volatility_window"] or 0
            )
            + 1,
            "warmup_exclusions": warmup,
            "eligible_signals": n,
            "additional_exclusions": len(own) - warmup - n,
            "signals_with_next_observed_close": sum(
                r["score"] is not None and r["execution_date"] is not None for r in own
            ),
        }
        for key, value in counts.items():
            expected[f"{symbol}.{key}"] = {"value": value, "unit": "count"}
        # Exact copy integrity in addition to the independent Decimal summary check.
        for key, value in inspection["body"]["summary"]["by_symbol"][symbol].items():
            if key.endswith("score"):
                expected[f"{symbol}.{key}"] = {"value": value, "unit": "dimensionless"}
    assert pinned["metrics"] == expected
    for item in body.get("comparisons", []):
        left_head = next(e for e in events if e["id"] == item["left_candidate_id"])
        right_event = next(e for e in events if e["id"] == item["right_inspection_id"])
        assert right_event["actor"] == head["actor"]
        assert item["left_candidate_id"] == head["body"]["parent_id"]
        left_spec = left_head["body"].get("spec", episode["initial_spec"])
        right_spec = right_event["body"]["spec"]
        assert item["left_spec_sha256"] == digest(left_spec)
        assert item["right_spec_sha256"] == digest(right_spec)
        panels = [
            {
                (r["symbol"], r["signal_date"]): r["score"]
                for r in decimal_scores(episode["rows"], s)
                if r["score"] is not None
            }
            for s in (left_spec, right_spec)
        ]
        common = set(panels[0]) & set(panels[1])
        assert item["cohort"] in ("paired_eligible_symbol_dates", "each_spec_eligible_symbol_dates")
        keys = [common, common] if item["cohort"].startswith("paired") else [set(p) for p in panels]
        assert item["same_observations"] == (keys[0] == keys[1])
        values = []
        for side, panel, selected in zip(("left", "right"), panels, keys, strict=True):
            deviations = []
            for symbol in episode["symbols"]:
                own = sorted(k for k in selected if k[0] == symbol)
                saved = item[f"{side}_by_symbol"][symbol]
                assert saved["count"] == len(own)
                assert saved["dates_sha256"] == digest([k[1] for k in own])
                if len(own) < 2:
                    assert saved["sample_sd"] is None
                    deviations.append(None)
                    continue
                numbers = [Decimal(str(panel[k])) for k in own]
                mean = sum(numbers) / len(numbers)
                sd = (sum((v - mean) ** 2 for v in numbers) / (len(numbers) - 1)).sqrt()
                assert math.isclose(saved["sample_sd"], float(sd), rel_tol=1e-10, abs_tol=1e-12)
                deviations.append(sd)
            assert item["measure"] in ("score_sd_max_minus_min", "score_sd_max_over_min")
            if any(v is None for v in deviations):
                value = None
            elif item["measure"].endswith("minus_min"):
                value = max(deviations) - min(deviations)
            else:
                value = max(deviations) / min(deviations) if min(deviations) > 0 else None
            observed = item[f"{side}_value"]
            assert (
                observed is None
                if value is None
                else math.isclose(observed, float(value), rel_tol=1e-10, abs_tol=1e-12)
            )
            values.append(value)
        a, b = values
        direction = (
            "undefined"
            if a is None or b is None
            else "equal"
            if a == b
            else "increased"
            if b > a
            else "decreased"
        )
        assert item["direction_right_vs_left"] == direction
    return {
        "status": "pass",
        "report_sha256": report["sha256"],
        "changed_rows_from_initial": changed,
        "checks": [
            "complete artifact/review binding",
            "exact metric copies",
            "independent specification hash and changed-row count",
            "independent counts",
            "units and evidence states",
            "inspection provenance",
        ],
        "limits": "Qualitative interpretation still requires independent semantic review.",
    }
