"""The eligible cross-section shared by operators, metrics and backtests (PLAN 6.5)."""

from typing import Self

import polars as pl
from pydantic import BaseModel, ConfigDict, Field, JsonValue


class Eligibility(BaseModel):
    """Universe at t (point in time), listed long enough, not suspended at t.

    Factor and label availability are added by each consumer. Dates with fewer than
    cross_section_min eligible names are skipped.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)
    universe: str = Field(pattern=r"^[a-z0-9_]+$")
    listed_days_min: int = Field(ge=0)
    exclude_suspended: bool
    cross_section_min: int = Field(ge=2)

    @property
    def universe_column(self) -> str:
        return f"in_{self.universe}"

    def mask(self) -> pl.Expr:
        expr = pl.col(self.universe_column) & (pl.col("listed_days") >= self.listed_days_min)
        if self.exclude_suspended:
            expr = expr & ~pl.col("is_suspended")
        return expr.fill_null(False)

    @classmethod
    def from_protocol(
        cls, universe: dict[str, JsonValue], eligibility: dict[str, JsonValue]
    ) -> Self:
        return cls.model_validate(
            {
                "universe": universe["name"],
                "listed_days_min": eligibility["listed_days_min"],
                "exclude_suspended": eligibility["exclude_suspended"],
                "cross_section_min": eligibility["cross_section_min"],
            }
        )
