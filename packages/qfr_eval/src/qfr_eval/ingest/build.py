"""Trusted, on-demand zone construction. No evaluation scheduling or protocol execution."""

from collections.abc import Sequence
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Literal

from qfr_core.contracts.data import ExposureAndQuality
from qfr_core.data_layer.snapshots import Snapshot, TableInput, slice_frame, write_snapshot


def build_zones(
    root: Path,
    tables: Sequence[TableInput],
    *,
    cutoff: date,
    as_of: date,
    profile: str,
    source: str,
    build_code_version: str,
    exposure: ExposureAndQuality,
    conventions: dict[str, str],
    principal: str,
    request_id: str,
    release_tag: str | None = None,
    archive_sha256: str | None = None,
    audit_root: Path | None = None,
) -> tuple[Snapshot, Snapshot]:
    if cutoff > as_of:
        raise ValueError("research cutoff exceeds supplied snapshot as_of")

    def emit(items: Sequence[TableInput], zone: Literal["full", "research"]) -> Snapshot:
        return write_snapshot(
            root,
            items,
            zone=zone,
            cutoff=cutoff if zone == "research" else None,
            as_of=cutoff if zone == "research" else as_of,
            profile=profile,
            source=source,
            build_code_version=build_code_version,
            exposure=exposure,
            conventions=conventions,
            principal=principal,
            request_id=request_id,
            release_tag=release_tag,
            archive_sha256=archive_sha256,
            audit_root=audit_root,
        )

    full = emit(tables, "full")
    research_tables = [
        replace(
            table,
            frame=slice_frame(table.frame, cutoff, table.date_column, table.available_date_column),
        )
        for table in tables
        if table.research_visible
    ]
    research = emit(research_tables, "research")
    return research, full
