"""Measured team usage and activity-window resources, without isolated-agent claims."""

import json
from collections import Counter
from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from qfh.coding_plan import coding_detail
from qfh.research import parse_worker_report

TOKEN_FIELDS = ("input_uncached", "input_cached", "input_cache_write", "output")


def peak_rate(calls, field, weighted=False):
    points = sorted(
        (
            datetime.fromisoformat(c[field]).timestamp(),
            (sum(c["usage"].values()) if c["usage"] else 0) if weighted else 1,
        )
        for c in calls
        if c[field]
    )
    return max((sum(n for t, n in points if end - 60 < t <= end) for end, _ in points), default=0)


def offpeak_cost(call, pricing):
    """Price only complete calls wholly outside any possible peak interval."""
    usage = call.get("usage")
    if (
        not usage
        or usage["input_cache_write"]
        or call["state"] != "settled"
        or not call.get("finished")
    ):
        return None
    zone = ZoneInfo(pricing["timezone"])
    start = datetime.fromisoformat(call["started"])
    finish = datetime.fromisoformat(call["finished"])
    if start.tzinfo is None or finish.tzinfo is None:
        return None
    start, finish = start.astimezone(zone), finish.astimezone(zone)
    if finish < start:
        return None
    day = start.date()
    while day <= finish.date():
        for lower, upper in pricing["possible_peak_hours"]:
            peak_start = datetime.combine(day, time(lower), zone)
            peak_end = datetime.combine(day, time(upper), zone)
            if start < peak_end and finish >= peak_start:
                return None
        day += timedelta(days=1)
    rate = pricing["offpeak_per_million"]
    return sum(Decimal(rate[k]) * usage[k] for k in rate) / pricing["tokens_per_price_unit"]


def model_metrics(calls, pricing, *, synthetic=False):
    subscription = pricing.get("funding") == "coding_plan"
    totals = {k: sum(c["usage"][k] for c in calls if c["usage"]) for k in TOKEN_FIELDS}
    inputs = sum(totals[k] for k in TOKEN_FIELDS if k != "output")
    costs = [None if subscription else offpeak_cost(c, pricing) for c in calls]
    complete = bool(calls) and all(c["state"] == "settled" and c["usage"] for c in calls)
    details = [coding_detail(c) for c in calls] if subscription else []
    cache_known = (
        not subscription
        or bool(details)
        and all(d.get("cache_tokens_reported") is True for d in details)
    )
    return {
        "requests": len(calls),
        "requests_with_known_usage": sum(c["usage"] is not None for c in calls),
        "all_usage_settled": complete,
        "tokens": totals
        if cache_known
        else {
            "input_total": inputs,
            "input_uncached": None,
            "input_cached": None,
            "input_cache_write": None,
            "output": totals["output"],
        },
        "total_tokens": sum(totals.values()),
        "input_cache_hit_ratio": totals["input_cached"] / inputs
        if inputs and cache_known
        else None,
        "cache_tokens_reported_for_all_calls": cache_known,
        "cache_reporting_note": "Absent cache counters do not establish a zero hit rate."
        if not cache_known
        else "Explicit provider cache counters.",
        "peak_rolling_60s_dispatch_rpm": peak_rate(calls, "started"),
        "peak_rolling_60s_completion_rpm": peak_rate(calls, "finished"),
        "peak_rolling_60s_dispatch_tpm": peak_rate(calls, "started", True),
        "peak_rolling_60s_completion_tpm": peak_rate(calls, "finished", True),
        "conservative_settled_cny": sum(c["charged"] or 0 for c in calls) / 1_000_000,
        "unresolved_reserved_cny": sum(c["reserved"] for c in calls if c["charged"] is None)
        / 1_000_000,
        "published_price_estimate_cny": float(sum(costs))
        if calls and not synthetic and all(v is not None for v in costs)
        else None,
        "unpriced_requests": sum(v is None for v in costs),
        "cost_invoice_verified": False,
        "funding": pricing.get("funding", "metered_api"),
        "subscription_credits_settled_upper_bound": sum(
            d.get("quota_settled_upper_microcredits") or 0 for d in details
        )
        / 1_000_000
        if subscription
        else None,
        "subscription_credits_unresolved_reserved": sum(
            d.get("quota_reserved_microcredits", 0)
            for d in details
            if d.get("quota_settled_upper_microcredits") is None
        )
        / 1_000_000
        if subscription
        else None,
        "rate_definition": "Call totals attributed to dispatch/completion, not per-token arrival. "
        "Unknown usage is excluded from TPM, counted in RPM and retains its budget reservation.",
        "cost_basis": "Synthetic fixture; no actual spend."
        if synthetic
        else "Existing GLM Coding Plan Pro. The shared cash ledger retains a conservative "
        "exposure debit, not an incremental cash invoice; subscription purchase cost is not "
        "allocated. Credits are a conservative upper estimate ignoring "
        "cache and off-peak discounts, not an account invoice."
        if subscription
        else "Actual provider token counts at published off-peak rates; estimate, not invoice. "
        "The separate conservative amount remains the budget debit.",
    }


def role_windows(members, events, start, finish):
    """Native worker activation spans; supervisor excludes those waiting periods."""
    windows = {m["role"]: [] for m in members}
    workers = []
    for member in members:
        if member["role"] == "supervisor":
            continue
        marks = [e for e in events if e["body"].get("child_id") == member["session_id"]]
        begins = [datetime.fromisoformat(e["at"]) for e in marks if e["kind"] == "worker_started"]
        ends = [datetime.fromisoformat(e["at"]) for e in marks if e["kind"] == "worker_finished"]
        if not begins:
            continue
        lower, upper = max(start, min(begins)), min(finish, max(ends) if ends else finish)
        if upper >= lower:
            windows[member["role"]] = [(lower, upper)]
            workers.append((lower, upper))
    cursor = start
    for lower, upper in sorted(workers):
        if lower > cursor:
            windows["supervisor"].append((cursor, lower))
        cursor = max(cursor, upper)
    if cursor < finish:
        windows["supervisor"].append((cursor, finish))
    return windows


