import pytest

from qfh.budget import BudgetRefused
from qfh.proxy import parse_usage, validate_request


def test_messages_usage_is_cumulative_not_additive():
    events = [
        {
            "type": "message_start",
            "message": {
                "usage": {
                    "input_tokens": 10,
                    "cache_read_input_tokens": 90,
                    "cache_creation_input_tokens": 0,
                    "output_tokens": 0,
                }
            },
        },
        {"type": "message_delta", "usage": {"output_tokens": 20}},
        {"type": "message_delta", "usage": {"output_tokens": 30}},
        {"type": "message_stop"},
    ]
    usage = parse_usage(events)
    assert usage.input_total == 100 and usage.output == 30
    with pytest.raises(ValueError, match="incomplete"):
        parse_usage(events[:-1])
    with pytest.raises(ValueError, match="incomplete"):
        parse_usage([events[0], events[-1]])


@pytest.mark.parametrize(
    "extra",
    [
        {"dsh_session_log": "private"},
        {"dsh_plugin_packages": []},
        {"model": "claude-opus"},
        {"max_tokens": 999999},
        {"tools": [{"name": "web_search", "type": "web_search_20250305"}]},
        {"tools": [{"name": "bash", "input_schema": {}}]},
    ],
)
def test_request_cannot_expand_privilege_or_billing(extra):
    with pytest.raises(BudgetRefused):
        validate_request(
            {"model": "deepseek-flash", "stream": True, "max_tokens": 8192, **extra},
            "deepseek-flash",
            8192,
            set(),
        )
