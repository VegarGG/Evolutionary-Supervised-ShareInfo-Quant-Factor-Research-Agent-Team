"""Private epoch/window configuration: never exported as a public protocol card."""

from datetime import date
from typing import Literal, Self

from pydantic import NonNegativeInt, model_validator
from qfr_core.contracts.base import Contract, Text


class Window(Contract):
    start: date
    end: date | None
    end_rule: Text | None = None
    exposure: Literal["previously_seen", "unknown", "prospective"]

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.end is not None and self.end < self.start:
            raise ValueError("window end precedes start")
        if self.end is None and self.end_rule is None:
            raise ValueError("unresolved end requires a documented rule")
        return self


class EpochConfig(Contract):
    schema_version: Literal["1"]
    profile: Literal["pilot_industry_v1", "stock_daily_v1"]
    epoch_id: Text
    status: Literal["draft"]
    owner: Literal["evaluation"]
    windows: dict[Text, Window]
    embargo_trading_days: NonNegativeInt | None
    original_replay_windows: dict[Text, Window]
    unresolved: list[Text]
