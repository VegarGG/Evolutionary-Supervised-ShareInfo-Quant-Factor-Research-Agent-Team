"""Data-only JSON interfaces for declared package runners."""

from typing import Literal, Self

from pydantic import Field, JsonValue, NonNegativeInt, model_validator

from qfr_core.contracts.base import Contract, Text
from qfr_core.contracts.enums import ArtifactKind

ScalarType = Literal[
    "Int8",
    "Int16",
    "Int32",
    "Int64",
    "UInt8",
    "UInt16",
    "UInt32",
    "UInt64",
    "Float32",
    "Float64",
    "Boolean",
    "String",
    "Date",
    "Null",
]


class RunnerTable(Contract):
    columns: list[Text]
    dtypes: list[ScalarType]
    rows: list[list[JsonValue]]

    @model_validator(mode="after")
    def rectangular(self) -> Self:
        if len(set(self.columns)) != len(self.columns) or len(self.columns) != len(self.dtypes):
            raise ValueError("runner table requires unique typed columns")
        if any(len(row) != len(self.columns) for row in self.rows):
            raise ValueError("runner table rows must match its columns")
        if not self.columns and self.rows:
            raise ValueError("an untyped empty table cannot contain rows")
        if any(isinstance(cell, (dict, list)) for row in self.rows for cell in row):
            raise ValueError("runner table cells must be scalar JSON values")
        return self


class RunnerInput(Contract):
    schema_version: Literal["1"]
    tables: dict[Text, RunnerTable] = Field(min_length=1)
    seed: NonNegativeInt


class RunnerOutput(Contract):
    schema_version: Literal["1"]
    kind: ArtifactKind
    tables: dict[Text, RunnerTable] = Field(min_length=1)


class ReleasedNumericClaim(Contract):
    """A machine-checkable claim about an already released scalar field."""

    report_id: Text
    field_path: list[Text] = Field(min_length=1)
    value: float


class ResearchNoteDocument(Contract):
    schema_version: Literal["1"]
    title: Text
    body: Text
    citation_refs: list[Text]
    numeric_claims: list[ReleasedNumericClaim]

    @model_validator(mode="after")
    def unique_citations(self) -> Self:
        if len(set(self.citation_refs)) != len(self.citation_refs):
            raise ValueError("research-note citations must be unique")
        return self
