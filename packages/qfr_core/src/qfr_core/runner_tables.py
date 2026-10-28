"""Explicit scalar-table serialization; never pickle or import uploaded objects."""

from datetime import date
from typing import cast

import polars as pl
from pydantic import JsonValue

from qfr_core.contracts.execution import RunnerTable, ScalarType

DTYPES: dict[str, type[pl.DataType]] = {
    name: getattr(pl, name)
    for name in (
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
    )
}


def pack_table(frame: pl.DataFrame) -> RunnerTable:
    types = [str(dtype) for dtype in frame.dtypes]
    if any(dtype not in DTYPES for dtype in types):
        raise ValueError("unsupported runner table dtype")
    rows: list[list[JsonValue]] = []
    for values in frame.iter_rows():
        row: list[JsonValue] = []
        for value in values:
            if isinstance(value, date):
                row.append(value.isoformat())
            elif value is None or isinstance(value, (str, int, float, bool)):
                row.append(value)
            else:
                raise ValueError("unsupported runner table scalar")
        rows.append(row)
    return RunnerTable(columns=frame.columns, dtypes=cast(list[ScalarType], types), rows=rows)


def unpack_table(table: RunnerTable) -> pl.DataFrame:
    rows: list[list[object]] = []
    for values in table.rows:
        row: list[object] = []
        for value, dtype in zip(values, table.dtypes, strict=True):
            parsed: object = value
            if dtype == "Date" and value is not None:
                if not isinstance(value, str):
                    raise ValueError("runner dates require ISO strings")
                parsed = date.fromisoformat(value)
            row.append(parsed)
        rows.append(row)
    return pl.DataFrame(
        rows,
        schema=[
            (column, DTYPES[dtype])
            for column, dtype in zip(table.columns, table.dtypes, strict=True)
        ],
        orient="row",
        strict=True,
    )
