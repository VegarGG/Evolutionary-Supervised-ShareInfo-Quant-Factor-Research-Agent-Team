"""Native DSH pi-ai Chat Completions validation and usage accounting."""

from qfh.budget import BudgetRefused, Usage


def validate_chat_request(body, model, max_tokens, allowed_tools):
    allowed = {
        "model",
        "messages",
        "max_tokens",
        "max_completion_tokens",
        "stream",
        "stream_options",
        "temperature",
        "top_p",
        "stop",
        "tools",
        "tool_choice",
        "parallel_tool_calls",
        "reasoning_effort",
        "thinking",
        "tool_stream",
    }
    if set(body) - allowed:
        raise BudgetRefused(
            "unapproved Chat Completions fields: " + ", ".join(sorted(set(body) - allowed))
        )
    if body.get("tool_choice", "auto") != "auto":
        raise BudgetRefused("unapproved Chat Completions tool choice")
    if "tool_stream" in body and type(body["tool_stream"]) is not bool:
        raise BudgetRefused("invalid streamed tool-call option")
    if body.get("thinking", {}).get("type", "enabled") != "enabled":
        raise BudgetRefused("GLM 5.3 Flash requires thinking enabled")
    if body.get("model") != model or body.get("stream") is not True:
        raise BudgetRefused("only the configured streaming model is allowed")
    caps = [body[k] for k in ("max_tokens", "max_completion_tokens") if k in body]
    if len(caps) != 1 or type(caps[0]) is not int or not 0 < caps[0] <= max_tokens:
        raise BudgetRefused("missing or excessive requested output cap")
    if body.get("stream_options") != {"include_usage": True}:
        raise BudgetRefused("streaming usage must be requested")
    for tool in body.get("tools", []):
        if (
            tool.get("type") != "function"
            or tool.get("function", {}).get("name") not in allowed_tools
        ):
            raise BudgetRefused("unapproved or separately billed tool")
    return caps[0]


def parse_chat_usage(events, *, complete, model):
    usages = [e["usage"] for e in events if e.get("usage")]
    identities = {e["model"].lower() for e in events if e.get("model")}
    finished = any(c.get("finish_reason") for e in events for c in e.get("choices", []))
    if not complete or not finished or not usages or identities != {model}:
        raise ValueError("incomplete or unexpected model response; retain reservation")
    value = usages[-1]
    prompt, output = value["prompt_tokens"], value["completion_tokens"]
    cached = value.get("prompt_tokens_details", {}).get("cached_tokens")
    if cached is None:
        cached = value.get("prompt_cache_hit_tokens")
    if (
        type(prompt) is not int
        or type(output) is not int
        or (cached is not None and type(cached) is not int)
    ):
        raise ValueError("invalid Chat Completions usage counters")
    if prompt < 0 or output < 0 or cached is not None and not 0 <= cached <= prompt:
        raise ValueError("inconsistent cache usage")
    if value.get("total_tokens", prompt + output) != prompt + output:
        raise ValueError("inconsistent total token usage")
    # Completion tokens already include thinking; never add reasoning_tokens twice.
    return Usage(
        input_uncached=prompt - (cached or 0),
        input_cached=cached or 0,
        input_cache_write=0,
        output=output,
    ), {
        "cache_tokens_reported": cached is not None,
        "usage_semantics": "Chat Completions prompt includes cached input; "
        "completion includes reasoning",
        "returned_models": sorted(identities),
    }
