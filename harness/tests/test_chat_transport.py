import pytest

from qfh.budget import BudgetRefused
from qfh.chat_transport import parse_chat_usage, validate_chat_request

MODEL = "glm-5.3-flash"


def events():
    return [
        {
            "model": MODEL,
            "choices": [{"finish_reason": "stop"}],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 10,
                "total_tokens": 110,
                "prompt_tokens_details": {"cached_tokens": 60},
                "completion_tokens_details": {"reasoning_tokens": 8},
            },
        }
    ]


def test_chat_cache_counts_and_thinking_are_not_double_counted():
    usage, meta = parse_chat_usage(events(), complete=True, model=MODEL)
    assert usage.input_uncached == 40 and usage.input_cached == 60 and usage.output == 10
    assert meta["cache_tokens_reported"] is True
    missing = events()
    del missing[0]["usage"]["prompt_tokens_details"]
    usage, meta = parse_chat_usage(missing, complete=True, model=MODEL)
    assert usage.input_total == 100 and meta["cache_tokens_reported"] is False


@pytest.mark.parametrize("damage", ["done", "model", "usage", "finish", "cached", "total"])
def test_chat_uncertain_or_inconsistent_usage_cannot_settle(damage):
    value = events()
    if damage == "model":
        value[0]["model"] = "glm-5.3"
    if damage == "usage":
        del value[0]["usage"]
    if damage == "finish":
        value[0]["choices"] = []
    if damage == "cached":
        value[0]["usage"]["prompt_tokens_details"]["cached_tokens"] = 101
    if damage == "total":
        value[0]["usage"]["total_tokens"] = 999
    with pytest.raises(ValueError):
        parse_chat_usage(value, complete=damage != "done", model=MODEL)


def test_native_chat_request_is_bounded_before_dispatch():
    valid = {
        "model": MODEL,
        "stream": True,
        "max_tokens": 128,
        "stream_options": {"include_usage": True},
        "messages": [],
        "tools": [{"type": "function", "function": {"name": "read_evidence"}}],
    }
    assert validate_chat_request(valid, MODEL, 8192, {"read_evidence"}) == 128
    for change in (
        {"thinking": {"type": "disabled"}},
        {"tool_stream": "true"},
        {"model": "glm-5.3"},
        {"max_tokens": 8193},
        {"tool_choice": "required"},
        {"max_completion_tokens": 128},
        {"stream_options": {}},
        {"tools": [{"type": "web_search"}]},
        {"store": True},
    ):
        with pytest.raises(BudgetRefused):
            validate_chat_request({**valid, **change}, MODEL, 8192, {"read_evidence"})
