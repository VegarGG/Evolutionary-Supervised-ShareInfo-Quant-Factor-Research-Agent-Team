"""The shipped epoch_001 meets its 20-trading-day embargoes on the SSE calendar.

The plan's default W1 and W2 starts leave 17 and 16 trading days after the Spring
Festival closures; the owner moved both starts later (decision of 2026-10-31). The
closures below are the SSE weekday closures around the three gaps (checked against the
exchange_calendars XSHG calendar); every other weekday is a session for this check.
"""

from datetime import date, timedelta
from pathlib import Path

from qfr_eval.configs import epoch_from_mapping, load_epoch_file, resolve_windows

SSE_CLOSURES = {
    date.fromisoformat(d)
    for d in (
        "2020-01-01", "2020-01-24", "2020-01-27", "2020-01-28", "2020-01-29",
        "2020-01-30", "2020-01-31",
        "2023-01-02", "2023-01-23", "2023-01-24", "2023-01-25", "2023-01-26",
        "2023-01-27",
    )
}  # fmt: skip
ACTIVATION = date(2026, 10, 31)


def calendar() -> list[date]:
    days, day = [], date(2010, 1, 4)
    while day <= date(2026, 9, 30):
        if day.weekday() < 5 and day not in SSE_CLOSURES:
            days.append(day)
        day += timedelta(days=1)
    return days


def test_the_shipped_epoch_meets_its_embargo_on_the_sse_calendar():
    epoch, _ = load_epoch_file(Path("configs/epochs/epoch_001.yaml"))
    windows, check = resolve_windows(epoch, calendar(), ACTIVATION)
    assert check["gaps_trading_days"] == {"W0-W1": 20, "W1-W2": 20, "W2-W3": 23}
    assert check["passed"] is True
    assert windows["W1"].start == date(2020, 2, 7)
    assert windows["W2"].start == date(2023, 2, 7)
    assert windows["W3"].end == date(2026, 9, 30)


def test_the_plan_default_starts_would_be_refused():
    epoch, _ = load_epoch_file(Path("configs/epochs/epoch_001.yaml"))
    raw = epoch.model_dump(mode="json")
    raw["W1"]["start"], raw["W2"]["start"] = "2020-02-04", "2023-02-01"
    plan_default, _ = epoch_from_mapping(raw)
    _, check = resolve_windows(plan_default, calendar(), ACTIVATION)
    assert check["gaps_trading_days"]["W0-W1"] == 17
    assert check["gaps_trading_days"]["W1-W2"] == 16
    assert check["passed"] is False  # activation refuses this with EMBARGO_TOO_SHORT
