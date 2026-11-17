"""Post-settlement team accounting, independent of model prose and native root footer."""

from qfh.coding_plan import coding_detail
from qfh.shared_state import digest


def summarize_calls(calls, package_id):
    prefix = f"case:{package_id}:"
    selected = [c for c in calls if c["step"].startswith(prefix)]
    if not selected or any(c["state"] != "settled" or not c["usage"] for c in selected):
        raise ValueError("settled team usage requires every request to have known settled usage")
    agents = {}
    for call in selected:
        actor = call["step"][len(prefix) :].removesuffix(":ack")
        own = agents.setdefault(
            actor,
            {
                "work_requests": 0,
                "acknowledgement_requests": 0,
                "input_cached": 0,
                "input_uncached": 0,
                "input_cache_write": 0,
                "output": 0,
                "conservative_exposure_micro_cny": 0,
                "conservative_microcredits": 0,
            },
        )
        own["acknowledgement_requests" if call["step"].endswith(":ack") else "work_requests"] += 1
        usage = call["usage"]
        for key in ("input_cached", "input_uncached", "input_cache_write", "output"):
            own[key] += usage[key]
        own["conservative_exposure_micro_cny"] += call["charged"]
        detail = coding_detail(call)
        own["conservative_microcredits"] += detail.get("quota_settled_upper_microcredits", 0)
    totals = {k: sum(a[k] for a in agents.values()) for k in next(iter(agents.values()))}
    for value in [*agents.values(), totals]:
        value["requests"] = value["work_requests"] + value["acknowledgement_requests"]
        input_total = sum(value[k] for k in ("input_cached", "input_uncached", "input_cache_write"))
        value["total_tokens"] = input_total + value["output"]
        value["input_cache_hit_rate"] = value["input_cached"] / input_total if input_total else None
    return {
        "schema": "qfh.settled-team-usage.v1",
        "package_id": package_id,
        "calls_sha256": digest(selected),
        "request_ids": [c["id"] for c in selected],
        "settled_through": max(c["finished"] for c in selected),
        "agents": agents,
        "team": totals,
        "status": "all_settled",
        "scope": "All team work and worker acknowledgements. Supervisor ends via native "
        "concludeTurn after finalization; no paid supervisor acknowledgement or summary.",
        "billing_basis": "Conservative ledger exposure and credits, not a subscription invoice "
        "or provider account quota. Native footer covers its session only.",
    }


def settled_usage(host):
    snapshot = host.research.ledger.snapshot()
    summary = summarize_calls(snapshot["calls"], host.policy.package_id)
    summary["original_budget"] = {
        "cap_micro_cny": host.research.ledger.policy.total_micro_cny,
        **{
            k: snapshot[k]
            for k in (
                "cumulative_micro_cny",
                "unresolved_micro_cny",
                "remaining_unreserved_micro_cny",
            )
        },
    }
    return summary


def render_usage(summary):
    total = summary["team"]
    lines = ["SETTLED TEAM USAGE — host ledger", summary["scope"]]
    for actor, value in sorted(summary["agents"].items()):
        lines.append(
            f"{actor}: {value['work_requests']} work + "
            f"{value['acknowledgement_requests']} acknowledgement = "
            f"{value['requests']} requests; {value['total_tokens']} tokens"
        )
    lines += [
        f"Team: {total['requests']} requests; {total['total_tokens']} tokens; "
        f"{total['conservative_exposure_micro_cny'] / 1_000_000:.6f} CNY conservative exposure",
        summary["billing_basis"],
        "All requests settled. Pending independent research audit.",
    ]
    return "\n".join(lines)