def resource_metrics(samples, windows):
    """The shared local process tree observed during selected activity intervals.

    CPU deltas crossing a role boundary are excluded. These are observations
    during activity, not additive or isolated per-agent allocations.
    """
    samples = sorted(samples, key=lambda s: s["at"])

    def inside(value):
        return any(lower <= value < upper for lower, upper in windows)

    selected = [s for s in samples if inside(datetime.fromisoformat(s["at"]))]
    rates = []
    covered_seconds = cpu_seconds = 0.0
    for first, second in zip(samples, samples[1:], strict=False):
        lower, upper = datetime.fromisoformat(first["at"]), datetime.fromisoformat(second["at"])
        if not any(begin <= lower < upper <= end for begin, end in windows):
            continue
        previous = first.get("process_cpu_seconds_by_pid", {})
        current = second.get("process_cpu_seconds_by_pid", {})
        if not previous or not current:
            continue
        elapsed = (upper - lower).total_seconds()
        cpu = sum(max(0, seconds - previous.get(pid, 0)) for pid, seconds in current.items())
        rates.append(cpu / elapsed)
        cpu_seconds += cpu
        covered_seconds += elapsed
    host_cpu = [s["host_cpu_percent"] for s in selected if s.get("host_cpu_percent") is not None]
    memory = [s["host_memory"] for s in selected if s.get("host_memory")]
    disk = [s["disk_free_bytes"] for s in selected if s.get("disk_free_bytes") is not None]
    return {
        "activity_windows_utc": [[a.isoformat(), b.isoformat()] for a, b in windows],
        "activity_wall_seconds": sum((b - a).total_seconds() for a, b in windows),
        "samples": len(selected),
        "process_tree_peak_rss_bytes": max(
            (s["process_tree_rss_bytes"] for s in selected), default=None
        ),
        "process_tree_peak_sampled_cpu_cores": max(rates, default=None),
        "process_tree_mean_sampled_cpu_cores": cpu_seconds / covered_seconds
        if covered_seconds
        else None,
        "cpu_sample_coverage_seconds": covered_seconds,
        "host_cpu_max_percent": max(host_cpu, default=None),
        "swap_peak_bytes": max(
            (s["host_swap"]["used"] for s in selected if s.get("host_swap")), default=None
        ),
        "host_total_ram_bytes": memory[0]["total"] if memory else None,
        "host_available_ram_min_bytes": min((m["available"] for m in memory), default=None),
        "work_volume_min_free_bytes": min(disk, default=None),
        "measurement_errors": sorted(
            {e for s in selected for e in s.get("measurement_errors", [])}
        ),
        "scope": "Shared guard/DSH/data process tree during activity windows, not isolated "
        "per-agent allocation. Host readings include other work. CPU intervals crossing "
        "activity boundaries and short-lived children may be missed. Null means unmeasured.",
    }


def work_metrics(member, events, draft):
    own = [e for e in events if e["principal"] == member["session_id"]]
    tools = [e for e in own if e["kind"] == "tool_result"]
    report = None
    if member["role"] != "supervisor" and member["state"] == "completed":
        submitted = [e for e in own if e["kind"] == "worker_report_submitted"]
        if submitted:
            report = submitted[0]["body"]["report"]
        else:
            # Historical trials used final-text reports; retain their original contract.
            result = json.loads(member["result"])
            report, _ = parse_worker_report(result, len(member["result"]))
            report = report.model_dump()
    return {
        "model_authored_report": None
        if report is None
        else {
            k: report.get(k)
            for k in (
                "summary",
                "findings",
                "proposed_formula",
                "recommended_changes",
                "limitations",
                "measurement_refs",
                "specification_id",
            )
        },
        "verified_measurements": [
            fact
            for e in events
            if e["kind"] == "tool_result"
            and e["body"]["op"] == "finish_worker"
            and e["body"]["result"].get("contribution_id") == member["session_id"]
            for fact in e["body"]["result"].get("measured_facts", [])
        ],
        "executed_specifications": [
            e["body"]["result"] for e in tools if e["body"]["op"] == "specification"
        ],
        "successful_tool_operations": dict(
            Counter(
                e["body"]["op"]
                + (":" + e["body"]["args"].get("kind", "") if e["body"]["op"] == "data" else "")
                for e in tools
            )
        ),
        "operation_count_scope": "Backend operations include host-side lifecycle bookkeeping.",
        "failed_tool_operations": sum(e["kind"] == "tool_failure" for e in own),
        "report_submission_rejections": sum(
            e["body"]["op"] == "submit_report" and e["body"]["result"].get("status") == "rejected"
            for e in tools
        ),
        "evidence_fetches": [
            {k: e["body"]["result"].get(k) for k in ("evidence_id", "cache_reused", "row_count")}
            for e in tools
            if e["body"]["op"] == "data" and e["body"]["args"].get("kind") == "bars"
        ],
        "contribution_decisions": []
        if draft is None
        else [
            d
            for d in draft["decisions"]
            if member["role"] == "supervisor" or d["worker"] == member["role"]
        ],
        "draft_recorded": member["role"] == "supervisor" and draft is not None,
    }
